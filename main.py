from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langgraph_use import graph
from utils import clean_text, fetch_webpage_content
import traceback
import uvicorn

app = FastAPI()


# 定义前端请求格式
class GenerateRequest(BaseModel):
    prd_text: str | None = None
    web_url: str | None = None


# POST 接口，供前端/客户端调用，生成测试用例
@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        # 判断用户提供的是 PRD 文本还是链接
        if request_data.web_url and request_data.web_url.strip():
            prd_text = await fetch_webpage_content(request_data.web_url)
        elif request_data.prd_text:
            prd_text = clean_text(request_data.prd_text)
        else:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "请提供 prd_text 或 web_url 中的一个"
            })

        # 调用 LangGraph 流程生成用例
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


# 启动服务器
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
