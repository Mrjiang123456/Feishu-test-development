import asyncio
import json
import aiohttp
from typing import List, Dict, Any, Tuple
from logger import log, log_error
from llm_api import async_call_llm, extract_valid_json
from config import JUDGE_MODELS, MAX_JUDGES_CONCURRENCY, EVALUATION_DIMENSIONS, ENABLE_COLLAB_EVAL
import re


class EvaluationCommittee:
    """评估委员会类，管理多个LLM评委对测试用例的评估，实现CollabEval三阶段评测框架"""

    def __init__(self, session: aiohttp.ClientSession):
        """
        初始化评估委员会

        :param session: aiohttp会话
        """
        self.session = session
        self.judges = JUDGE_MODELS
        self.dimensions = EVALUATION_DIMENSIONS
        self.max_concurrency = MAX_JUDGES_CONCURRENCY
        # 添加主席模型，使用deepseek-r1
        self.chairman_model = "deepseek-r1-250528"
        # 定义低共识阈值
        self.low_consensus_threshold = 0.5
        # 高争议阈值
        self.high_disagreement_threshold = 1.0

    def _build_evaluation_prompt(self, ai_cases: Dict, golden_cases: Dict, duplicate_info_text: str, judge_model: str = None) -> str:
        """
        构建评测提示，可针对不同评委定制

        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :param judge_model: 评委模型名称，用于定制提示
        :return: 完整的评测提示
        """
        # 序列化测试用例
        ai_cases_json = json.dumps(ai_cases, ensure_ascii=False, indent=2)
        golden_cases_json = json.dumps(golden_cases, ensure_ascii=False, indent=2)

        # 基础提示
        prompt = """
# 任务
评估AI生成的测试用例与黄金标准测试用例的质量对比。
"""

        # 针对不同模型定制评测角度和提示
        if judge_model:
            if "doubao" in judge_model.lower():
                prompt += """
## 评委特定视角
你是功能测试专家，请重点关注测试用例的**功能覆盖度**和**缺陷发现能力**。
你应该特别注意评估边界值测试、异常路径和边缘场景的覆盖情况。
"""
            elif "deepseek" in judge_model.lower():
                prompt += """
## 评委特定视角
你是工程质量专家，请重点关注测试用例的**工程效率**和**语义质量**。
你应该特别注意评估测试用例的可维护性、重复度、可读性以及与需求描述的符合度。
"""
            else:
                prompt += """
## 评委特定视角
你是测试安全专家，请重点关注测试用例的**安全与经济性**。
你应该特别注意评估测试用例对安全场景的覆盖、恶意输入的处理以及资源使用效率。
"""

        # 标准评估维度
        prompt += """
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
    "final_suggestion": "如何改进测试用例生成的建议，如有较高的重复率，请提出降低重复的建议",
    "confidence": "你对自己评分的信心（1-5之间的一位小数）",
    "rationale": "你给出该评分的主要理由"
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

    def _build_debate_prompt(self, dimension: str, initial_scores: List[Dict], reasons: List[str]) -> str:
        """
        构建辩论提示，基于思维树框架

        :param dimension: 有争议的评测维度
        :param initial_scores: 初始评分和理由
        :param reasons: 其他评委的理由
        :return: 辩论提示
        """
        # 提取可能的边界值范围
        min_val, max_val = 0, 100  # 默认范围
        for reason in reasons:
            if "范围" in reason:
                range_match = re.search(r'范围[：:]*\s*\[?\s*(\d+)\s*[,，-]\s*(\d+)\s*\]?', reason)
                if range_match:
                    min_val, max_val = range_match.groups()
                    break

        # 构建辩论提示
        prompt = f"""
# 评测辩论阶段
## 评测维度: {dimension}

## 你的初始评分
{initial_scores[0]['score']} - {initial_scores[0]['reason']}

## 其他评委的评分理由
{' '.join([f"- {r}" for r in reasons])}

## 辩论指南
你收到其他评委的评分依据，请分析分歧点，重点检查：
- 是否遗漏需求隐含条件？
- 边界值覆盖是否充分？（如：数值范围[{min_val}, {max_val}]外的测试）
- 测试用例的质量与标准是否一致评判？

## 输出要求
请基于思维树框架，从多个维度思考问题，然后给出你的修订评分和理由。请按以下格式输出：

```json
{{
  "revised_evaluation": {{
    "score": "修订后的分数（1-5之间的一位小数）",
    "reason": "修订后的理由，请明确指出为何修改了评分",
    "confidence": "你对修订评分的信心（1-5之间的一位小数）"
  }},
  "thought_process": [
    "思考点1：针对xxx的分析...",
    "思考点2：关于边界值的考虑...",
    "思考点3：对比其他评委意见后..."
  ]
}}
```
"""
        return prompt

    def _build_chairman_prompt(self, dimension_results: Dict, judge_scores: Dict, high_variance_dimensions: List[str]) -> str:
        """
        构建主席决策提示

        :param dimension_results: 各维度的评分结果
        :param judge_scores: 各评委的评分
        :param high_variance_dimensions: 高方差的维度
        :return: 主席决策提示
        """
        # 转换评分数据为JSON格式
        dimension_results_json = json.dumps(dimension_results, ensure_ascii=False, indent=2)
        judge_scores_json = json.dumps(judge_scores, ensure_ascii=False, indent=2)
        
        prompt = f"""
# 主席决策阶段

你是评委会主席，需要根据多位评委的评分和辩论结果，做出最终的综合评判。

## 评分数据
### 各维度评分结果
```json
{dimension_results_json}
```

### 各评委总体评分
```json
{judge_scores_json}
```

## 高争议维度
以下维度存在较大分歧，需要特别关注：
{', '.join(high_variance_dimensions) if high_variance_dimensions else "没有高争议维度"}

## 任务说明
作为主席，你需要：
1. 综合考虑各评委意见，基于专业知识而非简单平均给出各维度的最终评分
2. 对高争议维度给予特别关注，分析争议原因并给出更合理的评分
3. 根据各维度权重计算最终评分：总分 = 0.3×功能覆盖得分 + 0.25×缺陷发现得分 + 0.2×工程效率得分 + 0.15×语义质量得分 + 0.1×安全经济得分
4. 标记出高争议用例，建议后续人工复核

## 输出要求
请输出以下格式的JSON：

```json
{{
  "chairman_decision": {{
    "final_scores": {{
      "overall_score": "最终综合评分（1-5之间的一位小数）",
      "format_compliance": "格式合规性最终评分",
      "content_accuracy": "内容准确性最终评分",
      "test_coverage": "测试覆盖度最终评分",
      "functional_coverage": "功能覆盖度最终评分",
      "defect_detection": "缺陷发现能力最终评分",
      "engineering_efficiency": "工程效率最终评分",
      "semantic_quality": "语义质量最终评分",
      "security_economy": "安全与经济性最终评分",
      "duplicate_analysis": "测试用例重复分析最终评分"
    }},
    "rationale": "主席决策理由，解释为何给出这些最终评分",
    "high_disagreement_areas": [
      "争议点1及处理意见",
      "争议点2及处理意见"
    ],
    "final_suggestion": "如何改进测试用例生成的最终建议"
  }}
}}
```
"""
        return prompt

    async def evaluate_with_judge(self,
                                  judge_model: str,
                                  ai_cases: Dict,
                                  golden_cases: Dict,
                                  duplicate_info_text: str = "") -> Dict:
        """
        阶段1：使用单个评委模型进行独立评测

        :param judge_model: 评委模型名称
        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :return: 评测结果
        """
        log(f"评委 {judge_model} 开始阶段1独立评测", important=True, model_name=judge_model)

        # 构建评测提示，针对不同评委定制
        prompt = self._build_evaluation_prompt(ai_cases, golden_cases, duplicate_info_text, judge_model)
        system_prompt = "你是一位精通软件测试和质量评估的专家。请根据提供的测试用例进行客观、专业的评估，注重你擅长的领域。"

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

        log(f"评委 {judge_model} 阶段1评测完成", important=True, model_name=judge_model)

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

    async def debate_dimension(self, judge_model: str, dimension: str, initial_scores: List[Dict], 
                               all_reasons: List[str]) -> Dict:
        """
        阶段2：针对特定维度进行辩论

        :param judge_model: 评委模型名称
        :param dimension: 有争议的维度
        :param initial_scores: 该评委在该维度的初始评分
        :param all_reasons: 所有评委关于该维度的理由
        :return: 辩论后的评分结果
        """
        log(f"评委 {judge_model} 开始阶段2辩论，维度: {dimension}", model_name=judge_model)
        
        # 构建辩论提示
        prompt = self._build_debate_prompt(dimension, initial_scores, all_reasons)
        system_prompt = "你是一位参与评测辩论的专家评委，需要根据其他评委的意见重新思考你的评分。请用批判性思维分析问题，但也要保持开放的态度接受合理的不同观点。"
        
        # 调用LLM进行辩论
        result = await async_call_llm(
            self.session,
            prompt, 
            system_prompt,
            model_name=judge_model
        )
        
        if not result:
            log_error(f"评委 {judge_model} 在维度 {dimension} 的辩论失败", model_name=judge_model)
            return {"error": f"辩论失败", "original_score": initial_scores[0]["score"]}
            
        # 处理辩论结果
        if isinstance(result, dict) and "text" in result:
            try:
                text_content = result["text"]
                try:
                    parsed_result = json.loads(text_content)
                    log(f"评委 {judge_model} 完成维度 {dimension} 的辩论，修订评分: {parsed_result.get('revised_evaluation', {}).get('score', 'N/A')}", model_name=judge_model)
                    return parsed_result
                except json.JSONDecodeError:
                    extracted_json = extract_valid_json(text_content)
                    if extracted_json:
                        log(f"成功从评委 {judge_model} 的辩论响应中提取有效JSON", model_name=judge_model)
                        return extracted_json
                    else:
                        log_error(f"评委 {judge_model} 的辩论结果无法解析为JSON", {"text": text_content[:200]}, model_name=judge_model)
                        return {"error": "辩论结果无法解析", "original_score": initial_scores[0]["score"]}
            except Exception as e:
                log_error(f"处理评委 {judge_model} 的辩论结果时出错: {str(e)}", model_name=judge_model)
                return {"error": f"处理辩论结果出错: {str(e)}", "original_score": initial_scores[0]["score"]}

        return result

    async def chairman_decision(self, dimension_results: Dict, judge_scores: Dict, 
                                high_variance_dimensions: List[str]) -> Dict:
        """
        阶段3：主席决策，加权聚合评分并标记高争议用例
        
        :param dimension_results: 各维度的评分结果
        :param judge_scores: 各评委的评分
        :param high_variance_dimensions: 高方差的维度列表
        :return: 主席决策结果
        """
        log(f"主席开始阶段3决策", important=True, model_name=self.chairman_model)
        
        # 构建主席决策提示
        prompt = self._build_chairman_prompt(dimension_results, judge_scores, high_variance_dimensions)
        system_prompt = "你是评委会主席，需要综合各位专家评委的意见，做出最终的评判决策。请基于专业知识而非简单平均来进行决策，并特别关注存在高度争议的维度。"
        
        # 调用LLM进行主席决策
        result = await async_call_llm(
            self.session,
            prompt,
            system_prompt,
            model_name=self.chairman_model
        )

        if not result:
            log_error("主席决策失败", important=True, model_name=self.chairman_model)
            return {"error": "主席决策失败"}
            
        # 处理主席决策结果
        if isinstance(result, dict) and "text" in result:
            try:
                text_content = result["text"]
                try:
                    parsed_result = json.loads(text_content)
                    log("主席完成决策", important=True, model_name=self.chairman_model)
                    return parsed_result
                except json.JSONDecodeError:
                    extracted_json = extract_valid_json(text_content)
                    if extracted_json:
                        log("成功从主席决策响应中提取有效JSON", model_name=self.chairman_model)
                        return extracted_json
                    else:
                        log_error("主席决策结果无法解析为JSON", {"text": text_content[:200]}, model_name=self.chairman_model)
                        return {"error": "主席决策结果无法解析"}
            except Exception as e:
                log_error(f"处理主席决策结果时出错: {str(e)}", model_name=self.chairman_model)
                return {"error": f"处理主席决策结果出错: {str(e)}"}

        return result

    async def run_committee_evaluation(self,
                                       ai_cases: Dict,
                                       golden_cases: Dict,
                                       duplicate_info_text: str = "") -> Dict:
        """
        运行委员会评测，由多个评委进行评测，并汇总结果

        :param ai_cases: AI生成的测试用例
        :param golden_cases: 黄金标准测试用例
        :param duplicate_info_text: 重复测试用例分析信息
        :return: 汇总后的评测结果
        """
        log("开始委员会评测流程", important=True)

        # 创建信号量，限制并发评委数量
        semaphore = asyncio.Semaphore(self.max_concurrency)

        # 定义带有信号量的评测函数
        async def evaluate_with_semaphore(judge_model):
            """使用信号量限制并发评测"""
            async with semaphore:
                log(f"评委 {judge_model} 开始评测", important=True)
                try:
                    # 设置较短的超时时间，避免单个评委阻塞整个流程
                    result = await asyncio.wait_for(
                        self.evaluate_with_judge(judge_model, ai_cases, golden_cases, duplicate_info_text),
                        timeout=300  # 5分钟超时
                    )
                    log(f"评委 {judge_model} 评测完成", important=True)
                    return judge_model, result
                except asyncio.TimeoutError:
                    log_error(f"评委 {judge_model} 评测超时", important=True)
                    return judge_model, {"error": "评测超时"}
                except Exception as e:
                    log_error(f"评委 {judge_model} 评测出错: {str(e)}", important=True)
                    return judge_model, {"error": str(e)}

        # 并行执行所有评委的评测
        tasks = [evaluate_with_semaphore(judge) for judge in self.judges]
        all_results = await asyncio.gather(*tasks)

        # 记录每个评委的结果
        judge_results = {}
        for judge_model, result in all_results:
            judge_results[judge_model] = result

        # 提取有效的评委结果
        valid_results = {}
        for judge, result in judge_results.items():
            if isinstance(result, dict) and "evaluation_summary" in result and "detailed_report" in result:
                valid_results[judge] = result
            else:
                log_error(f"评委 {judge} 返回的结果格式不正确，将被排除在后续阶段外", {"result": result})

        if not valid_results:
            log_error("没有有效的评委结果可供后续阶段使用", important=True)
            return {
                "error": "没有有效的评委结果",
                "committee_results": judge_results
            }

        log(f"阶段1完成，有效评委数量: {len(valid_results)}/{len(judge_results)}", important=True)
        
        # 如果不启用CollabEval，使用简单的平均评分方法
        if not ENABLE_COLLAB_EVAL:
            log("使用标准多评委评测方法（不执行辩论和主席决策阶段）", important=True)

            # 计算各维度的平均分
            dimensions = [
                "format_compliance", "content_accuracy", "test_coverage",
                "functional_coverage", "defect_detection", "engineering_efficiency",
                "semantic_quality", "security_economy", "duplicate_analysis"
            ]

            # 构建最终结果
            final_result = {
                "evaluation_summary": {},
                "detailed_report": {},
                "committee_summary": {
                    "judge_count": len(valid_results),
                    "judge_scores": {},
                    "evaluation_framework": "Standard"
                }
            }

            # 计算各评委的总体评分
            judge_overall_scores = {}
            for judge, result in valid_results.items():
                try:
                    overall_score = float(result["evaluation_summary"]["overall_score"])
                    judge_overall_scores[judge] = overall_score
                except (ValueError, KeyError):
                    judge_overall_scores[judge] = "N/A"

            final_result["committee_summary"]["judge_scores"] = judge_overall_scores

            # 计算总体平均分
            overall_scores = [score for score in judge_overall_scores.values() if isinstance(score, (int, float))]
            if overall_scores:
                final_result["evaluation_summary"]["overall_score"] = round(sum(overall_scores) / len(overall_scores), 1)
            else:
                final_result["evaluation_summary"]["overall_score"] = "N/A"

            # 合并所有评委的建议
            suggestions = []
            for judge, result in valid_results.items():
                suggestion = result["evaluation_summary"].get("final_suggestion", "")
                if suggestion:
                    suggestions.append(suggestion)
            
            if suggestions:
                final_result["evaluation_summary"]["final_suggestion"] = max(suggestions, key=len)
            else:
                final_result["evaluation_summary"]["final_suggestion"] = "无法获取有效建议"

            # 计算各维度的平均分和汇总理由
            for dimension in dimensions:
                scores = []
                reasons = []

                for judge, result in valid_results.items():
                    if dimension in result.get("detailed_report", {}):
                        dim_data = result["detailed_report"][dimension]
                        try:
                            score = float(dim_data.get("score", 0))
                            scores.append(score)
                            reason = dim_data.get("reason", "")
                            if reason:
                                reasons.append(reason)
                        except (ValueError, TypeError):
                            pass

                if scores:
                    if dimension not in final_result["detailed_report"]:
                        final_result["detailed_report"][dimension] = {}

                    final_result["detailed_report"][dimension]["score"] = round(sum(scores) / len(scores), 1)

                    # 使用最长的理由作为汇总理由
                    if reasons:
                        final_result["detailed_report"][dimension]["reason"] = max(reasons, key=len)

            # 添加是否为委员会结果的标记
            final_result["is_committee_result"] = True
            final_result["collab_eval_result"] = False

            log(f"标准多评委评测完成，最终评分: {final_result['evaluation_summary'].get('overall_score', 'N/A')}", important=True)

            return final_result

        # 以下是CollabEval三阶段评测流程（仅在ENABLE_COLLAB_EVAL=True时执行）
        # 计算各维度方差，识别低共识维度
        dimension_variances = {}
        dimension_scores = {}
        
        # 评分维度列表
        dimensions = [
            "format_compliance", "content_accuracy", "test_coverage",
            "functional_coverage", "defect_detection", "engineering_efficiency",
            "semantic_quality", "security_economy", "duplicate_analysis"
        ]

        # 收集每个维度的评分和理由
        for dimension in dimensions:
            scores = []
            reasons = []
            judge_dimension_data = {}

            for judge, result in valid_results.items():
                if dimension in result.get("detailed_report", {}):
                    dim_data = result["detailed_report"][dimension]
                    try:
                        score = float(dim_data.get("score", 0))
                        scores.append(score)
                        reason = dim_data.get("reason", "")
                        if reason:
                            reasons.append(reason)
                            judge_dimension_data[judge] = {
                                "score": score,
                                "reason": reason
                            }
                    except (ValueError, TypeError):
                        pass

            if scores:
                variance = self._calculate_variance(scores)
                dimension_variances[dimension] = variance
                dimension_scores[dimension] = {
                    "scores": scores,
                    "reasons": reasons,
                    "judge_data": judge_dimension_data,
                    "variance": variance
                }

        # 识别需要辩论的低共识维度
        low_consensus_dimensions = {
            dim: data for dim, data in dimension_scores.items()
            if data["variance"] >= self.low_consensus_threshold
        }
        
        # 阶段2：辩论协作
        if low_consensus_dimensions:
            log(f"开始阶段2：辩论协作，发现{len(low_consensus_dimensions)}个低共识维度", important=True)

            # 存储辩论后的修订结果
            debate_results = {}
            
            # 为每个低共识维度进行辩论
            for dimension, data in low_consensus_dimensions.items():
                log(f"对维度 {dimension} 进行辩论，方差: {data['variance']}", important=True)
                debate_dimension_results = {}

                # 所有评委的理由，用于辩论
                all_reasons = data["reasons"]

                # 每个评委对该维度进行辩论
                debate_tasks = []
                for judge, judge_data in data["judge_data"].items():
                    # 准备辩论参数
                    initial_scores = [judge_data]
                    debate_task = self.debate_dimension(judge, dimension, initial_scores, all_reasons)
                    debate_tasks.append((judge, debate_task))

                # 并行执行辩论
                for judge, debate_task in debate_tasks:
                    debate_result = await debate_task
                    if debate_result and "revised_evaluation" in debate_result:
                        debate_dimension_results[judge] = debate_result

                debate_results[dimension] = debate_dimension_results

            log(f"阶段2完成，{len(debate_results)}个维度完成辩论", important=True)

            # 更新评委结果，将辩论结果合并到原始评估中
            for dimension, judge_debates in debate_results.items():
                for judge, debate in judge_debates.items():
                    if judge in valid_results and "revised_evaluation" in debate:
                        revised = debate["revised_evaluation"]
                        try:
                            # 更新评分和理由
                            valid_results[judge]["detailed_report"][dimension]["score"] = revised["score"]
                            valid_results[judge]["detailed_report"][dimension]["reason"] = revised["reason"]
                            # 保存思考过程
                            if "thought_process" in debate:
                                valid_results[judge]["detailed_report"][dimension]["debate_thoughts"] = debate["thought_process"]
                            log(f"评委 {judge} 在维度 {dimension} 的评分已更新: {revised['score']}", model_name=judge)
                        except (KeyError, TypeError) as e:
                            log_error(f"更新评委 {judge} 在维度 {dimension} 的评分失败: {str(e)}", model_name=judge)
        else:
            log("所有维度共识度较高，跳过阶段2辩论", important=True)
            
        # 重新计算各维度的评分数据，准备主席决策
        updated_dimension_scores = {}
        judge_overall_scores = {}
        high_variance_dimensions = []

        # 收集更新后的各维度评分
        for dimension in dimensions:
            scores = []
            reasons = []
            for judge, result in valid_results.items():
                if dimension in result.get("detailed_report", {}):
                    dim_data = result["detailed_report"][dimension]
                    try:
                        score = float(dim_data.get("score", 0))
                        scores.append(score)
                        reason = dim_data.get("reason", "")
                        if reason:
                            reasons.append(reason)
                    except (ValueError, TypeError):
                        pass

            if scores:
                variance = self._calculate_variance(scores)
                updated_dimension_scores[dimension] = {
                    "scores": scores,
                    "average": sum(scores) / len(scores),
                    "variance": variance,
                    "reasons": reasons
                }

                # 标记高争议维度
                if variance >= self.high_disagreement_threshold:
                    high_variance_dimensions.append(dimension)

        # 收集各评委的总体评分
        for judge, result in valid_results.items():
            try:
                overall_score = float(result["evaluation_summary"]["overall_score"])
                judge_overall_scores[judge] = overall_score
            except (ValueError, KeyError):
                judge_overall_scores[judge] = "N/A"
        
        # 阶段3：主席决策
        log("开始阶段3：主席决策", important=True)

        chairman_result = await self.chairman_decision(
            updated_dimension_scores,
            judge_overall_scores,
            high_variance_dimensions
        )

        # 构建最终结果
        final_result = {
            "evaluation_summary": {},
            "detailed_report": {},
            "committee_summary": {
                "judge_count": len(valid_results),
                "judge_scores": judge_overall_scores,
                "high_disagreement_dimensions": high_variance_dimensions,
                "stage1_results": {judge: result["evaluation_summary"] for judge, result in valid_results.items()},
                "stage2_debate_occurred": len(low_consensus_dimensions) > 0,
                "stage3_chairman_decision": chairman_result
            }
        }

        # 从主席决策中提取最终评分
        if chairman_result and "chairman_decision" in chairman_result:
            chairman_decision = chairman_result["chairman_decision"]
            
            # 设置总体评分和建议
            if "final_scores" in chairman_decision:
                final_scores = chairman_decision["final_scores"]
                if "overall_score" in final_scores:
                    final_result["evaluation_summary"]["overall_score"] = final_scores["overall_score"]

                # 设置各维度评分
                for dimension in dimensions:
                    if dimension in final_scores:
                        if dimension not in final_result["detailed_report"]:
                            final_result["detailed_report"][dimension] = {}
                        final_result["detailed_report"][dimension]["score"] = final_scores[dimension]
            
            # 设置最终建议
            if "final_suggestion" in chairman_decision:
                final_result["evaluation_summary"]["final_suggestion"] = chairman_decision["final_suggestion"]

            # 添加主席理由
            if "rationale" in chairman_decision:
                final_result["evaluation_summary"]["chairman_rationale"] = chairman_decision["rationale"]

            # 添加高争议领域
            if "high_disagreement_areas" in chairman_decision:
                final_result["committee_summary"]["high_disagreement_areas"] = chairman_decision["high_disagreement_areas"]
        else:
            # 如果主席决策失败，使用评委平均分作为备选
            log_error("主席决策失败或格式不正确，使用评委平均分作为备选", important=True)
            
            # 计算评委平均分作为备选
            overall_scores = [score for score in judge_overall_scores.values() if isinstance(score, (int, float))]
            if overall_scores:
                final_result["evaluation_summary"]["overall_score"] = round(sum(overall_scores) / len(overall_scores), 1)
            else:
                final_result["evaluation_summary"]["overall_score"] = "N/A"
                
            # 使用所有评委的综合建议
            suggestions = []
            for judge, result in valid_results.items():
                suggestion = result["evaluation_summary"].get("final_suggestion", "")
                if suggestion:
                    suggestions.append(suggestion)

            if suggestions:
                final_result["evaluation_summary"]["final_suggestion"] = max(suggestions, key=len)
            else:
                final_result["evaluation_summary"]["final_suggestion"] = "无法获取有效建议"

            # 为各维度设置平均分
            for dimension, data in updated_dimension_scores.items():
                if dimension not in final_result["detailed_report"]:
                    final_result["detailed_report"][dimension] = {}
                final_result["detailed_report"][dimension]["score"] = round(data["average"], 1)

                # 使用最长的理由
                if data["reasons"]:
                    final_result["detailed_report"][dimension]["reason"] = max(data["reasons"], key=len)

        # 添加是否为委员会结果的标记
        final_result["is_committee_result"] = True
        final_result["collab_eval_result"] = ENABLE_COLLAB_EVAL  # 标记使用了CollabEval框架

        log(f"CollabEval三阶段评测完成，最终评分: {final_result['evaluation_summary'].get('overall_score', 'N/A')}", important=True)

        return final_result

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
    committee = EvaluationCommittee(session)
    
    # 临时修改配置
    from config import ENABLE_COLLAB_EVAL
    original_collab_eval = ENABLE_COLLAB_EVAL
    
    if use_collab_eval is not None:
        # 如果明确指定了是否使用CollabEval，则临时修改全局配置
        import config
        config.ENABLE_COLLAB_EVAL = use_collab_eval
        
    try:
        # 执行评测
        result = await committee.run_committee_evaluation(ai_cases, golden_cases, duplicate_info_text)
        
        # 添加明确的评测框架标识
        if result and isinstance(result, dict):
            result["evaluation_framework"] = "CollabEval" if config.ENABLE_COLLAB_EVAL else "Standard"
            
        return result
    finally:
        # 恢复原始配置
        if use_collab_eval is not None:
            config.ENABLE_COLLAB_EVAL = original_collab_eval
