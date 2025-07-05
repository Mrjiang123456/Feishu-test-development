import json
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

# 加载中文字体
simsun_font = FontProperties(fname='SimSun.ttf')

# 读取测试用例数据
with open('test_cases_20250705_184244.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
test_cases = data['test_cases']

# 提取预期结果数量
expected_counts = [len(case['expected_results']) for case in test_cases]

# 分类统计（1个、2个、3个及以上）
count_1 = sum(1 for cnt in expected_counts if cnt == 1)
count_2 = sum(1 for cnt in expected_counts if cnt == 2)
count_3plus = sum(1 for cnt in expected_counts if cnt >= 3)

# 计算占比
total = len(expected_counts)
percent_1 = (count_1 / total) * 100
percent_2 = (count_2 / total) * 100
percent_3plus = (count_3plus / total) * 100

# 输出中间结果
print(f'预期结果数量统计：1个-{count_1}个，2个-{count_2}个，3个及以上-{count_3plus}个')
print(f'占比：1个-{percent_1:.1f}%，2个-{percent_2:.1f}%，3个及以上-{percent_3plus:.1f}%')

# 绘制饼图
plt.figure(figsize=(8, 8))
labels = ['1个', '2个', '3个及以上']
values = [percent_1, percent_2, percent_3plus]
plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, textprops={'fontproperties': simsun_font})
plt.title('测试用例预期结果数量占比', fontproperties=simsun_font, fontsize=14)
plt.axis('equal')

# 保存图表
plt.savefig('expected_result_pie.png', dpi=300, bbox_inches='tight')
plt.close()
