import pandas as pd
import json

# 读取JSON文件
with open('test_cases_20250705_184244.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

test_cases = data['test_cases']

# 转换为DataFrame（模拟之前process_test_cases.py的处理逻辑）
rows = []
for case in test_cases:
    preconditions = case.get('preconditions', '')
    # 处理前置条件可能为列表的情况（兼容之前错误处理逻辑）
    if isinstance(preconditions, list):
        preconditions = '；'.join(preconditions) if preconditions else ''
    preconditions_count = len(preconditions.split('；')) if preconditions else 0
    steps_count = len(case.get('steps', []))
    expected_results_count = len(case.get('expected_results', []))
    rows.append({ 
        'case_id': case['case_id'],
        'title': case['title'],
        'preconditions_count': preconditions_count,
        'steps_count': steps_count,
        'expected_results_count': expected_results_count
    })
df = pd.DataFrame(rows)

# 计算指标
metrics = {
    '测试用例总数': len(df),
    '步骤数量最小值': df['steps_count'].min(),
    '步骤数量最大值': df['steps_count'].max(),
    '步骤数量平均值': round(df['steps_count'].mean(), 2),
    '预期结果数量最小值': df['expected_results_count'].min(),
    '预期结果数量最大值': df['expected_results_count'].max(),
    '预期结果数量平均值': round(df['expected_results_count'].mean(), 2),
    '前置条件缺失的用例数': len(df[df['preconditions_count'] == 0])
}

# 打印结果
print('指标计算结果：')
for key, value in metrics.items():
    print(f'{key}: {value}')