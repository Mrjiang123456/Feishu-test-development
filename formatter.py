import json
import aiohttp
from logger import log
from llm_api import async_call_llm

async def format_test_cases(session: aiohttp.ClientSession, file_content, file_type="AI"):
    """
    调用LLM格式化测试用例
    
    :param session: aiohttp会话
    :param file_content: 文件内容
    :param file_type: 文件类型，"AI"或"Golden"
    :return: 格式化后的测试用例
    """
    log(f"开始格式化{file_type}测试用例", important=True)
    
    try:
        # 先尝试解析原始JSON数据
        data = json.loads(file_content)
        log(f"{file_type}测试用例JSON解析成功")
        
        # 提取所有测试用例，不限制数量
        all_test_cases = []
        
        # 从原始数据中提取测试用例，处理各种可能的格式
        if isinstance(data, dict):
            # 情况1：顶层有testcases字段
            if "testcases" in data:
                if isinstance(data["testcases"], dict) and "test_cases" in data["testcases"]:
                    all_test_cases = data["testcases"]["test_cases"]
                elif isinstance(data["testcases"], list):
                    all_test_cases = data["testcases"]
                elif isinstance(data["testcases"], dict) and "test_suite" in data["testcases"]:
                    # 特殊情况，可能有嵌套结构
                    if "test_cases" in data["testcases"]:
                        all_test_cases = data["testcases"]["test_cases"]
            # 情况2：顶层有test_cases字段
            elif "test_cases" in data:
                if isinstance(data["test_cases"], list):
                    all_test_cases = data["test_cases"]
                elif isinstance(data["test_cases"], dict):
                    # 合并所有分类下的测试用例
                    for category, cases in data["test_cases"].items():
                        if isinstance(cases, list):
                            all_test_cases.extend(cases)
            # 情况3：可能有其他命名的字段包含测试用例
            elif any(key for key in data.keys() if "case" in key.lower() or "test" in key.lower()):
                for key in data.keys():
                    if "case" in key.lower() or "test" in key.lower():
                        if isinstance(data[key], list):
                            all_test_cases.extend(data[key])
                        elif isinstance(data[key], dict):
                            all_test_cases.append(data[key])
        # 情况4：顶层直接是测试用例列表
        elif isinstance(data, list):
            all_test_cases = data
            
        log(f"从原始数据中提取到{len(all_test_cases)}个测试用例", important=True)
        
        # 格式化所有测试用例到统一格式
        formatted_test_cases = []
        for i, case in enumerate(all_test_cases):
            if not isinstance(case, dict):
                log(f"警告：跳过非字典格式的测试用例 {case}")
                continue
                
            # 确保case_id字段
            case_id = case.get("case_id", "")
            if not case_id:
                case_id = case.get("id", "")
                if not case_id:
                    case_id = f"TC-FUNC-{i+1:03d}"
            if not case_id.startswith("TC-") and not case_id.startswith("FUNC-"):
                case_id = f"FUNC-SCEN-{i+1:03d}"
            
            # 确保title字段
            title_candidates = ["title", "标题", "测试标题", "test_title", "name", "测试名称"]
            title = None
            for candidate in title_candidates:
                if candidate in case:
                    title = case[candidate]
                    break
            if not title:
                title = f"Test Case {i+1}"
            
            # 确保preconditions字段
            preconditions_candidates = ["preconditions", "前置条件", "pre_conditions", "prerequisites", "前提条件"]
            preconditions = None
            for candidate in preconditions_candidates:
                if candidate in case and case[candidate]:
                    preconditions = case[candidate]
                    break
            if not preconditions:
                preconditions = ""
            
            # 转换前置条件为字符串
            if isinstance(preconditions, list):
                preconditions = "\n".join([str(item) for item in preconditions if item])
            
            # 确保steps字段
            steps_candidates = ["steps", "步骤", "test_steps", "测试步骤", "操作步骤", "actions"]
            steps = None
            for candidate in steps_candidates:
                if candidate in case and case[candidate]:
                    steps = case[candidate]
                    break
            if not steps:
                steps = []
            
            # 转换步骤为列表
            if not isinstance(steps, list):
                if isinstance(steps, str) and steps.strip():
                    # 尝试分割字符串成为列表
                    if "\n" in steps:
                        steps = steps.split("\n")
                    else:
                        steps = [steps]
                else:
                    steps = []
            
            # 确保expected_results字段
            expected_candidates = ["expected_results", "预期结果", "expected", "assertions", "expected_outcome", "结果"]
            expected_results = None
            for candidate in expected_candidates:
                if candidate in case and case[candidate]:
                    expected_results = case[candidate]
                    break
            if not expected_results:
                expected_results = []
            
            # 转换预期结果为列表
            if not isinstance(expected_results, list):
                if isinstance(expected_results, str) and expected_results.strip():
                    # 尝试分割字符串成为列表
                    if "\n" in expected_results:
                        expected_results = expected_results.split("\n")
                    else:
                        expected_results = [expected_results]
                else:
                    expected_results = []
            
            # 构建格式化后的测试用例
            formatted_case = {
                "case_id": case_id,
                "title": title,
                "preconditions": preconditions,
                "steps": [str(step).strip() for step in steps if step],
                "expected_results": [str(result).strip() for result in expected_results if result]
            }
            formatted_test_cases.append(formatted_case)
        
        # 构建最终格式
        test_suite_name = "B端产品登录功能测试用例"
        if isinstance(data, dict) and "test_suite" in data:
            test_suite_name = data["test_suite"]
        elif isinstance(data, dict) and "testcases" in data and isinstance(data["testcases"], dict) and "test_suite" in data["testcases"]:
            test_suite_name = data["testcases"]["test_suite"]
        
        final_data = {
            "success": True,
            "testcases": {
                "test_suite": test_suite_name,
                "test_cases": formatted_test_cases
            }
        }
        
        log(f"成功格式化{len(formatted_test_cases)}个{file_type}测试用例", important=True)
        return final_data
        
    except json.JSONDecodeError as e:
        log(f"解析{file_type}原始JSON数据失败: {e}", important=True)
        return None
    except Exception as e:
        log(f"格式化{file_type}测试用例时发生错误: {e}", important=True)
        import traceback
        log(f"错误详情: {traceback.format_exc()}")
        return None 