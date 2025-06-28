import os
import requests
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi import Request
from pydantic import BaseModel
from dotenv import load_dotenv
from volcenginesdkarkruntime import Ark

# 加载环境变量
load_dotenv()

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配置静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 请求模型
class EvaluationRequest(BaseModel):
    doc_token: str
    user_access_token: str
    human_cases_text: str
    llm_cases_text: str

# 生成测试用例请求模型
class GenerateTestCasesRequest(BaseModel):
    doc_token: str
    user_access_token: str

# 测试用例评估请求模型
class TestCaseEvaluationRequest(BaseModel):
    doc_token: str
    user_access_token: str
    llm_test_cases: str
    golden_test_cases: str

# 简化的测试用例评估请求模型（无需文档信息）
class TestCaseEvaluationOnlyRequest(BaseModel):
    llm_test_cases: str
    golden_test_cases: str

# Markdown报告请求模型
class MarkdownReportRequest(BaseModel):
    llm_test_cases: str
    golden_test_cases: str

# 响应模型
class ReportResponse(BaseModel):
    report_markdown: str

# 飞书文档API获取函数
def fetch_lark_document(doc_token: str, user_access_token: str) -> str:
    """获取飞书文档内容"""
    try:
        # 使用正确的飞书API端点
        # 文档API: https://open.feishu.cn/document/ukTMukTMukTM/uADOwUjLwgDM14CM4ATN
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/raw_content"
        
        headers = {
            "Authorization": f"Bearer {user_access_token}",
            "Content-Type": "application/json"
        }
        
        # 发送请求
        response = requests.get(url, headers=headers)
        
        # 先检查状态码
        if response.status_code != 200:
            error_msg = f"飞书API返回错误状态码: {response.status_code}"
            try:
                error_data = response.json()
                error_msg += f", 错误信息: {error_data.get('msg', '未知错误')}"
            except:
                error_msg += f", 响应内容: {response.text[:200]}"
            
            raise HTTPException(status_code=400, detail=error_msg)
        
        # 安全解析JSON
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            # 打印原始响应内容以便调试
            error_msg = f"解析JSON失败: {str(e)}. 原始响应内容: {response.text[:200]}"
            raise HTTPException(status_code=500, detail=error_msg)
        
        # 检查API返回的状态码
        if data.get("code") != 0:
            error_msg = f"飞书API返回错误: {data.get('msg', '未知错误')}"
            raise HTTPException(status_code=400, detail=error_msg)
        
        # 提取文档内容
        content = data.get("data", {}).get("content", "")
        if not content:
            # 尝试使用替代方法获取内容
            # 有些文档API可能在不同字段返回内容
            content = data.get("data", {})
            print(f"文档内容结构: {json.dumps(content, ensure_ascii=False)[:500]}")
            
            # 如果找不到具体内容，使用整个data部分作为内容
            content = json.dumps(content, ensure_ascii=False)
        
        return content
    
    except HTTPException:
        # 直接重新抛出HTTP异常
        raise
    except Exception as e:
        error_msg = f"处理飞书文档时出错: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# 构建评估提示
def build_evaluation_prompt(prd: str, human_cases: str, llm_cases: str) -> str:
    """构建要求输出Markdown的评估Prompt"""
    prompt = f"""
# Role and Objective
You are a meticulous and experienced QA Lead with 10+ years in software testing. Your task is to critically evaluate a set of AI-generated test cases (Case_LLM) based on a Product Requirements Document (PRD) and a golden-standard set of human-written test cases (Case_Human), and then write a comprehensive evaluation report in Markdown format.

# Context
Here is all the information for your evaluation:

---PRD START---
{prd}
---PRD END---

---Case_Human START---
{human_cases}
---Case_Human END---

---Case_LLM START---
{llm_cases}
---Case_LLM END---


# Instructions & Workflow
Analyze the provided materials and generate a complete report by following these steps:

1.  **Coverage Analysis**: Identify if Case_LLM missed any key test points from the PRD and Case_Human.
2.  **Accuracy Analysis**: Verify if the "Expected Result" in Case_LLM is accurate and consistent with the PRD.
3.  **Depth & Format Analysis**: Assess if Case_LLM considers deeper quality aspects and if its formatting is clear.
4.  **Scoring**: Provide a score from 0-10 for each evaluation dimension.

# Output Format
You MUST respond with a single, well-structured Markdown document. Do not include any text outside of this Markdown. The structure must be as follows:

# 测试用例评估报告

## 1. 综合评估
- **总体结论:** <在此处填写对LLM生成用例的简短总体评价>
- **综合得分:** <在此处填写0-10之间的一个浮点数>

## 2. 各维度评分
- **需求覆盖度:** <0-10分>
- **准确性:** <0-10分>
- **格式与清晰度:** <0-10分>
- **测试深度:** <0-10分>

## 3. 详细分析

### 3.1 遗漏的用例分析
*   **[遗漏的用例标题1]:** <对这个遗漏点的简要描述>
*   **[遗漏的用例标题2]:** <对这个遗漏点的简要描述>
*   ... (如果没有遗漏，请填写 "无")

### 3.2 不准确的用例分析
*   **[有问题的用例标题1]:** <描述预期结果与PRD不符的具体情况>
*   **[有问题的用例标题2]:** <描述预期结果与PRD不符的具体情况>
*   ... (如果没有不准确的用例，请填写 "无")

### 3.3 深度分析
- **优点:** <在此处描述在深度测试方面做得好的地方>
- **不足:** <在此处描述在深度测试方面做得不足的地方>

"""
    return prompt

# 构建生成测试用例的提示
def build_test_cases_generation_prompt(prd: str) -> str:
    """构建生成JSON测试用例的Prompt"""
    prompt = f"""
# 角色与任务
你是一名经验十分丰富的测试工程师，需要根据提供的产品需求文档（PRD）生成一套全面的测试用例。

# 产品需求文档
以下是需要你理解并生成测试用例的产品需求文档内容：

---PRD START---
{prd}
---PRD END---

# 输出要求
请生成一个包含完整测试用例的JSON，格式如下：
```json
{{
    "success": true,
    "testcases": [
        {{
            "标题": "测试用例1标题",
            "前置条件": "测试用例的前置条件描述",
            "操作步骤": [
                "步骤1",
                "步骤2",
                "..."
            ],
            "预期结果": [
                "预期结果1",
                "预期结果2",
                "..."
            ]
        }},
        ... 更多测试用例
    ]
}}
```

# 测试用例要求
1. 请至少生成10个测试用例，确保覆盖产品的所有核心功能
2. 请同时考虑正面测试（验证功能正常工作）和负面测试（验证异常处理）
3. 请包含边界条件测试用例
4. 每个测试用例的操作步骤和预期结果需详细且一一对应
5. 请严格按照要求的JSON格式输出，不要添加额外的解释文字

请生成规范的、高质量的测试用例JSON。
"""
    return prompt

# 构建测试用例评估提示
def build_test_cases_evaluation_prompt(prd: str, llm_test_cases: str, golden_test_cases: str) -> str:
    """构建测试用例评估的Prompt"""
    prompt = f"""
# 角色与任务
你是一名测试专家，需要基于给定的标准对由AI生成的测试用例进行全面评估。

# 评估材料
以下是你需要评估的内容：

## 产品需求文档
---PRD START---
{prd}
---PRD END---

## AI生成的测试用例
---AI_TEST_CASES START---
{llm_test_cases}
---AI_TEST_CASES END---

## 标准测试用例（Golden Cases）
---GOLDEN_TEST_CASES START---
{golden_test_cases}
---GOLDEN_TEST_CASES END---

# 评分标准
| 评分 |   级别   |   核心特征   | 具体表现                                                     |
| :--: | :------: | :----------: | ------------------------------------------------------------ |
| 1分  |   无效   | 基础功能缺失 | • 语法错误导致无法编译/解析<br/>• 未覆盖任何核心需求条目<br/>• 无有效断言或断言逻辑完全错误<br/>• 输出内容与需求描述无关（BLEU/ROUGE得分<0.2） |
| 2分  | 勉强可用 | 部分基础达标 | • 语法正确但存在编译警告<br/>• 覆盖≤30%基础需求，遗漏边界条件<br/>• 含简单断言但未验证关键输出<br/>• 语义匹配度低（ROUGE-L<0.4）<br/>• 无法直接集成到测试框架 |
| 3分  |   合格   | 基本功能完整 | • 语法无误且可编译执行<br/>• 覆盖50%-70%需求，含部分边界值<br/>• 断言覆盖主要正常路径输出<br/>• 语义基本匹配需求（ROUGE-L≥0.6）<br/>• 可适配主流测试框架（如JUnit/Selenium） |
| 4分  |   良好   |   高可用性   | • 零编译/执行错误且通过基础测试<br/>• 覆盖≥80%需求，含关键边界值及异常场景<br/>• 断言完备（含异常处理及多状态验证）<br/>• 语义精准（METEOR≥0.7）<br/>• 支持跨环境重复执行（如多浏览器/OS） |
| 5分  |   优秀   |  专家级质量  | • 通过所有静态/动态检查（CodeBLEU≥0.8）<br/>• 100%需求覆盖+等价类/边界值完备<br/>• 断言含业务上下文验证（如安全规则）<br/>• 语义与需求高度一致（人工评估无歧义）<br/>• 优化工程效能（如减少冗余用例≥30%） |

# 输出要求
请提供一份JSON格式的详细评估报告，包含以下结构：

```json
{{
  "evaluation_summary": {{
    "overall_score": "分数（1-5之间的一位小数）",
    "final_suggestion": "如何改进测试用例生成的建议"
  }},
  "detailed_report": {{
    "format_compliance": {{
      "score": "格式合规性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "content_accuracy": {{
      "score": "内容准确性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "test_coverage": {{
      "score": "测试覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由",
      "analysis": {{
        "covered_features": [
          "已覆盖功能1",
          "已覆盖功能2"
        ],
        "missed_features_or_scenarios": [
          "未覆盖功能/场景1",
          "未覆盖功能/场景2"
        ],
        "scenario_types_found": [
          "发现的场景类型，如正面用例、负面用例、边界用例等"
        ]
      }}
    }}
  }}
}}
```

请确保你的评估客观、全面、准确，直接输出符合格式的JSON，不要包含额外的前缀或后缀文本。
"""
    return prompt

# 构建仅测试用例评估提示（无需PRD）
def build_test_cases_evaluation_only_prompt(llm_test_cases: str, golden_test_cases: str) -> str:
    """构建仅测试用例评估的Prompt（无需PRD）"""
    prompt = f"""
# 角色与任务
你是一名世界顶级的资深测试专家，需要基于给定的标准对由AI生成的测试用例进行全面评估。

# 评估材料
以下是你需要评估的内容：

## AI生成的测试用例
---AI_TEST_CASES START---
{llm_test_cases}
---AI_TEST_CASES END---

## 标准测试用例（Golden Cases）
---GOLDEN_TEST_CASES START---
{golden_test_cases}
---GOLDEN_TEST_CASES END---

# 评分标准
| 评分 |   级别   |   核心特征   | 具体表现                                                     |
| :--: | :------: | :----------: | ------------------------------------------------------------ |
| 1分  |   无效   | 基础功能缺失 | • 语法错误导致无法编译/解析<br/>• 未覆盖任何核心需求条目<br/>• 无有效断言或断言逻辑完全错误<br/>• 输出内容与需求描述无关（BLEU/ROUGE得分<0.2） |
| 2分  | 勉强可用 | 部分基础达标 | • 语法正确但存在编译警告<br/>• 覆盖≤30%基础需求，遗漏边界条件<br/>• 含简单断言但未验证关键输出<br/>• 语义匹配度低（ROUGE-L<0.4）<br/>• 无法直接集成到测试框架 |
| 3分  |   合格   | 基本功能完整 | • 语法无误且可编译执行<br/>• 覆盖50%-70%需求，含部分边界值<br/>• 断言覆盖主要正常路径输出<br/>• 语义基本匹配需求（ROUGE-L≥0.6）<br/>• 可适配主流测试框架（如JUnit/Selenium） |
| 4分  |   良好   |   高可用性   | • 零编译/执行错误且通过基础测试<br/>• 覆盖≥80%需求，含关键边界值及异常场景<br/>• 断言完备（含异常处理及多状态验证）<br/>• 语义精准（METEOR≥0.7）<br/>• 支持跨环境重复执行（如多浏览器/OS） |
| 5分  |   优秀   |  专家级质量  | • 通过所有静态/动态检查（CodeBLEU≥0.8）<br/>• 100%需求覆盖+等价类/边界值完备<br/>• 断言含业务上下文验证（如安全规则）<br/>• 语义与需求高度一致（人工评估无歧义）<br/>• 优化工程效能（如减少冗余用例≥30%） |

# 评估方法
由于没有提供PRD文档，请基于以下方法进行评估：
1. 把Golden Cases作为正确的标准，假设它完全符合需求
2. 评估LLM用例与Golden Cases的匹配程度，分析差异
3. 评估LLM用例的结构完整性、格式规范性及内部一致性

# 输出要求
请提供一份JSON格式的详细评估报告，包含以下结构：

```json
{{
  "evaluation_summary": {{
    "overall_score": "分数（1-5之间的一位小数）",
    "final_suggestion": "如何改进测试用例生成的建议"
  }},
  "detailed_report": {{
    "format_compliance": {{
      "score": "格式合规性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "content_accuracy": {{
      "score": "内容准确性得分（1-5之间的一位小数）",
      "reason": "得分理由"
    }},
    "test_coverage": {{
      "score": "测试覆盖度得分（1-5之间的一位小数）",
      "reason": "得分理由",
      "analysis": {{
        "covered_features": [
          "已覆盖功能1",
          "已覆盖功能2"
        ],
        "missed_features_or_scenarios": [
          "未覆盖功能/场景1",
          "未覆盖功能/场景2"
        ],
        "scenario_types_found": [
          "发现的场景类型，如正面用例、负面用例、边界用例等"
        ]
      }}
    }}
  }}
}}
```

请确保你的评估客观、全面、准确，直接输出符合格式的JSON，不要包含额外的前缀或后缀文本。
"""
    return prompt

# 构建Markdown格式的评估报告提示
def build_markdown_report_prompt(llm_test_cases: str, golden_test_cases: str) -> str:
    """构建Markdown格式评估报告的Prompt"""
    prompt = f"""
# 角色与任务
你是一名测试专家，需要根据提供的标准对AI生成的测试用例与人工编写的标准测试用例进行详细对比，并生成一份专业的Markdown格式评估报告。

# 评估材料
以下是你需要评估的测试用例：

## AI生成的测试用例
```json
{llm_test_cases}
```

## 标准测试用例（Golden Cases）
```json
{golden_test_cases}
```

# 评分标准
| 评分 |   级别   |   核心特征   | 具体表现                                                     |
| :--: | :------: | :----------: | ------------------------------------------------------------ |
| 1分  |   无效   | 基础功能缺失 | • 语法错误导致无法编译/解析<br/>• 未覆盖任何核心需求条目<br/>• 无有效断言或断言逻辑完全错误<br/>• 输出内容与需求描述无关（BLEU/ROUGE得分<0.2） |
| 2分  | 勉强可用 | 部分基础达标 | • 语法正确但存在编译警告<br/>• 覆盖≤30%基础需求，遗漏边界条件<br/>• 含简单断言但未验证关键输出<br/>• 语义匹配度低（ROUGE-L<0.4）<br/>• 无法直接集成到测试框架 |
| 3分  |   合格   | 基本功能完整 | • 语法无误且可编译执行<br/>• 覆盖50%-70%需求，含部分边界值<br/>• 断言覆盖主要正常路径输出<br/>• 语义基本匹配需求（ROUGE-L≥0.6）<br/>• 可适配主流测试框架（如JUnit/Selenium） |
| 4分  |   良好   |   高可用性   | • 零编译/执行错误且通过基础测试<br/>• 覆盖≥80%需求，含关键边界值及异常场景<br/>• 断言完备（含异常处理及多状态验证）<br/>• 语义精准（METEOR≥0.7）<br/>• 支持跨环境重复执行（如多浏览器/OS） |
| 5分  |   优秀   |  专家级质量  | • 通过所有静态/动态检查（CodeBLEU≥0.8）<br/>• 100%需求覆盖+等价类/边界值完备<br/>• 断言含业务上下文验证（如安全规则）<br/>• 语义与需求高度一致（人工评估无歧义）<br/>• 优化工程效能（如减少冗余用例≥30%） |

# 报告评价指标与维度
你需要从以下几个核心维度进行评估：

1. **功能覆盖度**（权重30%）：评估需求覆盖率、边界值覆盖度、分支路径覆盖率
2. **缺陷发现能力**（权重25%）：评估缺陷检测率、突变分数、失败用例比例
3. **工程效率**（权重20%）：评估测试用例生成速度、维护成本、CI/CD集成度
4. **语义质量**（权重15%）：评估语义准确性、人工可读性、断言描述清晰度
5. **安全与经济性**（权重10%）：评估恶意代码率、冗余用例比例、综合成本

# 评分公式
总分 = 0.3×功能覆盖得分 + 0.25×缺陷发现得分 + 0.2×工程效率得分 + 0.15×语义质量得分 + 0.1×安全经济得分
各维度得分 = (LLM指标值/人工基准值)×10（满分10分）

# 输出要求
请生成一份专业、详细的Markdown格式评估报告，包含以下内容：

1. **报告标题与摘要**：简要总结评估结果
2. **评估指标与方法**：说明使用的评估标准和方法
3. **综合评分**：根据评分标准给出1-5分的总体评分及每个维度的评分
4. **详细分析**：
   - 功能覆盖度分析
   - 缺陷发现能力分析
   - 工程效率分析
   - 语义质量分析
   - 安全与经济性分析
5. **优缺点对比**：列出AI生成测试用例相对于人工标准的优势和劣势
6. **改进建议**：给出3-5条具体可行的改进AI生成测试用例的建议
7. **综合结论**：总结AI测试用例的整体表现和适用场景

报告必须是可读性高、专业且有洞察力的，同时确保内容全面客观。
"""
    return prompt

# 调用火山引擎LLM API
def call_volcano_llm(prompt: str) -> str:
    """调用火山引擎方舟LLM API获取评估结果"""
    try:
        # 获取API密钥
        api_key = os.getenv("ARK_API_KEY")
        
        if not api_key:
            raise ValueError("火山引擎API凭证未配置")
        
        # 创建火山引擎客户端
        client = Ark(
            # 根据业务所在地域进行配置
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            # 从环境变量中获取API Key
            api_key=api_key
        )
        
        # 创建请求并发送
        response = client.chat.completions.create(
            # 指定模型 - 您可能需要更改为您有权限使用的模型
            model="doubao-seed-1-6-250615",  # 或您有权访问的其他模型
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ]
                }
            ],
            temperature=0.1,  # 设置较低的温度以获得更确定性的输出
            max_tokens=4096
        )
        
        # 提取LLM回复内容
        llm_response = response.choices[0].message.content
        
        return llm_response
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用火山引擎LLM时出错: {str(e)}")

# 首页路由
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    return templates.TemplateResponse("test_cases.html", {"request": request})

# 以下路由不再使用，但保留以避免潜在的依赖问题
@app.get("/test-cases", response_class=HTMLResponse)
async def get_test_cases_page(request: Request):
    return templates.TemplateResponse("test_cases.html", {"request": request})

# 评估端点
@app.post("/evaluate")
async def evaluate_test_cases(request: EvaluationRequest):
    # 1. 获取PRD内容
    prd_content = fetch_lark_document(request.doc_token, request.user_access_token)
    
    # 2. 构建新的、要求输出Markdown的评估Prompt
    evaluation_prompt = build_evaluation_prompt(
        prd=prd_content,
        human_cases=request.human_cases_text,
        llm_cases=request.llm_cases_text
    )
    
    # 3. 调用LLM获得Markdown报告字符串
    markdown_report_str = call_volcano_llm(evaluation_prompt)
    
    # 4. 直接将Markdown报告包装在JSON中返回
    return JSONResponse(content={"report_markdown": markdown_report_str})

# 根据PRD生成测试用例端点
@app.post("/generate-test-cases")
async def generate_test_cases(request: GenerateTestCasesRequest):
    # 1. 获取PRD内容
    prd_content = fetch_lark_document(request.doc_token, request.user_access_token)
    
    # 2. 构建生成测试用例的Prompt
    generation_prompt = build_test_cases_generation_prompt(prd_content)
    
    # 3. 调用LLM生成测试用例
    test_cases_json_str = call_volcano_llm(generation_prompt)
    
    # 4. 返回生成的测试用例JSON
    return JSONResponse(content={"test_cases_json": test_cases_json_str})

# 评估测试用例质量端点
@app.post("/evaluate-test-cases")
async def evaluate_test_cases_quality(request: TestCaseEvaluationRequest):
    # 1. 获取PRD内容
    prd_content = fetch_lark_document(request.doc_token, request.user_access_token)
    
    # 2. 构建评估测试用例的Prompt
    evaluation_prompt = build_test_cases_evaluation_prompt(
        prd=prd_content,
        llm_test_cases=request.llm_test_cases,
        golden_test_cases=request.golden_test_cases
    )
    
    # 3. 调用LLM评估测试用例
    evaluation_json_str = call_volcano_llm(evaluation_prompt)
    
    # 4. 返回评估结果JSON
    return JSONResponse(content={"evaluation_json": evaluation_json_str})

# 仅评估测试用例质量端点（不需要文档信息）
@app.post("/evaluate-test-cases-only")
async def evaluate_test_cases_only(request: TestCaseEvaluationOnlyRequest):
    # 构建评估测试用例的Prompt
    evaluation_prompt = build_test_cases_evaluation_only_prompt(
        llm_test_cases=request.llm_test_cases,
        golden_test_cases=request.golden_test_cases
    )
    
    # 调用LLM评估测试用例
    evaluation_json_str = call_volcano_llm(evaluation_prompt)
    
    # 返回评估结果JSON
    return JSONResponse(content={"evaluation_json": evaluation_json_str})

# 生成Markdown格式评估报告端点
@app.post("/generate-markdown-report")
async def generate_markdown_report(request: MarkdownReportRequest):
    # 构建Markdown格式评估报告的Prompt
    report_prompt = build_markdown_report_prompt(
        llm_test_cases=request.llm_test_cases,
        golden_test_cases=request.golden_test_cases
    )
    
    # 调用LLM生成Markdown评估报告
    markdown_report = call_volcano_llm(report_prompt)
    
    # 返回Markdown报告
    return JSONResponse(content={"report_markdown": markdown_report})

# 启动服务
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 