# 测试用例评测工具

## 项目概述

测试用例评测工具是一个用于比较AI生成的测试用例与黄金标准测试用例的工具，能够评估测试用例的质量、覆盖度和有效性。本工具支持命令行模式和API服务模式，可以灵活应对不同使用场景。同时，工具集成了frp服务，可以将本地API服务映射到外网，方便远程访问。

## 主要功能

- 自动格式化各种格式的测试用例，统一为标准JSON格式
- 分析测试用例重复情况，提供合并建议
- 评估测试用例质量，包括功能覆盖度、缺陷发现能力等多个维度
- 生成详细的评测报告（JSON和Markdown格式），包含可视化图表
- 提供REST API接口，支持远程调用
- **新增：** 集成frp服务，自动将本地API服务映射到外网

## 文件结构

工具已经被重构为模块化设计，主要包含以下文件：

- `config.py` - 配置参数和常量
- `logger.py` - 日志记录功能
- `llm_api.py` - 与LLM API的通信
- `formatter.py` - 测试用例格式化
- `analyzer.py` - 测试用例重复分析
- `evaluator.py` - 测试用例质量评估
- `api_server.py` - API服务接口
- `core.py` - 主要程序逻辑
- `main.py` - 程序入口点，包含frp服务启动功能
- `compare.py` - 向后兼容的入口点
- `frpc.toml` - frp客户端配置文件

## 安装步骤

1. 克隆仓库到本地
2. 安装依赖库：
```
pip install fastapi uvicorn aiohttp chardet python-multipart
```
3. 下载frp客户端：
   - 从[frp官方GitHub](https://github.com/fatedier/frp/releases)下载适合您系统的frp客户端
   - 将`frpc`可执行文件放置在项目根目录，或确保它在系统PATH中

## 使用方法

### API模式（推荐）

1. 启动API服务器和frp服务：
```
python main.py
```

2. 服务器将在本地启动（http://127.0.0.1:8000）并通过frp映射到外网
3. 控制台会显示本地和外网访问地址
4. 调用API接口进行评测

### 命令行模式（不启动API和frp）

```
python main.py --cli --ai [AI测试用例文件路径] --golden [黄金标准测试用例文件路径]
```

### 向后兼容模式

```
python compare.py --ai [AI测试用例文件路径] --golden [黄金标准测试用例文件路径]
```

## frp服务配置

frp服务配置位于`frpc.toml`文件中，您可以根据需要修改以下参数：

```toml
serverAddr = "x.x.x.x"  # frp服务器地址
serverPort = 7000               # frp服务器端口

auth.method = "token"           # 认证方式
auth.token = "xxxxxxxxxx"  # 认证令牌

[[proxies]]
name = "feishu-tcp"             # 代理名称
type = "tcp"                    # 代理类型
localIP = "127.0.0.1"           # 本地IP
localPort = 8000                # 本地端口
remotePort = 8000               # 远程端口
```

如需使用自己的frp服务器，请修改`serverAddr`、`serverPort`和`auth.token`参数。

## API接口文档

### 1. 比较测试用例

**请求：** `POST http://x.x.x.x:8000/compare-test-cases`

**参数：**
```json
{
  "ai_test_cases": "JSON字符串",
  "golden_test_cases": "JSON字符串（可选）",
  "model_name": "deepseek-r1-250528（可选）",
  "save_results": true
}
```

**响应：**
```json
{
  "success": true,
  "message": "测试用例评测完成",
  "evaluation_result": { /* 评测结果 */ },
  "report": "Markdown格式的报告",
  "files": {
    "report_md": "报告文件路径",
    "report_json": "JSON报告文件路径"
  },
  "finish_task": true
}
```

### 2. 上传测试用例

**请求：** `POST http://x.x.x.x:8000/upload-test-cases`

**参数：**
- `file`: 文件上传
- `file_type`: "ai" 或 "golden"

**响应：**
```json
{
  "success": true,
  "message": "测试用例文件上传成功",
  "file_path": "保存路径"
}
```

### 3. 健康检查

**请求：** `GET http://x.x.x.x:8000/health`

**响应：**
```json
{
  "status": "healthy",
  "timestamp": 1689123456.789,
  "dirs_status": { /* 目录状态 */ },
  "model_info": { /* 模型信息 */ }
}
```

## 配置说明

主要配置参数位于 `config.py` 文件中，包括：

- API_URL：LLM API的URL
- MODEL_NAME：使用的模型名称（当前默认为"deepseek-r1-250528"）
- VOLC_BEARER_TOKEN：API认证令牌
- 输入/输出文件路径设置
- 并行处理配置

## 目录结构

程序会自动创建以下目录：
- `goldenset/`：存放黄金标准测试用例
- `testset/`：存放AI生成的测试用例
- `log/`：存放日志文件
- `output_evaluation/evaluation_json/`：存放JSON格式评测结果
- `output_evaluation/evaluation_markdown/`：存放Markdown格式评测报告

## 评测报告特性

- 树状评估框架图：直观展示评估维度的层次结构
- 综合评分表格：使用星号评分可视化展示各维度得分
- 重复率对比图：比较AI测试用例与黄金标准的重复率
- 重复类型分布图：展示不同类型重复的分布情况
- 测试覆盖流程图：可视化测试用例覆盖的关键流程
- 实时生成时间：每次生成报告时自动更新时间戳
- 自定义评估中心：显示"gogogo出发喽评估中心"品牌

## 测试用例格式

工具会自动将各种格式的测试用例标准化为统一格式，包含以下字段：
- `case_id`：测试用例ID
- `title`：测试用例标题
- `preconditions`：前置条件
- `steps`：测试步骤
- `expected_results`：预期结果

## 常见问题解答

1. **frp服务无法启动怎么办？**
   - 检查frpc可执行文件是否存在于项目根目录
   - 确认frpc.toml配置是否正确
   - 查看日志文件了解具体错误信息

2. **如何更改外网映射端口？**
   - 修改frpc.toml文件中的remotePort参数

3. **如何使用自己的frp服务器？**
   - 修改frpc.toml中的serverAddr、serverPort和auth.token参数

4. **评测报告中的图表无法显示？**
   - 确保使用支持Mermaid图表的Markdown查看器
   - 或使用支持Mermaid的在线Markdown编辑器查看

## 注意事项

1. 首次运行前请确保配置文件中的API密钥已正确设置
2. 评测结果会自动保存到指定目录
3. 如需使用API模式，请确保已安装FastAPI和uvicorn
4. 使用frp服务需要确保frpc可执行文件存在且配置正确

## 许可证

本项目采用MIT许可证 