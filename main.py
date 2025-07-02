from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langgraph_use import graph
from feishu_api import get_feishu_doc_content
import logging
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()


class GenerateRequest(BaseModel):
    document_id: str
    user_access_token: str


@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        logger.info(f"收到飞书请求，document_id={request_data.document_id}")
        # 入参飞书云文档的document_id和user_access_token
        result = await get_feishu_doc_content(request_data.document_id, request_data.user_access_token)

        prd_text = result.get("markdown")
        print("调试 Markdown 内容示例：\n", prd_text[:10000])
        images = result.get("images", [])

        logger.info(f"飞书文档内容获取成功，markdown长度: {len(prd_text)}, 图片数量: {len(images)}")

        initial_state = {
            "prd_text": prd_text,
            "prd_title": "",
            "requirements": "",
            "testcases": {},
            "validated": ""
        }

        logger.info("开始调用图谱生成测试用例")
        result_graph = await graph.ainvoke(initial_state)
        logger.info("图谱调用完成，生成测试用例成功")

        # json格式返回用例
        return JSONResponse(content={
            "success": True,
            "testcases": result_graph.get("testcases", {})
        })

    except Exception as e:
        logger.error("生成测试用例失败", exc_info=True)
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": f"生成测试用例失败: {str(e)}"
        })


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
