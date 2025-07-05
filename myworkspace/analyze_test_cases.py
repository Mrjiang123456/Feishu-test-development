import pandas as pd

# 读取测试用例DataFrame（假设process_test_cases.py已生成并保存为CSV）
df = pd.read_csv('test_cases_df.csv')

# 计算测试用例总数
total_cases = len(df)
print(f"测试用例总数: {total_cases}")

# 计算步骤数量指标
steps_min = df['steps_count'].min()
steps_max = df['steps_count'].max()
steps_mean = df['steps_count'].mean()
print(f"步骤数量最小值: {steps_min}")
print(f"步骤数量最大值: {steps_max}")
print(f"步骤数量平均值: {steps_mean:.2f}")

# 计算预期结果数量指标
expected_min = df['expected_results_count'].min()
expected_max = df['expected_results_count'].max()
expected_mean = df['expected_results_count'].mean()
print(f"预期结果数量最小值: {expected_min}")
print(f"预期结果数量最大值: {expected_max}")
print(f"预期结果数量平均值: {expected_mean:.2f}")

# 计算前置条件缺失用例数（处理字符串/列表两种情况）
def check_preconditions(pre):
    if isinstance(pre, str):
        return len(pre.strip()) == 0
    elif isinstance(pre, list):
        return len(pre) == 0
    else:
        return True  # 异常类型默认视为缺失
preconditions_missing = df['preconditions'].apply(check_preconditions).sum()
print(f"前置条件缺失的用例数: {preconditions_missing}")