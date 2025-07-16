# 测试用例评测系统使用手册

## 1. 系统概述

测试用例评测系统是一个用于评估和比较测试用例质量的工具，可以对AI生成的测试用例与黄金标准测试用例进行对比分析，并生成详细的评测报告。系统支持两种运行模式：命令行模式和API服务模式。

### 主要功能

- 测试用例格式化：统一不同格式的测试用例
- 测试用例评测：评估测试用例的质量，包括格式合规性、内容准确性、测试覆盖度等多个维度
- 重复测试用例分析：检测并分析测试用例中的重复内容，提供合并建议
- 迭代对比分析：比较不同版本测试用例之间的差异和改进情况
- 多评委评测：支持多个模型共同评测，提高评估结果的可靠性
- 报告生成：生成详细的Markdown格式评测报告，包含数据可视化

### 系统架构

系统由以下核心模块组成：

- `main.py`: 主程序入口，支持命令行和API服务两种运行模式
- `core.py`: 核心处理逻辑，协调各个模块的工作流程
- `formatter.py`: 测试用例格式化模块，统一各种格式的测试用例
- `evaluator.py`: 测试用例评测模块，负责评估测试用例质量
- `analyzer.py`: 重复测试用例分析模块，检测测试用例中的重复内容
- `committee.py`: 多评委评测模块，支持多个模型共同评测
- `api_server.py`: API服务模块，提供RESTful API接口
- `llm_api.py`: 大语言模型API调用模块，负责与LLM交互
- `logger.py`: 日志模块，记录系统运行日志
- `config.py`: 配置模块，存储系统配置参数

## 2. 安装说明

### 系统要求

- Python 3.7+
- 网络连接（用于调用大语言模型API）

### 安装步骤

1. 克隆或下载项目代码

2. 安装依赖库

```bash
pip install fastapi uvicorn aiohttp chardet python-multipart
```

3. 确保项目目录结构完整，包含所有必要的Python文件和配置文件

### 目录结构准备

系统启动时会自动创建以下目录结构：

```
├── goldenset/            # 存放黄金标准测试用例
├── testset/              # 存放AI生成的测试用例
├── log/                  # 存放日志文件
├── output_evaluation/    # 存放评测结果
│   ├── evaluation_json/      # JSON格式评测结果
│   └── evaluation_markdown/  # Markdown格式评测报告
├── templates/            # 存放HTML模板
└── static/               # 存放静态资源
```

## 3. 使用方法

### 命令行模式

命令行模式适用于单次评测任务，使用以下命令运行：

```bash
python main.py --cli --ai <AI测试用例文件路径> --golden <黄金标准测试用例文件路径>
```

#### 参数说明

- `--ai`: AI生成的测试用例文件路径（必需）
- `--golden`: 黄金标准测试用例文件路径（必需）
- `--iteration`: 启用迭代前后对比功能（可选）
- `--prev`: 上一次迭代的测试用例文件路径，仅在`--iteration`为true时有效（可选）

#### 示例

```bash
# 基本评测
python main.py --cli --ai testset/ai_cases.json --golden goldenset/golden_cases.json

# 启用迭代对比
python main.py --cli --ai testset/ai_cases_v2.json --golden goldenset/golden_cases.json --iteration --prev testset/ai_cases_v1.json
```

### API服务模式

API服务模式提供RESTful API接口，支持多次评测任务，使用以下命令启动：

```bash
python main.py
```

启动后，API服务将在本地8000端口运行，同时通过frpc映射到外网（如果frpc配置正确）。

#### 访问地址

- 本地访问地址：http://127.0.0.1:8000
- 黄金标准测试用例页面：http://127.0.0.1:8000/golden-cases
- 外网访问地址：根据frpc.toml配置决定，通常为http://<serverAddr>:<remotePort>

## 4. API接口说明

### 1. 测试用例比较评测

**接口**：`POST /compare-test-cases`

**功能**：比较AI生成的测试用例与黄金标准测试用例，生成评测报告

**请求参数**：

```json
{
  "ai_test_cases": "JSON字符串，AI生成的测试用例",
  "golden_test_cases": "JSON字符串，黄金标准测试用例（可选）",
  "model_name": "使用的模型名称（可选，默认使用配置文件中的MODEL_NAME）",
  "save_results": true,  // 是否保存结果文件（可选，默认为true）
  "is_iteration": false,  // 是否启用迭代前后对比功能（可选，默认为false）
  "prev_iteration": "JSON字符串，上一次迭代的测试用例（可选）"
}
```

**响应结果**：

```json
{
  "success": true,
  "message": "测试用例评测完成",
  "evaluation_result": {
    // 评测结果详情
  },
  "report": "Markdown格式的评测报告",
  "report_iteration": "Markdown格式的迭代简洁报告（仅在is_iteration为true时返回）",
  "files": {
    "report_md": "报告文件路径",
    "report_json": "JSON结果文件路径"
  },
  "request_id": "请求ID"
}
```

### 2. 从JSON直接评测

**接口**：`POST /evaluate-from-json`

**功能**：与`/compare-test-cases`相同，是其别名

### 3. 保存黄金标准测试用例

**接口**：`POST /api/save-golden-cases`

**功能**：保存黄金标准测试用例到系统

**请求参数**：

```json
{
  "golden_test_cases": "JSON字符串，黄金标准测试用例"
}
```

**响应结果**：

```json
{
  "success": true,
  "message": "黄金标准测试用例保存成功",
  "file_path": "保存的文件路径"
}
```

### 4. 上传测试用例文件

**接口**：`POST /upload-test-cases`

**功能**：上传测试用例文件（AI生成或黄金标准）

**请求参数**：
- `file`: 文件（multipart/form-data）
- `file_type`: 文件类型，"ai"或"golden"

**响应结果**：

```json
{
  "success": true,
  "message": "文件上传成功",
  "file_path": "保存的文件路径",
  "file_content": "文件内容"
}
```

### 5. 查询任务状态

**接口**：`GET /task-status/{task_id}`

**功能**：查询异步评测任务的状态

**响应结果**：

```json
{
  "task_id": "任务ID",
  "status": "任务状态（pending/running/completed/failed）",
  "result": {
    // 任务结果（如果已完成）
  },
  "error": "错误信息（如果失败）"
}
```

### 6. 健康检查

**接口**：`GET /health`

**功能**：检查API服务是否正常运行

**响应结果**：

```json
{
  "status": "ok",
  "version": "系统版本"
}
```

## 5. 测试用例格式

系统支持多种测试用例格式，会自动进行格式化处理。以下是推荐的标准格式：

### 标准格式

```json
{
  "testcases": {
    "test_suite": "测试套件名称",
    "test_cases": [
      {
        "case_id": "TC-FUNC-001",
        "title": "测试用例标题",
        "preconditions": "前置条件",
        "steps": [
          "步骤1",
          "步骤2",
          "..."
        ],
        "expected_results": [
          "预期结果1",
          "预期结果2",
          "..."
        ],
        "category": "功能类别（可选）"
      },
      // 更多测试用例...
    ]
  }
}
```

### 其他支持的格式

系统还支持以下格式：

1. 按类别分组的测试用例：
```json
{
  "functional": [
    // 功能测试用例...
  ],
  "security": [
    // 安全测试用例...
  ]
}
```

2. 简单列表格式：
```json
[
  {
    "case_id": "TC-FUNC-001",
    "title": "测试用例标题",
    // ...其他字段
  },
  // 更多测试用例...
]
```

3. 中文格式：
```json
{
  "测试用例": {
    "功能测试": [
      // 功能测试用例...
    ],
    "安全性测试": [
      // 安全性测试用例...
    ]
  }
}
```

## 6. 评测报告说明

系统生成两种格式的评测报告：

1. **JSON格式评测结果**：包含详细的评测数据，适合程序解析
2. **Markdown格式评测报告**：包含可视化图表和详细分析，适合人工阅读

### 标准评测报告内容

标准评测报告包含以下内容：

1. 报告标题与摘要
2. 评估指标与方法
3. 综合评分（各维度评分表格和图表）
4. 详细分析（各评估维度的详细分析）
5. 重复测试用例分析（重复率、类型和合并建议）
6. 测试覆盖率分析（关键流程和功能覆盖情况）
7. 多评委评测信息（如果启用）
8. 优缺点对比
9. 改进建议
10. 综合结论

### 迭代对比报告内容

当启用迭代对比功能时，系统会生成两种报告：

1. **标准报告**：与上述标准评测报告相同，但增加了迭代对比分析部分
2. **迭代简洁报告**：只包含迭代前后对比分析的关键信息，包括：
   - 总体评分
   - 总体建议
   - 合并建议
   - 改进建议
   - 重复率分析

## 7. 多评委评测

系统支持两种评测框架：

1. **标准多评委评测**：多个模型独立评测，然后聚合结果
2. **CollabEval三阶段评测**：三阶段评测流程（独立评分 -> 辩论协作 -> 主席聚合）

### 配置多评委评测

在`config.py`中配置：

```python
# 启用多评委评测
ENABLE_MULTI_JUDGES = True

# 启用CollabEval框架（如果为False则使用标准多评委评测）
ENABLE_COLLAB_EVAL = True

# 评委模型列表
JUDGE_MODELS = [
    "deepseek-v3-250324",
    "doubao-seed-1-6-250615"
]
```

## 8. 常见问题解答

### Q1: 如何更新黄金标准测试用例？

A1: 可以通过以下两种方式更新：
1. 通过API接口`/api/save-golden-cases`上传新的黄金标准测试用例
2. 通过Web界面访问`/golden-cases`页面，上传新的黄金标准测试用例

### Q2: 系统支持哪些大语言模型？

A2: 系统设计为模型无关的，可以通过配置`config.py`中的`MODEL_NAME`和`API_URL`来使用不同的大语言模型。默认支持多种模型，如deepseek、doubao等。

### Q3: 如何启用迭代对比功能？

A3: 
- 命令行模式：使用`--iteration`和`--prev`参数
- API模式：在请求中设置`is_iteration=true`并提供`prev_iteration`参数

### Q4: 如何解决"找不到黄金标准测试用例文件"的错误？

A4: 确保`goldenset`目录中存在有效的黄金标准测试用例文件（如`golden_cases.json`）。可以通过Web界面或API接口上传黄金标准测试用例。

### Q5: 如何配置外网访问？

A5: 系统使用frpc进行内网穿透，配置`frpc.toml`文件中的`serverAddr`、`serverPort`和`remotePort`参数，确保frpc可执行文件在系统路径中或项目目录下。

### Q6: 报告中的图表无法正常显示怎么办？

A6: Markdown格式的报告使用Mermaid语法生成图表，需要使用支持Mermaid的Markdown查看器（如VS Code、Typora等）或将报告转换为HTML/PDF格式。 
