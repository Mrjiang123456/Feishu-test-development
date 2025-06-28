# 测试用例评估系统

这是一个全栈Web应用，通过集成飞书文档API和火山引擎方舟LLM API，实现自动化测试用例评估，并生成Markdown格式的评估报告。

## 功能特点

- 从飞书文档获取PRD内容
- 对比人工编写和LLM生成的测试用例
- 生成详细的Markdown格式评估报告
- 实时渲染评估结果

## 技术栈

### 后端
- Python 3.8+
- FastAPI
- 飞书开放API
- 火山引擎方舟LLM API

### 前端
- HTML, CSS, JavaScript
- marked.js (Markdown渲染库)

## 安装与运行

1. 克隆仓库
```
git clone <仓库地址>
cd <项目文件夹>
```

2. 安装依赖
```
pip install -r requirements.txt
```

3. 配置环境变量
创建 `.env` 文件，填入相关API密钥：
```
# 飞书API凭证
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret

# 火山引擎API凭证
ARK_API_KEY=your_ark_api_key
```

4. 启动服务
```
python main.py
```

5. 访问应用
在浏览器中打开 `http://localhost:8000`

## 使用指南

1. 填写飞书文档Token和用户访问Token
2. 输入人工编写的测试用例
3. 输入LLM生成的测试用例
4. 点击"开始评估"按钮
5. 查看自动生成的Markdown评估报告

## 注意事项

- 确保飞书文档的权限设置允许API访问
- 火山引擎API调用需要有效的API密钥
- 处理大型文档或复杂测试用例时，响应可能需要较长时间 