import os
import json
import time
import requests  # 使用 requests 库
from typing import Union
# --- 配置区 ---
# API的URL，从curl命令中获取
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


MODEL_NAME = "deepseek-v3-250324"


# VOLC_BEARER_TOKEN = os.getenv("VOLC_BEARER_TOKEN")
VOLC_BEARER_TOKEN = "c67334ea-dfc7-45b0-8376-0ffb448a902b" # 直接在这里写入你的密钥

# 输入文件名
AI_CASES_FILE = "ai_cases.json"
GOLDEN_CASES_FILE = "golden_cases.json"

# 输出报告文件名
REPORT_FILE = "evaluation_report_http.md"


# --- LLM 通信模块 ---

def call_llm(prompt: str, system_prompt: str = "You are a helpful assistant."):
    """
    通过HTTP POST请求调用火山引擎大模型并获取结果。

    :param prompt: 用户输入的提示。
    :param system_prompt: 系统角色提示。
    :return: 解析后的JSON对象，如果失败则返回None。
    """
    if not VOLC_BEARER_TOKEN:
        print("错误：环境变量 VOLC_BEARER_TOKEN 未设置。请设置你的API Bearer Token。")
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
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)

        # 检查HTTP响应状态码
        if response.status_code != 200:
            print(f"    > LLM API调用失败，状态码: {response.status_code}")
            print(f"    > 响应内容: {response.text}")
            return None

        print("    > LLM响应接收成功。")
        response_json = response.json()
        content = response_json['choices'][0]['message']['content']

        # 尝试从返回的Markdown代码块中提取JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()

        return json.loads(content)

    except requests.exceptions.RequestException as e:
        print(f"    > HTTP请求失败: {e}")
        return None
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"    > 解析LLM响应或其中的JSON失败: {e}")
        print(f"    > 原始返回内容: {response.text if 'response' in locals() else 'N/A'}")
        return None


# --- 核心评测逻辑 (这部分无需修改) ---

def get_match_prompt(ai_case: dict, golden_case: dict) -> str:
    """生成用于匹配的Prompt"""
    return f"""
# 角色
你是一个资深的软件测试专家。

# 任务
判断下面【测试用例A】和【测试用例B】是否指向同一个核心测试场景。请忽略措辞和步骤拆分的细微差异，关注其核心测试目的。

# 测试用例A (AI生成)
标题：{ai_case.get('title', '')}
步骤：{ai_case.get('steps', '')}

# 测试用例B (黄金标准)
标题：{golden_case.get('title', '')}
步骤：{golden_case.get('steps', '')}

# 输出要求
请仅使用JSON格式输出，不要包含任何其他说明文字。
JSON格式包含两个字段：
1. "is_match": 布尔值(true/false)，表示是否匹配。
2. "reason": 字符串，简要说明你的判断理由（不超过30字）。

示例输出:
{{"is_match": true, "reason": "两者都测试了使用正确凭据成功登录的场景。"}}
"""


def get_evaluation_prompt(ai_case: dict, golden_case: dict) -> str:
    """生成用于详细评估的Prompt"""
    return f"""
# 角色
你是一位极其挑剔和严谨的软件质量保证（QA）总监。

# 任务
你正在审查一个由AI生成的测试用例。请将其与一个人工编写的“黄金标准”用例进行对比，并从多个维度进行严格打分。请重点关注语义，而不是字面。

# 黄金标准用例 (Golden Case)
{json.dumps(golden_case, ensure_ascii=False, indent=2)}

# AI生成的待评估用例 (AI Case)
{json.dumps(ai_case, ensure_ascii=False, indent=2)}

# 评分标准与输出要求
请根据以下标准，以JSON格式输出你的评估结果，不要包含任何其他说明文字。分数范围为1-5分，5分表示完美，1分表示严重缺陷。
{{
  "scores": {{
    "completeness_preconditions": {{
      "score": "<1-5之间的整数>",
      "reason": "<评价理由，说明AI用例的前置条件相比黄金用例是缺失、等价还是更优>"
    }},
    "completeness_steps": {{
      "score": "<1-5之间的整数>",
      "reason": "<评价理由，说明AI用例的操作步骤是否有遗漏、冗余或错误>"
    }},
    "completeness_expected_results": {{
      "score": "<1-5之间的整数>",
      "reason": "<评价理由，说明AI用例的预期结果是否准确且全面>"
    }},
    "accuracy": {{
      "score": "<1-5之间的整数>",
      "reason": "<评价理由，说明AI用例的核心业务逻辑是否准确无误>"
    }},
    "clarity": {{
      "score": "<1-5之间的整数>",
      "reason": "<评价理由，说明AI用例的语言是否清晰易懂，无歧义>"
    }}
  }},
  "overall_comment": "<对这个AI用例的总体评价和改进建议>"
}}
"""


def find_best_match(ai_case: dict, golden_cases: list) -> Union[dict, None]:
    """在黄金用例中为AI用例找到最佳匹配"""
    # ... 函数内容 ...
    for golden_case in golden_cases:
        prompt = get_match_prompt(ai_case, golden_case)
        result = call_llm(prompt, system_prompt="你是一个资深的软件测试专家，严格按照指令输出JSON。")
        time.sleep(1)  # 避免API调用过于频繁
        if result and result.get("is_match") is True:
            return golden_case
    return None


# --- 主程序  ---

def main():
    print("自动化评测流程开始...")

    # 1. 加载用例文件
    try:
        with open(AI_CASES_FILE, 'r', encoding='utf-8') as f:
            ai_cases = json.load(f)
        with open(GOLDEN_CASES_FILE, 'r', encoding='utf-8') as f:
            golden_cases = json.load(f)
        print(f"成功加载 {len(ai_cases)} 个AI用例和 {len(golden_cases)} 个黄金用例。")
    except FileNotFoundError as e:
        print(f"错误：找不到文件 {e.filename}。请确保文件存在于正确的位置。")
        return
    except json.JSONDecodeError as e:
        print(f"错误：JSON文件格式不正确: {e}")
        return

    # 2. 匹配阶段
    print("\n--- 阶段一：匹配AI用例与黄金用例 ---")
    matched_pairs = []
    unmatched_ai_cases = []
    covered_golden_case_ids = set()
    available_golden_cases = list(golden_cases)

    for i, ai_case in enumerate(ai_cases):
        print(f"\n正在处理第 {i + 1}/{len(ai_cases)} 个AI用例 (ID: {ai_case.get('id', 'N/A')})...")
        best_match = find_best_match(ai_case, available_golden_cases)

        if best_match:
            print(f"  > 匹配成功: AI用例 '{ai_case['id']}' -> 黄金用例 '{best_match['id']}'")
            matched_pairs.append({"ai_case": ai_case, "golden_case": best_match})
            covered_golden_case_ids.add(best_match['id'])
            available_golden_cases = [gc for gc in available_golden_cases if gc['id'] != best_match['id']]
        else:
            print(f"  > 匹配失败: AI用例 '{ai_case['id']}' 未找到对应黄金用例。")
            unmatched_ai_cases.append(ai_case)

    # 3. 评估阶段
    print("\n--- 阶段二：详细评估匹配的用例对 ---")
    evaluation_results = []
    for i, pair in enumerate(matched_pairs):
        print(
            f"\n正在评估第 {i + 1}/{len(matched_pairs)} 对用例 (AI: {pair['ai_case']['id']}, Golden: {pair['golden_case']['id']})...")
        prompt = get_evaluation_prompt(pair['ai_case'], pair['golden_case'])
        eval_result = call_llm(prompt, system_prompt="你是一位极其挑剔和严谨的QA总监，严格按照指令输出JSON。")
        time.sleep(1)  # 避免API调用过于频繁
        if eval_result:
            evaluation_results.append({
                "pair": pair,
                "evaluation": eval_result
            })
            print("  > 评估完成。")
        else:
            print("  > 评估失败，跳过此对。")

    # 4. 计算与报告生成
    print("\n--- 阶段三：计算指标并生成报告 ---")

    total_golden = len(golden_cases)
    total_ai = len(ai_cases)
    coverage = len(covered_golden_case_ids) / total_golden if total_golden > 0 else 0
    precision = len(matched_pairs) / total_ai if total_ai > 0 else 0
    f1_score = 2 * (precision * coverage) / (precision + coverage) if (precision + coverage) > 0 else 0

    avg_scores = {}
    if evaluation_results:
        score_keys = evaluation_results[0]['evaluation']['scores'].keys()
        for key in score_keys:
            scores_list = [res['evaluation']['scores'][key]['score'] for res in evaluation_results if
                           isinstance(res['evaluation']['scores'][key].get('score'), int)]
            if scores_list:
                avg_scores[key] = sum(scores_list) / len(scores_list)

    report_content = f"""
# LLM生成测试用例自动化评测报告

## 1. 核心指标摘要

| 指标 | 计算公式 | 结果 | 解读 |
| :--- | :--- | :--- | :--- |
| **覆盖率 (Recall)** | (AI覆盖的黄金用例数 / 黄金用例总数) | **{coverage:.2%}** | AI生成能力是否全面，是否遗漏了关键测试点。 |
| **精确率 (Precision)** | (有效AI用例数 / AI用例总数) | **{precision:.2%}** | AI生成的内容是否“靠谱”，有多少是有效用例。 |
| **F1-Score** | 2 * (Precision * Recall) / (Precision + Recall) | **{f1_score:.2f}** | 覆盖率和精确率的调和平均值，综合评价指标。 |

---

## 2. 平均质量分数 (1-5分)

根据已成功匹配的 **{len(evaluation_results)}** 对用例进行打分：

| 评估维度 | 平均分 |
| :--- | :--- |
| 前置条件完整度 | {avg_scores.get('completeness_preconditions', 'N/A'):.2f} |
| 操作步骤完整度 | {avg_scores.get('completeness_steps', 'N/A'):.2f} |
| 预期结果完整度 | {avg_scores.get('completeness_expected_results', 'N/A'):.2f} |
| 逻辑准确性 | {avg_scores.get('accuracy', 'N/A'):.2f} |
| 语言清晰度 | {avg_scores.get('clarity', 'N/A'):.2f} |

---

## 3. 详细分析

### 3.1 未被AI覆盖的黄金用例

以下 **{total_golden - len(covered_golden_case_ids)}** 个黄金用例没有被任何AI用例覆盖，表明模型可能存在这些场景的生成盲区：

"""
    uncovered_golden_cases = [gc for gc in golden_cases if gc['id'] not in covered_golden_case_ids]
    if not uncovered_golden_cases:
        report_content += "- 无\n"
    else:
        for case in uncovered_golden_cases:
            report_content += f"- **ID: {case['id']}** - {case['title']}\n"

    report_content += """
### 3.2 无效/冗余的AI生成用例

以下 **{len(unmatched_ai_cases)}** 个AI用例未能匹配任何黄金用例，可能是无效、超出范围或冗余的用例：

"""
    if not unmatched_ai_cases:
        report_content += "- 无\n"
    else:
        for case in unmatched_ai_cases:
            report_content += f"- **ID: {case['id']}** - {case['title']}\n"

    report_content += """
---

## 4. 逐项评估详情

"""
    if not evaluation_results:
        report_content += "- 无匹配用例，无详细评估。\n"
    else:
        for i, result in enumerate(evaluation_results):
            ai_case = result['pair']['ai_case']
            golden_case = result['pair']['golden_case']
            eval_data = result['evaluation']

            report_content += f"""
### 4.{i + 1} 对比：AI用例 `{ai_case['id']}` vs 黄金用例 `{golden_case['id']}`

**AI用例标题**: {ai_case['title']}
**黄金用例标题**: {golden_case['title']}

**总体评价**: {eval_data.get('overall_comment', 'N/A')}

| 维度 | 分数 | 评审意见 |
| :--- | :--- | :--- |
| 前置条件 | {eval_data['scores']['completeness_preconditions']['score']} | {eval_data['scores']['completeness_preconditions']['reason']} |
| 操作步骤 | {eval_data['scores']['completeness_steps']['score']} | {eval_data['scores']['completeness_steps']['reason']} |
| 预期结果 | {eval_data['scores']['completeness_expected_results']['score']} | {eval_data['scores']['completeness_expected_results']['reason']} |
| 准确性 | {eval_data['scores']['accuracy']['score']} | {eval_data['scores']['accuracy']['reason']} |
| 清晰度 | {eval_data['scores']['clarity']['score']} | {eval_data['scores']['clarity']['reason']} |

"""
    # 5. 写入报告文件
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"\n评测完成！详细报告已生成在: {REPORT_FILE}")


if __name__ == "__main__":
    main()