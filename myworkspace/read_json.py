import json

file_path = "test_cases_20250705_183556.json"

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"成功加载JSON文件：{file_path}")
except FileNotFoundError:
    print(f"错误：文件 {file_path} 不存在")
except json.JSONDecodeError as e:
    print(f"错误：JSON格式错误，位置：{e.pos}，行号：{e.lineno}，列号：{e.colno}，错误信息：{e.msg}")
except Exception as e:
    print(f"发生未知错误：{e}")