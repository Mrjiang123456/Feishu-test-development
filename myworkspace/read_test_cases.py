import json

try:
    with open('test_cases_20250705_184244.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print('文件存在且JSON格式正确')
    test_suite = data.get('test_suite')
    test_cases = data.get('test_cases', [])
    print(f'提取到的测试套件名称：{test_suite}')
    print(f'提取到的测试用例数量：{len(test_cases)}')
except FileNotFoundError:
    print('错误：文件不存在')
except json.JSONDecodeError as e:
    print(f'错误：JSON格式解析失败，错误信息：{e}')