from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langgraph_use import graph
from utils import clean_text, fetch_webpage_content
from feishu_api import get_feishu_doc_content
import traceback
import uvicorn

app = FastAPI()

# 请求体模型
class GenerateRequest(BaseModel):
    prd_text: str | None = None
    web_url: str | None = None
    evaluate: bool = False  # 添加参数，决定是否评估生成的测试用例


@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        # 飞书文档支持 docx/wiki 自动识别
        if request_data.web_url and "feishu.cn/" in request_data.web_url:

            prd_text = await get_feishu_doc_content(request_data.web_url)
        # 普通网页
        elif request_data.web_url and request_data.web_url.strip():

            prd_text = await fetch_webpage_content(request_data.web_url)
        # 用户输入文本
        elif request_data.prd_text and request_data.prd_text.strip():

            prd_text = clean_text(request_data.prd_text)

        else:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "请提供 prd_text 或 web_url 中的一个（支持普通网页和飞书文档链接）"
            })

        # 执行 LangGraph 流程
        result = await graph.ainvoke({"prd_text": prd_text})
        testcases = result.get("testcases", [])
        
        # 创建响应数据
        response_data = {
            "success": True,
            "testcases": testcases
        }
        
        # 如果需要评估，则调用group.py的main函数
        if request_data.evaluate:
            try:
                # 导入group模块的main函数
                from group import main as evaluate_testcases
                
                # 将testcases传递给evaluate_testcases函数
                evaluation_result = evaluate_testcases({"testcases": testcases})
                
                # 将评估结果添加到响应中
                response_data["evaluation"] = evaluation_result
                
            except Exception as eval_error:
                # 记录评估过程中的错误，但不影响测试用例的返回
                traceback.print_exc()
                response_data["evaluation_error"] = str(eval_error)

        return JSONResponse(content=response_data)

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": f"生成测试用例失败: {str(e)}"
        })


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
