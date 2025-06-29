from langgraph.graph import StateGraph
from typing import TypedDict
from model_api import call_doubao_model
import json
import re


class GraphState(TypedDict):
    prd_text: str
    images: list[str]
    requirements: str
    testcases: list[dict]


# 第一步：从 PRD 文本中提取关键需求点
async def extract_requirements(state: GraphState) -> GraphState:
    prompt = f"""你是一位产品分析专家，请从以下图文 PRD 中提取关键功能需求点：

PRD文字如下：\n{state['prd_text']}

如有图片，可作为参考：\n{chr(10).join(state.get('images', []))}。

请输出清晰分条的需求点，每条需求用阿拉伯数字编号：
1. xxx
2. xxx
...
"""
    requirements = await call_doubao_model(prompt)
    return {
        "requirements": requirements.strip(),
        "images": state.get("images", [])
    }


# 第二步：将需求逐条生成结构化测试用例
async def generate_testcases(state: GraphState) -> GraphState:
    raw_points = re.findall(r"\d+\.\s*(.+)", state["requirements"])
    if not raw_points:
        raise ValueError(f"未能识别需求点，请检查提取内容：\n{state['requirements']}")

    all_testcases = []
    for i, point in enumerate(raw_points, start=1):
        prompt = f"""
你是一个智能测试用例生成代理（Test Agent），根据以下功能需求和参考图片，生成一条结构化测试用例：

需求点：
{point}

参考图片：
{chr(10).join(state.get('images', []))}

请使用以下 JSON 格式输出：
{{
  "title": "测试用例标题，概括测试目标",
  "precondition": "执行前的准备条件",
  "steps": ["步骤1", "步骤2", ...],
  "expected_results": ["步骤1的预期", "步骤2的预期", ...]
}}

要求：
1. 步骤与预期结果一一对应；
2. 内容完整，语义清晰；
3. 输出必须是严格的 JSON 格式，不能包含解释、注释或 markdown；
4. 仅输出 JSON 结构。
"""
        try:
            response = await call_doubao_model(prompt)
            testcase = json.loads(response)
            all_testcases.append(testcase)
        except Exception as e:
            raise ValueError(f"第{i}条需求生成失败: {e}\n原始输出为:\n{response}")

    return {
        "testcases": all_testcases
    }


# 构建 LangGraph 工作流
workflow = StateGraph(GraphState)
workflow.add_node("extract_requirements", extract_requirements)
workflow.add_node("generate_testcases", generate_testcases)
workflow.set_entry_point("extract_requirements")
workflow.add_edge("extract_requirements", "generate_testcases")
workflow.set_finish_point("generate_testcases")

graph = workflow.compile()
