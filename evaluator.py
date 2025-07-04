import json
import aiohttp
from logger import log, log_error
from llm_api import async_call_llm
from analyzer import find_duplicate_test_cases
import re
import asyncio

async def evaluate_test_cases(session: aiohttp.ClientSession, ai_cases, golden_cases):
    """
    评测测试用例质量
    
    :param session: aiohttp会话
    :param ai_cases: AI生成的测试用例
    :param golden_cases: 黄金标准测试用例
    :return: 评测结果
    """
    log("开始测试用例评测", important=True)
    
    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.1)
    
    # 获取所有测试用例
    ai_testcases = []
    golden_testcases = []
    
    # 提取AI测试用例，适配新的格式化结构
    if isinstance(ai_cases, dict):
        if "testcases" in ai_cases and isinstance(ai_cases["testcases"], dict) and "test_cases" in ai_cases["testcases"]:
            # 新的统一格式
            ai_testcases = ai_cases["testcases"]["test_cases"]
        elif "test_cases" in ai_cases:
            if isinstance(ai_cases["test_cases"], dict):
                # 旧格式，分类测试用例
                for category, cases in ai_cases["test_cases"].items():
                    if isinstance(cases, list):
                        ai_testcases.extend(cases)
            elif isinstance(ai_cases["test_cases"], list):
                # 旧格式，直接列表
                ai_testcases = ai_cases["test_cases"]
    
    # 提取黄金标准测试用例，适配新的格式化结构
    if isinstance(golden_cases, dict):
        if "testcases" in golden_cases and isinstance(golden_cases["testcases"], dict) and "test_cases" in golden_cases["testcases"]:
            # 新的统一格式
            golden_testcases = golden_cases["testcases"]["test_cases"]
        elif "test_cases" in golden_cases:
            if isinstance(golden_cases["test_cases"], dict):
                # 旧格式，分类测试用例
                for category, cases in golden_cases["test_cases"].items():
                    if isinstance(cases, list):
                        golden_testcases.extend(cases)
            elif isinstance(golden_cases["test_cases"], list):
                # 旧格式，直接列表
                golden_testcases = golden_cases["test_cases"]
    
    log(f"AI测试用例数量: {len(ai_testcases)}, 黄金标准测试用例数量: {len(golden_testcases)}", important=True)
    
    # 检查重复的测试用例
    ai_duplicate_info = find_duplicate_test_cases(ai_testcases)
    golden_duplicate_info = find_duplicate_test_cases(golden_testcases)
    
    log(f"AI测试用例重复率: {ai_duplicate_info['duplicate_rate']}% ({ai_duplicate_info['duplicate_count']}个)", important=True)
    log(f"黄金标准测试用例重复率: {golden_duplicate_info['duplicate_rate']}% ({golden_duplicate_info['duplicate_count']}个)", important=True)
    
    # 记录重复类型分布
    log(f"AI测试用例重复类型分布: {json.dumps(ai_duplicate_info['duplicate_types'], ensure_ascii=False)}", important=True)
    if ai_duplicate_info['duplicate_categories']:
        log(f"AI测试用例按类别重复率: {json.dumps(ai_duplicate_info['duplicate_categories'], ensure_ascii=False)}", important=True)
    
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

    # 如果有合并建议，添加到提示中
    if merge_suggestions_count > 0:
        duplicate_info_text += "\n## AI测试用例合并建议\n"
        for i, suggestion in enumerate(ai_duplicate_info.get("merge_suggestions", [])):
            suggestion_type = "标题重复" if suggestion["type"] == "title_duplicate" else "步骤相似"
            case_ids = ", ".join(suggestion["case_ids"][:3])
            if len(suggestion["case_ids"]) > 3:
                case_ids += f" 等{len(suggestion['case_ids'])}个用例"
                
            merged_case = suggestion["merged_case"]
            duplicate_info_text += f"\n### 合并建议 {i+1}（{suggestion_type}）\n"
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
    
    # 构建完整提示
    prompt = f"""
# 任务
评估AI生成的测试用例与黄金标准测试用例的质量对比。

# 评估维度和权重
1. **功能覆盖度**（权重30%）：评估需求覆盖率、边界值覆盖度、分支路径覆盖率
2. **缺陷发现能力**（权重25%）：评估缺陷检测率、突变分数、失败用例比例
3. **工程效率**（权重20%）：评估测试用例生成速度、维护成本、CI/CD集成度
4. **语义质量**（权重15%）：评估语义准确性、人工可读性、断言描述清晰度
5. **安全与经济性**（权重10%）：评估恶意代码率、冗余用例比例、综合成本

{duplicate_info_text}

# 评分公式
总分 = 0.3×功能覆盖得分 + 0.25×缺陷发现得分 + 0.2×工程效率得分 + 0.15×语义质量得分 + 0.1×安全经济得分
各维度得分 = (AI指标值/人工基准值)×10（满分10分）

# AI生成的测试用例
```json
{json.dumps(ai_testcases, ensure_ascii=False, indent=2)}
```

# 黄金标准测试用例
```json
{json.dumps(golden_testcases, ensure_ascii=False, indent=2)}
```

# 输出要求
必须严格按照以下JSON格式输出评估结果，不要添加任何额外内容，不要使用```json或其他代码块包装，不要返回Markdown格式内容。直接输出下面这种JSON结构：

```json
{{
  "evaluation_summary": {{
    "overall_score": "分数（1-5之间的一位小数）",
    "final_suggestion": "如何改进测试用例生成的建议，如有较高的重复率，请提出降低重复的建议，并参考我提供的具体合并建议"
  }},
  "detailed_report": {{
    "format_compliance": {{
      "score": "格式合规性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "content_accuracy": {{
      "score": "内容准确性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "test_coverage": {{
      "score": "测试覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由",
      "analysis": {{
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
      }}
    }},
    "functional_coverage": {{
      "score": "功能覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "defect_detection": {{
      "score": "缺陷发现能力得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "engineering_efficiency": {{
      "score": "工程效率得分（1-5之间的一位小数）",
      "reason": "得分理由，如有较高的重复率，请在此处提及"
    }},
    "semantic_quality": {{
      "score": "语义质量得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "security_economy": {{
      "score": "安全与经济性得分（1-5之间的一位小数）",
      "reason": "得分理由，如有较高的重复率，请在此处提及冗余率"
    }},
    "duplicate_analysis": {{
      "score": "测试用例重复分析得分（1-5之间的一位小数）",
      "reason": "分析重复测试用例的影响",
      "merge_suggestions": "具体如何合并重复测试用例的建议，可以参考我提供的合并建议"
    }}
  }},
  "duplicate_types": {{
    "title": {ai_duplicate_info['duplicate_types'].get('title', 0)},
    "steps": {ai_duplicate_info['duplicate_types'].get('steps', 0)},
    "expected_results": {ai_duplicate_info['duplicate_types'].get('expected_results', 0)},
    "mixed": {ai_duplicate_info['duplicate_types'].get('mixed', 0)}
  }},
  "duplicate_categories": {json.dumps(ai_duplicate_info.get('duplicate_categories', {}))}
}}
```
"""
    
    system_prompt = "你是一位精通软件测试和技术文档写作的专家。请根据评估结果生成一份专业、清晰的Markdown格式报告，并使用Mermaid图表可视化关键数据。请直接保留并使用我提供的评分表格格式，不要修改其结构。请直接输出Markdown格式，不要尝试输出JSON。严格禁止在文档开头添加'markdown'这个词，直接以'# '开头的标题开始。不要在内容外包含```或```markdown标记，完全避免使用代码块，但保留提供的Mermaid图表语法。"
    result = await async_call_llm(session, prompt, system_prompt)
    
    if not result:
        log("测试用例评测失败", important=True)
        return None
    
    log("测试用例评测完成", important=True)
    return result

# 添加测试覆盖流程图生成函数
def generate_test_coverage_flow_chart(test_cases):
    """
    根据测试用例内容动态生成测试覆盖流程图
    
    :param test_cases: 测试用例列表
    :return: Mermaid格式的流程图
    """
    # 提取测试用例ID中的功能模块信息
    modules = {}
    submodules = {}
    
    for case in test_cases:
        case_id = case.get("case_id", "")
        title = case.get("title", "")
        
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
    
    # 提取主要功能和子功能的关系
    # 如果测试用例标题中包含类似"xx流程"、"xx功能"、"xx验证"等词语，提取为功能点
    features = {}
    for case in test_cases:
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
                    
                    # 将if语句移到for循环外部，修复缩进
                    if action and len(action) <= 15:
                        features[feature]["subfeatures"].add(action)
    
    # 按测试用例数量排序功能点
    sorted_features = sorted(features.items(), key=lambda x: x[1]["count"], reverse=True)
    
    # 生成Mermaid图表
    chart = "```mermaid\ngraph TD\n"
    
    # 添加主节点
    chart += "    A[测试覆盖范围] --> B[功能验证]\n"
    chart += "    A --> C[异常处理]\n"
    chart += "    A --> D[边界测试]\n"
    
    # 添加主要功能点（最多8个，避免图表过大）
    node_id = 0
    node_map = {}
    edge_set = set()  # 避免重复的边
    
    for i, (feature, info) in enumerate(sorted_features[:8]):
        if i >= 8:
            break
            
        node_id += 1
        feature_node = f"F{node_id}"
        node_map[feature] = feature_node
        
        # 添加功能点节点
        chart += f"    B --> {feature_node}[{feature}]\n"
        
        # 添加子功能点（每个功能点最多添加5个子功能）
        subfeatures = list(info["subfeatures"])[:5]
        for j, subfeature in enumerate(subfeatures):
            if j >= 5:
                break
                
            node_id += 1
            subfeature_node = f"SF{node_id}"
            
            # 创建边的标识
            edge = f"{feature_node}->{subfeature_node}"
            
            # 避免添加重复的边
            if edge not in edge_set:
                chart += f"    {feature_node} --> {subfeature_node}[{subfeature}]\n"
                edge_set.add(edge)
    
    # 添加异常处理示例节点
    chart += "    C --> E1[输入验证]\n"
    chart += "    C --> E2[超时处理]\n"
    chart += "    C --> E3[安全检查]\n"
    
    # 添加边界测试示例节点
    chart += "    D --> B1[最大值测试]\n"
    chart += "    D --> B2[最小值测试]\n"
    
    chart += "```\n"
    return chart

async def generate_markdown_report(session: aiohttp.ClientSession, evaluation_result):
    """
    生成Markdown格式的评测报告
    
    :param session: aiohttp会话
    :param evaluation_result: 评测结果
    :return: Markdown格式的报告
    """
    log("开始生成Markdown报告", important=True)
    
    # 确保日志记录按照正确的顺序执行
    await asyncio.sleep(0.1)  # 添加小延迟，确保日志顺序
    
    # 从评估结果中提取关键数据用于可视化
    mermaid_data = {
        "scores": {},
        "duplicate_rates": {
            "ai": 0,
            "golden": 0
        },
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
                    ai_testcases = [{"case_id": f"FEAT-{i+1}", "title": feature} 
                                   for i, feature in enumerate(covered_features)]
    
    # 动态生成测试覆盖流程图
    coverage_chart = generate_test_coverage_flow_chart(ai_testcases)
    
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
    radar_chart = f"## 综合评分 (总体: {overall_score}/5.0)\n\n"
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
    
    # 生成重复率对比图模板
    duplicate_chart = "```mermaid\npie\n    title 测试用例重复率对比\n"
    
    # 尝试从评估结果中找到重复率数据
    if "duplicate_types" in evaluation_result:
        # 从evaluation_result直接获取重复率数据，不使用硬编码的固定值
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
                if golden_rates:
                    mermaid_data["duplicate_rates"]["golden"] = float(golden_rates[0])
    
    duplicate_chart += f"    \"AI测试用例重复率\" : {mermaid_data['duplicate_rates']['ai']}\n"
    duplicate_chart += f"    \"黄金标准重复率\" : {mermaid_data['duplicate_rates']['golden']}\n"
    duplicate_chart += "```\n\n"
    
    # 生成重复类型分布图
    duplicate_types_chart = "```mermaid\npie\n    title AI测试用例重复类型分布\n"
    
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
                    "预期结果重复": duplicate_types.get("expected_results", 0)
                }
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
    
    for dup_type, count in dup_types.items():
        if count > 0:
            duplicate_types_chart += f"    \"{dup_type}\" : {count}\n"
    
    duplicate_types_chart += "```\n\n"
    
    # 添加树状评估框架图模板
    evaluation_framework_chart = """```mermaid
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
```

"""

    # 在提示中说明使用更新的图表语法
    prompt = f"""
# 任务
基于提供的测试用例评估结果，生成一份详细的Markdown格式评估报告，包含Mermaid图表可视化关键数据。

# 评估结果
```json
{json.dumps(evaluation_result, ensure_ascii=False, indent=2)}
```

# 报告要求
请生成一份专业、详细的Markdown格式评估报告，包含以下内容：

1. **报告标题与摘要**：简要总结评估结果
2. **评估指标与方法**：说明使用的评估标准和方法，并包含评估框架图
{evaluation_framework_chart}
3. **综合评分**：使用提供的表格和饼图展示各维度评分
{radar_chart}
4. **详细分析**：
   - 功能覆盖度分析
   - 缺陷发现能力分析
   - 工程效率分析
   - 语义质量分析
   - 安全与经济性分析
5. **重复测试用例分析**：
   - 重复测试用例比率
   - 重复类型分析
   - 测试用例合并建议
6. **优缺点对比**：列出AI生成测试用例相对于人工标准的优势和劣势
7. **改进建议**：给出3-5条具体可行的改进AI生成测试用例的建议，包括如何减少重复
8. **综合结论**：总结AI测试用例的整体表现和适用场景

# 可视化图表要求
请在报告中包含以下Mermaid图表，使用下方提供的模板（已包含数据），或者根据评估结果创建更准确的图表：

1. **重复率对比图**：AI测试用例与黄金标准的重复率对比
{duplicate_chart}

2. **重复类型分布图**：AI测试用例重复类型分布
{duplicate_types_chart}

3. **测试覆盖率流程图**：展示测试用例覆盖的关键流程或功能
{coverage_chart}

# 页脚格式
请在报告末尾添加一行页脚，使用以下格式：
**生成时间：{{当前年月日时间}} • gogogo出发喽评估中心**

# 美化要求
1. 请使用更丰富的Markdown格式元素来增强报告的可读性，如适当使用分隔线、引用块、表情符号等
2. 为关键数据添加醒目的标记，如重要的评分、显著的差异等
3. 在评分部分使用中文维度名称和星号评分可视化
4. 为报告添加简洁美观的页眉页脚
5. 添加有针对性的改进建议，使结论更具操作性

请确保使用上面提供的图表模板，这些模板已经包含了从评估结果中提取的实际数据。
这些图表使用的是较为通用的Mermaid语法 - graph和pie，确保与大多数Markdown查看器兼容。
你可以根据评估结果调整图表内容，但要保持```mermaid语法格式。
直接以# 开头的标题开始你的报告，不要在开头写"markdown"，不要包含其他解释。
"""
    
    system_prompt = "你是一位精通软件测试和技术文档写作的专家。请根据评估结果生成一份专业、清晰的Markdown格式报告，并使用Mermaid图表可视化关键数据。请直接保留并使用我提供的评分表格格式，不要修改其结构。请直接输出Markdown格式，不要尝试输出JSON。严格禁止在文档开头添加'markdown'这个词，直接以'# '开头的标题开始。不要在内容外包含```或```markdown标记，完全避免使用代码块，但保留提供的Mermaid图表语法。"
    result = await async_call_llm(session, prompt, system_prompt)
    
    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.1)
    
    if not result:
        log_error("生成Markdown报告失败", important=True)
        return "# 评测报告生成失败\n\n无法生成详细报告，请检查评测结果或重试。"
    
    # 检查返回的结果类型
    if isinstance(result, dict):
        # 如果返回的是字典，检查是否包含文本内容
        if "text" in result:
            # 返回文本内容
            markdown_content = result["text"]
            log("成功生成Markdown报告", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.1)
            return markdown_content
        elif "error" in result:
            # 返回错误信息
            log_error(f"生成Markdown报告失败: {result['error']}")
            return f"# 评测报告生成失败\n\n{result['error']}"
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
                return md_content
            except Exception as e:
                log_error(f"从字典生成Markdown报告失败: {e}")
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
        return result
    
    # 其他情况，返回错误信息
    log_error("无法处理LLM返回的结果类型", {"result_type": type(result).__name__})
    return "# 评测报告生成失败\n\n无法解析评测结果，请检查数据格式。" 