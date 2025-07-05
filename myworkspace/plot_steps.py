import json
import matplotlib.pyplot as plt
from collections import defaultdict

# 读取测试用例数据
with open('test_cases_20250705_184244.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
test_cases = data['test_cases']

# 提取步骤数量
step_counts = [len(case['steps']) for case in test_cases]
print('步骤数量列表:', step_counts)

# 定义区间并统计
intervals = {'1-3步': 0, '4-6步': 0}
for count in step_counts:
    if 1 <= count <= 3:
        intervals['1-3步'] += 1
    elif 4 <= count <= 6:
        intervals['4-6步'] += 1
print('步骤区间统计:', intervals)

# 配置中文字体
plt.rcParams['font.family'] = ['SimSun']  # 加载SimSun字体解决中文乱码
plt.rcParams['axes.unicode_minus'] = False

# 绘制柱状图
plt.bar(intervals.keys(), intervals.values())
plt.title('测试用例步骤数量分布')
plt.xlabel('步骤数量区间')
plt.ylabel('用例数量')

# 保存图表
plt.savefig('step_distribution.png')
plt.close()
print('步骤数量分布柱状图已保存为step_distribution.png')