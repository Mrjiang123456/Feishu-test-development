from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph_use import graph
from utils import clean_text, fetch_webpage_content
from feishu_api import get_feishu_doc_content
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    prd_text: str | None = None
    web_url: str | None = None

@app.post("/generate-json")
async def generate_testcases_api(request_data: GenerateRequest):
    try:
        images = []
        prd_text = ""

        if request_data.web_url and "feishu.cn/" in request_data.web_url:
            logger.info(f"收到飞书链接: {request_data.web_url}")
            try:
                result = await get_feishu_doc_content(request_data.web_url)
                prd_text = result.get("text", "")
                images = result.get("images", [])
                logger.info(f"飞书文档内容获取成功，文本长度: {len(prd_text)}, 图片数量: {len(images)}")
            except Exception as e:
                logger.error(f"飞书文档内容获取失败: {e}", exc_info=True)
                return JSONResponse(status_code=500, content={
                    "success": False,
                    "error": f"飞书文档内容获取失败: {str(e)}"
                })
        elif request_data.web_url and request_data.web_url.strip():
            logger.info(f"收到网页链接: {request_data.web_url}")
            result = await fetch_webpage_content(request_data.web_url)
            prd_text = result.get("text", "")
            images = result.get("images", [])
        elif request_data.prd_text and request_data.prd_text.strip():
            prd_text = clean_text(request_data.prd_text)
            logger.info(f"收到纯文本PRD，长度: {len(prd_text)}")
        else:
            logger.warning("请求中缺少有效的 prd_text 或 web_url")
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "请提供 prd_text 或 web_url（支持飞书链接与网页链接）"
            })

        initial_state = {
            "prd_text": prd_text,
            "images": images,
            "prd_title": "",
            "requirements": "",
            "testcases": {},
            "validated": ""
        }
        logger.info("开始调用图谱生成测试用例")
        result = await graph.ainvoke(initial_state)
        logger.info("图谱调用完成，生成测试用例成功")

        return JSONResponse(content={
            "success": True,
            "testcases": result.get("testcases", {})
        })

    except Exception as e:
        logger.error("生成测试用例失败", exc_info=True)
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": "生成测试用例失败，请稍后重试。"
        })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
