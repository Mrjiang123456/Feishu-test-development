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


@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        images = []
        prd_text = ""

        # 飞书文档支持 docx/wiki 自动识别
        if request_data.web_url and "feishu.cn/" in request_data.web_url:
            result = await get_feishu_doc_content(request_data.web_url)
            prd_text = result.get("text", "")
            images = result.get("images", [])

        # 普通网页
        elif request_data.web_url and request_data.web_url.strip():
            result = await fetch_webpage_content(request_data.web_url)
            prd_text = result.get("text", "")
            images = result.get("images", [])

        # 用户输入文本
        elif request_data.prd_text and request_data.prd_text.strip():
            prd_text = clean_text(request_data.prd_text)

        else:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "请提供 prd_text 或 web_url（支持飞书链接与网页链接）"
            })

        # 执行 LangGraph 流程
        result = await graph.ainvoke({"prd_text": prd_text})
        testcases = result.get("testcases", [])

        return JSONResponse(content={
            "success": True,
            "testcases": testcases
        })

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": f"生成测试用例失败: {str(e)}"
        })


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
