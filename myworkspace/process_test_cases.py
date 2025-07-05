import json
import pandas as pd

# 读取JSON文件
with open('test_cases_20250705_184244.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

test_cases = data['test_cases']

extracted_data = []

for case in test_cases:
    case_id = case['case_id']
    title = case['title']
    preconditions = case.get('preconditions', '')
    preconditions_count = len(preconditions) if isinstance(preconditions, list) else len(preconditions.split('；')) if preconditions else 0  # 兼容列表/字符串类型前置条件统计
    steps_count = len(case.get('steps', []))  # 统计步骤数组长度
    expected_results_count = len(case.get('expected_results', []))  # 统计预期结果数组长度
    extracted_data.append({
        'case_id': case_id,
        'title': title,
        'preconditions_count': preconditions_count,
        'steps_count': steps_count,
        'expected_results_count': expected_results_count
    })

df = pd.DataFrame(extracted_data)

print('测试用例数据提取完成，DataFrame内容：')
print(df)