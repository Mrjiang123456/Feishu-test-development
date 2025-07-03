from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langgraph_use import graph
from regenerate import regenerate_graph
from feishu_api import get_feishu_doc_content
import logging
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()


class GenerateRequest(BaseModel):
    document_id: str
    user_access_token: str


class RegenerateRequest(BaseModel):
    document_id: str
    user_access_token: str
    current_testcases: list
    review_report: str
    reason: str


@app.post("/generate-cases")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        logger.info(f"收到飞书请求，document_id={request_data.document_id}")

        # 获取飞书文档内容
        result = await get_feishu_doc_content(request_data.document_id, request_data.user_access_token)
        prd_text = result.get("markdown")
        logger.info(prd_text)

        if not prd_text:
            return JSONResponse({"success": False, "error": "文档内容为空"}, status_code=400)

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

        return JSONResponse({
            "success": True,
            "testcases": result_graph.get("testcases")
        })

    except Exception as e:
        logger.error("生成测试用例失败", exc_info=True)
        return JSONResponse({"success": False, "error": f"生成测试用例失败: {str(e)}"}, status_code=500)


@app.post("/regenerate-cases")
async def regenerate_testcases_api(request_data: RegenerateRequest):
    try:
        # 重新从飞书获取 PRD 文本
        result = await get_feishu_doc_content(request_data.document_id, request_data.user_access_token)
        prd_text = result.get("markdown")
        logger.info(prd_text)

        if not prd_text:
            return JSONResponse({"success": False, "error": "飞书文档内容为空"}, status_code=400)

        logger.info("开始调用重新生成图谱")
        initial_state = {
            "prd_text": prd_text,
            "current_testcases": request_data.current_testcases,
            "review_report": request_data.review_report,
            "reason": request_data.reason,
            "new_requirements": "",
            "new_testcases": {}
        }

        result_graph = await regenerate_graph.ainvoke(initial_state)
        logger.info("重新生成成功")

        return JSONResponse({
            "success": True,
            "testcases": result_graph.get("new_testcases")
        })

    except Exception as e:
        logger.error("重新生成失败", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
