# 项目描述

这是一个基于FastAPI的测试用例生成系统，能够从飞书文档中提取产品需求文档(PRD)内容，自动生成全面的测试用例，并支持根据反馈重新生成测试用例。

# 项目结构
```plaintext
project-root/
│
├── main.py                # 主应用入口，FastAPI服务
├── langgraph_use.py       # 主测试用例生成工作流
├── regenerate.py          # 测试用例重新生成工作流
├── feishu_api.py          # 飞书文档API集成
├── model_api.py           # 模型API调用（支持图像）
├── model_api2.py          # 模型API调用（doubao1.6）
├── model_api3.py          # 模型API调用（deepseekR1）
│
├── frpc.exe               # 内网穿透客户端
├── frpc.toml              # 内网穿透配置
│
├── logs/                  # 日志目录（自动生成）
│   └── app_20250714_1530.log
│
├── README.md              # 项目文档
```  

# 主要功能

## 1. 测试用例生成
从飞书文档提取PRD内容

分析文档中的图像内容

提取和优化测试点

生成结构化测试用例

自动去重和验证

## 2. 测试用例重新生成
根据评审报告和用户反馈

重新分析PRD内容

优化测试点

生成改进版测试用例

## 3. 飞书文档集成
支持飞书文档ID和用户token

提取文档内容和图片

自动处理文档结构

## 4. 模型API集成
支持多类型模型调用

图像内容识别和分析

文本内容处理

## 环境要求

Python 3.9+

##运行服务
```plaintext
python main.py
```
服务将在 http://localhost:8080 启动

## 飞书获取文档生成测试用例
1. 生成测试用例

##POST /generate-cases

请求体
```plaintext
{
  "document_id": "飞书文档ID",
  "user_access_token": "飞书用户token"
}
```

响应示例：
```plaintext
{
  "success": true,
  "testcases": {
    "test_suite": "文档标题",
    "test_cases": {
      "functional_test_cases": [
        {
          "case_id": "001",
          "title": "测试用例标题",
          "preconditions": ["前提条件1", "前提条件2"],
          "steps": ["步骤1", "步骤2", "步骤3"],
          "expected_results": ["预期结果1", "预期结果2"]
        }
      ],
      // 其他测试类型...
    }
  }
}
```
## 重新生成测试用例
## POST /regenerate-cases

请求体：

```plaintext
{
  "review_report": "评审报告内容",
  "reason": "重新生成原因",
  "testcases": {},  // 原始测试用例（可选）
  "document_id": "飞书文档ID",  // 可选
  "user_access_token": "飞书用户token"  // 可选
}
```

响应格式：同生成测试用例接口

# 工作流程

<img width="1280" height="835" alt="image" src="https://github.com/user-attachments/assets/0101154e-d5ff-4f69-a4ac-2879b23fa72c" />


## 配置选项

##日志配置

日志文件自动按时间戳生成

存储在 logs/ 目录

格式：app_YYYYMMDD_HHMMSS.log

同时输出到控制台和文件

性能调优
并发控制：MAX_CONCURRENT = 30

重试机制：MAX_RETRIES = 3

超时设置：300秒

## 注意事项

图像处理限制：

系统会自动识别文档中的图像

超大图像可能无法处理，会使用替代描述

确保图像URL可公开访问

## 飞书文档权限：

需要有效的用户access token

用户需有文档访问权限

## 测试用例分类：

功能测试(functional_test_cases)

易用性测试(usability_test_cases)

安全性测试(security_test_cases)

兼容性测试(compatibility_test_cases)

性能测试(performance_test_cases)

## 缓存机制：

最后一次生成的测试用例会被缓存

重新生成时可复用缓存数据

缓存包括文档ID和用户token



# 许可证
本项目采用 MIT 许可证

