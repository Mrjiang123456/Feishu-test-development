# 测试用例评测工具使用指南

本工具用于评测AI生成的测试用例与黄金标准测试用例的质量对比，支持API接口和命令行两种使用方式。

## 目录结构

```
- goldenset/           # 黄金标准测试用例目录
  - golden_cases.json  # 黄金标准测试用例文件
- testset/             # 待评测测试用例目录
  - test_cases.json    # 待评测测试用例文件
- log/                 # 日志文件目录
  - evaluation_log.txt # 评测日志
- output_evaluation/   # 评测结果输出目录
  - evaluation_json/   # JSON格式评测结果
  - evaluation_markdown/ # Markdown格式评测报告
```

## 安装依赖

```bash
pip install fastapi uvicorn aiohttp chardet python-multipart
```

## 使用方法

### 1. API服务方式（默认）

#### 启动服务

```bash
python compare.py
```

服务将在 http://127.0.0.1:8000 上运行，自动创建所需目录。

#### API接口

##### 1.1 评测测试用例

```http
POST http://127.0.0.1:8000/compare-test-cases
Content-Type: application/json

{
  "ai_test_cases": "AI测试用例的JSON字符串",
  "golden_test_cases": "黄金标准测试用例的JSON字符串(可选)",
  "model_name": "deepseek-r1-250528",
  "save_results": true
}
```

**参数说明**:
- `ai_test_cases`: 必填，AI生成的测试用例JSON字符串
- `golden_test_cases`: 可选，黄金标准测试用例JSON字符串。如果不提供，系统会自动从goldenset目录读取
- `model_name`: 可选，使用的模型名称，默认为"deepseek-r1-250528"
- `save_results`: 可选，是否保存结果文件，默认为true

**返回示例**:
```json
{
  "success": true,
  "message": "任务已提交",
  "task_id": "task_1625147890_12345"
}
```

##### 1.2 查询评测任务状态和结果

```http
GET http://127.0.0.1:8000/task-status/{task_id}
```

**返回示例**:
```json
{
  "success": true,
  "message": "测试用例评测完成",
  "evaluation_result": {
    "evaluation_summary": {
      "overall_score": "4.2",
      "final_suggestion": "..."
    },
    "detailed_report": {
      // 详细评测数据
    }
  },
  "report": "# 测试用例评估报告\n\n...",
  "files": {
    "report_md": "output_evaluation/evaluation_markdown/evaluation_report-deepseek-r1-250528.md",
    "report_json": "output_evaluation/evaluation_json/evaluation_report-deepseek-r1-250528.json"
  }
}
```

##### 1.3 上传测试用例文件

```http
POST http://127.0.0.1:8000/upload-test-cases
Content-Type: multipart/form-data

file: [测试用例文件]
file_type: "ai"  # 或 "golden"
```

**参数说明**:
- `file`: 上传的测试用例文件
- `file_type`: 文件类型，"ai"表示AI生成的测试用例，"golden"表示黄金标准测试用例

**返回示例**:
```json
{
  "success": true,
  "message": "ai测试用例文件上传成功",
  "file_path": "testset/test_cases.json"
}
```

##### 1.4 从JSON数据评测测试用例

```http
POST http://127.0.0.1:8000/evaluate-from-json
Content-Type: application/json

{
  "ai_test_cases": "AI测试用例的JSON字符串",
  "golden_test_cases": "黄金标准测试用例的JSON字符串(可选)"
}
```

### 2. 命令行方式

如果您想直接在命令行使用工具而不启动API服务，可以使用：

```bash
python compare.py --cli [--ai AI测试用例文件路径] [--golden 黄金标准测试用例文件路径]
```

**示例**:
```bash
# 使用自定义文件路径
python compare.py --cli --ai ./my_test_cases.json --golden ./my_golden_cases.json

# 使用默认文件路径
python compare.py --cli
```

如果不指定文件路径，将使用默认的`testset/test_cases.json`和`goldenset/golden_cases.json`。

## 与外部系统集成示例

以下是一个Python示例，展示如何将本工具与外部测试用例生成系统集成：

```python
import requests
import json
import time

# 1. 从外部系统获取测试用例
response = requests.post("http://127.0.0.1:8000/generate-json", json={
    # 您的参数
})
test_cases = response.json()

# 2. 发送评测请求
eval_response = requests.post("http://127.0.0.1:8000/compare-test-cases", json={
    "ai_test_cases": json.dumps(test_cases)  # 自动从goldenset中读取黄金标准
})

# 3. 获取任务ID
task_id = eval_response.json().get("task_id")
print(f"评测任务已提交，任务ID: {task_id}")

# 4. 等待并查询评测结果
status = "processing"
result = None
while status == "processing":
    time.sleep(2)  # 等待2秒
    result_response = requests.get(f"http://127.0.0.1:8000/task-status/{task_id}")
    result = result_response.json()
    
    if result.get("success") == True and result.get("message") != "任务已提交，正在处理中":
        status = "completed"
    elif "error" in result:
        status = "failed"
        print(f"评测失败: {result.get('error')}")
        break
    else:
        print("评测中...")

# 5. 处理评测结果
if status == "completed":
    print("评测完成!")
    evaluation_result = result.get("evaluation_result")
    report = result.get("report")
    
    # 输出总体得分
    overall_score = evaluation_result.get("evaluation_summary", {}).get("overall_score")
    print(f"总体得分: {overall_score}")
    
    # 保存报告到文件
    with open("evaluation_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("报告已保存到 evaluation_report.md")
```

## 注意事项

1. 首次运行时，系统会自动创建所需的目录结构
2. 黄金标准测试用例应当放在`goldenset`文件夹中，命名为`golden_cases*.json`（如`golden_cases.json`、`golden_cases_v2.json`等）
3. 评测结果将保存在`output_evaluation`文件夹的对应子文件夹中
4. 日志文件将保存在`log`文件夹中
5. API接口支持跨域请求，可以从前端页面直接调用

## 测试用例文件格式示例

### AI测试用例格式示例

```json
{
  "testcases": [
    {
      "case_id": "TC-FUNC-001",
      "title": "测试用户注册功能-有效输入",
      "preconditions": "系统处于注册页面",
      "steps": "1. 输入有效用户名\n2. 输入有效密码\n3. 输入有效邮箱\n4. 点击注册按钮",
      "expected_results": "1. 注册成功\n2. 跳转到首页\n3. 收到欢迎邮件"
    },
    {
      "case_id": "TC-FUNC-002",
      "title": "测试用户注册功能-无效用户名",
      "preconditions": "系统处于注册页面",
      "steps": "1. 输入无效用户名（少于3个字符）\n2. 输入有效密码\n3. 输入有效邮箱\n4. 点击注册按钮",
      "expected_results": "1. 提示用户名无效\n2. 注册失败"
    }
  ]
}
```

### 黄金标准测试用例格式示例

```json
{
  "test_cases": {
    "functional_test_cases": [
      {
        "case_id": "TC-FUNC-001",
        "title": "验证用户注册-有效数据",
        "preconditions": "用户位于注册页面",
        "steps": "1. 输入有效用户名\n2. 输入有效密码\n3. 确认密码\n4. 输入有效邮箱\n5. 点击提交按钮",
        "expected_results": "1. 用户成功注册\n2. 系统显示注册成功消息\n3. 系统发送确认邮件到用户邮箱"
      },
      {
        "case_id": "TC-FUNC-002",
        "title": "验证用户注册-用户名已存在",
        "preconditions": "用户位于注册页面\n系统中已存在用户名'existinguser'",
        "steps": "1. 输入用户名'existinguser'\n2. 输入有效密码\n3. 确认密码\n4. 输入有效邮箱\n5. 点击提交按钮",
        "expected_results": "1. 系统显示错误消息'用户名已存在'\n2. 注册失败"
      }
    ]
  }
}
``` 