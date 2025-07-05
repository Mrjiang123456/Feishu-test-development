from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from state import State
from nodes import (
    report_node,
    execute_node,
    create_planner_node,
    update_planner_node
)


def _build_base_graph():
    """Build and return the base state graph with all nodes and edges."""
    builder = StateGraph(State)
    builder.add_edge(START, "create_planner")
    builder.add_node("create_planner", create_planner_node)
    builder.add_node("update_planner", update_planner_node)
    builder.add_node("execute", execute_node)
    builder.add_node("report", report_node)
    builder.add_edge("report", END)
    return builder


def build_graph_with_memory():
    """Build and return the agent workflow graph with memory."""
    memory = MemorySaver()
    builder = _build_base_graph()
    return builder.compile(checkpointer=memory)


def build_graph():
    """Build and return the agent workflow graph without memory."""
    # build state graph
    builder = _build_base_graph()
    return builder.compile()


graph = build_graph()

# user_message = "对所给文档进行分析，生成分析报告，文档路径为student_habits_performance.csv"

# graph.invoke(inputs, {"recursion_limit":100})

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import aiofiles
import asyncio
from fastapi.responses import JSONResponse
from datetime import datetime
import json
from fastapi.staticfiles import StaticFiles


'''
Define api processing 
'''
app = FastAPI(
    title="Visualize API",
    description="Visualize API",
)
# 配置 CORS（允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有域名（生产环境建议限制）
    allow_credentials=True,  # 允许带凭证（如 cookies）
    allow_methods=["*"],  # 允许所有 HTTP 方法（GET/POST/PUT/DELETE 等）
    allow_headers=["*"],  # 允许所有请求头
)
# 挂载静态文件目录
app.mount("/files", StaticFiles(directory="."), name="files")

@app.post("/test")
async def test():
    return {
        "status": "200",
        "message": "success"
    }


async def save_data(data):
    try:
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_cases_{timestamp}.json"
        
        # 异步写入文件
        async with aiofiles.open(filename, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=4, ensure_ascii=False))
            
        print(f"数据已成功保存到 {filename}")
        return {"status": True, "filename": str(filename)}
    
    except Exception as e:
        print(f"保存文件时出错: {str(e)}")
        return {"status": False, "message": str(e)}


@app.post("/visualize")
async def visualize(data: dict):
    try:
        if "test_suite" not in data or "test_cases" not in data:
            return JSONResponse({
                "status": "201",
                "message": "Missing required parameters: test_suite or test_cases"
            })

        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_cases_{timestamp}.json"
        
        # 异步写入文件
        async with aiofiles.open(filename, mode='w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=4, ensure_ascii=False))
    except Exception as e:
        return JSONResponse({
            "status": "500",
            "message": f"{str(e)}"
        })

    try:
        user_message = """
        对所给json数据中的测试用例进行分析，生成分析报告。json文件路径为{dir}
        数据格式如下：
        {{
            "ai_test_cases": {{
                "测试用例": {{
                    "功能测试": [{{"case_id": "...", "title": "...", "preconditions": "...", "steps": [...], "expected_results": "..."}}],
                    "安全性测试": [...],
                    "兼容性测试": [...],
                    "性能测试": [...],
                    "边界测试": [...],
                    "异常测试": [...]
                }}
            }}
        }}
        """
        user_message = user_message.format(dir=filename)
        inputs = {"user_message": REPORT_SYSTEM_PROMPT.format(user_message), 
            "plan": None,
            "observations": [], 
            "final_report": ""}
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, graph.invoke, inputs, {"recursion_limit": 100})
        final_report = result.get('final_report')
        return JSONResponse({
            "status": "200",
            "message": "success",
            "report": "https://visualize.bithao.com.cn/files/{}".format(final_report)
        })
    except Exception as e:
        return JSONResponse({
            "status": "500",
            "message": f"{str(e)}"
        })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


