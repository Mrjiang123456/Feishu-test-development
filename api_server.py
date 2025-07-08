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
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from fastapi.middleware.cors import CORSMiddleware


    # 定义API请求模型
    class TestCaseComparisonRequest(BaseModel):
        ai_test_cases: str  # AI生成的测试用例，JSON字符串
        golden_test_cases: Optional[str] = None  # 黄金标准测试用例，JSON字符串，可选
        model_name: str = MODEL_NAME  # 可选，使用的模型名称
        save_results: bool = True  # 可选，是否保存结果文件

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


    @app.post("/compare-test-cases")
    async def compare_test_cases_api(request: TestCaseComparisonRequest):
        """
        比较AI生成的测试用例与黄金标准测试用例

        :param request: 请求数据，包含AI测试用例和黄金标准测试用例
        :return: 评测结果
        """
        # 生成唯一请求ID
        request_id = f"task-{str(uuid.uuid4())[:8]}-{int(time.time() * 1000)}"
        log(f"接收到评测测试用例请求: {request_id}", important=True)

        # 确保清除缓存，让每个请求都是全新的评测
        clear_cache()

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
                if request.ai_test_cases:
                    # 检查是否是已经转义的JSON字符串
                    ai_test_cases = request.ai_test_cases
                    try:
                        # 尝试直接解析
                        json.loads(ai_test_cases)
                    except json.JSONDecodeError:
                        # 如果解析失败，可能是双重转义的情况，尝试去除一层转义
                        log("尝试处理可能的双重转义JSON字符串", level="WARNING")
                        try:
                            # 将字符串解析为Python对象，然后再转回JSON字符串
                            ai_test_cases = json.dumps(eval(ai_test_cases))
                            json.loads(ai_test_cases)
                            log("成功处理双重转义的JSON字符串", important=True)
                        except Exception as e:
                            log_error(f"处理双重转义JSON失败: {str(e)}")
                            # 回退到原始字符串
                            ai_test_cases = request.ai_test_cases
                else:
                    raise ValueError("AI测试用例数据为空")
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
            result = await async_main(ai_test_cases, golden_test_cases)

            if result and result.get("success", False):
                log(f"评测任务 {request_id} 完成")
                return JSONResponse(
                    content={
                        "success": True,
                        "message": "测试用例评测完成",
                        "evaluation_result": result["evaluation_result"],
                        "report": result["markdown_report"],
                        "files": result["files"],
                        "finish_task": True,
                        "request_id": request_id
                    }
                )
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
        """
        从JSON数据评测测试用例（与/compare-test-cases相同）

        :param request: 请求数据，包含AI测试用例和黄金标准测试用例
        :return: 评测结果
        """
        # 确保清除缓存，让每次请求都是全新的评测
        clear_cache()

        # 直接调用compare_test_cases_api
        return await compare_test_cases_api(request)


    @app.get("/")
    async def root():
        """API根路径，返回基本信息"""
        log("访问API根路径")
        return JSONResponse(content={
            "name": "测试用例比较工具API",
            "version": "1.0.0",
            "description": "比较AI生成的测试用例与黄金标准测试用例，评估测试用例质量",
            "model": MODEL_NAME
        })


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