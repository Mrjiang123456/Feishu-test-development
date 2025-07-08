import asyncio
import json
import aiohttp
from typing import List, Dict, Any
from logger import log, log_error
from llm_api import async_call_llm, extract_valid_json
from config import JUDGE_MODELS, MAX_JUDGES_CONCURRENCY, EVALUATION_DIMENSIONS


class EvaluationCommittee:
    """评估委员会类，管理多个LLM评委对测试用例的评估"""

    def __init__(self, session: aiohttp.ClientSession):
        """
        初始化评估委员会

        :param session: aiohttp会话
        """
        self.session = session
        self.judges = JUDGE_MODELS
        self.dimensions = EVALUATION_DIMENSIONS
        self.max_concurrency = MAX_JUDGES_CONCURRENCY

    def _build_evaluation_prompt(self, ai_cases: Dict, golden_cases: Dict, duplicate_info_text: str) -> str:
        """
        构建评测提示

        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :return: 完整的评测提示
        """
        # 序列化测试用例
        ai_cases_json = json.dumps(ai_cases, ensure_ascii=False, indent=2)
        golden_cases_json = json.dumps(golden_cases, ensure_ascii=False, indent=2)

        # 基础提示
        prompt = """
# 任务
评估AI生成的测试用例与黄金标准测试用例的质量对比。

# 评估维度和权重
1. **功能覆盖度**（权重30%）：评估需求覆盖率、边界值覆盖度、分支路径覆盖率
2. **缺陷发现能力**（权重25%）：评估缺陷检测率、突变分数、失败用例比例
3. **工程效率**（权重20%）：评估测试用例生成速度、维护成本、CI/CD集成度
4. **语义质量**（权重15%）：评估语义准确性、人工可读性、断言描述清晰度
5. **安全与经济性**（权重10%）：评估恶意代码率、冗余用例比例、综合成本
"""

        # 添加重复测试用例信息
        if duplicate_info_text:
            prompt += "\n" + duplicate_info_text + "\n"

        # 添加评分公式
        prompt += """
# 评分公式
总分 = 0.3×功能覆盖得分 + 0.25×缺陷发现得分 + 0.2×工程效率得分 + 0.15×语义质量得分 + 0.1×安全经济得分
各维度得分 = (AI指标值/人工基准值)×10（满分10分）

# AI生成的测试用例
```json
"""
        # 添加AI测试用例
        prompt += ai_cases_json + "\n```\n\n"

        # 添加黄金标准测试用例
        prompt += """
# 黄金标准测试用例
```json
"""
        prompt += golden_cases_json + "\n```\n\n"

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
      "reason": "得分理由"
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
      "reason": "得分理由"
    },
    "semantic_quality": {
      "score": "语义质量得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "security_economy": {
      "score": "安全与经济性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    },
    "duplicate_analysis": {
      "score": "测试用例重复分析得分（1-5之间的一位小数）",
      "reason": "分析重复测试用例的影响"
    }
  }
}
```
"""

        return prompt

    async def evaluate_with_judge(self,
                                  judge_model: str,
                                  ai_cases: Dict,
                                  golden_cases: Dict,
                                  duplicate_info_text: str = "") -> Dict:
        """
        使用单个评委模型进行评测

        :param judge_model: 评委模型名称
        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :return: 评测结果
        """
        log(f"评委 {judge_model} 开始评测", important=True, model_name=judge_model)

        # 构建评测提示
        prompt = self._build_evaluation_prompt(ai_cases, golden_cases, duplicate_info_text)
        system_prompt = "你是一位精通软件测试和质量评估的专家。请根据提供的测试用例进行客观、专业的评估。"

        # 调用LLM进行评测
        result = await async_call_llm(
            self.session,
            prompt,
            system_prompt,
            model_name=judge_model
        )

        if not result:
            log_error(f"评委 {judge_model} 评测失败", important=True, model_name=judge_model)
            return {"error": f"评委 {judge_model} 评测失败"}

        log(f"评委 {judge_model} 评测完成", important=True, model_name=judge_model)

        # 处理评测结果
        if isinstance(result, dict) and "text" in result:
            # 尝试解析文本为JSON
            try:
                text_content = result["text"]
                # 首先尝试直接解析
                try:
                    parsed_result = json.loads(text_content)
                    return parsed_result
                except json.JSONDecodeError:
                    # 使用提取函数尝试从文本中提取有效的JSON
                    log(f"评委 {judge_model} 返回的结果无法直接解析为JSON，尝试提取有效JSON部分", model_name=judge_model)
                    extracted_json = extract_valid_json(text_content)
                    if extracted_json:
                        log(f"成功从评委 {judge_model} 的响应中提取有效JSON", model_name=judge_model)
                        return extracted_json
                    else:
                        log_error(f"评委 {judge_model} 返回的结果无法解析为JSON，即使尝试提取",
                                  {"text": text_content[:200]}, model_name=judge_model)
                        return {"error": f"评委 {judge_model} 返回的结果无法解析为JSON", "raw_text": text_content}
            except Exception as e:
                log_error(f"处理评委 {judge_model} 返回的结果时出错: {str(e)}", {"text": result["text"][:200]},
                          model_name=judge_model)
                return {"error": f"处理评委返回结果时出错: {str(e)}", "raw_text": result["text"]}

        return result

    async def run_committee_evaluation(self,
                                       ai_cases: Dict,
                                       golden_cases: Dict,
                                       duplicate_info_text: str = "") -> Dict:
        """
        并行运行多个评委模型进行评测

        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :return: 汇总后的评测结果
        """
        log(f"启动评委委员会评测，评委数量: {len(self.judges)}", important=True)

        # 创建信号量限制并发数
        sem = asyncio.Semaphore(self.max_concurrency)

        async def evaluate_with_semaphore(judge_model):
            async with sem:
                return judge_model, await self.evaluate_with_judge(judge_model, ai_cases, golden_cases,
                                                                   duplicate_info_text)

        # 并行执行所有评委的评测
        tasks = [evaluate_with_semaphore(judge) for judge in self.judges]
        all_results = await asyncio.gather(*tasks)

        # 记录每个评委的结果
        judge_results = {}
        for judge_model, result in all_results:
            judge_results[judge_model] = result

        # 汇总结果
        aggregated_result = self._aggregate_evaluation_results(judge_results)

        return aggregated_result

    def _aggregate_evaluation_results(self, judge_results: Dict[str, Dict]) -> Dict:
        """
        汇总多个评委的评测结果

        :param judge_results: 各评委的评测结果
        :return: 汇总后的评测结果
        """
        log("开始汇总评委评测结果", important=True)

        # 初始化汇总结果
        aggregated_result = {
            "evaluation_summary": {
                "overall_score": 0.0,
                "final_suggestion": ""
            },
            "detailed_report": {},
            "committee_results": {}  # 保存每个评委的原始结果
        }

        # 保存原始评委结果
        aggregated_result["committee_results"] = judge_results

        # 提取有效的评委结果
        valid_results = {}
        for judge, result in judge_results.items():
            if isinstance(result, dict) and "evaluation_summary" in result and "detailed_report" in result:
                valid_results[judge] = result
            else:
                log_error(f"评委 {judge} 返回的结果格式不正确，将被排除在汇总外", {"result": result})

        if not valid_results:
            log_error("没有有效的评委结果可供汇总", important=True)
            return {
                "error": "没有有效的评委结果可供汇总",
                "committee_results": judge_results
            }

        log(f"有效评委数量: {len(valid_results)}/{len(judge_results)}", important=True)

        # 汇总整体评分
        overall_scores = []
        for judge, result in valid_results.items():
            try:
                overall_score = float(result["evaluation_summary"]["overall_score"])
                overall_scores.append(overall_score)
            except (ValueError, KeyError):
                log_error(f"评委 {judge} 的整体评分无效",
                          {"overall_score": result["evaluation_summary"].get("overall_score", "N/A")})

        if overall_scores:
            aggregated_result["evaluation_summary"]["overall_score"] = round(sum(overall_scores) / len(overall_scores),
                                                                             1)

        # 合并改进建议
        suggestions = []
        for judge, result in valid_results.items():
            suggestion = result["evaluation_summary"].get("final_suggestion", "")
            if suggestion:
                suggestions.append(suggestion)

        if suggestions:
            # 选择最长或最详细的建议
            aggregated_result["evaluation_summary"]["final_suggestion"] = max(suggestions, key=len)

        # 汇总各维度评分
        dimension_scores = {}

        for judge, result in valid_results.items():
            detailed_report = result.get("detailed_report", {})
            for dimension, data in detailed_report.items():
                if dimension not in dimension_scores:
                    dimension_scores[dimension] = {
                        "scores": [],
                        "reasons": []
                    }

                try:
                    score = float(data.get("score", 0))
                    dimension_scores[dimension]["scores"].append(score)
                except (ValueError, TypeError):
                    pass

                reason = data.get("reason", "")
                if reason:
                    dimension_scores[dimension]["reasons"].append(reason)

        # 计算各维度的平均分和合并理由
        for dimension, data in dimension_scores.items():
            if data["scores"]:
                avg_score = round(sum(data["scores"]) / len(data["scores"]), 1)
                # 选择最长或最详细的理由
                merged_reason = max(data["reasons"], key=len) if data["reasons"] else ""

                aggregated_result["detailed_report"][dimension] = {
                    "score": avg_score,
                    "reason": merged_reason
                }

        # 如果有评委提供了详细的分析，保留下来
        for judge, result in valid_results.items():
            detailed_report = result.get("detailed_report", {})
            for dimension, data in detailed_report.items():
                if "analysis" in data and dimension in aggregated_result["detailed_report"]:
                    aggregated_result["detailed_report"][dimension]["analysis"] = data["analysis"]
                    break

        # 记录评委评分情况
        judge_scores = {}
        for judge, result in valid_results.items():
            try:
                judge_scores[judge] = float(result["evaluation_summary"]["overall_score"])
            except (ValueError, KeyError):
                judge_scores[judge] = "N/A"

        aggregated_result["committee_summary"] = {
            "judge_count": len(valid_results),
            "judge_scores": judge_scores,
            "score_variance": round(self._calculate_variance(overall_scores), 2) if len(overall_scores) > 1 else 0
        }

        log(f"委员会汇总评分: {aggregated_result['evaluation_summary']['overall_score']}", important=True)
        log(f"评委评分情况: {json.dumps(judge_scores, ensure_ascii=False)}", important=True)

        return aggregated_result

    def _calculate_variance(self, scores: List[float]) -> float:
        """
        计算评分的方差

        :param scores: 评分列表
        :return: 方差
        """
        if not scores or len(scores) <= 1:
            return 0

        mean = sum(scores) / len(scores)
        variance = sum((x - mean) ** 2 for x in scores) / len(scores)
        return variance


async def evaluate_with_committee(session: aiohttp.ClientSession,
                                  ai_cases: Dict,
                                  golden_cases: Dict,
                                  duplicate_info_text: str = "") -> Dict:
    """
    使用评委委员会评测测试用例

    :param session: aiohttp会话
    :param ai_cases: AI生成的测试用例
    :param golden_cases: 黄金标准测试用例
    :param duplicate_info_text: 重复测试用例分析信息
    :return: 汇总后的评测结果
    """
    committee = EvaluationCommittee(session)
    return await committee.run_committee_evaluation(ai_cases, golden_cases, duplicate_info_text)