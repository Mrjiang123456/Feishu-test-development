import difflib
from collections import Counter
from logger import log
from config import DUPLICATE_SIMILARITY_THRESHOLD, BATCH_SIZE
import concurrent.futures
import functools


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

    log(f"开始查找重复测试用例，总数: {total_cases}")

    # 优化：一次性收集所有标题，避免重复迭代
    all_titles = []
    title_case_map = {}
    case_steps_map = {}
    case_results_map = {}
    case_id_to_index = {}  # 新增：测试用例ID到索引的映射，避免多次遍历

    # 收集所有标题和对应的测试用例
    for i, case in enumerate(test_cases):
        case_id = case.get("case_id", str(i))
        title = case.get("title", "")

        # 记录测试用例ID到索引的映射
        case_id_to_index[case_id] = i

        # 记录标题
        all_titles.append(title)

        # 映射标题到测试用例
        if title not in title_case_map:
            title_case_map[title] = []
        title_case_map[title].append((case_id, case))

        # 预处理并存储步骤和预期结果
        steps = case.get("steps", [])
        if steps:
            if isinstance(steps, list):
                steps_text = "\n".join(str(s) for s in steps)
            else:
                steps_text = str(steps)
            case_steps_map[case_id] = steps_text

        expected_results = case.get("expected_results", [])
        if expected_results:
            if isinstance(expected_results, list):
                results_text = "\n".join(str(r) for r in expected_results)
            else:
                results_text = str(expected_results)
            case_results_map[case_id] = results_text

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

    # 优化：使用Counter一次性计算标题重复
    title_counter = Counter(all_titles)

    # 查找标题重复的测试用例
    for title, count in title_counter.items():
        if count > 1 and title:
            # 获取具有相同标题的测试用例
            same_title_cases = title_case_map.get(title, [])
            case_ids = [case_id for case_id, _ in same_title_cases]
            case_objs = [case for _, case in same_title_cases]

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

                for case in case_objs:
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

                # 去重 - 使用集合而不是字典
                unique_steps = list({str(step).strip() for step in all_steps if str(step).strip()})
                unique_expected = list({str(result).strip() for result in all_expected_results if str(result).strip()})

                # 生成合并建议
                duplicate_info["merge_suggestions"].append({
                    "type": "title_duplicate",
                    "title": title,
                    "case_ids": case_ids,
                    "merged_case": {
                        "title": title,
                        "case_id": f"MERGED-{case_ids[0]}",
                        "preconditions": case_objs[0].get("preconditions", ""),
                        "steps": unique_steps,
                        "expected_results": unique_expected
                    },
                    "original_case_ids": case_ids  # 确保保留原始case_ids
                })

    # 查找步骤或预期结果高度相似的测试用例
    # 优化：使用哈希表和集合加速相似度检查
    from difflib import SequenceMatcher

    # 记录已处理的相似度比较，避免重复计算
    processed_comparisons = set()
    steps_similar_cases = {}

    # 使用预先计算的映射关系
    case_ids = list(case_steps_map.keys())
    
    log(f"进行步骤相似性比较，用例数: {len(case_ids)}")

    # 优化：实现批量处理比较操作
    def batch_compare_similarity(cases_batch):
        results = {}
        for case_id1, case_id2 in cases_batch:
            if case_id1 not in case_steps_map or case_id2 not in case_steps_map:
                continue

            steps1 = case_steps_map[case_id1]
            steps2 = case_steps_map[case_id2]

            # 快速预筛选：比较长度和简单特征
            len1, len2 = len(steps1), len(steps2)
            if abs(len1 - len2) > min(len1, len2) * 0.3:
                continue  # 长度差异过大，跳过详细比较

            # 快速特征比较：比较首尾几个字符和词袋特征
            if len1 > 20 and len2 > 20:
                # 比较首尾字符
                if steps1[:10] != steps2[:10] and steps1[-10:] != steps2[-10:]:
                    # 使用词袋模型进行快速比较
                    words1 = set(steps1.lower().split())
                    words2 = set(steps2.lower().split())
                    # 计算Jaccard相似度
                    intersection = len(words1.intersection(words2))
                    union = len(words1.union(words2))
                    if union > 0 and intersection / union < DUPLICATE_SIMILARITY_THRESHOLD * 0.8:
                        continue  # 词袋相似度过低，跳过详细比较

            # 只有在快速预筛选通过后，才使用序列匹配算法计算相似度
            similarity = SequenceMatcher(None, steps1, steps2).quick_ratio()
            if similarity > DUPLICATE_SIMILARITY_THRESHOLD:  # 使用配置参数作为相似度阈值
                results[(case_id1, case_id2)] = similarity
        return results

    # 准备批量比较任务
    comparison_batches = []
    batch_size = BATCH_SIZE  # 使用配置中的批处理大小
    current_batch = []

    for i, case_id1 in enumerate(case_ids):
        for j in range(i + 1, len(case_ids)):
            case_id2 = case_ids[j]

            # 跳过已处理的比较
            pair_key = f"{case_id1}-{case_id2}"
            if pair_key in processed_comparisons:
                continue

            # 添加到当前批次
            current_batch.append((case_id1, case_id2))
            processed_comparisons.add(pair_key)

            # 如果当前批次达到指定大小，添加到批量列表
            if len(current_batch) >= batch_size:
                comparison_batches.append(current_batch)
                current_batch = []

    # 添加最后一批
    if current_batch:
        comparison_batches.append(current_batch)

    log(f"分批处理相似性比较，批次数: {len(comparison_batches)}")

    # 使用线程池并行执行批量比较
    batch_results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # 提交所有批次任务
        future_to_batch = {executor.submit(batch_compare_similarity, batch): i for i, batch in enumerate(comparison_batches)}

        # 处理完成的任务
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_index = future_to_batch[future]
            try:
                result = future.result()
                batch_results.update(result)
            except Exception as e:
                log(f"批次 {batch_index} 处理出错: {str(e)}")

    log(f"相似性比较完成，找到 {len(batch_results)} 对相似步骤")

    # 处理批量比较结果
    for (case_id1, case_id2), similarity in batch_results.items():
        # 更新重复类型计数
        duplicate_info["duplicate_types"]["steps"] += 1

        # 记录相似步骤的用例
        if case_id1 not in steps_similar_cases:
            steps_similar_cases[case_id1] = []
        steps_similar_cases[case_id1].append(case_id2)

        if case_id2 not in steps_similar_cases:
            steps_similar_cases[case_id2] = []
        steps_similar_cases[case_id2].append(case_id1)

    # 构建步骤重复的测试用例组
    processed_case_ids = set()
    for case_id, similar_ids in steps_similar_cases.items():
        if case_id in processed_case_ids:
            continue

        # 构建一组相似的测试用例
        group = {case_id} | set(similar_ids)
        processed_case_ids.update(group)

        # 如果组中有多个测试用例，记录为步骤重复
        if len(group) > 1:
            case_ids = list(group)
            titles = []

            for case_id in case_ids:
                # 通过映射直接获取测试用例，避免遍历
                if case_id in case_id_to_index:
                    case_index = case_id_to_index[case_id]
                    case = test_cases[case_index]
                    titles.append(case.get("title", ""))

            duplicate_info["steps_duplicates"].append({
                "count": len(case_ids),
                "case_ids": case_ids,
                "titles": titles
            })

            # 查找具有相似步骤的测试用例详情
            similar_cases = []
            for case_id in case_ids:
                if case_id in case_id_to_index:
                    case_index = case_id_to_index[case_id]
                    similar_cases.append(test_cases[case_index])

            if similar_cases:
                # 为步骤相似的测试用例生成合并建议
                # 合并标题：使用最长或最具描述性的标题
                titles_sorted = sorted(titles, key=len, reverse=True)
                merged_title = titles_sorted[0] if titles_sorted else "合并测试用例"

                # 合并预期结果
                all_expected_results = []
                for case in similar_cases:
                    expected = case.get("expected_results", "")
                    if isinstance(expected, list):
                        all_expected_results.extend(expected)
                    elif expected:
                        all_expected_results.append(expected)

                # 去重 - 使用集合
                unique_expected = list({str(result).strip() for result in all_expected_results if str(result).strip()})

                # 生成合并建议
                duplicate_info["merge_suggestions"].append({
                    "type": "steps_duplicate",
                    "case_ids": case_ids,
                    "titles": titles,
                    "merged_case": {
                        "title": merged_title,
                        "case_id": f"MERGED-STEPS-{case_ids[0]}",
                        "preconditions": similar_cases[0].get("preconditions", "") if similar_cases else "",
                        "steps": similar_cases[0].get("steps", "") if similar_cases else "",  # 使用相似的步骤
                        "expected_results": unique_expected
                    },
                    "original_case_ids": case_ids  # 确保保留原始case_ids
                })

    # 按类别统计重复情况 - 使用哈希表和Counter优化
    for category, cases in categories.items():
        # 直接使用Counter计算标题重复
        category_titles = [case.get("title", "") for case in cases]
        title_counter = Counter(category_titles)
        title_duplicates = sum(count - 1 for count in title_counter.values() if count > 1)

        # 使用集合检测步骤重复
        steps_set = set()
        steps_duplicates = 0

        for case in cases:
            steps = case.get("steps", "")
            if steps:
                if isinstance(steps, list):
                    steps = "\n".join([str(s) for s in steps])
                steps_hash_val = hash(steps)
                if steps_hash_val in steps_set:
                    steps_duplicates += 1
                else:
                    steps_set.add(steps_hash_val)

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

    log(f"重复用例分析完成，重复率: {duplicate_info['duplicate_rate']}%, 重复数: {duplicate_count}")
    
    return duplicate_info
