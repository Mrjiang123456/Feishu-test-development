import json
import logging
import asyncio
from typing import TypedDict, List
from langgraph.graph import StateGraph
from model_api import call_model
import time
from model_api2 import call_model2
from typing import Tuple, Dict, Any
from collections import defaultdict
import re
import httpx
import traceback
from model_api3 import call_model3

logger = logging.getLogger(__name__)


class RegenerateState(TypedDict):
    prd_title: str
    prd_text: str
    current_testcases: List[Dict[str, Any]]
    review_report: str
    reason: str
    new_requirements: str
    new_testcases: Dict[str, Any]


async def analyze_images_from_markdown(state: dict) -> dict:
    logger.info("[Step 1] 开始处理图像内容")
    text = state.get("prd_text", "")
    image_pattern = re.compile(r'(!\[.*?\]\((.*?)\))')
    matches = list(image_pattern.finditer(text))

    if not matches:
        logger.info("[Step 1] 未检测到图片，跳过此步骤")
        return state

    image_markdowns = [m.group(1) for m in matches]
    image_urls = [m.group(2) for m in matches]
    logger.info(f"[Step 1] 发现 {len(image_urls)} 张图片，开始识别...")

    image_descs = []
    for i, url in enumerate(image_urls, 1):
        try:
            logger.info(f"  处理图片 {i}/{len(image_urls)}: {url[:50]}...")
            prompt = """请仔细阅读图中的内容（这是产品需求文档中的原型图/流程图/界面截图），该图将用于生成测试用例。请按以下要求描述图中内容，确保描述能直接用于提取测试点：
输出要求：
1. 模块划分：按功能模块（如“登录模块”“注册模块”）或页面区域（如顶部导航，表单区域）分块描述，每块内容用“模块名”明确分隔；  
2. 核心交互：重点描述用户操作路径（如用户进入登录页→输入手机号→点击“获取验证码”→输入验证码→点击"登录"），每一步用“步骤X：”标注；  
3. 关键控件：列出所有交互控件（输入框、按钮、下拉菜单等），标注其功能（如“手机号输入框：限制11位数字”“提交按钮：点击后触发登录验证”）；  
4. 状态提示：描述正常/异常状态下的界面反馈（如输入错误手机号时，输入框下方显示红色提示："手机号格式不正确”“提交成功时，页面跳转至首页并显示""登录成功”）；  
5. 忽略细节：无需描述与功能无关的装饰性元素（如图标颜色、背景图案、非交互性文字）。  
输出格式要求：  
1. 语言简洁，避免冗余修饰；  
2. 关键信息（如控件名称、步骤顺序、提示文案）需准确无误；  
3. 整体结构清晰，便于后续提取测试点。
"""
            desc = await call_model(prompt, img_urls=[url])

            desc = desc.strip()
            desc = re.sub(r"^[【图像描述】]+", "", desc)

            desc = f"【图像描述】{desc}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "exceeds the maximum allowed total pixels" in e.response.text:
                logger.warning(f"  图片尺寸过大，使用替代描述: {url}")
                desc = "【图像描述】页面结构示意图"
            else:
                logger.warning(f"  图片识别失败: {str(e)[:100]}")
                desc = "【图像描述】识别失败"
        except Exception as e:
            logger.warning(f"  图片识别失败: {str(e)[:100]}")
            desc = "【图像描述】识别失败"

        image_descs.append(desc)

    # 替换 Markdown 中的图片为文字描述
    for md, desc in zip(image_markdowns, image_descs):
        text = text.replace(md, desc)

    logger.info(f"[Step 1] 图像处理完成，共处理 {len(image_urls)} 张图片")
    logger.info(text)
    return {**state, "prd_text": text}


async def extract_prd_title(state: RegenerateState) -> RegenerateState:
    logger.info("[Step 2] 尝试直接从 PRD 文本提取标题")
    try:
        lines = state['prd_text'].splitlines()
        for line in lines:
            line = line.strip()
            if line:
                line = re.sub(r"^#+\s*", "", line)
                if len(line) < 50:
                    title = line.strip()
                    logger.info(f"[Step 2] 提取标题成功: {title}")
                    return {**state, "prd_title": title}
        logger.info("[Step 2] 未提取成功，调用模型")
        prompt = f"""请从以下产品需求文档中提取模块或系统名称作为文档标题，文中包含顺序图文，图片以 Markdown 格式插入，请结合文本和图片内容理解：
{state['prd_text'][:1500]}
（只返回标题，不要解释）"""
        res = await call_model2(prompt, temperature=0.1)
        title = res.strip().splitlines()[0]
        title = re.sub(r"^#+\s*", "", title).strip()
        return {**state, "prd_title": title}
    except Exception as e:
        logger.warning(f"标题提取失败: {e}\n{traceback.format_exc()}")
        return {**state, "prd_title": "自动生成测试用例"}


async def generate_new_requirements(state: RegenerateState) -> RegenerateState:
    logger.info("[重新生成 Step 3] 根据评测报告和反馈生成新的测试点")
    prompt = f"""你是一位资深测试工程师，结合以下信息，重新生成详细且分类清晰的测试点，包含功能、异常、边界、兼容、安全等维度：
当前测试用例：
{state['current_testcases']}
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
    requirements = await call_model3(prompt)
    state['new_requirements'] = requirements.strip()
    return state


MAX_CONCURRENT = 30
MAX_RETRIES = 3


async def generate_case(point: str, idx: int, semaphore: asyncio.Semaphore) -> Tuple[str, Dict[str, Any]] | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with semaphore:
                start = time.time()
                logger.info(f"生成第 {idx} 个用例，第 {attempt} 次尝试")
                prompt = f"""你是一个专业的测试用例生成专家;
生成 1 条结构清晰、内容完整的测试用例，格式如下：
{{
"category": "五选一，必须为以下之一：
- functional_test_cases
- usability_test_cases
- security_test_cases
- compatibility_test_cases
- performance_test_cases
如无法明确分类，请选择最接近的一类，不要自创类别。",
"title": "简洁明确的测试标题",
"precondition": ["1. 系统正常运行", "2. 用户已登录"],
"steps": ["1. 打开页面", "2. 输入信息", "3. 点击提交"],
"expected_results": ["1. 页面跳转成功", "2. 显示欢迎信息"]
}}
要求：
- 仅返回合法 JSON，不要包含多余解释说明；
测试点如下：
{point}"""
                resp = await call_model2(prompt)
                case_json = json.loads(resp)
                if isinstance(case_json, list):
                    case_json = case_json[0]
                duration = time.time() - start
                logger.info(f" 第 {idx} 个用例生成成功，用时 {duration:.2f}s")

                category = case_json.get("category", "functional_test_cases")

                case = {
                    "case_id": f"{idx:03d}",
                    "title": case_json["title"],
                    "preconditions": case_json["precondition"],
                    "steps": case_json["steps"],
                    "expected_results": case_json["expected_results"]
                }
                return category, case
        except Exception as e:
            logger.warning(f" 第 {idx} 个测试点失败（第 {attempt} 次）：{str(e)[:100]}...")
            await asyncio.sleep(1)
    logger.error(f" 第 {idx} 个用例多次失败，跳过")
    return None


async def generate_refined_testcases(state: RegenerateState) -> RegenerateState:
    logger.info("[重新生成 Step 4] 根据新的测试点生成测试用例")

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

    grouped_cases = defaultdict(list)
    failed_cases = []
    success_idx = 1

    for i, result in enumerate(all_results):
        if result is None:
            failed_cases.append({
                "case_id": f"{i + 1:03d}",
                "requirement": raw_points[i]
            })
            continue

        category, case = result
        case["case_id"] = f"{success_idx:03d}"
        grouped_cases[category].append(case)
        success_idx += 1

    logger.info(f"重新生成测试用例完成，成功 {success_idx - 1}，失败 {len(failed_cases)}")

    state['new_testcases'] = {
        "test_cases": dict(grouped_cases)
    }
    return state


async def validate_testcases(state: RegenerateState) -> RegenerateState:
    logger.info("[Step 5] 校验测试用例，移除高度一致的重复项")
    try:
        testcases_dict = state.get("new_testcases", {}).get("test_cases", {})
        if not testcases_dict:
            logger.warning("无测试用例可校验")
            return {
                **state,
                "validated": "无测试用例"
            }

        validated_cases = {}
        total_removed = 0

        for category, cases in testcases_dict.items():
            seen = set()
            unique_cases = []
            for case in cases:
                key = (case["title"], tuple(case["steps"]), tuple(case["expected_results"]))
                if key not in seen:
                    seen.add(key)
                    unique_cases.append(case)
                else:
                    logger.info(f"移除重复用例: {case['title']} 类别: {category}")

            # 重新编号
            for idx, case in enumerate(unique_cases, start=1):
                case["case_id"] = f"{category[:3].upper()}-{idx:03d}"

            removed_count = len(cases) - len(unique_cases)
            total_removed += removed_count
            validated_cases[category] = unique_cases

        validated_msg = f"共去除重复用例 {total_removed} 条" if total_removed else "未发现重复用例"
        logger.info(f"[Step 5] 校验完成：{validated_msg}")

        return {
            **state,
            "new_testcases": {
                "test_suite": state["prd_title"],
                "test_cases": validated_cases
            },
            "validated": validated_msg
        }
    except Exception as e:
        logger.error(f"[Step 5] 校验测试用例失败: {e}\n{traceback.format_exc()}")
        return state


regenerate_workflow = StateGraph(RegenerateState)
regenerate_workflow.add_node("step1_analyze_images_from_markdown", analyze_images_from_markdown)
regenerate_workflow.add_node("step2_extract_prd_title", extract_prd_title)
regenerate_workflow.add_node("step3_generate_new_requirements", generate_new_requirements)
regenerate_workflow.add_node("step4_generate_refined_testcases", generate_refined_testcases)
regenerate_workflow.add_node("step5_validate_testcases", validate_testcases)
regenerate_workflow.set_entry_point("step1_analyze_images_from_markdown")
regenerate_workflow.add_edge("step1_analyze_images_from_markdown", "step2_extract_prd_title")
regenerate_workflow.add_edge("step2_extract_prd_title", "step3_generate_new_requirements")
regenerate_workflow.add_edge("step3_generate_new_requirements", "step4_generate_refined_testcases")
regenerate_workflow.add_edge("step4_generate_refined_testcases", "step5_validate_testcases")
regenerate_workflow.set_finish_point("step5_validate_testcases")
regenerate_graph = regenerate_workflow.compile()
