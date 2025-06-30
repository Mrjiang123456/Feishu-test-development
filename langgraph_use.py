import json
import re
import logging
import asyncio
import time
from typing import TypedDict
from langgraph.graph import StateGraph
from model_api import call_doubao_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class GraphState(TypedDict):
    prd_text: str
    prd_title: str
    images: list[str]
    requirements: str
    testcases: dict
    validated: str

async def extract_prd_title(state: GraphState) -> GraphState:
    logger.info("[Step 1] 尝试直接从 PRD 文本提取标题")
    lines = state['prd_text'].splitlines()
    for line in lines:
        line = line.strip()
        if line:
            line = re.sub(r"^#+\s*", "", line)
            if len(line) < 50:
                title = line.strip()
                logger.info(f"[Step 1] 提取标题成功: {title}")
                return {**state, "prd_title": title}
    logger.info("[Step 1] 未提取成功，调用模型")
    prompt = f"""请从以下产品需求中提取模块或系统名称作为文档标题：
    {state['prd_text'][:1500]}
    （只返回标题，不要解释）"""
    try:
        res = await call_doubao_model(prompt)
        title = res.strip().splitlines()[0]
        title = re.sub(r"^#+\s*", "", title).strip()
    except Exception as e:
        logger.warning(f"标题提取失败，使用默认标题: {e}")
        title = "自动生成测试用例"
    return {**state, "prd_title": title}

async def extract_requirements(state: GraphState) -> GraphState:
    logger.info("[Step 2] 提取测试点")
    prompt = f"""你是一位资深测试工程师，正在根据产品需求文档分析功能测试点。请根据以下 PRD 文本提取测试点（功能、易用、异常等维度），按模块分类：\n{state['prd_text']}\n如有图像信息：\n{chr(10).join(state.get('images', []))}\n请按如下格式：\n- 模块名：\n  - 测试点1：\n  - 测试点2：\n"""
    try:
        requirements = await call_doubao_model(prompt)
        return {**state, "requirements": requirements.strip()}
    except Exception as e:
        logger.error(f"[Step 2] 测试点提取失败: {e}")
        raise

async def optimize_requirements(state: GraphState) -> GraphState:
    logger.info("[Step 3] 优化测试点")
    prompt = f"""你是一位测试专家，请对以下功能测试点内容进行检查和优化：
目标：
1. 查漏补缺；
2. 确保测试点覆盖功能、易用性、兼容性、安全性、性能等；
3. 分类清晰，每个测试点都归属到模块，并注明测试维度（功能/异常/边界/兼容/安全等）请优化以下测试点内容，补充遗漏，分类清晰，并注明测试维度：\n{state['requirements']}"""
    try:
        optimized = await call_doubao_model(prompt)
        return {**state, "requirements": optimized.strip()}
    except Exception as e:
        logger.error(f"[Step 3] 优化失败: {e}")
        raise

MAX_CONCURRENT = 10
MAX_RETRIES = 3

async def generate_case(point: str, idx: int, semaphore: asyncio.Semaphore) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with semaphore:
                start = time.time()
                logger.info(f"生成第 {idx} 个用例，第 {attempt} 次尝试")
                prompt = f"""你是一个测试用例生成专家，请将下列测试点转为格式规范的测试用例，输出格式为 JSON（务必符合以下字段）：\n{{\n  \"title\": \"简洁明确的测试标题\",\n  \"precondition\": \"按点列出前置条件，例如 1. 系统正常运行；2. 测试账号已登录\",\n  \"steps\": [\"1. 打开页面\", \"2. 输入信息\", \"3. 点击提交\"],\n  \"expected_results\": [\"1. 页面跳转成功\", \"2. 显示欢迎信息\"]\n}}\n请仅返回 JSON，不要附加文字。测试点如下：\n{point}"""
                resp = await call_doubao_model(prompt)
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

async def generate_testcases(state: GraphState) -> GraphState:
    logger.info("[Step 4] 生成测试用例")
    raw_points = [
        line.strip("-• 0123456789.").strip()
        for line in state["requirements"].splitlines()
        if line.strip() and len(line.strip()) > 4
    ]
    if not raw_points:
        raise ValueError("未能提取有效的测试点")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    start = time.time()
    tasks = [generate_case(p, i + 1, semaphore) for i, p in enumerate(raw_points)]
    all_results = await asyncio.gather(*tasks)

    test_cases = [c for c in all_results if c is not None]
    failed_cases = [
        {"case_id": f"{i + 1:03d}", "requirement": p}
        for i, (p, r) in enumerate(zip(raw_points, all_results)) if r is None
    ]

    logger.info(f"[Step 4] 用例生成完成: 成功 {len(test_cases)} 个，失败 {len(failed_cases)} 个，用时 {time.time() - start:.2f}s")
    return {
        **state,
        "testcases": {
            "test_suite": state["prd_title"],
            "test_cases": test_cases,
            "failed_cases": failed_cases
        }
    }

async def validate_testcases(state: GraphState) -> GraphState:
    logger.info("[Step 5] 重试生成失败的测试用例")
    testcases = state.get("testcases", {}).get("test_cases", [])
    failed = state.get("testcases", {}).get("failed_cases", [])

    if not failed:
        logger.info("无失败用例，无需重试")
        return {
            **state,
            "testcases": {
                "test_suite": state["prd_title"],
                "test_cases": testcases,
                "failed_cases": []
            },
            "validated": "全部测试用例已生成成功"
        }

    logger.info(f"开始重试 {len(failed)} 个失败用例")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def retry_case(item: dict):
        for retry in range(MAX_RETRIES):
            try:
                async with semaphore:
                    logger.info(f"重试失败用例 {item['case_id']}, 第 {retry + 1} 次")
                    prompt = f"""请将以下测试点转为测试用例 JSON：\n{{\n  "title": "...",\n  "precondition": "...",\n  "steps": ["..."],\n  "expected_results": ["..."]\n}}\n\n测试点：\n{item['requirement']}"""
                    res = await call_doubao_model(prompt)
                    data = json.loads(res)
                    if isinstance(data, list):
                        data = data[0]
                    return {
                        "case_id": item["case_id"],
                        "title": data["title"],
                        "preconditions": data["precondition"],
                        "steps": data["steps"],
                        "expected_results": data["expected_results"]
                    }
            except Exception as e:
                logger.warning(f"重试失败: {e}")
                await asyncio.sleep(1)
        logger.error(f"用例 {item['case_id']} 多次重试失败，跳过")
        return None

    retry_results = await asyncio.gather(*[retry_case(item) for item in failed])

    successful_retries = [r for r in retry_results if r is not None]
    remaining_failed = [f for f, r in zip(failed, retry_results) if r is None]

    testcases += successful_retries

    validated_msg = f"重试后成功补全 {len(successful_retries)} 条用例" if successful_retries else "重试未成功"

    return {
        **state,
        "testcases": {
            "test_suite": state["prd_title"],
            "test_cases": testcases,
            "failed_cases": remaining_failed
        },
        "validated": validated_msg
    }


workflow = StateGraph(GraphState)
workflow.add_node("step1_extract_title", extract_prd_title)
workflow.add_node("step2_extract_requirements", extract_requirements)
workflow.add_node("step3_optimize_requirements", optimize_requirements)
workflow.add_node("step4_generate_testcases", generate_testcases)
workflow.add_node("step5_validate_testcases", validate_testcases)

workflow.set_entry_point("step1_extract_title")
workflow.add_edge("step1_extract_title", "step2_extract_requirements")
workflow.add_edge("step2_extract_requirements", "step3_optimize_requirements")
workflow.add_edge("step3_optimize_requirements", "step4_generate_testcases")
workflow.add_edge("step4_generate_testcases", "step5_validate_testcases")
workflow.set_finish_point("step5_validate_testcases")

graph = workflow.compile()
