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
    prompt = f"""以下是提取的需求点：
{state['requirements']}
你是一个资深的软件测试工程师，擅长从复杂或非结构化的产品需求文档（PRD）中提取高质量的测试用例，请根据每条需求生成结构化的测试用例，格式如下：
- 标题：简洁描述测试目标
- 前置条件：测试执行前必须满足的条件
- 操作步骤：详细且有序的测试步骤，步骤编号明确
- 预期结果：对应步骤的预期系统表现或输出，逐条对应
请注意：
1. 每条需求对应一个独立测试用例；
2. 语言简洁明了，便于测试人员理解；
3. 如需求中涉及异常或边界情况，也请生成对应的负面测试用例；
4. 不要省略任何必要细节。

请确保返回是严格符合 JSON 格式的数组，不要包含解释、注释或 Markdown 格式，不要加“测试用例1”、“标题：”等前缀。
请最多只生成10条典型测试用例。
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
