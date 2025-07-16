import os
import time
import glob
import asyncio
import aiohttp
import json
import traceback
import uuid  # 添加uuid导入
from typing import Optional
from config import MODEL_NAME, API_URL
from logger import log, log_error, start_logging, end_logging
from llm_api import clear_cache  # 导入清除缓存函数

try:
    from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request
    from fastapi.responses import JSONResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel
    from fastapi.middleware.cors import CORSMiddleware


    # 定义API请求模型
    class TestCaseComparisonRequest(BaseModel):
        ai_test_cases: str  # AI生成的测试用例，JSON字符串
        golden_test_cases: Optional[str] = None  # 黄金标准测试用例，JSON字符串，可选
        model_name: str = MODEL_NAME  # 可选，使用的模型名称
        save_results: bool = True  # 可选，是否保存结果文件
        is_iteration: bool = False  # 可选，是否启用迭代前后对比功能
        prev_iteration: Optional[str] = None  # 可选，上一次迭代的测试用例，JSON字符串

        # 添加model_config配置，禁用保护命名空间检查
        model_config = {
            "protected_namespaces": ()
        }
    
    # 定义保存黄金标准测试用例的请求模型
    class SaveGoldenCasesRequest(BaseModel):
        golden_test_cases: str  # 黄金标准测试用例，JSON字符串
        
        # 添加model_config配置，禁用保护命名空间检查
        model_config = {
            "protected_namespaces": ()
        }


    # 定义API响应模型
    class ApiResponse(BaseModel):
        success: bool
        message: str = None
        error: str = None
        evaluation_result: dict = None
        report: str = None
        report_iteration: str = None
        files: dict = None


    # 创建FastAPI应用
    app = FastAPI(
        title="测试用例比较工具API",
        description="比较AI生成的测试用例与黄金标准测试用例，评估测试用例质量",
        version="1.0.0"
    )

    # 允许跨域请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 允许所有来源的请求
        allow_credentials=True,
        allow_methods=["*"],  # 允许所有HTTP方法
        allow_headers=["*"],  # 允许所有HTTP头
    )

    # 创建模板目录和静态文件目录
    templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(templates_dir, exist_ok=True)
    templates = Jinja2Templates(directory=templates_dir)
    
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # 创建输出目录的静态文件挂载
    output_dir = os.path.join(os.path.dirname(__file__), "output_evaluation")
    os.makedirs(output_dir, exist_ok=True)
    app.mount("/output_evaluation", StaticFiles(directory=output_dir), name="output_evaluation")

    # 状态追踪
    evaluation_tasks = {}

    # 导入主程序模块
    from core import async_main


    # 全局异常处理中间件
    @app.middleware("http")
    async def log_requests_and_errors(request: Request, call_next):
        start_time = time.time()
        request_id = f"req-{int(start_time * 1000)}"

        # 记录请求信息
        log(f"API请求开始: {request_id} - {request.method} {request.url.path}", important=True)

        try:
            # 处理请求
            response = await call_next(request)
            process_time = time.time() - start_time
            log(f"API请求完成: {request_id} - 状态码: {response.status_code}, 耗时: {process_time:.2f}秒")
            return response
        except Exception as e:
            # 记录异常
            process_time = time.time() - start_time
            error_details = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "process_time": f"{process_time:.2f}秒",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc()
            }
            log_error(f"API请求处理异常: {request_id}", error_details)

            # 返回错误响应
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"服务器内部错误: {str(e)}",
                    "request_id": request_id,
                    "finish_task": True
                }
            )


    @app.get("/", response_class=HTMLResponse)
    async def get_index(request: Request):
        """
        返回主页
        """
        log("访问主页")
        return templates.TemplateResponse("index.html", {"request": request})
    
    
    @app.get("/golden-cases", response_class=HTMLResponse)
    async def get_golden_cases_page(request: Request):
        """
        返回黄金标准测试用例页面
        """
        log("访问黄金标准测试用例页面")
        return templates.TemplateResponse("golden_cases.html", {"request": request})


    @app.post("/api/save-golden-cases")
    async def save_golden_cases(request: SaveGoldenCasesRequest):
        """
        保存黄金标准测试用例
        
        :param request: 包含黄金标准测试用例的请求
        :return: 保存结果
        """
        request_id = f"save-golden-{str(uuid.uuid4())[:8]}-{int(time.time() * 1000)}"
        log(f"接收到保存黄金标准测试用例请求: {request_id}", important=True)
        
        try:
            # 验证JSON格式
            try:
                golden_cases_data = request.golden_test_cases
                json.loads(golden_cases_data)  # 验证JSON格式
                log(f"黄金标准测试用例JSON格式有效")
            except json.JSONDecodeError as e:
                error_info = {
                    "request_id": request_id,
                    "error_type": "JSON解析错误",
                    "error_message": str(e)
                }
                log_error("黄金标准测试用例JSON格式无效", error_info)
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": f"黄金标准测试用例JSON格式无效: {str(e)}"
                    }
                )
            
            # 确保goldenset目录存在
            goldenset_dir = "goldenset"
            os.makedirs(goldenset_dir, exist_ok=True)
            
            # 保存到文件
            golden_file_path = os.path.join(goldenset_dir, "golden_cases.json")
            
            # 如果已有文件，备份旧文件
            if os.path.exists(golden_file_path):
                backup_path = os.path.join(goldenset_dir, f"golden_cases_backup_{int(time.time())}.json")
                try:
                    os.rename(golden_file_path, backup_path)
                    log(f"已将旧的黄金标准测试用例备份至 {backup_path}")
                except Exception as e:
                    log_error(f"备份旧的黄金标准测试用例失败: {str(e)}")
            
            # 保存新的黄金标准测试用例
            with open(golden_file_path, "w", encoding="utf-8") as f:
                f.write(golden_cases_data)
            
            log(f"黄金标准测试用例已保存至 {golden_file_path}", important=True)
            
            return JSONResponse(
                content={
                    "success": True,
                    "message": "黄金标准测试用例保存成功",
                    "file_path": golden_file_path
                }
            )
            
        except Exception as e:
            error_info = {
                "request_id": request_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc()
            }
            log_error("保存黄金标准测试用例时发生错误", error_info)
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"保存黄金标准测试用例失败: {str(e)}"
                }
            )


    @app.post("/compare-test-cases")
    async def compare_test_cases_api(request: TestCaseComparisonRequest):
        """
        比较AI生成的测试用例与黄金标准测试用例

        :param request: 请求数据，包含AI测试用例和黄金标准测试用例
        :return: 评测结果
        """
        # 生成唯一请求ID
        request_id = f"task-{str(uuid.uuid4())}-{int(time.time() * 1000)}"
        log(f"接收到评测测试用例请求: {request_id}", important=True)

        # 确保清除缓存，让每个请求都是全新的评测
        clear_cache()
        log("已清除缓存，确保本次评测是全新的", important=True)

        try:
            # 更新全局变量
            global MODEL_NAME
            MODEL_NAME = request.model_name
            log(f"使用模型: {MODEL_NAME}")

            # 准备黄金标准测试用例数据
            golden_test_cases = request.golden_test_cases
            if golden_test_cases is None:
                # 如果请求中没有提供黄金标准测试用例，则从文件读取
                log("从goldenset文件夹读取黄金标准测试用例", important=True)
                golden_files = glob.glob("goldenset/golden_cases*.json")
                if not golden_files:
                    error_info = {
                        "request_id": request_id,
                        "search_pattern": "goldenset/golden_cases*.json",
                        "current_dir": os.getcwd(),
                        "goldenset_exists": os.path.exists("goldenset"),
                        "goldenset_files": os.listdir("goldenset") if os.path.exists("goldenset") else "目录不存在"
                    }
                    error_msg = "在goldenset文件夹中找不到黄金标准测试用例文件"
                    log_error(error_msg, error_info)
                    return JSONResponse(
                        content={
                            "success": False,
                            "error": error_msg,
                            "message": "评测失败：找不到黄金标准测试用例",
                            "finish_task": True,
                            "request_id": request_id
                        }
                    )

                try:
                    with open(golden_files[0], 'r', encoding='utf-8') as f:
                        golden_test_cases = f.read()
                    log(f"成功从文件 {golden_files[0]} 读取黄金标准测试用例", important=True)
                except Exception as e:
                    error_info = {
                        "request_id": request_id,
                        "file_path": golden_files[0],
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()
                    }
                    error_msg = f"读取黄金标准测试用例文件失败: {str(e)}"
                    log_error(error_msg, error_info)
                    return JSONResponse(
                        content={
                            "success": False,
                            "error": error_msg,
                            "message": "评测失败：读取黄金标准测试用例出错",
                            "finish_task": True,
                            "request_id": request_id
                        }
                    )

            # 检查AI测试用例数据是否有效
            try:
                # 尝试解析JSON，确保数据有效
                if not request.ai_test_cases:
                    raise ValueError("AI测试用例数据为空")
                
                # 检查是否是已经转义的JSON字符串
                ai_test_cases = request.ai_test_cases
                try:
                    # 尝试直接解析
                    json.loads(ai_test_cases)
                    log("成功直接解析AI测试用例JSON", important=True)
                except json.JSONDecodeError as decode_error:
                    # 如果解析失败，可能是双重转义的情况，尝试去除一层转义
                    log(f"JSON解析失败({str(decode_error)})，尝试处理可能的双重转义JSON字符串", level="WARNING")
                    try:
                        # 方法1：使用eval评估字符串
                        eval_result = eval(ai_test_cases)
                        if isinstance(eval_result, dict):
                            ai_test_cases = json.dumps(eval_result)
                            log("通过eval成功处理双重转义的JSON字符串", important=True)
                        else:
                            # 方法2：替换转义字符
                            ai_test_cases = ai_test_cases.replace('\\"', '"').replace('\\\\', '\\')
                            # 再次尝试解析
                            json.loads(ai_test_cases)
                            log("通过替换转义字符成功处理JSON字符串", important=True)
                    except Exception as e:
                        log_error(f"处理JSON字符串失败: {str(e)}")
                        # 尝试进一步处理常见格式问题
                        try:
                            # 检查是否包含类别分组格式的特征（如functional、security等键）
                            if '"functional":' in ai_test_cases or '"security":' in ai_test_cases:
                                log("检测到可能是按类别分组的测试用例格式，尝试特殊处理", level="WARNING")
                                # 移除外层转义
                                cleaned_json = ai_test_cases.strip('"\'')
                                # 替换内部转义
                                cleaned_json = cleaned_json.replace('\\"', '"').replace('\\\\', '\\')
                                # 解析验证
                                json.loads(cleaned_json)
                                ai_test_cases = cleaned_json
                                log("成功处理类别分组格式的JSON字符串", important=True)
                            else:
                                # 回退到原始字符串
                                ai_test_cases = request.ai_test_cases
                                log("无法处理JSON格式，回退到原始字符串", level="WARNING")
                        except Exception as special_e:
                            log_error(f"特殊处理JSON字符串失败: {str(special_e)}")
                            # 回退到原始字符串
                            ai_test_cases = request.ai_test_cases
                        
            except json.JSONDecodeError as e:
                error_info = {
                    "request_id": request_id,
                    "error_type": "JSON解析错误",
                    "error_message": str(e),
                    "data_preview": request.ai_test_cases[:100] + "..." if request.ai_test_cases else "无数据"
                }
                log_error("AI测试用例JSON格式无效", error_info)
                return JSONResponse(
                    content={
                        "success": False,
                        "error": "AI测试用例JSON格式无效",
                        "message": f"JSON解析错误: {str(e)}",
                        "finish_task": True,
                        "request_id": request_id
                    }
                )
            except ValueError as e:
                log_error(f"AI测试用例数据无效: {str(e)}")
                return JSONResponse(
                    content={
                        "success": False,
                        "error": f"AI测试用例数据无效: {str(e)}",
                        "message": "请提供有效的AI测试用例数据",
                        "finish_task": True,
                        "request_id": request_id
                    }
                )

            # 直接执行评测任务
            log(f"开始执行评测任务: {request_id}")
            
            # 记录是否启用迭代对比
            if request.is_iteration:
                if request.prev_iteration:
                    log(f"启用迭代前后对比功能，比较当前测试用例与上一次迭代", important=True)
                else:
                    log(f"请求启用迭代对比但未提供上一次迭代数据，迭代对比功能将被禁用", level="WARNING")
            
            result = await async_main(
                ai_test_cases, 
                golden_test_cases, 
                is_iteration=request.is_iteration, 
                prev_iteration_data=request.prev_iteration
            )

            if result and result.get("success", False):
                log(f"评测任务 {request_id} 完成")
                response_content = {
                    "success": True,
                    "message": "测试用例评测完成",
                    "evaluation_result": result["evaluation_result"],
                    "files": result["files"],
                    "finish_task": True,
                    "request_id": request_id
                }
                
                # 标准报告
                if "report" in result:
                    response_content["report"] = result["report"]
                    log(f"添加标准报告到API响应，长度: {len(result['report'])}", important=True)
                elif "markdown_report" in result:
                    response_content["report"] = result["markdown_report"]
                    log(f"添加标准报告(markdown_report)到API响应，长度: {len(result['markdown_report'])}", important=True)
                
                # 迭代简洁报告，只有在迭代模式下才返回
                if request.is_iteration and "report_iteration" in result:
                    response_content["report_iteration"] = result["report_iteration"]
                    log(f"添加迭代报告到API响应，长度: {len(result['report_iteration'])}", important=True)
                elif request.is_iteration:
                    log("警告: 迭代模式启用但结果中没有report_iteration字段", level="WARNING")
                    log(f"结果中可用的字段: {', '.join(result.keys())}", important=True)
                
                # 打印响应内容中包含的字段
                log(f"最终API响应包含以下字段: {', '.join(response_content.keys())}", important=True)
                
                return JSONResponse(content=response_content)
            else:
                error_msg = result.get("error", "未知错误")
                error_type = result.get("error_type", "unknown")
                log_error(f"评测任务 {request_id} 失败: {error_msg}", {"error_type": error_type})
                return JSONResponse(
                    content={
                        "success": False,
                        "error": error_msg,
                        "error_type": error_type,
                        "message": "评测失败",
                        "finish_task": True,
                        "request_id": request_id
                    }
                )

        except Exception as e:
            error_info = {
                "request_id": request_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc()
            }
            log_error(f"评测过程中发生未知错误", error_info)
            return JSONResponse(
                content={
                    "success": False,
                    "error": str(e),
                    "message": "评测过程中发生未知错误",
                    "finish_task": True,
                    "request_id": request_id
                }
            )


    # 保留task-status接口以兼容旧版本调用
    @app.get("/task-status/{task_id}")
    async def get_task_status(task_id: str):
        """
        获取任务状态

        :param task_id: 任务ID
        :return: 任务状态和结果
        """
        log(f"查询任务状态: {task_id}")

        if task_id not in evaluation_tasks:
            log_error(f"找不到指定任务: {task_id}", {"available_tasks": list(evaluation_tasks.keys())})
            raise HTTPException(status_code=404, detail="找不到指定任务")

        response_content = evaluation_tasks[task_id]
        # 添加finish_task字段
        response_content["finish_task"] = True
        log(f"返回任务 {task_id} 状态")
        return JSONResponse(content=response_content)


    @app.post("/upload-test-cases")
    async def upload_test_cases(
            file: UploadFile = File(...),
            file_type: str = Form(...),  # "ai" 或 "golden"
    ):
        """
        上传测试用例文件

        :param file: 上传的测试用例文件
        :param file_type: 文件类型，"ai"表示AI生成的测试用例，"golden"表示黄金标准测试用例
        :return: 上传结果
        """
        request_id = f"upload-{str(uuid.uuid4())[:8]}-{int(time.time() * 1000)}"
        log(f"接收到文件上传请求: {request_id}, 文件类型: {file_type}, 文件名: {file.filename}")

        try:
            contents = await file.read()
            file_content = contents.decode("utf-8")

            if file_type.lower() == "ai":
                save_path = "testset/test_cases.json"
                dir_path = "testset"
            elif file_type.lower() == "golden":
                save_path = "goldenset/golden_cases.json"
                dir_path = "goldenset"
            else:
                log_error(f"无效的文件类型: {file_type}", {"request_id": request_id, "expected": "ai或golden"})
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "无效的文件类型，必须是'ai'或'golden'", "request_id": request_id}
                )

            # 验证JSON格式
            try:
                json.loads(file_content)
            except json.JSONDecodeError as e:
                error_info = {
                    "request_id": request_id,
                    "file_name": file.filename,
                    "file_type": file_type,
                    "error_position": str(e),
                    "content_preview": file_content[:100] + "..." if len(file_content) > 100 else file_content
                }
                log_error(f"上传的文件不是有效的JSON格式", error_info)
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": f"上传的文件不是有效的JSON格式: {str(e)}",
                        "request_id": request_id
                    }
                )

            # 确保目录存在
            os.makedirs(dir_path, exist_ok=True)

            # 保存文件
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(file_content)

            log(f"文件上传成功: {request_id}, 保存路径: {save_path}")
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"{file_type}测试用例文件上传成功",
                    "file_path": save_path,
                    "request_id": request_id
                }
            )
        except UnicodeDecodeError as e:
            error_info = {
                "request_id": request_id,
                "file_name": file.filename,
                "file_type": file_type,
                "error_type": "UnicodeDecodeError",
                "error_message": str(e)
            }
            log_error("文件编码错误，无法解码为UTF-8", error_info)
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"文件编码错误，请确保文件为UTF-8编码: {str(e)}",
                    "request_id": request_id
                }
            )
        except Exception as e:
            error_info = {
                "request_id": request_id,
                "file_name": file.filename,
                "file_type": file_type,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc()
            }
            log_error("文件上传失败", error_info)
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": f"文件上传失败：{str(e)}",
                    "request_id": request_id
                }
            )


    @app.post("/evaluate-from-json")
    async def evaluate_from_json(request: TestCaseComparisonRequest):
        """处理JSON数据的评估请求"""
        # 复用比较测试用例的API，避免代码重复
        return await compare_test_cases_api(request)


    @app.get("/health")
    async def health_check():
        """健康检查接口"""
        try:
            # 检查目录结构
            dirs_status = {
                "goldenset": os.path.exists("goldenset"),
                "testset": os.path.exists("testset"),
                "log": os.path.exists("log"),
                "output_evaluation": os.path.exists("output_evaluation")
            }

            # 检查模型配置
            model_info = {
                "model_name": MODEL_NAME,
                "api_url_configured": bool(API_URL)
            }

            return JSONResponse(content={
                "status": "healthy",
                "timestamp": time.time(),
                "dirs_status": dirs_status,
                "model_info": model_info
            })
        except Exception as e:
            error_info = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc()
            }
            log_error("健康检查失败", error_info)
            return JSONResponse(
                status_code=500,
                content={
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": time.time()
                }
            )

except ImportError as e:
    # 如果未安装FastAPI，则跳过API接口部分
    import_error = {
        "error_type": "ImportError",
        "error_message": str(e),
        "missing_module": str(e).split("'")[1] if "'" in str(e) else "未知模块"
    }
    log_error("未检测到FastAPI库，API接口不可用", import_error)
    log("请安装FastAPI和uvicorn: pip install fastapi uvicorn", important=True)
    app = None 
