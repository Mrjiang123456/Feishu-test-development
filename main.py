from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langgraph_use import graph
from utils import clean_text, fetch_webpage_content
from feishu_api import get_feishu_doc_content
import traceback
import uvicorn
from group import main as group_evaluate
import os
import json
import time
import datetime

app = FastAPI()


# 请求体模型
class GenerateRequest(BaseModel):
    prd_text: str | None = None
    web_url: str | None = None
    run_evaluation: bool = True  # 默认自动运行评测


@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    start_time = time.time()
    try:
        images = []
        prd_text = ""
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 收到新请求...")

        # 飞书文档支持 docx/wiki 自动识别
        if request_data.web_url and "feishu.cn/" in request_data.web_url:
            print(f"[{current_time}] 正在获取飞书文档内容: {request_data.web_url}")
            result = await get_feishu_doc_content(request_data.web_url)
            prd_text = result.get("text", "")
            images = result.get("images", [])

        # 普通网页
        elif request_data.web_url and request_data.web_url.strip():
            print(f"[{current_time}] 正在获取网页内容: {request_data.web_url}")
            result = await fetch_webpage_content(request_data.web_url)
            prd_text = result.get("text", "")
            images = result.get("images", [])

        # 用户输入文本
        elif request_data.prd_text and request_data.prd_text.strip():
            print(f"[{current_time}] 使用直接提供的文本作为PRD")
            prd_text = clean_text(request_data.prd_text)

        else:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "请提供 prd_text 或 web_url（支持飞书链接与网页链接）"
            })

        # 执行 LangGraph 流程生成测试用例
        generate_start_time = time.time()
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 开始生成测试用例...")
        result = await graph.ainvoke({"prd_text": prd_text})
        testcases = result.get("testcases", [])
        generate_end_time = time.time()
        generate_time = generate_end_time - generate_start_time
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 成功生成 {len(testcases)} 个测试用例，用时 {generate_time:.2f} 秒")

        # 构建返回数据
        response_data = {
            "success": True,
            "testcases": testcases,
            "generation_time_seconds": round(generate_time, 2)
        }
        
        # 自动执行评测（除非明确禁用）
        if request_data.run_evaluation and testcases:
            # 检查golden_cases.json文件是否存在
            golden_cases_file = "golden_cases.json"
            if not os.path.exists(golden_cases_file):
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{current_time}] 警告: 找不到黄金用例文件 {golden_cases_file}，无法进行评测")
                response_data["evaluation_error"] = f"找不到黄金用例文件 {golden_cases_file}"
            else:
                try:
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{current_time}] 开始评测测试用例...")
                    evaluation_start_time = time.time()
                    
                    # 为确保评测正常进行，先将测试用例保存到临时文件
                    temp_ai_cases_file = "temp_ai_cases.json"
                    with open(temp_ai_cases_file, "w", encoding="utf-8") as f:
                        json.dump({"testcases": testcases}, f, ensure_ascii=False, indent=2)
                    
                    # 将生成的测试用例传递给 group.py 进行评测
                    ai_cases_data = {"testcases": testcases}
                    
                    # 立即执行评测
                    evaluation_result = group_evaluate(ai_cases_data)
                    evaluation_end_time = time.time()
                    evaluation_time = evaluation_end_time - evaluation_start_time
                    
                    response_data["evaluation"] = evaluation_result
                    response_data["evaluation_time_seconds"] = round(evaluation_time, 2)
                    
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{current_time}] 评测完成，用时 {evaluation_time:.2f} 秒")
                    
                    # 清理临时文件
                    if os.path.exists(temp_ai_cases_file):
                        os.remove(temp_ai_cases_file)
                        
                except Exception as eval_error:
                    error_msg = str(eval_error)
                    response_data["evaluation_error"] = error_msg
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{current_time}] 评测出错: {error_msg}")
                    traceback.print_exc()

        # 计算总耗时
        total_time = time.time() - start_time
        response_data["total_time_seconds"] = round(total_time, 2)
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 请求处理完成，总耗时 {total_time:.2f} 秒")
        
        return JSONResponse(content=response_data)

    except Exception as e:
        error_msg = str(e)
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] 错误: {error_msg}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": f"生成测试用例失败: {error_msg}"
        })


if __name__ == "__main__":
    print("=" * 50)
    print("启动测试用例生成与评测服务...")
    print("访问 http://127.0.0.1:8000/docs 查看API文档")
    print("=" * 50)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
