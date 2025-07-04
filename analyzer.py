import difflib
from collections import Counter
from logger import log

def find_duplicate_test_cases(test_cases):
    """
    查找重复的测试用例，并提供合并建议
    
    :param test_cases: 测试用例列表
    :return: 重复的测试用例信息、重复率和合并建议
    """
    # 存储标题、步骤和预期结果的哈希值
    title_hash = {}
    steps_hash = {}
    expected_results_hash = {}
    duplicate_info = {
        "duplicate_count": 0,
        "duplicate_rate": 0.0,
        "title_duplicates": [],
        "steps_duplicates": [],
        "mixed_duplicates": [],  # 步骤和预期结果高度相似但标题不同的测试用例
        "merge_suggestions": [],  # 新增：测试用例合并建议
        "duplicate_types": {  # 新增：不同类型重复的详细统计
            "title": 0,
            "steps": 0,
            "expected_results": 0,
            "mixed": 0
        },
        "duplicate_categories": {},  # 新增：按测试类别统计重复情况
        "categories": []  # 新增：测试用例类别列表
    }
    
    total_cases = len(test_cases)
    if total_cases <= 1:
        return duplicate_info
    
    # 按类别分组测试用例（假设有case_category字段或根据标题提取）
    categories = {}
    for case in test_cases:
        # 尝试获取类别
        category = case.get("category", "")
        if not category:
            # 尝试从标题中提取类别
            title = case.get("title", "")
            if " - " in title:
                category = title.split(" - ")[0].strip()
            elif "：" in title or ":" in title:
                category = title.split("：")[0].split(":")[0].strip()
            else:
                category = "未分类"
        
        if category not in categories:
            categories[category] = []
        categories[category].append(case)
    
    # 记录类别信息
    duplicate_info["categories"] = list(categories.keys())
    
    # 查找标题重复的测试用例
    title_counter = Counter([case.get("title", "") for case in test_cases])
    for title, count in title_counter.items():
        if count > 1 and title:
            # 查找具有相同标题的测试用例
            same_title_cases = [case for case in test_cases if case.get("title", "") == title]
            case_ids = [case.get("case_id", "unknown") for case in same_title_cases]
            
            duplicate_info["title_duplicates"].append({
                "title": title, 
                "count": count,
                "case_ids": case_ids
            })
            
            # 更新重复类型计数
            duplicate_info["duplicate_types"]["title"] += count - 1
            
            # 为标题重复的测试用例生成合并建议
            if count > 1:
                # 提取所有相同标题测试用例的步骤和预期结果
                all_steps = []
                all_expected_results = []
                
                for case in same_title_cases:
                    steps = case.get("steps", "")
                    if isinstance(steps, list):
                        all_steps.extend(steps)
                    elif steps:
                        all_steps.append(steps)
                    
                    expected = case.get("expected_results", "")
                    if isinstance(expected, list):
                        all_expected_results.extend(expected)
                    elif expected:
                        all_expected_results.append(expected)
                
                # 去重
                unique_steps = list(dict.fromkeys([step.strip() for step in all_steps if step.strip()]))
                unique_expected = list(dict.fromkeys([result.strip() for result in all_expected_results if result.strip()]))
                
                # 生成合并建议
                duplicate_info["merge_suggestions"].append({
                    "type": "title_duplicate",
                    "title": title,
                    "case_ids": case_ids,
                    "merged_case": {
                        "title": title,
                        "case_id": f"MERGED-{case_ids[0]}",
                        "preconditions": same_title_cases[0].get("preconditions", ""),
                        "steps": unique_steps,
                        "expected_results": unique_expected
                    }
                })
    
    # 查找步骤或预期结果高度相似的测试用例
    for i, case in enumerate(test_cases):
        case_id = case.get("case_id", str(i))
        title = case.get("title", "")
        
        # 处理步骤
        steps = case.get("steps", "")
        if steps:
            # 如果是列表，转换为字符串
            if isinstance(steps, list):
                steps = "\n".join(steps)
            
            # 计算步骤的哈希值
            for existing_steps, existing_ids in steps_hash.items():
                # 使用序列匹配算法比较相似度
                similarity = difflib.SequenceMatcher(None, steps, existing_steps).ratio()
                if similarity > 0.8:  # 相似度阈值
                    existing_ids.append((case_id, title))
                    # 更新重复类型计数
                    duplicate_info["duplicate_types"]["steps"] += 1
                    break
            else:
                steps_hash[steps] = [(case_id, title)]
        
        # 处理预期结果
        expected_results = case.get("expected_results", "")
        if expected_results:
            # 如果是列表，转换为字符串
            if isinstance(expected_results, list):
                expected_results = "\n".join(expected_results)
            
            # 计算预期结果的哈希值
            for existing_results, existing_ids in expected_results_hash.items():
                # 使用序列匹配算法比较相似度
                similarity = difflib.SequenceMatcher(None, expected_results, existing_results).ratio()
                if similarity > 0.8:  # 相似度阈值
                    existing_ids.append((case_id, title))
                    # 更新重复类型计数
                    duplicate_info["duplicate_types"]["expected_results"] += 1
                    break
            else:
                expected_results_hash[expected_results] = [(case_id, title)]
    
    # 统计步骤重复的测试用例并生成合并建议
    for steps, ids in steps_hash.items():
        if len(ids) > 1:
            case_ids = [id[0] for id in ids]
            titles = [id[1] for id in ids]
            
            duplicate_info["steps_duplicates"].append({
                "count": len(ids),
                "case_ids": case_ids,
                "titles": titles
            })
            
            # 查找具有相似步骤的测试用例详情
            similar_cases = []
            for case_id in case_ids:
                for case in test_cases:
                    if case.get("case_id", "") == case_id:
                        similar_cases.append(case)
                        break
            
            if similar_cases:
                # 为步骤相似的测试用例生成合并建议
                # 合并标题：使用最长或最具描述性的标题
                titles_sorted = sorted(titles, key=len, reverse=True)
                merged_title = titles_sorted[0]
                
                # 合并预期结果
                all_expected_results = []
                for case in similar_cases:
                    expected = case.get("expected_results", "")
                    if isinstance(expected, list):
                        all_expected_results.extend(expected)
                    elif expected:
                        all_expected_results.append(expected)
                
                # 去重
                unique_expected = list(dict.fromkeys([result.strip() for result in all_expected_results if result.strip()]))
                
                # 生成合并建议
                duplicate_info["merge_suggestions"].append({
                    "type": "steps_duplicate",
                    "case_ids": case_ids,
                    "titles": titles,
                    "merged_case": {
                        "title": merged_title,
                        "case_id": f"MERGED-STEPS-{case_ids[0]}",
                        "preconditions": similar_cases[0].get("preconditions", ""),
                        "steps": similar_cases[0].get("steps", ""),  # 使用相似的步骤
                        "expected_results": unique_expected
                    }
                })
    
    # 按类别统计重复情况
    for category, cases in categories.items():
        title_duplicates = 0
        steps_duplicates = 0
        
        # 统计该类别中的标题重复
        title_counter = Counter([case.get("title", "") for case in cases])
        for title, count in title_counter.items():
            if count > 1 and title:
                title_duplicates += count - 1
        
        # 简化的步骤重复检测
        steps_set = set()
        for case in cases:
            steps = case.get("steps", "")
            if steps:
                if isinstance(steps, list):
                    steps = "\n".join([str(s) for s in steps])
                steps_hash = hash(steps)
                if steps_hash in steps_set:
                    steps_duplicates += 1
                else:
                    steps_set.add(steps_hash)
        
        # 记录该类别的重复情况
        duplicate_info["duplicate_categories"][category] = {
            "total": len(cases),
            "title_duplicates": title_duplicates,
            "steps_duplicates": steps_duplicates,
            "duplicate_rate": round((title_duplicates + steps_duplicates) / len(cases) * 100, 2) if cases else 0
        }
    
    # 计算重复测试用例数量和比率
    duplicate_count = len(duplicate_info["title_duplicates"]) + len(duplicate_info["steps_duplicates"])
    duplicate_info["duplicate_count"] = duplicate_count
    duplicate_info["duplicate_rate"] = round(duplicate_count / total_cases * 100, 2) if total_cases > 0 else 0
    
    return duplicate_info 