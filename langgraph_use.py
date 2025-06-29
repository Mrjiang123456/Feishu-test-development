from langgraph.graph import StateGraph
from typing import TypedDict
from model_api import call_doubao_model
import json

# 定义状态类型，每一步都基于 GraphState 传递状态
class GraphState(TypedDict):
    prd_text: str
    requirements: str
    testcases: str

# 第一步：从 PRD 文本中提取关键需求点
async def extract_requirements(state: GraphState) -> GraphState:
    prompt = f"请从以下 PRD 文档中提取关键需求点（列出每一条）：\n{state['prd_text']}"
    requirements = await call_doubao_model(prompt)
    return {"requirements": requirements.strip()}

# 第二步：根据需求生成结构化测试用例
async def generate_testcases(state: GraphState) -> GraphState:
    prompt = f"""你是一个智能测试用例生成代理（TestAgent），用户提供了多个PRD需求点，你需要为每个需求点生成高质量的结构化测试用例。
请根据以下格式，为每条需求生成一条测试用例：
示例格式：
[
  {{
    "标题": "登录-正常流程-非首次登录",
    "前置条件": "用户已注册有效账号",
    "操作步骤": [
      "1. 打开登录页面",
      "2. 输入正确用户名",
      "3. 输入正确密码",
      "4. 点击登录按钮"
    ],
    "预期结果": [
      "1. 登录成功",
      "2. 跳转至首页"
    ]
  }}
]

请遵守以下约定：
1. 每条需求点对应一条测试用例；
2. 步骤（steps）和预期结果（expected_results）必须一一对应；
3. 如有异常/边界场景，也请生成相应用例；
4. 语言简洁、规范，便于测试人员直接执行；
5. 输出为严格的 JSON 数组，不包含解释、注释或 Markdown。

以下是提取的需求点：
{state['requirements']}
"""
    raw_response = await call_doubao_model(prompt)
    try:
        testcases = json.loads(raw_response)
    except Exception as e:
        raise ValueError(f"JSON解析失败: {e}\n模型原始输出为:\n{raw_response}")

    return {"testcases": testcases}


workflow = StateGraph(GraphState)
workflow.add_node("extract_requirements", extract_requirements)
workflow.add_node("generate_testcases", generate_testcases)
workflow.set_entry_point("extract_requirements")
workflow.add_edge("extract_requirements", "generate_testcases")
workflow.set_finish_point("generate_testcases")

graph = workflow.compile()
