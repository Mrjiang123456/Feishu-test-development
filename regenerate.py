import json
import logging
import asyncio
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph
from model_api import call_model
import time

logger = logging.getLogger(__name__)


class RegenerateState(TypedDict):
    prd_text: str
    current_testcases: List[Dict[str, Any]]
    review_report: str
    reason: str
    new_requirements: str
    new_testcases: Dict[str, Any]


async def generate_new_requirements(state: RegenerateState) -> RegenerateState:
    logger.info("[重新生成 Step 1] 根据评测报告和反馈生成新的测试点")
    prompt = f"""你是一位资深测试工程师，结合以下信息，重新生成详细且分类清晰的测试点，包含功能、异常、边界、兼容、安全等维度：
当前测试用例：
{json.dumps(state['current_testcases'], ensure_ascii=False, indent=2)}
AI测评报告：
{state['review_report']}
用户反馈原因：
{state['reason']}
产品需求文档：
{state['prd_text']}
请直接输出测试点列表，格式如下：
- 模块名：
- 测试点1（功能）：
- 测试点2（异常）：
只返回测试点列表，不要解释。"""
    requirements = await call_model(prompt)
    state['new_requirements'] = requirements.strip()
    return state


MAX_CONCURRENT = 30
MAX_RETRIES = 3


async def generate_case(point: str, idx: int, semaphore: asyncio.Semaphore) -> Dict[str, Any] | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with semaphore:
                start = time.time()
                logger.info(f"生成第 {idx} 个用例，第 {attempt} 次尝试")
                prompt = f"""你是一个测试用例生成专家。根据以下测试点，结合产品需求文档中的顺序图文（图片通过 Markdown 格式插入），生成格式规范的测试用例，输出 JSON 格式，字段包括：
    {{
      "title": "简洁明确的测试标题",
      "precondition": "按点列出前置条件，例如 1. 系统正常运行；2. 测试账号已登录",
      "steps": ["1. 打开页面", "2. 输入信息", "3. 点击提交"],
      "expected_results": ["1. 页面跳转成功", "2. 显示欢迎信息"]
    }}
    请仅返回 JSON，不要附加文字。测试点如下：
    {point}"""
                resp = await call_model(prompt)
                case_json = json.loads(resp)
                if isinstance(case_json, list):
                    case_json = case_json[0]
                duration = time.time() - start
                logger.info(f" 第 {idx} 个用例生成成功，用时 {duration:.2f}s")
                return {
                    "case_id": f"{idx:03d}",
                    "title": case_json["title"],
                    "preconditions": case_json["precondition"],
                    "steps": case_json["steps"],
                    "expected_results": case_json["expected_results"]
                }
        except Exception as e:
            logger.warning(f" 第 {idx} 个测试点失败（第 {attempt} 次）：{str(e)[:100]}...")
            await asyncio.sleep(1)
    logger.error(f" 第 {idx} 个用例多次失败，跳过")
    return None


async def generate_refined_testcases(state: RegenerateState) -> RegenerateState:
    logger.info("[重新生成 Step 2] 根据新的测试点生成测试用例")

    raw_points = [
        line.strip("-• 0123456789.").strip()
        for line in state["new_requirements"].splitlines()
        if line.strip()
    ]
    if not raw_points:
        raise ValueError("未能提取有效的测试点")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [generate_case(p, i + 1, semaphore) for i, p in enumerate(raw_points)]
    all_results = await asyncio.gather(*tasks)

    test_cases = [c for c in all_results if c is not None]

    for new_idx, case in enumerate(test_cases, start=1):
        case["case_id"] = f"{new_idx:03d}"

    failed_cases = [
        {"case_id": f"{i + 1:03d}", "requirement": p}
        for i, (p, r) in enumerate(zip(raw_points, all_results)) if r is None
    ]

    logger.info(f"重新生成测试用例完成，成功{len(test_cases)}，失败{len(failed_cases)}")

    state['new_testcases'] = {
        "test_suite": "重新生成测试用例",
        "test_cases": test_cases,
    }
    return state


regenerate_workflow = StateGraph(RegenerateState)
regenerate_workflow.add_node("step1_generate_new_requirements", generate_new_requirements)
regenerate_workflow.add_node("step2_generate_refined_testcases", generate_refined_testcases)

regenerate_workflow.set_entry_point("step1_generate_new_requirements")
regenerate_workflow.add_edge("step1_generate_new_requirements", "step2_generate_refined_testcases")
regenerate_workflow.set_finish_point("step2_generate_refined_testcases")

regenerate_graph = regenerate_workflow.compile()
