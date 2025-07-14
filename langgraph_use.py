import json
import time
import traceback
from typing import TypedDict
from collections import defaultdict
from langgraph.graph import StateGraph
from model_api import call_model
from model_api2 import call_model2
from model_api3 import call_model3
import re
import asyncio
import httpx
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    prd_text: str
    prd_title: str
    requirements: str
    testcases: dict
    validated: str


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


async def extract_prd_title(state: GraphState) -> GraphState:
    logger.info("[Step 2] 尝试直接从 PRD 文本提取标题")
    try:
        lines = state['prd_text'].splitlines()
        for line in lines:
            line = line.strip()
            if line:
                line = re.sub(r"^#+\s*", "", line)
                if len(line) < 50:
                    title = line.strip()
                    logger.info(f"[Step 1] 提取标题成功: {title}")
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


async def extract_requirements(state: GraphState) -> GraphState:
    logger.info("[Step 3] 提取测试点")
    try:
        prompt = f"""你是一位资深测试工程师；
请注意：
1. 避免穷举所有可能情况，仅提取关键且能有代表性的测试点；
2. 可按模块划分（如登录模块、注册模块等），每个测试点简洁明了；
3. 仅基于markdown图文内容中明确描述的内容进行提取，不要自行联想或推测；
4. 覆盖功能、异常、易用性、兼容性、安全性、性能等维度；
5. 不要最后多加说明。
6. 格式如下所示
### 登录模块  
**功能性**：测试点1
**功能性**：测试点2    
**易用性**：测试点1
### 重置初始密码模块
**功能性**：测试点1
**功能性**：测试点2    
**易用性**：测试点1
图像内容在文中已经描述，例如[图像描述]：展示了一个流程图，可结合上下文理解，
根据下面的markdown图文生成测试点
{state['prd_text']}
"""
        requirements = await call_model3(prompt, temperature=0.4)
        logger.info(requirements)
        return {**state, "requirements": requirements.strip()}
    except Exception as e:
        logger.error(f"[Step 3] 测试点提取失败: {e}\n{traceback.format_exc()}")
        raise


async def optimize_requirements(state: GraphState) -> GraphState:
    logger.info("[Step 4] 优化测试点")
    try:
        prompt = f"""你是一位资深测试专家；
要求：
1. 合并相似或重复内容的测试点；
2. 测试点分类清晰，结构清楚；
3. 补充遗漏的关键测试点，确保覆盖以下维度：
   - 功能性
   - 易用性
   - 兼容性
   - 安全性
   - 性能
4. 严格基于已有测试点内容进行优化，不要引入未提及的功能或需求；
5. 无新增就基于原有的测试点展示；
6. 不要在最后加说明。
7. 格式如下所示
### 登录模块  
**功能性**：测试点1
**功能性**：测试点2    
**易用性**：测试点1
### 重置初始密码模块
**功能性**：测试点1
**功能性**：测试点2    
**易用性**：测试点1
根据下面的测试点进行优化：
{state['requirements']}
"""
        optimized = await call_model3(prompt, temperature=0.4)
        logger.info(optimized)
        return {**state, "requirements": optimized.strip()}
    except Exception as e:
        logger.error(f"[Step 4] 优化失败: {e}\n{traceback.format_exc()}")
        raise


MAX_CONCURRENT = 30
MAX_RETRIES = 3


async def generate_case(point: str, idx: int, semaphore: asyncio.Semaphore) -> tuple[str, dict] | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with semaphore:
                start = time.time()
                logger.info(f"生成第 {idx} 个用例，第 {attempt} 次尝试")
                prompt = f"""你是一个专业的测试用例生成专家；
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
- 仅返回合法 JSON，不要包含多余解释说明；
根据以下测试点生成测试用例：
{point}"""
                resp = await call_model2(prompt, temperature=0.2)
                case_json = json.loads(resp)
                if isinstance(case_json, list):
                    case_json = case_json[0]
                duration = time.time() - start
                logger.info(f" 第 {idx} 个用例生成成功，用时 {duration:.2f}s")

                category = case_json.get("category", "functional_test_cases")
                case = {
                    "case_id": f"{idx:03d}",
                    "title": case_json.get("title", ""),
                    "preconditions": case_json.get("precondition", []),
                    "steps": case_json.get("steps", []),
                    "expected_results": case_json.get("expected_results", [])
                }
                return category, case
        except Exception as e:
            error_msg = f"第 {idx} 个测试点失败（第 {attempt} 次）: {str(e)}\n{traceback.format_exc()}"
            logger.warning(error_msg[:1000])
            await asyncio.sleep(1)
    logger.error(f"第 {idx} 个用例多次失败，跳过: {traceback.format_exc()}")
    return None


async def generate_testcases(state: GraphState) -> GraphState:
    logger.info("[Step 5] 生成测试用例")
    try:
        raw_points = [
            line.strip("-• 0123456789.").strip()
            for line in state["requirements"].splitlines()
            if "#" not in line  # 先检查是否包含#
            and line.strip()   # 再检查是否非空
            and len(line.strip()) > 5  # 最后检查长度
        ]
        logger.info(raw_points)
        if not raw_points:
            raise ValueError("未能提取有效的测试点")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        start = time.time()
        tasks = [generate_case(p, i + 1, semaphore) for i, p in enumerate(raw_points)]
        all_results = await asyncio.gather(*tasks)

        grouped_cases = defaultdict(list)
        failed_cases = []

        idx = 1
        for i, result in enumerate(all_results):
            if result is None:
                failed_cases.append({
                    "case_id": f"{i + 1:03d}",
                    "requirement": raw_points[i]
                })
                continue

            category, case = result
            case["case_id"] = f"{idx:03d}"
            grouped_cases[category].append(case)
            idx += 1

        logger.info(
            f"[Step 5] 用例生成完成: 成功 {idx - 1} 个，失败 {len(failed_cases)} 个，用时 {time.time() - start:.2f}s")

        return {
            **state,
            "testcases": {
                "test_suite": state["prd_title"],
                "test_cases": dict(grouped_cases),
                "failed_cases": failed_cases
            }
        }
    except Exception as e:
        logger.error(f"[Step 4] 测试用例生成失败: {e}\n{traceback.format_exc()}")
        raise


async def validate_testcases(state: GraphState) -> GraphState:
    logger.info("[Step 6] 校验测试用例，移除高度一致的重复项")
    try:
        testcases_dict = state.get("testcases", {}).get("test_cases", {})
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
        logger.info(f"[Step 6] 校验完成：{validated_msg}")

        return {
            **state,
            "testcases": {
                "test_suite": state["prd_title"],
                "test_cases": validated_cases
            },
            "validated": validated_msg
        }
    except Exception as e:
        logger.error(f"[Step 5] 校验测试用例失败: {e}\n{traceback.format_exc()}")
        return state


# 构建工作流
workflow = StateGraph(GraphState)
workflow.add_node("step1_image_analysis", analyze_images_from_markdown)
workflow.add_node("step2_extract_title", extract_prd_title)
workflow.add_node("step3_extract_requirements", extract_requirements)
workflow.add_node("step4_optimize_requirements", optimize_requirements)
workflow.add_node("step5_generate_testcases", generate_testcases)
workflow.add_node("step6_validate_testcases", validate_testcases)
workflow.set_entry_point("step1_image_analysis")
workflow.add_edge("step1_image_analysis", "step2_extract_title")
workflow.add_edge("step2_extract_title", "step3_extract_requirements")
workflow.add_edge("step3_extract_requirements", "step4_optimize_requirements")
workflow.add_edge("step4_optimize_requirements", "step5_generate_testcases")
workflow.add_edge("step5_generate_testcases", "step6_validate_testcases")
workflow.set_finish_point("step6_validate_testcases")
graph = workflow.compile()
