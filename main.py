import logging
import time
import subprocess
import os
import sys
import datetime
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from langgraph_use import graph
from regenerate import regenerate_graph
from feishu_api import get_feishu_doc_content
import uvicorn

#  日志设置
LOG_FILE_PATH = None


def setup_logging():
    global LOG_FILE_PATH

    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"app_{timestamp}.log"
    LOG_FILE_PATH = os.path.join(log_dir, log_filename)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)

    is_reload = "--reload" in sys.argv or os.getenv("UVICORN_RELOAD")
    if not is_reload:
        root_logger.addHandler(console_handler)

    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = True

    if not is_reload:
        app_logger.info("=" * 50)
        app_logger.info("应用程序启动 - 日志系统初始化完成")
        app_logger.info(f"日志文件路径: {LOG_FILE_PATH}")
        app_logger.info("=" * 50)
    return is_reload


is_reload = setup_logging()
logger = logging.getLogger(__name__)

#  FastAPI 应用
app = FastAPI()

# 跨域设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


#  启动 frpc
def start_frpc():
    try:
        frpc_path = os.path.abspath("frpc.exe")
        config_path = os.path.abspath("frpc.toml")
        logger.info(f"启动 frpc: {frpc_path} -c {config_path}")
        subprocess.Popen(
            [frpc_path, "-c", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.info("frpc 启动成功")
    except Exception as e:
        logger.error(f"frpc 启动失败: {e}")


# 用户 token 校验
# def get_user_token_from_header(request: Request) -> str:
#     token = request.headers.get("user_access_token")
#     if not token:
#         logger.warning("请求缺少 user_access_token 请求头")
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
#     logger.info(f"user_access_token: {token}")
#     return token


#  请求模型
class GenerateRequest(BaseModel):
    document_id: str
    user_access_token: str


class RegenerateRequest(BaseModel):
    review_report: str
    reason: Optional[str] = ""
    testcases: Optional[dict] = None
    document_id: Optional[str] = None
    user_access_token: Optional[str] = None


#  缓存变量
last_testcases = None
last_document_id = None
last_user_access_token = None


#  生成测试用例接口
@app.post("/generate-cases")
async def generate_testcases_api(request: Request, request_data: GenerateRequest):
    # user_token = get_user_token_from_header(request)

    global last_testcases, last_document_id, last_user_access_token
    try:
        logger.info(f"收到飞书请求，document_id={request_data.document_id}")
        result = await get_feishu_doc_content(request_data.document_id, request_data.user_access_token)
        prd_text = result.get("markdown")
        logger.info(f"提取的 PRD 文本:\n{prd_text}")

        if not prd_text:
            return JSONResponse({"success": False, "error": "文档内容为空"}, status_code=400)

        initial_state = {
            "prd_text": prd_text,
            "prd_title": "",
            "requirements": "",
            "testcases": {},
            "validated": ""
        }

        start_time = time.time()
        logger.info("开始调用图谱生成测试用例")
        result_graph = await graph.ainvoke(initial_state)
        duration = time.time() - start_time
        logger.info(f"生成测试用例成功，耗时 {duration:.2f} 秒")

        testcases = result_graph.get("testcases")
        last_testcases = testcases
        last_document_id = request_data.document_id
        last_user_access_token = request_data.user_access_token

        return JSONResponse({"success": True, "testcases": testcases})

    except Exception as e:
        logger.error("生成测试用例失败", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# 重新生成测试用例接口
@app.post("/regenerate-cases")
async def regenerate_testcases_api(request: Request, request_data: RegenerateRequest):
    global last_testcases, last_document_id, last_user_access_token
    try:
        # 优先使用新参数，否则 fallback 到历史缓存
        current_testcases = request_data.testcases or last_testcases
        document_id = request_data.document_id or last_document_id
        user_token = request_data.user_access_token or last_user_access_token

        if not (current_testcases):
            logger.info("缺少必要参数，且历史缓存为空，请先调用 /generate_cases")
            return JSONResponse(
                {"success": False, "error": "缺少必要参数，且历史缓存为空，请先调用 /generate_cases"},
                status_code=400
            )

        if document_id and user_token:
            try:
                result = await get_feishu_doc_content(document_id, user_token)
                prd_text = result.get("markdown")
                logger.info(f"提取的 PRD 文本:\n{prd_text}")

                if not prd_text:
                    return JSONResponse({"success": False, "error": "飞书文档内容为空"}, status_code=400)
            except Exception as e:
                logger.error(f"从飞书获取文档内容失败: {str(e)}")
                return JSONResponse({"success": False, "error": f"从飞书获取文档内容失败: {str(e)}"}, status_code=500)
        else:
            logger.info("没有提供飞书文档ID和token，跳过文档获取步骤")

            prd_text = ""

        initial_state = {
            "prd_text": prd_text,
            "current_testcases": current_testcases,
            "review_report": request_data.review_report,
            "reason": request_data.reason or "",
            "new_requirements": "",
            "new_testcases": {}
        }

        logger.info("调用图谱重新生成测试用例")
        start_time = time.time()
        result_graph = await regenerate_graph.ainvoke(initial_state)
        duration = time.time() - start_time
        logger.info(f"重新生成成功，耗时 {duration:.2f} 秒")

        new_testcases = result_graph.get("new_testcases")
        if new_testcases:
            last_testcases = new_testcases
            last_document_id = document_id
            last_user_access_token = user_token

        return JSONResponse({"success": True, "testcases": new_testcases})

    except Exception as e:
        logger.error("重新生成失败", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/test")
async def test():
    return JSONResponse(content={"success": True})


if __name__ == "__main__":
    start_frpc()
    reload_flag = "--reload" in sys.argv

    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=reload_flag,
        log_config=None,
        timeout_keep_alive=300,
        timeout_graceful_shutdown=300,
        access_log=False
    )

    server = uvicorn.Server(config)
    server.run()
