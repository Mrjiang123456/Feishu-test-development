# --- START OF FILE main.py ---

import os
import json
import time
import requests
# 核心修复：从 typing 导入 Tuple, List, Dict
from typing import Union, List, Dict, Tuple

# --- 配置区 ---
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL_NAME = "deepseek-v3-250324"
VOLC_BEARER_TOKEN = "82cb3741-9d83-46fe-aeee-faad19eaf765"
AI_CASES_FILE = "ai_cases.json"
GOLDEN_CASES_FILE = "golden_cases.json"
REPORT_FILE = "evaluation_report_http.md"
REPORT_JSON_FILE = "evaluation_report_structured.json"

# --- 数据标准化模块 ---
def normalize_test_cases(test_cases_data: List[Dict], prefix: str) -> List[Dict]:
    normalized_list = []
    for i, case in enumerate(test_cases_data):
        steps_str = "\n".join(case.get("操作步骤", []))
        expected_results_str = "\n".join(case.get("预期结果", []))
        normalized_case = {
            "id": f"{prefix}_{i+1:03d}",
            "title": case.get("标题", "无标题"),
            "preconditions": case.get("前置条件", ""),
            "steps": steps_str,
            "expected_results": expected_results_str
        }
        normalized_list.append(normalized_case)
    return normalized_list

# --- LLM 通信模块 ---
def call_llm(prompt: str, system_prompt: str = "你是一个有帮助的助手，请用中文回答。"):
    if not VOLC_BEARER_TOKEN:
        print("错误：环境变量 VOLC_BEARER_TOKEN 未设置。")
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_BEARER_TOKEN}"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }
    try:
        print("    > 正在调用LLM API (via HTTP)...")
        response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        if response.status_code != 200:
            print(f"    > LLM API调用失败，状态码: {response.status_code}, 响应: {response.text}")
            return None
        response_json = response.json()
        content = response_json['choices'][0]['message']['content']
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        return json.loads(content)
    except requests.exceptions.RequestException as e:
        print(f"    > HTTP请求失败: {e}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"    > 解析LLM响应失败: {e}")
        print(f"    > 原始返回内容: {response.text if 'response' in locals() else 'N/A'}")
        return None

# --- 核心评测逻辑 ---
def get_top_candidates_prompt(ai_case: Dict, golden_cases: List[Dict]) -> str:
    golden_cases_str_list = []
    for case in golden_cases:
        summary = f"前置: {case.get('preconditions', '').splitlines()[0]} ... 预期: {case.get('expected_results', '').splitlines()[0]}"
        golden_cases_str_list.append(f"- ID: {case['id']}\n  标题: {case['title']}\n  摘要: {summary}")
    golden_cases_formatted = "\n\n".join(golden_cases_str_list)
    return f"""
# 角色
你是一个高效的软件测试分类专家。

# 任务
从下面的【黄金用例列表】中，为【待匹配AI用例】选出最相似的最多3个候选者。

# 待匹配AI用例
{json.dumps(ai_case, ensure_ascii=False, indent=2)}

# 黄金用例列表
{golden_cases_formatted}

# 输出要求
请严格按照JSON格式输出。JSON包含一个字段 "top_candidate_ids"，其值为一个包含最多3个最相关黄金用例ID的数组。按相关性从高到低排序。如果一个都找不到，返回空数组。
请务必使用中文思考和分析。

示例输出:
{{"top_candidate_ids": ["GOLDEN_001", "GOLDEN_007", "GOLDEN_003"]}}
"""

def get_match_score_prompt(ai_case: Dict, golden_case: Dict) -> str:
    return f"""
# 角色
你是一位资深的测试经理，你的强项是快速理解和识别测试用例背后的核心意图，而不是纠结于文字细节。

# 任务
请评估【测试用例A】和【测试用例B】的核心测试目的是否一致，并给出一个1-10分的相似度分数。

# 思考步骤（请在内部参考，无需输出）
1.  AI用例A的核心目标是什么？（例如：测试成功登录）
2.  黄金用例B的核心目标是什么？（例如：测试使用特定有效账号成功登录）
3.  这两个目标是否本质上一致？是否一个是成功路径，另一个是失败路径？
4.  基于此，参考下面的评分标准和关键示例，给出一个分数。

# 关键示例（这是一个重要的判例）
如果用例A是"标题:登录系统, 步骤:输入用户名密码, 预期:登录成功"，而用例B是"标题:账号密码登录成功, 步骤:输入'testuser'和'Test@123', 预期:跳转到仪表盘"，这种情况就应该被评为9分或10分，因为它们的核心意图完全一致。

# 评分标准（已调整）
- 1-3分：完全不相关。
- 4-6分：功能模块相关，但测试场景或目的完全不同（例如，一个测试创建，另一个测试删除；或一个测试成功，另一个测试失败）。
- 7-8分：高度相似。核心测试目的和用户行为路径基本一致。这是"好的匹配"。
- 9-10分：意图完全相同。可以明确判断AI用例就是在尝试生成这个黄金用例所描述的场景。这是"完美的匹配"。

# 测试用例A (AI生成)
{json.dumps(ai_case, ensure_ascii=False, indent=2)}

# 测试用例B (黄金标准)
{json.dumps(golden_case, ensure_ascii=False, indent=2)}

# 输出要求
严格按照JSON格式输出，只包含两个字段 "match_score" (1-10的整数) 和 "reason" (一句话理由)。
必须使用中文回答reason字段，这一点非常重要。
"""

def get_evaluation_prompt(ai_case: Dict, golden_case: Dict) -> str:
    return f"""
# 角色
你是一位极其挑剔和严谨的软件质量保证（QA）总监。

# 任务
你正在审查一个由AI生成的测试用例。请将其与一个人工编写的"黄金标准"用例进行对比，并从多个维度进行严格打分。请重点关注语义，而不是字面。

# 黄金标准用例 (Golden Case)
{json.dumps(golden_case, ensure_ascii=False, indent=2)}

# AI生成的待评估用例 (AI Case)
{json.dumps(ai_case, ensure_ascii=False, indent=2)}

# 评分标准与输出要求
请根据以下标准，以JSON格式输出你的评估结果，不要包含任何其他说明文字。分数范围为1-5分，5分表示完美，1分表示严重缺陷。
必须使用中文回答所有reason字段和overall_comment字段，这一点非常重要。

{{
  "scores": {{
    "completeness_preconditions": {{ "score": "<1-5>", "reason": "<使用中文表达的理由>" }},
    "completeness_steps": {{ "score": "<1-5>", "reason": "<使用中文表达的理由>" }},
    "completeness_expected_results": {{ "score": "<1-5>", "reason": "<使用中文表达的理由>" }},
    "accuracy": {{ "score": "<1-5>", "reason": "<使用中文表达的理由>" }},
    "clarity": {{ "score": "<1-5>", "reason": "<使用中文表达的理由>" }}
  }},
  "overall_comment": "<使用中文表达的对这个AI用例的总体评价和改进建议>"
}}
"""

# 核心修复：修改函数签名以兼容旧版Python
def find_best_match(ai_case: Dict, golden_cases: List[Dict]) -> Union[Tuple[Dict, None], Tuple[None, str]]:
    print("    > 阶段1/2：粗筛Top-3候选者...")
    prompt_candidates = get_top_candidates_prompt(ai_case, golden_cases)
    result_candidates = call_llm(prompt_candidates, "你是一个高效的软件测试分类专家，严格按JSON输出，请用中文思考和分析。")
    candidate_ids = result_candidates.get("top_candidate_ids", []) if result_candidates else []
    if not candidate_ids:
        reason = "粗筛阶段未能从黄金用例中找到任何相关候选者。"
        print(f"    > {reason}")
        return None, reason
    print(f"    > 粗筛结果: {candidate_ids}")
    candidate_cases = [case for case in golden_cases if case["id"] in candidate_ids]
    print("    > 阶段2/2：精排打分...")
    best_match_case = None
    best_score = 0
    best_reason = "精排阶段未收到任何有效的评分结果。"
    MIN_MATCH_SCORE_THRESHOLD = 7
    for candidate_case in candidate_cases:
        prompt_score = get_match_score_prompt(ai_case, candidate_case)
        result_score = call_llm(prompt_score, "你是一位极其严谨的软件测试架构师，严格按JSON输出，必须使用中文回答。")
        time.sleep(1)
        if result_score and isinstance(result_score.get("match_score"), int):
            current_score = result_score["match_score"]
            current_reason = result_score.get("reason", "无理由")
            print(f"      - AI '{ai_case['id']}' vs Golden '{candidate_case['id']}': 得分 {current_score} (理由: {current_reason})")
            if current_score > best_score:
                best_score = current_score
                best_match_case = candidate_case
                best_reason = current_reason
    if best_score >= MIN_MATCH_SCORE_THRESHOLD:
        print(f"    > 精排完成，最佳匹配为 '{best_match_case['id']}' (得分: {best_score})")
        return best_match_case, None
    else:
        unmatch_reason = f"精排最高分({best_score})低于门槛({MIN_MATCH_SCORE_THRESHOLD})。最高分理由: {best_reason}"
        print(f"    > {unmatch_reason}")
        return None, unmatch_reason

# --- 主程序 ---
def main(ai_cases_data=None):
    """
    执行自动化评测流程
    
    参数：
        ai_cases_data: 直接传入的AI测试用例数据，格式为dict，如果为None则从AI_CASES_FILE文件读取
    """
    print("自动化评测流程开始...")
    try:
        # 获取AI用例数据：优先使用传入的数据，如无则从文件读取
        if ai_cases_data is None:
            with open(AI_CASES_FILE, 'r', encoding='utf-8') as f:
                ai_cases_data = json.load(f)
        
        ai_cases = normalize_test_cases(ai_cases_data.get('testcases', []), "AI")
        
        # 黄金用例仍然从文件读取
        with open(GOLDEN_CASES_FILE, 'r', encoding='utf-8') as f:
            golden_cases_data = json.load(f)
            golden_cases = normalize_test_cases(golden_cases_data.get('testcases', []), "GOLDEN")
        print(f"成功加载并标准化 {len(ai_cases)} 个AI用例和 {len(golden_cases)} 个黄金用例。")
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"错误: 加载或解析文件失败 - {e}")
        return
    print("\n--- 阶段一：匹配AI用例与黄金用例 ---")
    matched_pairs = []
    unmatched_ai_cases = []
    covered_golden_case_ids = set()
    for i, ai_case in enumerate(ai_cases):
        print(f"\n正在处理第 {i + 1}/{len(ai_cases)} 个AI用例 (ID: {ai_case.get('id', 'N/A')})...")
        best_match, unmatch_reason = find_best_match(ai_case, golden_cases)
        if best_match:
            print(f"  > 匹配成功: AI用例 '{ai_case['id']}' -> 黄金用例 '{best_match['id']}'")
            matched_pairs.append({"ai_case": ai_case, "golden_case": best_match})
            covered_golden_case_ids.add(best_match['id'])
        else:
            print(f"  > 匹配失败: AI用例 '{ai_case['id']}' 未找到对应黄金用例。")
            unmatched_ai_cases.append({"case": ai_case, "reason": unmatch_reason})
    print("\n--- 阶段二：详细评估匹配的用例对 ---")
    evaluation_results = []
    for i, pair in enumerate(matched_pairs):
        print(
            f"\n正在评估第 {i + 1}/{len(matched_pairs)} 对用例 (AI: {pair['ai_case']['id']}, Golden: {pair['golden_case']['id']})...")
        prompt = get_evaluation_prompt(pair['ai_case'], pair['golden_case'])
        eval_result = call_llm(prompt, "你是一位极其挑剔和严谨的QA总监，严格按JSON输出，必须使用中文回答所有评价内容。")
        time.sleep(1)
        if eval_result:
            evaluation_results.append({"pair": pair, "evaluation": eval_result})
            print("  > 评估完成。")
        else:
            evaluation_results.append({"pair": pair, "evaluation": {"error": "LLM avaluation failed."}})
            print("  > 评估失败，已记录错误信息。")
    print("\n--- 阶段三：计算指标并生成报告 ---")
    total_golden = len(golden_cases)
    total_ai = len(ai_cases)
    coverage = len(covered_golden_case_ids) / total_golden if total_golden > 0 else 0
    precision = len(matched_pairs) / total_ai if total_ai > 0 else 0
    f1_score = 2 * (precision * coverage) / (precision + coverage) if (precision + coverage) > 0 else 0
    avg_scores = {}
    valid_evaluations = [res for res in evaluation_results if 'error' not in res.get('evaluation', {})]
    if valid_evaluations:
        if valid_evaluations[0].get('evaluation') and valid_evaluations[0]['evaluation'].get('scores'):
            score_keys = valid_evaluations[0]['evaluation']['scores'].keys()
            for key in score_keys:
                scores_list = [
                    res['evaluation']['scores'][key]['score']
                    for res in valid_evaluations
                    if isinstance(res.get('evaluation', {}).get('scores', {}).get(key, {}).get('score'), (int, float))
                ]
                if scores_list:
                    avg_scores[key] = sum(scores_list) / len(scores_list)
    print("    > 正在整理所有AI用例的评测结果...")
    all_ai_case_reports = []
    evaluated_map = {res['pair']['ai_case']['id']: res for res in evaluation_results}
    unmatched_map = {item['case']['id']: item['reason'] for item in unmatched_ai_cases}
    for ai_case in ai_cases:
        ai_case_id = ai_case.get('id')
        report_entry = {"ai_case_id": ai_case_id, "ai_case_title": ai_case.get('title')}
        if ai_case_id in evaluated_map:
            result = evaluated_map[ai_case_id]
            report_entry["status"] = "Matched"
            report_entry["matched_golden_case_id"] = result['pair']['golden_case'].get('id')
            report_entry["evaluation"] = result.get('evaluation')
            report_entry["unmatch_reason"] = None
        else:
            report_entry["status"] = "Unmatched"
            report_entry["matched_golden_case_id"] = None
            report_entry["evaluation"] = None
            report_entry["unmatch_reason"] = unmatched_map.get(ai_case_id, "未知原因")
        all_ai_case_reports.append(report_entry)
    final_json_report = {
        "summary_metrics": {
            "coverage_recall": f"{coverage:.4f}",
            "precision": f"{precision:.4f}",
            "f1_score": f"{f1_score:.4f}",
            "total_ai_cases": total_ai,
            "total_golden_cases": total_golden,
            "matched_ai_cases_count": len(matched_pairs),
            "unmatched_ai_cases_count": len(unmatched_ai_cases),
            "average_scores": {key: f"{value:.2f}" for key, value in avg_scores.items()}
        },
        "detailed_evaluations": all_ai_case_reports
    }
    with open(REPORT_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_json_report, f, ensure_ascii=False, indent=2)
    print(f"    > 结构化JSON报告已成功生成: {REPORT_JSON_FILE}")
    print(f"    > 正在生成Markdown详细报告...")
    uncovered_golden_cases = [gc for gc in golden_cases if gc['id'] not in covered_golden_case_ids]
    def safe_format(score_key):
        score = avg_scores.get(score_key)
        return f"{score:.2f}" if isinstance(score, (int, float)) else "N/A"
    report_content = f"""
# LLM生成测试用例自动化评测报告
## 1. 核心指标摘要
| 指标 | 计算公式 | 结果 | 解读 |
| :--- | :--- | :--- | :--- |
| **覆盖率 (Recall)** | (AI覆盖的黄金用例数 / 黄金用例总数) | **{coverage:.2%}** | AI生成能力是否全面，是否遗漏了关键测试点。 |
| **精确率 (Precision)** | (有效AI用例数 / AI用例总数) | **{precision:.2%}** | AI生成的内容是否"靠谱"，有多少是有效用例。 |
| **F1-Score** | 2 * (Precision * Recall) / (Precision + Recall) | **{f1_score:.2f}** | 覆盖率和精确率的调和平均值，综合评价指标。 |
---
## 2. 平均质量分数 (1-5分)
根据已成功匹配并评估的 **{len(valid_evaluations)}** 对用例进行打分：
| 评估维度 | 平均分 |
| :--- | :--- |
| 前置条件完整度 | {safe_format('completeness_preconditions')} |
| 操作步骤完整度 | {safe_format('completeness_steps')} |
| 预期结果完整度 | {safe_format('completeness_expected_results')} |
| 逻辑准确性 | {safe_format('accuracy')} |
| 语言清晰度 | {safe_format('clarity')} |
---
## 3. 详细分析
### 3.1 未被AI覆盖的黄金用例
以下 **{len(uncovered_golden_cases)}** 个黄金用例没有被任何AI用例覆盖，表明模型可能存在这些场景的生成盲区：
"""
    if not uncovered_golden_cases: report_content += "- 无\n"
    else:
        for case in uncovered_golden_cases: report_content += f"- **ID: {case.get('id', 'N/A')}** - {case.get('title', 'N/A')}\n"
    report_content += f"""
### 3.2 无效/冗余的AI生成用例
以下 **{len(unmatched_ai_cases)}** 个AI用例未能匹配任何黄金用例，可能是无效、超出范围或冗余的用例。**原因分析如下：**
"""
    if not unmatched_ai_cases: report_content += "- 无\n"
    else:
        for item in unmatched_ai_cases:
            case = item['case']
            reason = item['reason']
            report_content += f"- **ID: {case.get('id', 'N/A')}** - {case.get('title', 'N/A')}\n  - **未匹配原因**: {reason}\n"
    report_content += """
---
## 4. 逐项评估详情
"""
    if not evaluation_results: report_content += "- 无匹配用例，无详细评估。\n"
    else:
        for i, result in enumerate(evaluation_results):
            ai_case = result['pair']['ai_case']
            golden_case = result['pair']['golden_case']
            eval_data = result.get('evaluation', {})
            report_content += f"""
### 4.{i + 1} 对比：AI用例 `{ai_case.get('id', 'N/A')}` vs 黄金用例 `{golden_case.get('id', 'N/A')}`
**AI用例标题**: {ai_case.get('title', 'N/A')}
**黄金用例标题**: {golden_case.get('title', 'N/A')}
"""
            if 'error' in eval_data:
                report_content += f"\n**评估状态**: <span style='color:red;'>评估失败</span> ({eval_data['error']})\n"
            else:
                scores = eval_data.get('scores', {})
                report_content += f"""
**总体评价**: {eval_data.get('overall_comment', 'N/A')}
| 维度 | 分数 | 评审意见 |
| :--- | :--- | :--- |
| 前置条件 | {scores.get('completeness_preconditions', {}).get('score', 'N/A')} | {scores.get('completeness_preconditions', {}).get('reason', 'N/A')} |
| 操作步骤 | {scores.get('completeness_steps', {}).get('score', 'N/A')} | {scores.get('completeness_steps', {}).get('reason', 'N/A')} |
| 预期结果 | {scores.get('completeness_expected_results', {}).get('score', 'N/A')} | {scores.get('completeness_expected_results', {}).get('reason', 'N/A')} |
| 准确性 | {scores.get('accuracy', {}).get('score', 'N/A')} | {scores.get('accuracy', {}).get('reason', 'N/A')} |
| 清晰度 | {scores.get('clarity', {}).get('score', 'N/A')} | {scores.get('clarity', {}).get('reason', 'N/A')} |
"""
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"    > Markdown详细报告已生成: {REPORT_FILE}")
    print(f"\n评测完成！报告已生成:")
    print(f"- Markdown详细报告: {REPORT_FILE}")
    print(f"- JSON结构化报告: {REPORT_JSON_FILE}")
    
    # 返回评测报告结果
    return final_json_report

if __name__ == "__main__":
    main()