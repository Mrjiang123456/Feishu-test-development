import json
import aiohttp
from logger import log, log_error, end_logging
from llm_api import async_call_llm, extract_valid_json
from analyzer import find_duplicate_test_cases
import re
import asyncio
import concurrent.futures
from config import MAX_CONCURRENT_REQUESTS, LLM_TEMPERATURE, LLM_TEMPERATURE_REPORT, ENABLE_MULTI_JUDGES, ENABLE_COLLAB_EVAL
from typing import Dict
import time
import uuid
import os

# 在文件顶部导入委员会评测功能
try:
    from committee import evaluate_with_committee

    COMMITTEE_IMPORTED = True
except ImportError:
    log_error("无法导入评委委员会模块，将使用单一模型评测", level="WARNING")
    COMMITTEE_IMPORTED = False


async def evaluate_test_cases(session: aiohttp.ClientSession, ai_cases, golden_cases, is_iteration=False, prev_iteration_cases=None):
    """
    评测测试用例质量

    :param session: aiohttp会话
    :param ai_cases: AI生成的测试用例
    :param golden_cases: 黄金标准测试用例
    :param is_iteration: 是否启用迭代前后对比功能
    :param prev_iteration_cases: 上一次迭代的测试用例（可选），仅在is_iteration为true时有效
    :return: 评测结果
    """
    log("开始测试用例评测", important=True)
    if is_iteration and prev_iteration_cases:
        log("启用迭代前后对比功能，将分析测试用例迭代改进情况", important=True)

    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.05)

    # 获取所有测试用例
    ai_testcases = []
    golden_testcases = []
    prev_testcases = []

    # 定义格式化函数，便于并行处理
    def extract_ai_testcases(ai_cases):
        result = []
        # 提取AI测试用例，适配新的格式化结构
        if isinstance(ai_cases, dict):
            if "testcases" in ai_cases and isinstance(ai_cases["testcases"], dict):
                # 新的统一格式
                if "test_cases" in ai_cases["testcases"]:
                    # 处理test_cases可能是字典(包含不同类别的测试用例)的情况
                    if isinstance(ai_cases["testcases"]["test_cases"], dict):
                        for category, cases in ai_cases["testcases"]["test_cases"].items():
                            if isinstance(cases, list):
                                for case in cases:
                                    if isinstance(case, dict):
                                        case["category"] = category
                                    result.append(case)
                    # 处理test_cases是列表的情况
                    elif isinstance(ai_cases["testcases"]["test_cases"], list):
                        result = ai_cases["testcases"]["test_cases"]
            elif "test_cases" in ai_cases:
                if isinstance(ai_cases["test_cases"], dict):
                    # 旧格式，分类测试用例
                    for category, cases in ai_cases["test_cases"].items():
                        if isinstance(cases, list):
                            result.extend(cases)
                elif isinstance(ai_cases["test_cases"], list):
                    # 旧格式，直接列表
                    result = ai_cases["test_cases"]
        return result

    def extract_golden_testcases(golden_cases):
        result = []
        # 提取黄金标准测试用例，适配新的格式化结构
        if isinstance(golden_cases, dict):
            if "testcases" in golden_cases and isinstance(golden_cases["testcases"], dict):
                # 新的统一格式
                if "test_cases" in golden_cases["testcases"]:
                    # 处理test_cases可能是字典(包含不同类别的测试用例)的情况
                    if isinstance(golden_cases["testcases"]["test_cases"], dict):
                        for category, cases in golden_cases["testcases"]["test_cases"].items():
                            if isinstance(cases, list):
                                for case in cases:
                                    if isinstance(case, dict):
                                        case["category"] = category
                                    result.append(case)
                    # 处理test_cases是列表的情况
                    elif isinstance(golden_cases["testcases"]["test_cases"], list):
                        result = golden_cases["testcases"]["test_cases"]
            elif "test_cases" in golden_cases:
                if isinstance(golden_cases["test_cases"], dict):
                    # 旧格式，分类测试用例
                    for category, cases in golden_cases["test_cases"].items():
                        if isinstance(cases, list):
                            result.extend(cases)
                elif isinstance(golden_cases["test_cases"], list):
                    # 旧格式，直接列表
                    result = golden_cases["test_cases"]
        return result
        
    # 提取上一次迭代测试用例
    def extract_prev_testcases(prev_cases):
        # 复用提取AI测试用例的逻辑
        return extract_ai_testcases(prev_cases)

    # 并行执行AI测试用例和黄金标准测试用例的格式化处理
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        ai_future = executor.submit(extract_ai_testcases, ai_cases)
        golden_future = executor.submit(extract_golden_testcases, golden_cases)
        
        if is_iteration and prev_iteration_cases:
            prev_future = executor.submit(extract_prev_testcases, prev_iteration_cases)
            prev_testcases = prev_future.result()

        ai_testcases = ai_future.result()
        golden_testcases = golden_future.result()

    log(f"AI测试用例数量: {len(ai_testcases)}, 黄金标准测试用例数量: {len(golden_testcases)}", important=True)
    if is_iteration and prev_testcases:
        log(f"上一次迭代测试用例数量: {len(prev_testcases)}", important=True)

    # 检查重复的测试用例
    ai_duplicate_info = find_duplicate_test_cases(ai_testcases)
    golden_duplicate_info = find_duplicate_test_cases(golden_testcases)
    
    # 如果启用迭代对比，也检查上一次迭代的测试用例重复情况
    if is_iteration and prev_testcases:
        prev_duplicate_info = find_duplicate_test_cases(prev_testcases)
        log(f"上一次迭代测试用例重复率: {prev_duplicate_info['duplicate_rate']}% ({prev_duplicate_info['duplicate_count']}个)",
            important=True)

    log(f"AI测试用例重复率: {ai_duplicate_info['duplicate_rate']}% ({ai_duplicate_info['duplicate_count']}个)",
        important=True)
    log(f"黄金标准测试用例重复率: {golden_duplicate_info['duplicate_rate']}% ({golden_duplicate_info['duplicate_count']}个)",
        important=True)

    # 记录重复类型分布
    log(f"AI测试用例重复类型分布: {json.dumps(ai_duplicate_info['duplicate_types'], ensure_ascii=False)}",
        important=True)
    if ai_duplicate_info['duplicate_categories']:
        log(f"AI测试用例按类别重复率: {json.dumps(ai_duplicate_info['duplicate_categories'], ensure_ascii=False)}",
            important=True)

    # 提取合并建议
    merge_suggestions_count = len(ai_duplicate_info.get("merge_suggestions", []))
    log(f"生成了 {merge_suggestions_count} 条AI测试用例合并建议", important=True)

    # 构建评测提示
    duplicate_info_text = f"""
# 测试用例重复情况
## AI测试用例重复情况
- 重复率: {ai_duplicate_info['duplicate_rate']}%
- 重复测试用例数量: {ai_duplicate_info['duplicate_count']}个
- 标题重复的测试用例数量: {len(ai_duplicate_info['title_duplicates'])}个
- 步骤高度相似的测试用例数量: {len(ai_duplicate_info['steps_duplicates'])}个
- 合并建议数量: {merge_suggestions_count}个

## 黄金标准测试用例重复情况
- 重复率: {golden_duplicate_info['duplicate_rate']}%
- 重复测试用例数量: {golden_duplicate_info['duplicate_count']}个
- 标题重复的测试用例数量: {len(golden_duplicate_info['title_duplicates'])}个
- 步骤高度相似的测试用例数量: {len(golden_duplicate_info['steps_duplicates'])}个

如果AI测试用例的重复率明显高于黄金标准，请在改进建议中提出减少重复测试用例的建议。
"""

    # 如果启用迭代对比，添加迭代对比信息
    iteration_comparison_text = ""
    if is_iteration and prev_testcases:
        # 分析迭代前后的测试用例变化
        prev_count = len(prev_testcases)
        current_count = len(ai_testcases)
        count_change = current_count - prev_count
        count_change_percent = (count_change / prev_count * 100) if prev_count > 0 else 0
        
        # 分析重复率变化
        prev_duplicate_rate = prev_duplicate_info['duplicate_rate']
        current_duplicate_rate = ai_duplicate_info['duplicate_rate']
        duplicate_rate_change = current_duplicate_rate - prev_duplicate_rate
        
        # 计算功能覆盖变化（通过分类或标题分析）
        prev_categories = set()
        current_categories = set()
        
        for case in prev_testcases:
            category = case.get("category", "")
            if category:
                prev_categories.add(category)
            # 从标题中提取功能点
            title = case.get("title", "")
            if "功能" in title:
                feature = title.split("功能")[0] + "功能"
                prev_categories.add(feature)
            elif "测试" in title:
                feature = title.split("测试")[0]
                prev_categories.add(feature)
        
        for case in ai_testcases:
            category = case.get("category", "")
            if category:
                current_categories.add(category)
            # 从标题中提取功能点
            title = case.get("title", "")
            if "功能" in title:
                feature = title.split("功能")[0] + "功能"
                current_categories.add(feature)
            elif "测试" in title:
                feature = title.split("测试")[0]
                current_categories.add(feature)
        
        # 新增功能点
        new_categories = current_categories - prev_categories
        # 移除的功能点
        removed_categories = prev_categories - current_categories
        
        # 构建迭代对比信息
        iteration_comparison_text = f"""
# 迭代前后对比分析
## 测试用例数量变化
- 上一次迭代: {prev_count}个测试用例
- 当前迭代: {current_count}个测试用例
- 变化量: {count_change}个测试用例 ({count_change_percent:.2f}%)

## 重复率变化
- 上一次迭代重复率: {prev_duplicate_rate}%
- 当前迭代重复率: {current_duplicate_rate}%
- 变化量: {duplicate_rate_change:.2f}个百分点

## 功能覆盖变化
- 新增功能点: {len(new_categories)}个
- 移除功能点: {len(removed_categories)}个
"""
        
        # 添加新增和移除的功能点详情
        if new_categories:
            iteration_comparison_text += "\n### 新增功能点\n"
            for category in new_categories:
                iteration_comparison_text += f"- {category}\n"
        
        if removed_categories:
            iteration_comparison_text += "\n### 移除功能点\n"
            for category in removed_categories:
                iteration_comparison_text += f"- {category}\n"
                
        # 添加具体用例差异分析
        iteration_comparison_text += "\n## 测试用例质量变化分析\n"
        
        # 对比具体测试用例属性，如步骤数量、预期结果数量等
        prev_avg_steps = sum(len(case.get("steps", [])) for case in prev_testcases) / prev_count if prev_count > 0 else 0
        current_avg_steps = sum(len(case.get("steps", [])) for case in ai_testcases) / current_count if current_count > 0 else 0
        steps_change = current_avg_steps - prev_avg_steps
        steps_change_percent = (steps_change / prev_avg_steps * 100) if prev_avg_steps > 0 else 0
        
        prev_avg_expected = sum(len(case.get("expected_results", [])) for case in prev_testcases) / prev_count if prev_count > 0 else 0
        current_avg_expected = sum(len(case.get("expected_results", [])) for case in ai_testcases) / current_count if current_count > 0 else 0
        expected_change = current_avg_expected - prev_avg_expected
        expected_change_percent = (expected_change / prev_avg_expected * 100) if prev_avg_expected > 0 else 0
        
        iteration_comparison_text += f"""
- 平均步骤数变化: {prev_avg_steps:.2f} → {current_avg_steps:.2f} ({steps_change_percent:.2f}%)
- 平均预期结果数变化: {prev_avg_expected:.2f} → {current_avg_expected:.2f} ({expected_change_percent:.2f}%)

请根据以上对比信息，分析当前迭代相比上一次迭代的主要优缺点，并提出具体的改进建议。
"""
        
        log("已生成迭代前后对比分析", important=True)

    # 如果有合并建议，添加到提示中
    if merge_suggestions_count > 0:
        duplicate_info_text += "\n## AI测试用例合并建议\n"
        for i, suggestion in enumerate(ai_duplicate_info.get("merge_suggestions", [])):
            suggestion_type = "标题重复" if suggestion["type"] == "title_duplicate" else "步骤相似"
            case_ids = ", ".join(suggestion["case_ids"][:3])
            if len(suggestion["case_ids"]) > 3:
                case_ids += f" 等{len(suggestion['case_ids'])}个用例"

            merged_case = suggestion["merged_case"]
            duplicate_info_text += f"\n### 合并建议 {i + 1}（{suggestion_type}）\n"
            duplicate_info_text += f"- 涉及用例: {case_ids}\n"
            duplicate_info_text += f"- 合并后标题: {merged_case['title']}\n"

            # 添加步骤和预期结果摘要
            steps = merged_case.get("steps", "")
            if isinstance(steps, list) and len(steps) > 0:
                steps_preview = steps[0]
                if len(steps) > 1:
                    steps_preview += f" ... 等{len(steps)}个步骤"
                duplicate_info_text += f"- 合并后步骤: {steps_preview}\n"

            expected = merged_case.get("expected_results", "")
            if isinstance(expected, list) and len(expected) > 0:
                expected_preview = expected[0]
                if len(expected) > 1:
                    expected_preview += f" ... 等{len(expected)}个预期结果"
                duplicate_info_text += f"- 合并后预期结果: {expected_preview}\n"

    # 判断是否使用多评委委员会评测
    if ENABLE_MULTI_JUDGES and COMMITTEE_IMPORTED:
        log("启用多评委委员会评测", important=True)
        
        # 如果启用了CollabEval框架且不是迭代对比模式，记录到日志
        use_collab_eval = ENABLE_COLLAB_EVAL and not is_iteration
        if use_collab_eval:
            log("使用CollabEval三阶段评测框架 (独立评分->辩论协作->主席聚合)", important=True)
        else:
            if is_iteration:
                log("迭代对比模式下使用标准多评委评测框架，不启用CollabEval", important=True)
            else:
                log("使用标准多评委评测框架 (独立评分->结果聚合)", important=True)
            
        try:
            # 调用委员会评测，添加迭代对比信息
            if is_iteration and iteration_comparison_text:
                evaluation_result = await evaluate_with_committee(
                    session,
                    ai_testcases,
                    golden_testcases,
                    duplicate_info_text + "\n" + iteration_comparison_text,
                    use_collab_eval=False  # 迭代对比模式下强制使用标准多评委评测
                )
            else:
                evaluation_result = await evaluate_with_committee(
                    session,
                    ai_testcases,
                    golden_testcases,
                    duplicate_info_text,
                    use_collab_eval=use_collab_eval  # 根据条件决定是否使用CollabEval
                )

            if evaluation_result:
                if use_collab_eval:
                    log("CollabEval三阶段评测完成", important=True)
                else:
                    log("多评委委员会评测完成", important=True)

                # 将重复测试用例信息添加到评测结果中
                evaluation_result["duplicate_types"] = ai_duplicate_info['duplicate_types']
                evaluation_result["duplicate_categories"] = ai_duplicate_info.get('duplicate_categories', {})
                evaluation_result["duplicate_info"] = {
                    "ai_duplicate_rate": ai_duplicate_info['duplicate_rate'],
                    "golden_duplicate_rate": golden_duplicate_info['duplicate_rate'],
                    "merge_suggestions": ai_duplicate_info.get("merge_suggestions", [])
                }
                
                # 如果启用迭代对比，添加迭代对比信息
                if is_iteration and prev_testcases:
                    evaluation_result["iteration_comparison"] = {
                        "is_iteration": True,
                        "prev_count": len(prev_testcases),
                        "current_count": len(ai_testcases),
                        "count_change": len(ai_testcases) - len(prev_testcases),
                        "prev_duplicate_rate": prev_duplicate_info['duplicate_rate'],
                        "current_duplicate_rate": ai_duplicate_info['duplicate_rate'],
                        "new_categories": list(new_categories) if 'new_categories' in locals() else [],
                        "removed_categories": list(removed_categories) if 'removed_categories' in locals() else []
                    }

                # 明确标记为综合评测结果
                if "evaluation_summary" in evaluation_result:
                    if "final_suggestion" in evaluation_result["evaluation_summary"]:
                        # 检查评估框架
                        framework_type = "Standard"
                        if "evaluation_framework" in evaluation_result:
                            framework_type = evaluation_result["evaluation_framework"]
                        elif "committee_summary" in evaluation_result and "evaluation_framework" in evaluation_result["committee_summary"]:
                            framework_type = evaluation_result["committee_summary"]["evaluation_framework"]
                        
                        # 确定前缀
                        prefix = "【CollabEval三阶段综合评测】" if framework_type == "CollabEval" else "【多评委综合评测】"
                        if is_iteration:
                            prefix = "【迭代对比分析】" + prefix
                        evaluation_result["evaluation_summary"]["final_suggestion"] = prefix + \
                                                                                     evaluation_result[
                                                                                         "evaluation_summary"][
                                                                                         "final_suggestion"]

                    # 添加综合评测标记
                    evaluation_result["is_committee_result"] = True
                    evaluation_result["collab_eval_result"] = framework_type == "CollabEval"
                    evaluation_result["evaluation_framework"] = framework_type
                    evaluation_result["is_iteration_comparison"] = is_iteration and bool(prev_testcases)
                    evaluation_result["committee_info"] = {
                        "judge_count": len(evaluation_result.get("committee_summary", {}).get("judge_scores", {})),
                        "judges": list(evaluation_result.get("committee_summary", {}).get("judge_scores", {}).keys()),
                        "evaluation_framework": framework_type
                    }

                return evaluation_result
            else:
                log_error("多评委委员会评测失败，回退到单一模型评测", important=True)
                # 如果委员会评测失败，回退到单一模型评测
        except Exception as e:
            log_error(f"多评委委员会评测出错: {e}", important=True)
            log("回退到单一模型评测", important=True)

    # 单一模型评测流程
    log("使用单一模型进行评测", important=True)

    # 构建完整提示
    prompt = f"""
# 任务
评估AI生成的测试用例与黄金标准测试用例的质量对比。
"""

    # 如果是迭代对比，增加迭代对比任务说明
    if is_iteration and prev_testcases:
        prompt += f"""
# 迭代对比任务
本次评估包含迭代前后对比分析，需要重点关注测试用例在本次迭代中的质量改进情况，并提出针对性建议。
"""

    prompt += """
# 评估维度和权重
1. **功能覆盖度**（权重30%）：评估需求覆盖率、边界值覆盖度、分支路径覆盖率
2. **缺陷发现能力**（权重25%）：评估缺陷检测率、突变分数、失败用例比例
3. **工程效率**（权重20%）：评估测试用例生成速度、维护成本、CI/CD集成度
4. **语义质量**（权重15%）：评估语义准确性、人工可读性、断言描述清晰度
5. **安全与经济性**（权重10%）：评估恶意代码率、冗余用例比例、综合成本
"""

    # 添加重复测试用例信息
    prompt += "\n" + duplicate_info_text + "\n"
    
    # 如果启用迭代对比，添加迭代对比信息
    if is_iteration and iteration_comparison_text:
        prompt += "\n" + iteration_comparison_text + "\n"

    # 添加评分公式
    prompt += """
# 评分公式
总分 = 0.3×功能覆盖得分 + 0.25×缺陷发现得分 + 0.2×工程效率得分 + 0.15×语义质量得分 + 0.1×安全经济得分
各维度得分 = (AI指标值/人工基准值)×10（满分10分）

# AI生成的测试用例
```json
"""
    # 添加AI测试用例
    prompt += json.dumps(ai_testcases, ensure_ascii=False, indent=2) + "\n```\n\n"

    # 添加黄金标准测试用例
    prompt += """
# 黄金标准测试用例
```json
"""
    prompt += json.dumps(golden_testcases, ensure_ascii=False, indent=2) + "\n```\n\n"
    
    # 如果启用迭代对比，添加上一次迭代的测试用例
    if is_iteration and prev_testcases:
        prompt += """
# 上一次迭代的测试用例
```json
"""
        prompt += json.dumps(prev_testcases, ensure_ascii=False, indent=2) + "\n```\n\n"

    # 添加输出要求
    prompt += """
# 输出要求
必须严格按照以下JSON格式输出评估结果，不要添加任何额外内容，不要使用```json或其他代码块包装，不要返回Markdown格式内容。直接输出下面这种JSON结构：

```json
{
  "evaluation_summary": {
    "overall_score": "分数（1-5之间的一位小数）",
    "final_suggestion": "如何改进测试用例生成的建议，如有较高的重复率，请提出降低重复的建议"
  },
  "detailed_report": {
    "format_compliance": {
      "score": "格式合规性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "content_accuracy": {
      "score": "内容准确性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "test_coverage": {
      "score": "测试覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由",
      "analysis": {
        "covered_features": [
          "已覆盖功能1",
          "已覆盖功能2"
        ],
        "missed_features_or_scenarios": [
          "未覆盖功能/场景1",
          "未覆盖功能/场景2"
        ],
        "scenario_types_found": [
          "发现的场景类型，如正面用例、负面用例、边界用例等"
        ]
      }
    },
    "functional_coverage": {
      "score": "功能覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "defect_detection": {
      "score": "缺陷发现能力得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "engineering_efficiency": {
      "score": "工程效率得分（1-5之间的一位小数）",
      "reason": "得分理由，如有较高的重复率，请在此处提及"
    },
    "semantic_quality": {
      "score": "语义质量得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "security_economy": {
      "score": "安全与经济性得分（1-5之间的一位小数）",
      "reason": "得分理由，如有较高的重复率，请在此处提及冗余率"
    },
    "duplicate_analysis": {
      "score": "测试用例重复分析得分（1-5之间的一位小数）",
      "reason": "分析重复测试用例的影响",
      "merge_suggestions": "具体如何合并重复测试用例的建议，可以参考我提供的合并建议"
    }"""
    
    # 如果启用迭代对比，添加迭代对比评估维度
    if is_iteration:
        prompt += """,
    "iteration_comparison": {
      "score": "迭代改进得分（1-5之间的一位小数）",
      "reason": "对比本次迭代与上一次迭代的改进情况，分析主要优势和不足",
      "key_improvements": [
        "主要改进点1",
        "主要改进点2"
      ],
      "key_regressions": [
        "主要退步点1",
        "主要退步点2"
      ],
      "next_iteration_suggestions": [
        "下一次迭代改进建议1",
        "下一次迭代改进建议2"
      ]
    }"""
    
    prompt += """
  }"""
    
    # 添加重复类型信息
    prompt += f""",
  "duplicate_types": {{
    "title": {ai_duplicate_info['duplicate_types'].get('title', 0)},
    "steps": {ai_duplicate_info['duplicate_types'].get('steps', 0)},
    "expected_results": {ai_duplicate_info['duplicate_types'].get('expected_results', 0)},
    "mixed": {ai_duplicate_info['duplicate_types'].get('mixed', 0)}
  }},
  "duplicate_categories": {json.dumps(ai_duplicate_info.get('duplicate_categories', {}))}"""
    
    # 如果启用迭代对比，添加迭代对比结果
    if is_iteration and prev_testcases:
        prompt += f""",
  "iteration_comparison_data": {{
    "prev_count": {len(prev_testcases)},
    "current_count": {len(ai_testcases)},
    "count_change_percent": {(len(ai_testcases) - len(prev_testcases)) / len(prev_testcases) * 100 if len(prev_testcases) > 0 else 0:.2f},
    "prev_duplicate_rate": {prev_duplicate_info['duplicate_rate']},
    "current_duplicate_rate": {ai_duplicate_info['duplicate_rate']},
    "duplicate_rate_change": {ai_duplicate_info['duplicate_rate'] - prev_duplicate_info['duplicate_rate']:.2f},
    "new_categories_count": {len(new_categories) if 'new_categories' in locals() else 0},
    "removed_categories_count": {len(removed_categories) if 'removed_categories' in locals() else 0}
  }}"""
    
    prompt += """
}
```
"""

    system_prompt = "你是一位精通软件测试和技术文档写作的专家。请根据评估结果生成一份专业、清晰的Markdown格式报告，并使用Mermaid图表可视化关键数据。请直接保留并使用我提供的评分表格格式，不要修改其结构。请直接输出Markdown格式，不要尝试输出JSON。严格禁止在文档开头添加'markdown'这个词，直接以'# '开头的标题开始。不要在内容外包含```或```markdown标记，完全避免使用代码块，但保留提供的Mermaid图表语法。"

    # 使用较低的temperature值，确保评测结果的一致性和准确性
    result = await async_call_llm(
        session,
        prompt,
        system_prompt,
        temperature=LLM_TEMPERATURE,  # 使用配置中的低temperature值
        use_cache=False  # 禁用缓存，确保每次评测都是全新的
    )

    if not result:
        log("测试用例评测失败", important=True)
        return None

    log("测试用例评测完成", important=True)
    return result


# 添加测试覆盖流程图生成函数
def generate_test_coverage_flow_chart(test_cases, evaluation_result=None):
    """
    根据测试用例内容动态生成测试覆盖流程图

    :param test_cases: 测试用例列表或包含分类测试用例的字典
    :param evaluation_result: 评测结果数据（可选）
    :return: Mermaid格式的流程图
    """
    # 从配置文件导入测试覆盖率分析相关配置
    from config import COVERAGE_KEYWORDS, COVERAGE_FULL_THRESHOLD, COVERAGE_PARTIAL_THRESHOLD
    
    # 辅助函数：转义Mermaid图表中的特殊字符
    def escape_mermaid_text(text):
        """转义Mermaid图表中的特殊字符，确保节点文本正确显示"""
        if not isinstance(text, str):
            return str(text)
        
        # 替换双引号为单引号，避免Mermaid语法错误
        text = text.replace('"', "'")
        # 替换中文双引号为单引号
        text = text.replace("“", "'")
        text = text.replace("”", "'")
        # 处理全角直引号
        text = text.replace('＂', "'")
        # 处理中文直角引号
        text = text.replace('『', "'")
        text = text.replace('』', "'")
        
        # 替换其他可能导致Mermaid语法错误的字符
        text = text.replace("[", "(")
        text = text.replace("]", ")")
        text = text.replace("{", "(")
        text = text.replace("}", ")")
        
        return text
    
    # 初始化覆盖状态
    coverage_status = {
        "功能验证": "missing",  # 默认为未覆盖
        "异常处理": "missing",
        "边界测试": "missing",
        "输入验证": "missing",
        "超时处理": "missing",
        "安全检查": "missing",
        "最大值测试": "missing",
        "最小值测试": "missing"
    }
    
    # 功能分类计数器
    feature_counts = {
        "功能验证": 0,
        "异常处理": 0,
        "边界测试": 0,
        "输入验证": 0,
        "超时处理": 0,
        "安全检查": 0,
        "最大值测试": 0,
        "最小值测试": 0
    }
    
    # 提取测试用例ID中的功能模块信息
    modules = {}
    submodules = {}

    # 使用配置文件中的关键词列表
    keywords = COVERAGE_KEYWORDS
    
    # 处理测试用例，统一转换为列表格式
    all_test_cases = []
    
    # 检查test_cases是否是字典（包含分类的测试用例）
    if isinstance(test_cases, dict):
        # 遍历字典中的每个分类
        for category, cases in test_cases.items():
            if isinstance(cases, list):
                # 为每个测试用例添加category标记
                for case in cases:
                    if isinstance(case, dict):
                        case_copy = case.copy()
                        case_copy["category"] = category.lower()
                        all_test_cases.append(case_copy)
    elif isinstance(test_cases, list):
        # 如果已经是列表，直接使用
        all_test_cases = test_cases
    
    # 如果all_test_cases为空，尝试其他格式解析
    if not all_test_cases:
        # 尝试处理testcases.test_cases格式
        if isinstance(test_cases, dict) and "testcases" in test_cases:
            if isinstance(test_cases["testcases"], dict) and "test_cases" in test_cases["testcases"]:
                test_cases_data = test_cases["testcases"]["test_cases"]
                if isinstance(test_cases_data, dict):
                    # 处理按类别组织的测试用例
                    for category, cases in test_cases_data.items():
                        if isinstance(cases, list):
                            for case in cases:
                                if isinstance(case, dict):
                                    case_copy = case.copy()
                                    case_copy["category"] = category.lower()
                                    all_test_cases.append(case_copy)
                elif isinstance(test_cases_data, list):
                    all_test_cases = test_cases_data

    # 从测试用例分析覆盖情况
    for case in all_test_cases:
        case_id = case.get("case_id", "")
        title = case.get("title", "").lower()
        category = case.get("category", "").lower()
        
        # 直接检查category是否为特定类型
        if category == "functional" or case_id.startswith("FT-"):
            feature_counts["功能验证"] += 1
        
        if category == "security" or case_id.startswith("ST-"):
            feature_counts["安全检查"] += 1
        
        if category == "exception" or case_id.startswith("ET-"):
            feature_counts["异常处理"] += 1
            
        if category == "boundary" or case_id.startswith("BT-"):
            feature_counts["边界测试"] += 1
            # 对于边界测试，默认也增加最大值和最小值测试的计数
            # 除非标题中明确指出是最大值或最小值测试
            if "最大" in title or "上限" in title or "最高" in title or "最多" in title:
                feature_counts["最大值测试"] += 1
            elif "最小" in title or "下限" in title or "最低" in title or "最少" in title:
                feature_counts["最小值测试"] += 1
            else:
                # 如果没有明确指出，则同时增加两者的计数
                feature_counts["最大值测试"] += 1
                feature_counts["最小值测试"] += 1
        
        # 深入分析测试用例内容
        steps = []
        if "steps" in case and isinstance(case["steps"], list):
            steps = [step.lower() if isinstance(step, str) else "" for step in case["steps"]]
        
        expected_results = []
        if "expected_results" in case and isinstance(case["expected_results"], list):
            expected_results = [result.lower() if isinstance(result, str) else "" for result in case["expected_results"]]
        elif "expected_results" in case and isinstance(case["expected_results"], str):
            expected_results = [case["expected_results"].lower()]
        
        preconditions = ""
        if "preconditions" in case and case["preconditions"]:
            if isinstance(case["preconditions"], str):
                preconditions = case["preconditions"].lower()
            elif isinstance(case["preconditions"], list):
                preconditions = " ".join([p.lower() if isinstance(p, str) else "" for p in case["preconditions"]])
        
        # 合并所有文本内容进行分析
        all_text = title + " " + category + " " + case_id + " " + preconditions + " " + " ".join(steps) + " " + " ".join(expected_results)
        
        # 基于关键词分析覆盖类型
        for feature, feature_keywords in keywords.items():
            for keyword in feature_keywords:
                if keyword.lower() in all_text:
                    feature_counts[feature] += 1
                    break  # 找到一个关键词就跳出内层循环
        
        # 特殊规则：如果测试用例包含"登录"、"注册"等核心功能词，视为功能验证
        core_features = ["登录", "注册", "查询", "搜索", "创建", "删除", "修改", "更新", "上传", "下载"]
        for core in core_features:
            if core in all_text:
                feature_counts["功能验证"] += 1
                break
        
        # 特殊规则：如果测试用例描述了输入验证相关内容
        input_validation_patterns = ["输入", "填写", "输入框", "字段", "表单", "必填", "选填", "有效", "无效"]
        for pattern in input_validation_patterns:
            if pattern in all_text and ("验证" in all_text or "检查" in all_text or "校验" in all_text):
                feature_counts["输入验证"] += 1
                break
        
        # 特殊规则：识别边界测试 - 基于内容关键词
        if not (category == "boundary" or case_id.startswith("BT-")):  # 避免重复计数
            if any(boundary in all_text for boundary in ["边界", "极限", "临界"]):
                if any(value in all_text for value in ["值", "数量", "长度", "大小", "范围"]):
                    feature_counts["边界测试"] += 1
                    # 细分为最大值或最小值测试
                    if any(max_val in all_text for max_val in ["最大", "上限", "最高", "最多"]):
                        feature_counts["最大值测试"] += 1
                    if any(min_val in all_text for min_val in ["最小", "下限", "最低", "最少"]):
                        feature_counts["最小值测试"] += 1

        # 提取主要功能模块和子功能模块
        parts = case_id.split('-')
        if len(parts) >= 2:
            main_module = parts[0]
            if len(parts) >= 3:
                sub_module = parts[1]

                # 记录模块
                if main_module not in modules:
                    modules[main_module] = 0
                modules[main_module] += 1

                # 记录子模块
                module_key = f"{main_module}-{sub_module}"
                if module_key not in submodules:
                    submodules[module_key] = {
                        "name": sub_module,
                        "parent": main_module,
                        "count": 0
                    }
                submodules[module_key]["count"] += 1

    # 根据功能计数调整覆盖状态
    # 如果计数大于0但评估结果未覆盖，设为"partial"
    for feature, count in feature_counts.items():
        # 使用配置文件中的阈值，但确保至少有一个用例就标记为covered
        if count >= COVERAGE_FULL_THRESHOLD:  # 如果有足够多的用例覆盖该功能，认为是完全覆盖
            coverage_status[feature] = "covered"
        elif count >= COVERAGE_PARTIAL_THRESHOLD:  # 如果有至少一定数量的用例覆盖该功能，认为是部分覆盖
            coverage_status[feature] = "partial"
        
        # 特别处理：确保有任何边界测试用例时，边界测试状态为covered
        if feature == "边界测试" and count > 0:
            coverage_status[feature] = "covered"

    # 边界测试特殊处理：确保边界测试用例存在时，最大值和最小值测试状态也被设置
    if feature_counts["边界测试"] > 0:
        # 确保边界测试本身被标记为覆盖
        coverage_status["边界测试"] = "covered"
        
        # 如果有边界测试，但没有明确的最大值或最小值测试，则将两者设为部分覆盖
        if feature_counts["最大值测试"] == 0:
            coverage_status["最大值测试"] = "partial"
        else:
            coverage_status["最大值测试"] = "covered"
        
        if feature_counts["最小值测试"] == 0:
            coverage_status["最小值测试"] = "partial"
        else:
            coverage_status["最小值测试"] = "covered"

    # 提取主要功能和子功能的关系
    # 如果测试用例标题中包含类似"xx流程"、"xx功能"、"xx验证"等词语，提取为功能点
    features = {}
    for case in all_test_cases:
        title = case.get("title", "")
        if not title:
            continue

        # 尝试提取功能点
        feature = None
        if "流程" in title:
            feature = title.split("流程")[0] + "流程"
        elif "功能" in title:
            feature = title.split("功能")[0] + "功能"
        elif "验证" in title:
            feature = title.split("验证")[0] + "验证"
        elif "-" in title:
            feature = title.split("-")[0]
        elif "：" in title or ":" in title:
            feature = title.split("：")[0].split(":")[0]
        else:
            # 如果没有特定标识，使用前三个词作为功能点
            words = title.split()
            if words:
                feature = words[0]
                if len(words) > 1:
                    feature += words[1]

        if feature and len(feature) <= 20:  # 限制功能点名称长度
            if feature not in features:
                features[feature] = {
                    "count": 0,
                    "subfeatures": set()
                }
            features[feature]["count"] += 1

            # 尝试提取子功能点
            steps = case.get("steps", [])
            for step in steps:
                if isinstance(step, str) and step:
                    # 提取步骤中的关键动作
                    words = step.split("。")[0].split()
                    action = ""
                    for word in words:
                        if "点击" in word or "输入" in word or "选择" in word or "验证" in word:
                            action = word
                            break
                    
                    if action and len(action) <= 15:
                        features[feature]["subfeatures"].add(action)

    # 按测试用例数量排序功能点
    sorted_features = sorted(features.items(), key=lambda x: x[1]["count"], reverse=True)

    # 生成Mermaid图表
    chart = "```mermaid\ngraph TD\n"

    # 添加主节点 - 使用转义函数处理节点文本
    chart += f"    A[\"{escape_mermaid_text('测试覆盖范围')}\"] --> B[\"{escape_mermaid_text('功能验证')}\"]\n"
    chart += f"    A --> C[\"{escape_mermaid_text('异常处理')}\"]\n"
    chart += f"    A --> D[\"{escape_mermaid_text('边界测试')}\"]\n"

    # 根据实际功能点动态生成子节点
    # 如果有提取到实际功能点，使用它们；否则，使用默认节点
    if sorted_features:
        # 添加主要功能点（最多6个，避免图表过大）
        node_id = 0
        node_map = {}
        edge_set = set()  # 避免重复的边

        for i, (feature, info) in enumerate(sorted_features[:6]):
            if i >= 6:
                break

            node_id += 1
            feature_node = f"F{node_id}"
            node_map[feature] = feature_node

            # 添加功能点节点 - 使用转义函数处理节点文本
            chart += f"    B --> {feature_node}[\"{escape_mermaid_text(feature)}\"]\n"

            # 添加子功能点（每个功能点最多添加3个子功能）
            subfeatures = list(info["subfeatures"])[:3]
            for j, subfeature in enumerate(subfeatures):
                if j >= 3:
                    break

                node_id += 1
                subfeature_node = f"SF{node_id}"

                # 创建边的标识
                edge = f"{feature_node}->{subfeature_node}"

                # 避免添加重复的边
                if edge not in edge_set:
                    # 使用转义函数处理节点文本
                    chart += f"    {feature_node} --> {subfeature_node}[\"{escape_mermaid_text(subfeature)}\"]\n"
                    edge_set.add(edge)
    
    # 添加异常处理示例节点 - 使用转义函数处理节点文本
    chart += f"    C --> E1[\"{escape_mermaid_text('输入验证')}\"]\n"
    chart += f"    C --> E2[\"{escape_mermaid_text('超时处理')}\"]\n"
    chart += f"    C --> E3[\"{escape_mermaid_text('安全检查')}\"]\n"

    # 添加边界测试示例节点 - 使用转义函数处理节点文本
    chart += f"    D --> B1[\"{escape_mermaid_text('最大值测试')}\"]\n"
    chart += f"    D --> B2[\"{escape_mermaid_text('最小值测试')}\"]\n"
    
    # 添加CSS类定义，用不同颜色表示覆盖状态
    chart += "\n    classDef covered fill:#b6d7a8,stroke:#6aa84f;\n"
    chart += "    classDef partial fill:#ffe599,stroke:#f1c232;\n"
    chart += "    classDef missing fill:#ea9999,stroke:#e06666;\n"
    
    # 根据动态分析的覆盖状态添加类标记
    covered_nodes = []
    partial_nodes = []
    missing_nodes = []
    
    # 主要节点映射
    node_mapping = {
        "功能验证": "B",
        "异常处理": "C",
        "边界测试": "D",
        "输入验证": "E1",
        "超时处理": "E2",
        "安全检查": "E3",
        "最大值测试": "B1",
        "最小值测试": "B2"
    }
    
    # 根据覆盖状态分类节点
    for feature, status in coverage_status.items():
        if feature in node_mapping:
            node = node_mapping[feature]
            if status == "covered":
                covered_nodes.append(node)
            elif status == "partial":
                partial_nodes.append(node)
            else:
                missing_nodes.append(node)
    
    # 添加节点分类 - 确保即使列表为空也添加类定义
    chart += "\n"
    if covered_nodes:
        chart += f"    class {','.join(covered_nodes)} covered;\n"
    else:
        chart += "    %% 没有已覆盖的节点\n"
    
    if partial_nodes:
        chart += f"    class {','.join(partial_nodes)} partial;\n"
    else:
        chart += "    %% 没有部分覆盖的节点\n"
    
    if missing_nodes:
        chart += f"    class {','.join(missing_nodes)} missing;\n"
    else:
        chart += "    %% 没有未覆盖的节点\n"

    # 强制设置边界测试相关节点的样式
    if coverage_status["边界测试"] == "covered":
        chart += f"    class D covered;\n"
    if coverage_status["最大值测试"] == "covered" or coverage_status["最大值测试"] == "partial":
        chart += f"    class B1 {coverage_status['最大值测试']};\n"
    if coverage_status["最小值测试"] == "covered" or coverage_status["最小值测试"] == "partial":
        chart += f"    class B2 {coverage_status['最小值测试']};\n"

    chart += "```\n"
    
    # 添加图例说明
    chart += "\n> 🟢 已覆盖 | 🟡 部分覆盖 | 🔴 未覆盖  \n"
    
    # 添加覆盖状态描述
    coverage_description = "**覆盖现状**：  \n"
    
    # 分类覆盖状态
    covered_features = []
    partial_features = []
    missing_features = []
    
    for feature, status in coverage_status.items():
        if status == "covered":
            covered_features.append(feature)
        elif status == "partial":
            partial_features.append(feature)
        else:
            # 检查是否有相关测试用例，如果没有则不列为缺失项
            if feature in feature_counts and feature_counts[feature] > 0:
                missing_features.append(feature)
            # 对于关键功能点，即使没有用例也标记为缺失
            elif feature in ["功能验证", "异常处理", "边界测试", "安全检查"]:
                missing_features.append(feature)
    
    # 添加已覆盖功能
    if covered_features:
        coverage_description += "- 🟢 **已覆盖**：" + "、".join(covered_features) + "  \n"
    
    # 添加部分覆盖功能
    if partial_features:
        coverage_description += "- 🟡 **部分覆盖**：" + "、".join(partial_features) + "  \n"
    
    # 添加未覆盖功能
    if missing_features:
        coverage_description += "- 🔴 **未覆盖**：" + "、".join(missing_features) + "  \n"
    
    # 补充详细分析，根据评测结果中的描述
    if evaluation_result and isinstance(evaluation_result, dict):
        if "detailed_report" in evaluation_result and "test_coverage" in evaluation_result["detailed_report"]:
            test_coverage = evaluation_result["detailed_report"]["test_coverage"]
            if "reason" in test_coverage:
                reason = test_coverage["reason"]
                if reason:
                    coverage_description += "\n**测试覆盖分析**：  \n" + reason + "  \n"
    
    # 将覆盖状态描述添加到测试覆盖图后面
    chart += "\n" + coverage_description + "\n"
    
    # 打印调试信息，帮助诊断问题
    print(f"DEBUG: 测试用例总数: {len(all_test_cases)}")
    print(f"DEBUG: 功能计数: {feature_counts}")
    print(f"DEBUG: 覆盖状态: {coverage_status}")
    print(f"DEBUG: 已覆盖节点: {covered_nodes}")
    print(f"DEBUG: 部分覆盖节点: {partial_nodes}")
    print(f"DEBUG: 未覆盖节点: {missing_nodes}")

    # 修复图表语法中的双引号问题
    def fix_mermaid_chart_syntax(chart_text):
        """修复Mermaid图表中的语法问题，特别是双引号相关问题"""
        # 替换所有中文双引号为英文双引号
        chart_text = chart_text.replace(""", "\"").replace(""", "\"")
        
        # 修复节点定义中的双引号问题 - 确保使用英文双引号
        chart_text = re.sub(r'(\w+)\["([^"]+)"\]', r'\1["\2"]', chart_text)
        
        return chart_text

    # 在返回图表前修复语法
    chart = fix_mermaid_chart_syntax(chart)

    return chart


async def generate_markdown_report(session: aiohttp.ClientSession, evaluation_result, is_iteration=False, formatted_ai_cases=None, formatted_prev_cases=None):
    """
    生成Markdown格式的评测报告

    :param session: aiohttp会话
    :param evaluation_result: 评测结果
    :param is_iteration: 是否启用迭代前后对比功能
    :param formatted_ai_cases: 格式化后的AI测试用例（可选），用于迭代对比
    :param formatted_prev_cases: 格式化后的上一次迭代测试用例（可选），用于迭代对比
    :return: Markdown格式的报告
    """
    log("开始生成Markdown报告", important=True)
    
    # 在迭代模式下生成精简报告，只包含合并建议和改进建议
    if is_iteration:
        log("生成包含迭代对比分析的精简报告，只包含合并建议和改进建议", important=True)
        log(f"参数检查: is_iteration={is_iteration}, formatted_ai_cases类型={type(formatted_ai_cases)}, formatted_prev_cases类型={type(formatted_prev_cases)}")
        log(f"评测结果类型: {type(evaluation_result)}, 是字典: {isinstance(evaluation_result, dict)}")
        if isinstance(evaluation_result, dict):
            log(f"评测结果键: {', '.join(evaluation_result.keys())}")
            if "iteration_comparison" in evaluation_result:
                log("评测结果中包含迭代对比数据")
            elif "iteration_comparison_data" in evaluation_result:
                log("评测结果中包含迭代对比数据(data)")
            else:
                log("警告: 评测结果中不包含迭代对比数据", level="WARNING")
        
        # 确保日志记录按照正确的顺序执行
        await asyncio.sleep(0.05)  # 添加小延迟，确保日志顺序
        
        if not isinstance(evaluation_result, dict):
            return "# 迭代评测报告生成失败\n\n无法解析评测结果，请检查数据格式。"
        
        # 检查实际使用的评估框架
        actual_framework = "Standard"
        if "evaluation_framework" in evaluation_result:
            actual_framework = evaluation_result["evaluation_framework"]
        elif "committee_summary" in evaluation_result and "evaluation_framework" in evaluation_result["committee_summary"]:
            actual_framework = evaluation_result["committee_summary"]["evaluation_framework"]
        elif "committee_info" in evaluation_result and "evaluation_framework" in evaluation_result["committee_info"]:
            actual_framework = evaluation_result["committee_info"]["evaluation_framework"]
        
        # 根据实际评估框架设置标志
        is_using_collab_eval = actual_framework == "CollabEval"
        
        # 生成精简的迭代对比报告
        simplified_report = "# 🔄 迭代前后对比分析报告\n\n"
        
        # 添加总体评分信息
        if "evaluation_summary" in evaluation_result:
            overall_score = evaluation_result["evaluation_summary"].get("overall_score", "N/A")
            simplified_report += f"## 总体评分\n\n**总体评分**: {overall_score}/5.0\n\n"
            
            # 添加最终建议
            final_suggestion = evaluation_result["evaluation_summary"].get("final_suggestion", "无建议")
            
            # 替换可能不正确的评测框架描述
            if "【CollabEval三阶段综合评测】" in final_suggestion and not is_using_collab_eval:
                final_suggestion = final_suggestion.replace("【CollabEval三阶段综合评测】", "【多评委综合评测】")
            elif "【多评委综合评测】" in final_suggestion and is_using_collab_eval:
                final_suggestion = final_suggestion.replace("【多评委综合评测】", "【CollabEval三阶段综合评测】")
                
            simplified_report += f"## 总体建议\n\n{final_suggestion}\n\n"
        
        # 添加合并建议部分
        simplified_report += "## 🛠️ 合并建议\n\n"
        
        # 从evaluation_result中提取合并建议
        merge_suggestions = []
        if "duplicate_info" in evaluation_result and "merge_suggestions" in evaluation_result["duplicate_info"]:
            merge_suggestions = evaluation_result["duplicate_info"]["merge_suggestions"]
        elif "detailed_report" in evaluation_result and "duplicate_analysis" in evaluation_result["detailed_report"]:
            if "merge_suggestions" in evaluation_result["detailed_report"]["duplicate_analysis"]:
                merge_suggestions = evaluation_result["detailed_report"]["duplicate_analysis"]["merge_suggestions"]
        
        if merge_suggestions:
            if isinstance(merge_suggestions, str):
                # 如果merge_suggestions是字符串，直接添加
                simplified_report += merge_suggestions + "\n\n"
            elif isinstance(merge_suggestions, list) and len(merge_suggestions) > 0:
                # 如果是列表，遍历添加每个合并建议
                for i, suggestion in enumerate(merge_suggestions):
                    simplified_report += f"### 合并建议 {i+1}\n\n"
                    if isinstance(suggestion, dict):
                        # 提取重要信息
                        case_ids = suggestion.get("case_ids", [])
                        case_ids_str = ", ".join(str(case_id) for case_id in case_ids[:5])
                        if len(case_ids) > 5:
                            case_ids_str += f"... 等{len(case_ids)}个"
                            
                        if "merged_case" in suggestion:
                            merged_case = suggestion["merged_case"]
                            simplified_report += f"- **涉及测试用例**: {case_ids_str}\n"
                            simplified_report += f"- **合并后标题**: {merged_case.get('title', '无标题')}\n"
                            
                            # 添加步骤和预期结果摘要
                            steps = merged_case.get("steps", [])
                            if steps and len(steps) > 0:
                                simplified_report += "- **合并后步骤**:\n"
                                for step in steps[:3]:
                                    simplified_report += f"  - {step}\n"
                                if len(steps) > 3:
                                    simplified_report += f"  - ...等{len(steps)}个步骤\n"
                                    
                            expected = merged_case.get("expected_results", [])
                            if expected and len(expected) > 0:
                                simplified_report += "- **合并后预期结果**:\n"
                                for exp in expected[:3]:
                                    simplified_report += f"  - {exp}\n"
                                if len(expected) > 3:
                                    simplified_report += f"  - ...等{len(expected)}个预期结果\n"
                    else:
                        simplified_report += f"{suggestion}\n"
                    
                    simplified_report += "\n"
            else:
                simplified_report += "未找到需要合并的测试用例。\n\n"
        else:
            simplified_report += "未找到需要合并的测试用例。\n\n"
        
        # 添加改进建议部分
        simplified_report += "## 📝 改进建议\n\n"
        
        # 从迭代对比中提取改进建议
        if "detailed_report" in evaluation_result and "iteration_comparison" in evaluation_result["detailed_report"]:
            iteration_comparison = evaluation_result["detailed_report"]["iteration_comparison"]
            
            # 添加迭代对比分数
            score = iteration_comparison.get("score", "N/A")
            simplified_report += f"**迭代改进得分**: {score}/5.0\n\n"
            
            # 添加主要改进点
            if "key_improvements" in iteration_comparison and iteration_comparison["key_improvements"]:
                simplified_report += "### 主要改进点\n\n"
                for improvement in iteration_comparison["key_improvements"]:
                    simplified_report += f"✅ {improvement}\n"
                simplified_report += "\n"
                
            # 添加主要退步点
            if "key_regressions" in iteration_comparison and iteration_comparison["key_regressions"]:
                simplified_report += "### 主要退步点\n\n"
                for regression in iteration_comparison["key_regressions"]:
                    simplified_report += f"⚠️ {regression}\n"
                simplified_report += "\n"
                
            # 添加下一次迭代建议
            if "next_iteration_suggestions" in iteration_comparison and iteration_comparison["next_iteration_suggestions"]:
                simplified_report += "### 下一次迭代建议\n\n"
                for suggestion in iteration_comparison["next_iteration_suggestions"]:
                    simplified_report += f"📝 {suggestion}\n"
                simplified_report += "\n"
                
            # 添加简要理由说明
            if "reason" in iteration_comparison:
                reason = iteration_comparison["reason"]
                # 如果理由太长，只取前300个字符
                if len(reason) > 300:
                    simplified_report += f"### 简要分析\n\n{reason[:300]}...\n\n"
                else:
                    simplified_report += f"### 简要分析\n\n{reason}\n\n"
        else:
            # 提取一般性改进建议
            if "evaluation_summary" in evaluation_result and "final_suggestion" in evaluation_result["evaluation_summary"]:
                suggestion = evaluation_result["evaluation_summary"]["final_suggestion"]
                simplified_report += f"{suggestion}\n\n"
            else:
                simplified_report += "无具体改进建议。\n\n"
        
        # 添加重复率信息
        if "duplicate_info" in evaluation_result:
            duplicate_info = evaluation_result["duplicate_info"]
            ai_duplicate_rate = duplicate_info.get("ai_duplicate_rate", 0)
            
            # 如果迭代对比数据可用，添加重复率变化
            if "iteration_comparison_data" in evaluation_result:
                iteration_data = evaluation_result["iteration_comparison_data"]
                prev_duplicate_rate = iteration_data.get("prev_duplicate_rate", 0)
                duplicate_rate_change = ai_duplicate_rate - prev_duplicate_rate
                
                simplified_report += "## 📊 重复率分析\n\n"
                simplified_report += f"- **当前迭代重复率**: {ai_duplicate_rate}%\n"
                simplified_report += f"- **上一次迭代重复率**: {prev_duplicate_rate}%\n"
                simplified_report += f"- **变化**: {'+' if duplicate_rate_change > 0 else ''}{duplicate_rate_change:.2f}个百分点\n\n"
        
        # 添加页脚
        from datetime import datetime
        # 确保使用实时时间
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        # 构建页脚
        footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"
        
        # 检查是否已有页脚，如果有则替换，否则添加
        import re
        footer_pattern = r"\*\*生成时间：(.*?)(?:•|·|\*) *gogogo出发喽评估中心\*\*"
        placeholder_patterns = [
            r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
            r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
            r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
        ]
        
        # 先检查是否有明确的占位符
        placeholder_found = False
        for pattern in placeholder_patterns:
            if re.search(pattern, simplified_report):
                report = re.sub(pattern, footer, simplified_report)
                placeholder_found = True
                log("已替换基本报告页脚中的明确占位符为实时时间", important=True)
                break
        
        # 如果没有找到明确的占位符，尝试使用通用模式
        if not placeholder_found and re.search(footer_pattern, simplified_report):
            report = re.sub(footer_pattern, footer, simplified_report)
            log("已替换基本报告页脚中的日期为实时时间", important=True)
        elif not placeholder_found:
            # 如果没有找到页脚，则添加到报告末尾
            report += f"\n\n---\n{footer}\n"
            log("未找到页脚，已添加带有实时时间的页脚到基本报告", important=True)
        
        log(f"迭代对比精简报告生成完成，长度: {len(simplified_report)} 字符", important=True)
        return simplified_report
    
    # 以下是原有的完整报告生成逻辑，仅在非迭代模式下执行
    if is_iteration and formatted_prev_cases:
        log("生成包含迭代对比分析的报告", important=True)

    # 确保日志记录按照正确的顺序执行
    await asyncio.sleep(0.1)  # 添加小延迟，确保日志顺序

    # 从评估结果中提取关键数据用于可视化
    mermaid_data = {
        "scores": {},
        "duplicate_rates": {
            "ai": 0,
            "golden": 0
        },
        "duplicate_types": {},
        "coverage": []
    }

    # 尝试从评估结果获取测试用例数据
    ai_testcases = []
    if isinstance(evaluation_result, dict):
        # 尝试从不同可能的字段中提取测试用例
        if "test_cases" in evaluation_result:
            ai_testcases = evaluation_result.get("test_cases", [])
        elif "detailed_report" in evaluation_result and "test_coverage" in evaluation_result["detailed_report"]:
            if "analysis" in evaluation_result["detailed_report"]["test_coverage"]:
                coverage_analysis = evaluation_result["detailed_report"]["test_coverage"]["analysis"]
                # 尝试从覆盖分析中提取基本信息用于生成流程图
                if "covered_features" in coverage_analysis:
                    covered_features = coverage_analysis["covered_features"]
                    # 将覆盖的功能点转换为简单的测试用例结构
                    ai_testcases = [{"case_id": f"FEAT-{i + 1}", "title": feature}
                                    for i, feature in enumerate(covered_features)]

    # 如果ai_testcases为空，但有formatted_ai_cases，则使用formatted_ai_cases
    if not ai_testcases and formatted_ai_cases:
        log("使用formatted_ai_cases作为测试用例数据源", important=True)
        # 处理不同格式的formatted_ai_cases
        if isinstance(formatted_ai_cases, dict):
            if "testcases" in formatted_ai_cases and "test_cases" in formatted_ai_cases["testcases"]:
                ai_testcases = formatted_ai_cases["testcases"]["test_cases"]
            elif "test_cases" in formatted_ai_cases:
                ai_testcases = formatted_ai_cases["test_cases"]
            # 处理原始格式的测试用例（如包含functional、security等分类的字典）
            else:
                log("检测到原始格式的测试用例，直接传递给覆盖率分析函数", important=True)
                ai_testcases = formatted_ai_cases

        log(f"提取的测试用例数据类型: {type(ai_testcases)}", important=True)
        if isinstance(ai_testcases, dict):
            log(f"测试用例字典包含的键: {', '.join(ai_testcases.keys())}", important=True)
        elif isinstance(ai_testcases, list):
            log(f"测试用例列表长度: {len(ai_testcases)}", important=True)

    # 动态生成测试覆盖流程图
    coverage_chart = generate_test_coverage_flow_chart(ai_testcases, evaluation_result)

    # 如果启用迭代对比，生成迭代对比图表
    iteration_comparison_chart = ""
    if is_iteration and formatted_prev_cases and formatted_ai_cases and isinstance(evaluation_result, dict):
        log("生成迭代对比图表", important=True)
        
        # 提取当前迭代和上一次迭代的测试用例
        current_testcases = []
        prev_testcases = []

        # 提取当前迭代测试用例
        if formatted_ai_cases:
            if "testcases" in formatted_ai_cases and "test_cases" in formatted_ai_cases["testcases"]:
                current_testcases = formatted_ai_cases["testcases"]["test_cases"]

        # 提取上一次迭代测试用例
        if formatted_prev_cases:
            if "testcases" in formatted_prev_cases and "test_cases" in formatted_prev_cases["testcases"]:
                prev_testcases = formatted_prev_cases["testcases"]["test_cases"]

        # 生成测试用例数量对比图表
        count_chart = "## 📊 迭代测试用例数量对比\n\n"
        prev_count = len(prev_testcases) if isinstance(prev_testcases, list) else 0
        current_count = len(current_testcases) if isinstance(current_testcases, list) else 0
        count_change = current_count - prev_count
        count_change_percent = round((count_change / prev_count * 100) if prev_count > 0 else 0, 2)

        # 生成数量对比条形图
        count_chart += "```mermaid\nbar\n"
        count_chart += "    title 测试用例数量变化\n"
        count_chart += "    xlabel 迭代版本\n"
        count_chart += "    ylabel 测试用例数量\n"
        count_chart += f"    \"上一次迭代\" {prev_count}\n"
        count_chart += f"    \"当前迭代\" {current_count}\n"
        count_chart += "```\n\n"

        # 添加数量变化描述
        count_chart += f"### 数量变化分析\n\n"

        if count_change > 0:
            count_chart += f"📈 **增加**: +{count_change}个测试用例 (+{count_change_percent}%)\n\n"
        elif count_change < 0:
            count_chart += f"📉 **减少**: {count_change}个测试用例 ({count_change_percent}%)\n\n"
        else:
            count_chart += f"📊 **无变化**: 测试用例数量保持不变\n\n"

        # 从评估结果中提取重复率数据
        if "duplicate_info" in evaluation_result:
            duplicate_info = evaluation_result["duplicate_info"]
            current_duplicate_rate = duplicate_info.get("ai_duplicate_rate", 0)

            # 从迭代对比数据中提取上一次迭代的重复率
            prev_duplicate_rate = 0
            if "iteration_comparison_data" in evaluation_result:
                iteration_data = evaluation_result["iteration_comparison_data"]
                prev_duplicate_rate = iteration_data.get("prev_duplicate_rate", 0)

            # 计算重复率变化
            duplicate_rate_change = current_duplicate_rate - prev_duplicate_rate

            # 生成重复率对比图表
            count_chart += "### 重复率变化\n\n"
            count_chart += "```mermaid\nbar\n"
            count_chart += "    title 测试用例重复率变化\n"
            count_chart += "    xlabel 迭代版本\n"
            count_chart += "    ylabel 重复率(%)\n"
            count_chart += f"    \"上一次迭代\" {prev_duplicate_rate}\n"
            count_chart += f"    \"当前迭代\" {current_duplicate_rate}\n"
            count_chart += "```\n\n"

            # 添加重复率变化描述
            if duplicate_rate_change > 0:
                count_chart += f"⚠️ **增加**: +{duplicate_rate_change:.2f}个百分点\n\n"
            elif duplicate_rate_change < 0:
                count_chart += f"✅ **减少**: {duplicate_rate_change:.2f}个百分点\n\n"
            else:
                count_chart += f"📊 **无变化**: 重复率保持不变\n\n"

        # 从评估结果中提取迭代对比分析数据
        if "detailed_report" in evaluation_result and "iteration_comparison" in evaluation_result["detailed_report"]:
            iteration_comparison = evaluation_result["detailed_report"]["iteration_comparison"]

            # 添加迭代改进得分
            improvement_score = iteration_comparison.get("score", "N/A")
            count_chart += f"### 迭代改进得分: {improvement_score}/5.0\n\n"

            # 添加主要改进点
            if "key_improvements" in iteration_comparison and iteration_comparison["key_improvements"]:
                count_chart += "### 主要改进点\n\n"
                for improvement in iteration_comparison["key_improvements"]:
                    count_chart += f"✅ {improvement}\n"
                count_chart += "\n"

            # 添加主要退步点
            if "key_regressions" in iteration_comparison and iteration_comparison["key_regressions"]:
                count_chart += "### 主要退步点\n\n"
                for regression in iteration_comparison["key_regressions"]:
                    count_chart += f"⚠️ {regression}\n"
                count_chart += "\n"

            # 添加下一次迭代建议
            if "next_iteration_suggestions" in iteration_comparison and iteration_comparison["next_iteration_suggestions"]:
                count_chart += "### 下一次迭代建议\n\n"
                for suggestion in iteration_comparison["next_iteration_suggestions"]:
                    count_chart += f"📝 {suggestion}\n"
                count_chart += "\n"

            # 添加迭代对比理由
            if "reason" in iteration_comparison:
                count_chart += "### 详细分析\n\n"
                count_chart += f"{iteration_comparison['reason']}\n\n"

        # 将迭代对比图表添加到总的迭代对比图表中
        iteration_comparison_chart = "# 🔄 迭代前后对比分析\n\n" + count_chart

    # 添加测试覆盖状态的实际文字描述
    # 从评估结果中提取覆盖度相关信息
    coverage_status = {
        "功能验证": "missing",
        "异常处理": "missing",
        "边界测试": "missing",
        "输入验证": "missing",
        "超时处理": "missing",
        "安全检查": "missing",
        "最大值测试": "missing",
        "最小值测试": "missing"
    }

    # 如果有评估结果，从中提取信息增强覆盖分析
    if evaluation_result and isinstance(evaluation_result, dict):
        # 从评测结果中分析各维度分数，推断覆盖状态
        detailed = evaluation_result.get("detailed_report", {})

        # 功能覆盖度评分影响"功能验证"状态
        try:
            functional_score = float(detailed.get("functional_coverage", {}).get("score", 0))
            if functional_score >= 4.0:
                coverage_status["功能验证"] = "covered"
            elif functional_score >= 3.0:
                coverage_status["功能验证"] = "partial"

            # 缺陷发现能力评分影响"异常处理"和"安全检查"状态
            defect_score = float(detailed.get("defect_detection", {}).get("score", 0))
            if defect_score >= 4.0:
                coverage_status["异常处理"] = "covered"
            elif defect_score >= 3.0:
                coverage_status["异常处理"] = "partial"

            # 测试覆盖度评分影响"边界测试"状态
            test_coverage_score = float(detailed.get("test_coverage", {}).get("score", 0))
            if test_coverage_score >= 4.0:
                coverage_status["边界测试"] = "covered"
            elif test_coverage_score >= 3.0:
                coverage_status["边界测试"] = "partial"

            # 安全与经济性评分影响"安全检查"状态
            security_score = float(detailed.get("security_economy", {}).get("score", 0))
            if security_score >= 4.0:
                coverage_status["安全检查"] = "covered"
            elif security_score >= 3.0:
                coverage_status["安全检查"] = "partial"
        except (ValueError, TypeError):
            # 如果评分无法转换为浮点数，跳过
            pass

    # 提取功能计数
    feature_counts = {}
    for case in ai_testcases:
        title = case.get("title", "").lower()
        case_id = case.get("case_id", "")

        # 基于测试用例标题和ID分析覆盖类型
        if "功能" in title or "流程" in title or "FUNC" in case_id:
            feature_counts["功能验证"] = feature_counts.get("功能验证", 0) + 1

        if "异常" in title or "错误" in title or "EXCEP" in case_id:
            feature_counts["异常处理"] = feature_counts.get("异常处理", 0) + 1

        if "边界" in title or "极限" in title or "BOUND" in case_id:
            feature_counts["边界测试"] = feature_counts.get("边界测试", 0) + 1

        if "输入" in title and ("验证" in title or "校验" in title):
            feature_counts["输入验证"] = feature_counts.get("输入验证", 0) + 1

        if "超时" in title or "timeout" in title.lower():
            feature_counts["超时处理"] = feature_counts.get("超时处理", 0) + 1

        if "安全" in title or "攻击" in title or "漏洞" in title or "SEC" in case_id:
            feature_counts["安全检查"] = feature_counts.get("安全检查", 0) + 1

        if "最大" in title or "上限" in title or "max" in title.lower():
            feature_counts["最大值测试"] = feature_counts.get("最大值测试", 0) + 1

        if "最小" in title or "下限" in title or "min" in title.lower():
            feature_counts["最小值测试"] = feature_counts.get("最小值测试", 0) + 1

    # 根据功能计数调整覆盖状态
    # 如果计数为0，保持为"missing"
    # 如果计数大于0但评估结果未覆盖，设为"partial"
    for feature, count in feature_counts.items():
        if count > 0 and coverage_status[feature] == "missing":
            coverage_status[feature] = "partial"

    # 提取各维度评分
    if isinstance(evaluation_result, dict) and "detailed_report" in evaluation_result:
        detailed = evaluation_result["detailed_report"]

        # 提取评分数据
        for key, value in detailed.items():
            if isinstance(value, dict) and "score" in value:
                score_key = key.replace("_", " ").title()
                try:
                    score_value = float(value["score"])
                    mermaid_data["scores"][score_key] = score_value
                except (ValueError, TypeError):
                    mermaid_data["scores"][score_key] = value["score"]

    # 获取整体评分
    overall_score = "N/A"
    if isinstance(evaluation_result, dict) and "evaluation_summary" in evaluation_result:
        overall_score = evaluation_result["evaluation_summary"].get("overall_score", "N/A")
        mermaid_data["scores"]["Overall Score"] = overall_score

    # 生成评分雷达图
    # 由于Mermaid不支持真正的雷达图，改用Markdown表格和评分表示
    radar_chart = f"## 📊 综合评分 (总体: {overall_score}/5.0)\n\n"
    radar_chart += "| 评估维度 | 得分 | 评分可视化 |\n"
    radar_chart += "|---------|------|------------|\n"

    # 获取维度数据
    dimension_scores = []
    for name, score in mermaid_data["scores"].items():
        if name != "Overall Score":  # 排除总体评分
            try:
                # 确保分数是数值
                score_value = float(score) if isinstance(score, str) else score
                # 将英文维度名称转为中文
                chinese_name = name
                if name == "Format Compliance":
                    chinese_name = "格式合规性"
                elif name == "Content Accuracy":
                    chinese_name = "内容准确性"
                elif name == "Test Coverage":
                    chinese_name = "测试覆盖度"
                elif name == "Functional Coverage":
                    chinese_name = "功能覆盖度"
                elif name == "Defect Detection":
                    chinese_name = "缺陷发现能力"
                elif name == "Engineering Efficiency":
                    chinese_name = "工程效率"
                elif name == "Semantic Quality":
                    chinese_name = "语义质量"
                elif name == "Security Economy":
                    chinese_name = "安全与经济性"
                elif name == "Duplicate Analysis":
                    chinese_name = "重复性分析"
                dimension_scores.append((chinese_name, score_value))
            except (ValueError, TypeError):
                # 如果无法转换为数值，跳过
                continue

    # 按评分从高到低排序
    dimension_scores.sort(key=lambda x: x[1], reverse=True)

    # 添加数据行
    if dimension_scores:
        for name, score in dimension_scores:
            # 生成评分可视化
            score_int = int(score)
            stars = "★" * score_int + "☆" * (5 - score_int)
            radar_chart += f"| {name} | {score} | {stars} |\n"

    radar_chart += "\n"

    # 添加专门的评分图
    radar_chart += "```mermaid\npie\n    title 各维度评分分布\n"
    for name, score in dimension_scores:
        short_name = name.replace("Coverage", "覆盖").replace("Analysis", "分析")
        radar_chart += f"    \"{short_name}\" : {score}\n"
    radar_chart += "```\n\n"

    # 提取重复率和重复类型数据
    ai_duplicate_rate = 0
    golden_duplicate_rate = 0
    duplicate_types = {}

    # 尝试从评估结果中找到重复率数据
    if "duplicate_types" in evaluation_result:
        duplicate_types = evaluation_result.get("duplicate_types", {})

        # 从evaluation_result直接获取重复率数据
        try:
            # 尝试从具体数据中提取重复率
            duplicate_info = evaluation_result.get("duplicate_info", {})
            if duplicate_info:
                ai_duplicate_rate = duplicate_info.get("ai_duplicate_rate", 0)
                golden_duplicate_rate = duplicate_info.get("golden_duplicate_rate", 0)
                mermaid_data["duplicate_rates"]["ai"] = float(ai_duplicate_rate)
                mermaid_data["duplicate_rates"]["golden"] = float(golden_duplicate_rate)
        except:
            # 如果提取失败，保留初始化值
            pass
    else:
        # 尝试从原因描述中提取数据
        if "duplicate_analysis" in evaluation_result.get("detailed_report", {}):
            dup_analysis = evaluation_result["detailed_report"]["duplicate_analysis"]
            if "reason" in dup_analysis:
                # 尝试从原因描述中提取数字
                ai_rates = re.findall(r"AI[^0-9]*([0-9.]+)%", dup_analysis["reason"])
                golden_rates = re.findall(r"黄金[^0-9]*([0-9.]+)%", dup_analysis["reason"])

                if ai_rates:
                    mermaid_data["duplicate_rates"]["ai"] = float(ai_rates[0])
                    ai_duplicate_rate = float(ai_rates[0])
                if golden_rates:
                    mermaid_data["duplicate_rates"]["golden"] = float(golden_rates[0])
                    golden_duplicate_rate = float(golden_rates[0])

    # 尝试从评估结果中提取重复类型数据
    dup_types = {"标题重复": 0, "步骤重复": 0, "预期结果重复": 0, "混合重复": 0}

    # 如果evaluation_result中有具体的duplicate_types数据，则使用它
    if "duplicate_types" in evaluation_result:
        try:
            duplicate_types = evaluation_result.get("duplicate_types", {})
            if duplicate_types and sum(duplicate_types.values()) > 0:
                dup_types = {
                    "标题重复": duplicate_types.get("title", 0),
                    "步骤重复": duplicate_types.get("steps", 0),
                    "预期结果重复": duplicate_types.get("expected_results", 0),
                    "混合重复": duplicate_types.get("mixed", 0)
                }
                # 保存到mermaid_data
                mermaid_data["duplicate_types"] = dup_types
        except:
            pass
    else:
        # 尝试从原因描述中提取重复类型分布
        if "duplicate_analysis" in evaluation_result.get("detailed_report", {}):
            reason = evaluation_result["detailed_report"]["duplicate_analysis"].get("reason", "")

            # 尝试从reason中提取数据
            title_dup = re.findall(r"标题重复[^0-9]*([0-9]+)个", reason)
            steps_dup = re.findall(r"步骤[相似|重复][^0-9]*([0-9]+)个", reason)

            if title_dup:
                dup_types["标题重复"] = int(title_dup[0])
            if steps_dup:
                dup_types["步骤重复"] = int(steps_dup[0])

            # 保存到mermaid_data
            mermaid_data["duplicate_types"] = dup_types

    # 合并生成重复测试用例分析图
    duplicate_combined_chart = "## 🔄 重复测试用例分析\n\n"

    # 使用文字描述替代图表
    duplicate_combined_chart += "> ### 重复情况统计摘要\n>\n"

    # 添加重复率数据
    duplicate_combined_chart += f"> **AI测试用例重复率**: {ai_duplicate_rate}%\n>\n"
    duplicate_combined_chart += f"> **黄金标准重复率**: {golden_duplicate_rate}%\n>\n"

    # 添加重复类型数据
    duplicate_combined_chart += "> **重复类型明细**:\n"
    has_duplicates = False
    for dup_type, count in dup_types.items():
        if count > 0:
            has_duplicates = True
            duplicate_combined_chart += f"> - {dup_type}: **{count}个**\n"

    # 如果所有数据都是0，添加无重复说明
    if not has_duplicates:
        duplicate_combined_chart += "> - 未发现重复测试用例\n"

    # 添加模块分布的文字描述
    if "duplicate_categories" in evaluation_result:
        duplicate_categories = evaluation_result.get("duplicate_categories", {})
        if duplicate_categories:
            duplicate_combined_chart += ">\n> **重复用例模块分布**:\n"
            for category, value in duplicate_categories.items():
                # 检查value是否为字典（analyzer.py中的结构）或整数
                if isinstance(value, dict) and "total" in value:
                    # 如果是字典，提取duplicate_rate或计算重复率
                    duplicate_count = value.get("title_duplicates", 0) + value.get("steps_duplicates", 0)
                    if duplicate_count > 0:
                        duplicate_combined_chart += f"> - {category}: **{duplicate_count}个**\n"
                elif isinstance(value, (int, float)) and value > 0:
                    # 如果是数字且大于0
                    duplicate_combined_chart += f"> - {category}: **{value}个**\n"
                # 忽略其他类型或零值

    duplicate_combined_chart += "\n\n"

    # 生成合并建议方案图
    merge_suggestions = []
    if isinstance(evaluation_result, dict) and "detailed_report" in evaluation_result:
        detailed = evaluation_result["detailed_report"]
        if "duplicate_analysis" in detailed and "merge_suggestions" in detailed["duplicate_analysis"]:
            merge_suggestions = detailed["duplicate_analysis"]["merge_suggestions"]

    # 从duplicate_info中获取合并建议
    if "duplicate_info" in evaluation_result and "merge_suggestions" in evaluation_result["duplicate_info"]:
        merge_suggestions = evaluation_result["duplicate_info"]["merge_suggestions"]

    # 如果有合并建议，生成图表
    if merge_suggestions and isinstance(merge_suggestions, str) and len(merge_suggestions) > 10:
        # 如果merge_suggestions是字符串，尝试提取有用信息
        merge_chart = "### 🛠️ 合并建议方案\n\n"
        merge_chart += "> " + merge_suggestions.replace("\n", "\n> ") + "\n\n"
    elif merge_suggestions and (isinstance(merge_suggestions, list) and len(merge_suggestions) > 0):
        # 如果有结构化的合并建议，生成流程图
        merge_chart = "### 🛠️ 合并建议方案\n```mermaid\ngraph LR\n"
        merge_chart += "    A[重复用例] --> B[合并方案]\n"

        for i, suggestion in enumerate(merge_suggestions[:4]):  # 限制最多显示4个建议
            index = i + 1
            case_ids = ""
            title = ""
            node_id = ""  # 用于保存节点ID

            if isinstance(suggestion, dict):
                # 提取案例ID并生成节点ID
                all_case_ids = []
                if "original_case_ids" in suggestion:
                    # 优先使用原始case_ids
                    all_case_ids = suggestion["original_case_ids"]
                elif "case_ids" in suggestion and suggestion["case_ids"]:
                    # 如果没有原始case_ids，使用格式化后的case_ids
                    all_case_ids = suggestion["case_ids"]

                if all_case_ids:
                    # 尝试查找新格式ID (如FT-xxx, ST-xxx)
                    new_format_ids = [cid for cid in all_case_ids if isinstance(cid, str) and
                                     (cid.startswith("FT-") or
                                      cid.startswith("ST-") or
                                      cid.startswith("CT-") or
                                      cid.startswith("PT-") or
                                      cid.startswith("BT-") or
                                      cid.startswith("ET-"))]

                    # 如果找到新格式ID，使用它作为节点ID；否则使用第一个ID
                    node_id = new_format_ids[0] if new_format_ids else all_case_ids[0]

                    # 生成要显示的case_ids文本
                    if isinstance(all_case_ids, list):
                        # 显示原始case_ids，不做格式转换
                        display_ids = all_case_ids
                        case_ids = "/".join([str(cid) for cid in display_ids[:2]])
                        if len(display_ids) > 2:
                            case_ids += "..."
                    else:
                        case_ids = str(all_case_ids)
                else:
                    # 如果没有case_ids，使用索引作为节点ID
                    node_id = f"Case{index}"

                # 提取标题
                if "merged_case" in suggestion and "title" in suggestion["merged_case"]:
                    title = suggestion["merged_case"]["title"]
                elif "title" in suggestion:
                    title = suggestion["title"]
                else:
                    title = f"合并用例 {index}"

            else:
                # 如果suggestion不是字典，使用索引作为节点ID
                node_id = f"Case{index}"

            # 防止标题过长
            if len(title) > 30:
                title = title[:27] + "..."

            # 去除特殊字符，避免Mermaid语法错误
            title = title.replace("(", "").replace(")", "").replace("[", "").replace("]", "")

            # 确保节点ID不含特殊字符
            node_id = ''.join(c for c in str(node_id) if c.isalnum() or c in ['-', '_'])

            # 添加到图表中
            merge_chart += f"    {node_id}[\"{case_ids}\"] --> Merge{index}[\"{title}\"]\n"

        merge_chart += "```\n\n"
    else:
        # 没有合并建议或合并建议格式不适合生成图表
        merge_chart = "### 🛠️ 合并建议方案\n\n"
        merge_chart += "> 当前测试用例不需要合并或没有提供合并建议信息\n\n"

    # 将合并建议图添加到重复分析后面
    duplicate_combined_chart += merge_chart

    # 添加树状评估框架图模板
    evaluation_framework_chart = """## 🌳 测试用例评估框架
```mermaid
graph TD
    A[测试用例评估] --> B[格式合规性]
    A --> C[内容质量]
    A --> D[功能覆盖]
    A --> E[工程效率]
    A --> F[安全性]

    C --> C1[内容准确性]
    C --> C2[语义质量]

    D --> D1[测试覆盖度]
    D --> D2[功能覆盖度]
    D --> D3[缺陷发现能力]

    E --> E1[重复性分析]
    E --> E2[工程效率]

    F --> F1[安全与经济性]

    classDef important fill:#f9d77e,stroke:#f9a11b,stroke-width:2px;
    classDef quality fill:#a8d6ff,stroke:#4a86e8,stroke-width:2px;
    classDef coverage fill:#b6d7a8,stroke:#6aa84f,stroke-width:2px;

    class A,D important;
    class B,C,F quality;
    class D1,D2,D3 coverage;
```

"""

    # 检查是否是CollabEval结果
    is_collab_eval = evaluation_result.get("collab_eval_result", False)
    # 检查实际使用的评估框架
    actual_framework = "Standard"
    if "evaluation_framework" in evaluation_result:
        actual_framework = evaluation_result["evaluation_framework"]
    elif "committee_summary" in evaluation_result and "evaluation_framework" in evaluation_result["committee_summary"]:
        actual_framework = evaluation_result["committee_summary"]["evaluation_framework"]
    elif "committee_info" in evaluation_result and "evaluation_framework" in evaluation_result["committee_info"]:
        actual_framework = evaluation_result["committee_info"]["evaluation_framework"]

    # 根据实际评估框架设置标志
    is_using_collab_eval = actual_framework == "CollabEval"
    collab_eval_info = ""

    if is_collab_eval and "committee_summary" in evaluation_result:
        committee_summary = evaluation_result["committee_summary"]

        # 根据实际使用的框架选择不同的图表模板
        if is_using_collab_eval:
            collab_eval_info = """### 🔄 评测流程框架
```mermaid
graph TD
    A[CollabEval评测框架] --> B[阶段1: 独立评分]
    A --> C[阶段2: 辩论协作]
    A --> D[阶段3: 主席聚合]
    
    B --> B1[评委专属Prompt]
    B --> B2[计算初始共识度]
    
    C --> C1[低共识触发辩论]
    C --> C2[思维树框架]
    
    D --> D1[主席加权聚合]
    D --> D2[标记高争议用例]
    
    classDef highlight fill:#f9d77e,stroke:#f9a11b,stroke-width:2px;
    class A,C,D highlight;
```

"""
        else:
            collab_eval_info = """### 🔄 标准多评委评测框架
```mermaid
graph TD
    A[标准多评委评测] --> B[阶段1: 独立评分]
    A --> D[阶段2: 结果聚合]
    
    B --> B1[评委独立评估]
    B --> B2[基于专业领域评分]
    
    D --> D1[加权平均计算]
    D --> D2[最终分数确定]
    
    classDef highlight fill:#f9d77e,stroke:#f9a11b,stroke-width:2px;
    class A,D highlight;
```

"""

        # 添加评委评分情况
        if "judge_scores" in committee_summary:
            collab_eval_info += "### 评委评分情况\n"
            collab_eval_info += "| 评委模型 | 总体评分 |\n"
            collab_eval_info += "|---------|--------|\n"

            for judge, score in committee_summary["judge_scores"].items():
                collab_eval_info += f"| {judge} | {score} |\n"

            collab_eval_info += "\n"

        # 添加高争议维度
        if "high_disagreement_dimensions" in committee_summary and committee_summary["high_disagreement_dimensions"]:
            high_disagreement = committee_summary["high_disagreement_dimensions"]
            collab_eval_info += "### 高争议维度\n"
            for dimension in high_disagreement:
                collab_eval_info += f"- {dimension.replace('_', ' ').title()}\n"
            collab_eval_info += "\n"

        # 添加主席决策理由
        if is_using_collab_eval and "stage3_chairman_decision" in committee_summary:
            chairman_decision = committee_summary["stage3_chairman_decision"]
            if "chairman_decision" in chairman_decision and "rationale" in chairman_decision["chairman_decision"]:
                collab_eval_info += "### 主席决策理由\n"
                collab_eval_info += f"> {chairman_decision['chairman_decision']['rationale']}\n\n"

            # 添加高争议区域
            if "chairman_decision" in chairman_decision and "high_disagreement_areas" in chairman_decision["chairman_decision"]:
                high_areas = chairman_decision["chairman_decision"]["high_disagreement_areas"]
                if high_areas:
                    collab_eval_info += "### 主席标记的高争议区域\n"
                    for i, area in enumerate(high_areas):
                        collab_eval_info += f"{i+1}. {area}\n"
                    collab_eval_info += "\n"

    # 在提示中说明使用更新的图表语法
    prompt = f"""
# 任务
基于提供的测试用例评估结果，生成一份详细的Markdown格式评估报告，包含Mermaid图表可视化关键数据。
"""

    # 如果是迭代对比，增加迭代对比任务说明
    if is_iteration and formatted_prev_cases:
        prompt += f"""
# 迭代对比任务
本次评估包含迭代前后对比分析，需要重点关注测试用例在本次迭代中的质量改进情况，并提出针对性建议。
"""

    prompt += f"""
# 评估结果
```json
{json.dumps(evaluation_result, ensure_ascii=False, indent=2)}
```

# 报告要求
请生成一份专业、详细的Markdown格式评估报告，包含以下内容：

1. **报告标题与摘要**：{("【CollabEval三阶段评测】" if is_using_collab_eval else "【多评委综合评测】") if evaluation_result.get("is_committee_result", False) else ""}简要总结评估结果"""

    # 如果是迭代对比，在标题中添加迭代对比标识
    if is_iteration:
        prompt = prompt.replace("简要总结评估结果", "【迭代对比分析】简要总结评估结果")

    prompt += f"""
2. **评估指标与方法**：说明使用的评估标准和方法，并包含评估框架图
{evaluation_framework_chart}
3. **综合评分**：使用提供的表格和饼图展示各维度评分
{radar_chart}"""

    # 如果启用迭代对比，在适当位置添加迭代对比图表
    if is_iteration and iteration_comparison_chart:
        prompt += f"""
4. **迭代前后对比**：分析当前迭代与上一次迭代的测试用例质量变化
{iteration_comparison_chart}"""

        # 调整后续内容的序号
        prompt += """
5. **详细分析**：
   - 功能覆盖度分析
   - 缺陷发现能力分析
   - 工程效率分析
   - 语义质量分析
   - 安全与经济性分析
6. **重复测试用例分析**：
   - 重复测试用例比率与类型的综合分析
   - 测试用例合并建议
"""
    else:
        prompt += """
4. **详细分析**：
   - 功能覆盖度分析
   - 缺陷发现能力分析
   - 工程效率分析
   - 语义质量分析
   - 安全与经济性分析
5. **重复测试用例分析**：
   - 重复测试用例比率与类型的综合分析
   - 测试用例合并建议
"""

    # 添加重复测试用例分析图表
    prompt += f"""
{duplicate_combined_chart}
"""

    # 继续添加覆盖率分析等后续内容
    if is_iteration:
        prompt += f"""
7. **测试覆盖率分析**：
   - 关键流程和功能覆盖情况
{coverage_chart}
"""
    else:
        prompt += f"""
6. **测试覆盖率分析**：
   - 关键流程和功能覆盖情况
{coverage_chart}
"""

    # 如果是CollabEval结果，添加CollabEval信息部分
    if evaluation_result.get("collab_eval_result", False):
        if is_iteration:
            prompt += f"""
8. **{("CollabEval三阶段评测" if is_using_collab_eval else "标准多评委评测")}**：
   - {("三阶段评测流程" if is_using_collab_eval else "评测流程")}
   - 评委评分情况与争议维度
   - {("主席决策理由" if is_using_collab_eval else "结果聚合机制")}
{collab_eval_info}
"""
        else:
            prompt += f"""
7. **{("CollabEval三阶段评测" if is_using_collab_eval else "标准多评委评测")}**：
   - {("三阶段评测流程" if is_using_collab_eval else "评测流程")}
   - 评委评分情况与争议维度
   - {("主席决策理由" if is_using_collab_eval else "结果聚合机制")}
{collab_eval_info}
"""
    else:
        if is_iteration:
            prompt += """
8. **优缺点对比**：列出AI生成测试用例相对于人工标准的优势和劣势
"""
        else:
            prompt += """
7. **优缺点对比**：列出AI生成测试用例相对于人工标准的优势和劣势
"""

    # 添加通用部分，根据是否启用迭代对比调整序号
    if is_iteration:
        prompt += """
9. **改进建议**：给出3-5条具体可行的改进AI生成测试用例的建议，包括如何减少重复
10. **综合结论**：总结AI测试用例的整体表现和适用场景
"""
    else:
        prompt += """
8. **改进建议**：给出3-5条具体可行的改进AI生成测试用例的建议，包括如何减少重复
9. **综合结论**：总结AI测试用例的整体表现和适用场景
"""

    # 美化要求
    prompt += """
# 美化要求
1. 请使用更丰富的Markdown格式元素来增强报告的可读性，如适当使用分隔线、引用块、表情符号等
2. 为关键数据添加醒目的标记，如重要的评分、显著的差异等
3. 在评分部分使用中文维度名称和星号评分可视化
4. 为报告添加简洁美观的页眉页脚
5. 添加有针对性的改进建议，使结论更具操作性

# 特别说明
- 请不要在报告中添加"模块分布"相关的饼图，只保留文字描述形式的模块分布信息
- 不要使用饼图展示测试用例类型分布
"""

    # 如果是CollabEval结果，添加额外说明
    if is_collab_eval:
        prompt += """
- 在CollabEval部分，突出显示三阶段评测的过程和价值，特别强调辩论协作如何提高评测质量
- 在描述评委评分时，关注分歧点以及主席是如何处理这些分歧的
"""

    prompt += """
# 页脚格式
请在报告末尾添加一行页脚，使用以下格式（不要替换DATETIME_PLACEHOLDER，保持原样）：
**生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心**

系统会自动将DATETIME_PLACEHOLDER替换为实时时间，请不要自行填写任何日期时间。

请确保使用上面提供的图表模板，这些模板已经包含了从评估结果中提取的实际数据。
这些图表使用的是较为通用的Mermaid语法，确保与大多数Markdown查看器兼容。
你可以根据评估结果调整图表内容，但要保持```mermaid语法格式。
直接以# 开头的标题开始你的报告，不要在开头写"markdown"，不要包含其他解释。
"""

    system_prompt = "你是一位精通软件测试和技术文档写作的专家。请根据评估结果生成一份专业、清晰的Markdown格式报告，并使用Mermaid图表可视化关键数据。请直接保留并使用我提供的评分表格格式，不要修改其结构。请直接输出Markdown格式，不要尝试输出JSON。严格禁止在文档开头添加'markdown'这个词，直接以'# '开头的标题开始。不要在内容外包含```或```markdown标记，完全避免使用代码块，但保留提供的Mermaid图表语法。"

    # 使用较高的temperature值，生成更有创意的报告
    max_retries = 3
    for retry_count in range(max_retries):
        try:
            # 添加随机请求ID，确保每次请求都是全新的
            request_id = f"report-{int(time.time())}-{retry_count}-{uuid.uuid4().hex[:8]}"
            log(f"生成报告请求ID: {request_id}")
            
            result = await async_call_llm(
                session,
                prompt,
                system_prompt,
                temperature=LLM_TEMPERATURE_REPORT,  # 使用配置中的较高temperature值
                use_cache=False,  # 禁用缓存，确保每次评测都是全新的
                retries=2  # 设置内部重试次数
            )

            if not result:
                log_error(f"生成Markdown报告失败 (尝试 {retry_count + 1}/{max_retries})", important=True)
                if retry_count < max_retries - 1:
                    log(f"等待2秒后重试...", important=True)
                    await asyncio.sleep(2)
                    continue
                else:
                    return "# 评测报告生成失败\n\n无法生成详细报告，请检查评测结果或重试。"

            # 检查返回的结果类型
            if isinstance(result, dict):
                # 如果返回的是字典，检查是否包含文本内容
                if "text" in result and result["text"]:
                    # 返回文本内容
                    markdown_content = result["text"]
                    log("成功生成Markdown报告", important=True)
                    # 添加小延迟，确保日志顺序
                    await asyncio.sleep(0.1)

                    # 在返回前替换占位符
                    from datetime import datetime
                    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                    footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                    # 替换占位符
                    import re
                    placeholder_patterns = [
                        r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                        r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                        r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                    ]

                    placeholder_found = False
                    for pattern in placeholder_patterns:
                        if re.search(pattern, markdown_content):
                            markdown_content = re.sub(pattern, footer, markdown_content)
                            placeholder_found = True
                            log("已替换markdown_content中的占位符为实时时间", important=True)
                            break

                    if not placeholder_found:
                        log("markdown_content中未找到占位符，将检查是否有其他格式的时间戳", level="WARNING")

                    return markdown_content
                elif "error" in result:
                    # 返回错误信息
                    log_error(f"生成Markdown报告失败: {result['error']}")
                    if retry_count < max_retries - 1:
                        log(f"等待2秒后重试...", important=True)
                        await asyncio.sleep(2)
                        continue
                    else:
                        return f"# 评测报告生成失败\n\n{result['error']}"
                elif "api_response" in result:
                    # API返回了原始响应但无法解析
                    log_error(f"API返回的响应无法解析为有效内容 (尝试 {retry_count + 1}/{max_retries})")
                    if retry_count < max_retries - 1:
                        log(f"等待2秒后重试...", important=True)
                        await asyncio.sleep(2)
                        continue
                    else:
                        # 尝试生成一个基本报告
                        return generate_basic_report(evaluation_result)
                else:
                    # 尝试将字典转换为Markdown
                    try:
                        md_content = "# AI测试用例评估报告\n\n"

                        if "evaluation_summary" in result:
                            summary = result["evaluation_summary"]
                            md_content += f"## 摘要\n\n"
                            md_content += f"**总体评分**: {summary.get('overall_score', 'N/A')}\n\n"
                            md_content += f"**改进建议**: {summary.get('final_suggestion', 'N/A')}\n\n"

                        if "detailed_report" in result:
                            md_content += f"## 详细评估\n\n"
                            detailed = result["detailed_report"]

                            for key, value in detailed.items():
                                if isinstance(value, dict) and "score" in value:
                                    md_content += f"### {key.replace('_', ' ').title()}\n\n"
                                    md_content += f"**评分**: {value.get('score', 'N/A')}\n\n"
                                    md_content += f"**理由**: {value.get('reason', 'N/A')}\n\n"

                                    if key == "duplicate_analysis" and "merge_suggestions" in value:
                                        md_content += f"**合并建议**: {value.get('merge_suggestions', 'N/A')}\n\n"

                                    if "analysis" in value and isinstance(value["analysis"], dict):
                                        analysis = value["analysis"]
                                        if "covered_features" in analysis:
                                            md_content += "**覆盖的功能**:\n\n"
                                            for feature in analysis["covered_features"]:
                                                md_content += f"- {feature}\n"
                                            md_content += "\n"

                                        if "missed_features_or_scenarios" in analysis:
                                            md_content += "**未覆盖的功能或场景**:\n\n"
                                            for feature in analysis["missed_features_or_scenarios"]:
                                                md_content += f"- {feature}\n"
                                            md_content += "\n"

                                        if "scenario_types_found" in analysis:
                                            md_content += "**发现的场景类型**:\n\n"
                                            for scenario in analysis["scenario_types_found"]:
                                                md_content += f"- {scenario}\n"
                                            md_content += "\n"

                        log("成功从字典生成Markdown报告", important=True)
                        # 添加小延迟，确保日志顺序
                        await asyncio.sleep(0.1)

                        # 在返回前替换占位符
                        from datetime import datetime
                        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                        footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                        # 替换占位符
                        import re
                        placeholder_patterns = [
                            r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                            r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                            r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                        ]

                        placeholder_found = False
                        for pattern in placeholder_patterns:
                            if re.search(pattern, md_content):
                                md_content = re.sub(pattern, footer, md_content)
                                placeholder_found = True
                                log("已替换md_content中的占位符为实时时间", important=True)
                                break

                        if not placeholder_found:
                            log("md_content中未找到占位符，将检查是否有其他格式的时间戳", level="WARNING")

                        return md_content
                    except Exception as e:
                        log_error(f"从字典生成Markdown报告失败: {e}")
                        if retry_count < max_retries - 1:
                            log(f"等待2秒后重试...", important=True)
                            await asyncio.sleep(2)
                            continue
                        else:
                            # 如果无法转换为Markdown，直接返回JSON字符串
                            return f"# 评测报告\n\n```\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```"

            # 如果返回的不是字典，而是字符串，直接返回
            if isinstance(result, str):
                log("LLM直接返回了Markdown文本", important=True)
                # 添加小延迟，确保日志顺序
                await asyncio.sleep(0.1)
                # 删除Markdown文本顶部的"markdown"前缀
                if result.strip().startswith("markdown"):
                    result = result.strip().replace("markdown", "", 1).strip()
                    log("已删除Markdown文本顶部的'markdown'前缀", important=True)
                    # 添加小延迟，确保日志顺序
                    await asyncio.sleep(0.1)

                # 在返回前替换占位符
                from datetime import datetime
                current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                # 替换占位符
                import re
                placeholder_patterns = [
                    r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                    r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                    r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                ]

                placeholder_found = False
                for pattern in placeholder_patterns:
                    if re.search(pattern, result):
                        result = re.sub(pattern, footer, result)
                        placeholder_found = True
                        log("已替换LLM生成报告中的占位符为实时时间", important=True)
                        break

                if not placeholder_found:
                    log("LLM生成报告中未找到占位符，将检查是否有其他格式的时间戳", level="WARNING")

                return result

            # 尝试使用extract_valid_json函数从结果中提取有效的JSON
            try:
                log("尝试从LLM响应中提取有效的JSON", important=True)
                extracted_json = extract_valid_json(str(result))
                if extracted_json:
                    log("成功从LLM响应中提取有效的JSON", important=True)

                    # 将提取的JSON转换为Markdown
                    try:
                        md_content = "# AI测试用例评估报告\n\n"

                        if "evaluation_summary" in extracted_json:
                            summary = extracted_json["evaluation_summary"]
                            md_content += f"## 摘要\n\n"
                            md_content += f"**总体评分**: {summary.get('overall_score', 'N/A')}\n\n"
                            md_content += f"**改进建议**: {summary.get('final_suggestion', 'N/A')}\n\n"

                        if "detailed_report" in extracted_json:
                            md_content += f"## 详细评估\n\n"
                            detailed = extracted_json["detailed_report"]

                            for key, value in detailed.items():
                                if isinstance(value, dict) and "score" in value:
                                    md_content += f"### {key.replace('_', ' ').title()}\n\n"
                                    md_content += f"**评分**: {value.get('score', 'N/A')}\n\n"
                                    md_content += f"**理由**: {value.get('reason', 'N/A')}\n\n"

                                    if key == "duplicate_analysis" and "merge_suggestions" in value:
                                        md_content += f"**合并建议**: {value.get('merge_suggestions', 'N/A')}\n\n"

                                    if "analysis" in value and isinstance(value["analysis"], dict):
                                        analysis = value["analysis"]
                                        if "covered_features" in analysis:
                                            md_content += "**覆盖的功能**:\n\n"
                                            for feature in analysis["covered_features"]:
                                                md_content += f"- {feature}\n"
                                            md_content += "\n"

                                        if "missed_features_or_scenarios" in analysis:
                                            md_content += "**未覆盖的功能或场景**:\n\n"
                                            for feature in analysis["missed_features_or_scenarios"]:
                                                md_content += f"- {feature}\n"
                                            md_content += "\n"

                                        if "scenario_types_found" in analysis:
                                            md_content += "**发现的场景类型**:\n\n"
                                            for scenario in analysis["scenario_types_found"]:
                                                md_content += f"- {scenario}\n"
                                            md_content += "\n"

                        log("成功从提取的JSON生成Markdown报告", important=True)

                        # 在返回前替换占位符
                        from datetime import datetime
                        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                        footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                        # 替换占位符
                        import re
                        placeholder_patterns = [
                            r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                            r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                            r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                        ]

                        placeholder_found = False
                        for pattern in placeholder_patterns:
                            if re.search(pattern, md_content):
                                md_content = re.sub(pattern, footer, md_content)
                                placeholder_found = True
                                log("已替换提取JSON生成的md_content中的占位符为实时时间", important=True)
                                break

                        if not placeholder_found:
                            log("提取JSON生成的md_content中未找到占位符", level="WARNING")

                        return md_content
                    except Exception as e:
                        log_error(f"从提取的JSON生成Markdown报告失败: {e}")
                else:
                    log_error("从LLM响应中提取有效的JSON失败")
            except Exception as e:
                log_error(f"尝试提取JSON时出错: {e}")

            if retry_count < max_retries - 1:
                log(f"等待2秒后重试...", important=True)
                await asyncio.sleep(2)
            else:
                # 最后一次尝试失败，生成基本报告
                return generate_basic_report(evaluation_result)
        except Exception as e:
            log_error(f"生成报告时发生异常 (尝试 {retry_count + 1}/{max_retries}): {str(e)}")
            if retry_count < max_retries - 1:
                log(f"等待2秒后重试...", important=True)
                await asyncio.sleep(2)
            else:
                # 最后一次尝试失败，生成基本报告
                return generate_basic_report(evaluation_result)

    # 如果所有重试都失败，返回一个基本报告
    return generate_basic_report(evaluation_result)


def generate_basic_report(evaluation_result):
    """
    当LLM生成报告失败时，生成一个基本的报告
    
    :param evaluation_result: 评测结果
    :return: 基本的Markdown报告
    """
    try:
        # 提取评分
        overall_score = "N/A"
        if isinstance(evaluation_result, dict) and "evaluation_summary" in evaluation_result:
            overall_score = evaluation_result["evaluation_summary"].get("overall_score", "N/A")
        
        # 提取建议
        final_suggestion = "无法获取建议"
        if isinstance(evaluation_result, dict) and "evaluation_summary" in evaluation_result:
            final_suggestion = evaluation_result["evaluation_summary"].get("final_suggestion", "无法获取建议")
        
        # 构建基本报告
        report = f"""# AI测试用例评估报告

## 摘要

**总体评分**: {overall_score}/5.0

**改进建议**: {final_suggestion}

## 详细评估

"""
        
        # 添加详细评估
        if isinstance(evaluation_result, dict) and "detailed_report" in evaluation_result:
            detailed = evaluation_result["detailed_report"]
            for key, value in detailed.items():
                if isinstance(value, dict) and "score" in value:
                    report += f"### {key.replace('_', ' ').title()}\n\n"
                    report += f"**评分**: {value.get('score', 'N/A')}\n\n"
                    report += f"**理由**: {value.get('reason', 'N/A')}\n\n"
        
        # 添加页脚
        from datetime import datetime
        # 确保使用实时时间
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        # 构建页脚
        footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"
        
        # 检查是否已有页脚，如果有则替换，否则添加
        import re
        footer_pattern = r"\*\*生成时间：(.*?)(?:•|·|\*) *gogogo出发喽评估中心\*\*"
        placeholder_patterns = [
            r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
            r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
            r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
        ]
        
        # 先检查是否有明确的占位符
        placeholder_found = False
        for pattern in placeholder_patterns:
            if re.search(pattern, report):
                report = re.sub(pattern, footer, report)
                placeholder_found = True
                log("已替换基本报告页脚中的明确占位符为实时时间", important=True)
                break
        
        # 如果没有找到明确的占位符，尝试使用通用模式
        if not placeholder_found and re.search(footer_pattern, report):
            report = re.sub(footer_pattern, footer, report)
            log("已替换基本报告页脚中的日期为实时时间", important=True)
        elif not placeholder_found:
            # 如果没有找到页脚，则添加到报告末尾
            report += f"\n\n---\n{footer}\n"
            log("未找到页脚，已添加带有实时时间的页脚到基本报告", important=True)
        
        log("成功生成基本Markdown报告", important=True)
        return report
        
    except Exception as e:
        log_error(f"生成基本报告失败: {str(e)}")
        return "# 评测报告生成失败\n\n无法生成详细报告，请检查评测结果或重试。"


async def evaluate_and_generate_report(session: aiohttp.ClientSession, ai_cases, golden_cases, report_file, is_iteration=False, prev_iteration_cases=None, evaluation_result=None):
    """
    生成Markdown报告

    :param session: aiohttp会话
    :param ai_cases: AI生成的测试用例
    :param golden_cases: 黄金标准测试用例
    :param report_file: 报告文件路径
    :param is_iteration: 是否启用迭代前后对比功能
    :param prev_iteration_cases: 上一次迭代的测试用例（可选），仅在is_iteration为true时有效
    :param evaluation_result: 已有的评测结果（可选），如果提供则不再进行评测
    :return: 评估结果和Markdown报告
    """
    log("开始生成报告", important=True)

    # 如果没有提供评测结果，则进行评测
    if evaluation_result is None:
        log("未提供评测结果，开始进行评测", important=True)
        evaluation_result = await evaluate_test_cases(session, ai_cases, golden_cases, is_iteration, prev_iteration_cases)

        if not evaluation_result:
            log("测试用例评测失败", important=True)
            return {
                "success": False,
                "error": "测试用例评测失败"
            }
    else:
        log("使用已有评测结果生成报告", important=True)

    # 生成报告
    markdown_report = None
    markdown_report_iteration = None
    
    # 如果是迭代模式，需要生成两种报告：简洁的迭代报告和完整的标准报告
    if is_iteration:
        # 生成简洁的迭代报告
        log("生成简洁的迭代报告", important=True)
        markdown_report_iteration = await generate_markdown_report(session, evaluation_result, is_iteration=True, 
                                                           formatted_ai_cases=ai_cases, formatted_prev_cases=prev_iteration_cases)
        
        # 生成完整的标准报告（不使用迭代参数）
        log("生成完整的标准报告", important=True)
        markdown_report = await generate_markdown_report(session, evaluation_result, is_iteration=False, 
                                                 formatted_ai_cases=ai_cases)
    else:
        # 非迭代模式，只生成一种报告
        markdown_report = await generate_markdown_report(session, evaluation_result, 
                                                 formatted_ai_cases=ai_cases)

    # 确保至少有一个报告生成成功
    if (not markdown_report and not markdown_report_iteration) or (markdown_report and len(markdown_report.strip()) < 10):
        # 如果报告为空或内容太少，生成一个基本报告
        log("生成的Markdown报告为空或内容不足，尝试生成基本报告", important=True)
        markdown_report = generate_basic_report(evaluation_result)
        
        if not markdown_report or len(markdown_report.strip()) < 10:
            log("生成Markdown报告失败", important=True)
            return {
                "success": False,
                "error": "生成Markdown报告失败"
            }

    # 准备返回结果
    result = {
        "success": True,
        "evaluation_result": evaluation_result,
        "files": {
            "report_md": report_file,
            "report_json": report_file.replace("evaluation_markdown", "evaluation_json").replace(".md", ".json")
        }
    }
    
    # 添加相应的报告到结果中
    if markdown_report:
        result["markdown_report"] = markdown_report
        result["report"] = markdown_report
        log(f"已添加标准报告到结果，长度: {len(markdown_report)}", important=True)
        
    if markdown_report_iteration:
        result["report_iteration"] = markdown_report_iteration
        log(f"已添加迭代报告到结果，长度: {len(markdown_report_iteration)}", important=True)
    elif is_iteration:
        log("迭代模式已启用但迭代报告为空，未能添加迭代报告", level="WARNING")
    
    # 记录最终返回的字段
    log(f"最终结果包含以下字段: {', '.join(result.keys())}", important=True)
    
    # 如果是迭代模式，保存两种报告
    try:
        if is_iteration:
            # 保存完整的标准报告
            if markdown_report:
                # 确保目录存在
                os.makedirs(os.path.dirname(report_file), exist_ok=True)
                with open(report_file, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(markdown_report)
                # 验证文件写入成功
                if os.path.exists(report_file) and os.path.getsize(report_file) > 0:
                    log(f"完整的标准评测报告已保存到 {report_file} (大小: {os.path.getsize(report_file)}字节)", important=True)
                else:
                    log(f"警告：文件写入可能失败，文件大小为0或文件不存在: {report_file}", level="WARNING")
            
            # 保存简洁的迭代报告
            if markdown_report_iteration:
                iteration_report_file = report_file.replace(".md", "_iteration.md")
                # 确保目录存在
                os.makedirs(os.path.dirname(iteration_report_file), exist_ok=True)
                with open(iteration_report_file, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(markdown_report_iteration)
                # 验证文件写入成功
                if os.path.exists(iteration_report_file) and os.path.getsize(iteration_report_file) > 0:
                    log(f"简洁的迭代评测报告已保存到 {iteration_report_file} (大小: {os.path.getsize(iteration_report_file)}字节)", important=True)
                else:
                    log(f"警告：文件写入可能失败，文件大小为0或文件不存在: {iteration_report_file}", level="WARNING")
                result["files"]["report_iteration_md"] = iteration_report_file
        else:
            # 非迭代模式，只保存一种报告
            # 确保目录存在
            os.makedirs(os.path.dirname(report_file), exist_ok=True)
            with open(report_file, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(markdown_report)
            # 验证文件写入成功
            if os.path.exists(report_file) and os.path.getsize(report_file) > 0:
                log(f"Markdown格式的评测报告已保存到 {report_file} (大小: {os.path.getsize(report_file)}字节)", important=True)
            else:
                log(f"警告：文件写入可能失败，文件大小为0或文件不存在: {report_file}", level="WARNING")
            
        # 保存评测结果JSON文件
        json_file = report_file.replace("evaluation_markdown", "evaluation_json").replace(".md", ".json")
        try:
            with open(json_file, 'w', encoding='utf-8', errors='ignore') as f:
                json.dump(evaluation_result, f, ensure_ascii=False, indent=2)
            log(f"JSON格式的评测结果已保存到 {json_file}", important=True)
        except Exception as e:
            log_error(f"保存JSON格式的评测结果到 {json_file} 失败: {str(e)}")
            
        # 添加小延迟，确保日志顺序
        await asyncio.sleep(0.1)
    except Exception as e:
        log_error(f"保存Markdown格式的评测报告到 {report_file} 失败: {str(e)}")
        import traceback
        log_error(f"错误详情: {traceback.format_exc()}")
        # 继续执行，不中断流程

    log("报告生成流程完成！", important=True)
    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.1)
    end_logging()

    return result

async def evaluate_with_committee(session: aiohttp.ClientSession,
                                  ai_cases: Dict,
                                  golden_cases: Dict,
                                  duplicate_info_text: str = "",
                                  use_collab_eval: bool = None) -> Dict:
    """
    使用评委委员会评测测试用例

    :param session: aiohttp会话
    :param ai_cases: AI生成的测试用例
    :param golden_cases: 黄金标准测试用例
    :param duplicate_info_text: 重复测试用例分析信息
    :param use_collab_eval: 是否使用CollabEval框架，如果为None则使用配置文件中的设置
    :return: 汇总后的评测结果
    """
    try:
        # 直接使用委员会模块中的函数
        from committee import evaluate_with_committee as committee_evaluate
        return await committee_evaluate(session, ai_cases, golden_cases, duplicate_info_text, use_collab_eval)
    except TypeError as e:
        # 处理参数不匹配的情况
        log_error(f"调用委员会评测函数出现参数不匹配: {str(e)}", important=True)
        log("尝试不带use_collab_eval参数调用", important=True)
        try:
            # 尝试使用旧版本API调用
            from committee import evaluate_with_committee as committee_evaluate
            return await committee_evaluate(session, ai_cases, golden_cases, duplicate_info_text)
        except Exception as e2:
            log_error(f"备用调用也失败: {str(e2)}", important=True)
            return None
    except Exception as e:
        log_error(f"评委委员会评测过程中发生错误: {str(e)}", important=True)
        import traceback
        log_error(f"错误详情: {traceback.format_exc()}")
        return None
