document.addEventListener('DOMContentLoaded', function() {
    // 页签切换逻辑
    const tabGenerate = document.getElementById('tab-generate');
    const tabEvaluate = document.getElementById('tab-evaluate');
    const generateSection = document.getElementById('generate-section');
    const evaluateSection = document.getElementById('evaluate-section');
    
    tabGenerate.addEventListener('click', function() {
        tabGenerate.classList.add('active');
        tabEvaluate.classList.remove('active');
        generateSection.style.display = 'block';
        evaluateSection.style.display = 'none';
    });
    
    tabEvaluate.addEventListener('click', function() {
        tabEvaluate.classList.add('active');
        tabGenerate.classList.remove('active');
        evaluateSection.style.display = 'block';
        generateSection.style.display = 'none';
    });
    
    // 生成测试用例相关元素
    const docTokenGenInput = document.getElementById('doc-token-gen');
    const userTokenGenInput = document.getElementById('user-token-gen');
    const generateBtn = document.getElementById('generate-btn');
    const loadingGen = document.getElementById('loading-gen');
    const resultContainerGen = document.getElementById('result-container-gen');
    const testCasesResult = document.getElementById('test-cases-result');
    const copyResultBtn = document.getElementById('copy-result-btn');
    
    // 评估测试用例相关元素
    const llmTestCasesTextarea = document.getElementById('llm-test-cases');
    const goldenTestCasesTextarea = document.getElementById('golden-test-cases');
    const evaluateBtn = document.getElementById('evaluate-btn');
    const loadingEval = document.getElementById('loading-eval');
    const resultContainerMd = document.getElementById('result-container-md');
    const markdownReport = document.getElementById('markdown-report');
    const copyMdBtn = document.getElementById('copy-md-btn');
    
    // 生成测试用例按钮点击事件
    generateBtn.addEventListener('click', async function() {
        // 验证输入
        if (!docTokenGenInput.value) {
            alert('请输入飞书文档Token');
            docTokenGenInput.focus();
            return;
        }
        
        if (!userTokenGenInput.value) {
            alert('请输入用户访问Token');
            userTokenGenInput.focus();
            return;
        }
        
        // 显示加载动画
        loadingGen.style.display = 'block';
        resultContainerGen.style.display = 'none';
        
        // 准备请求数据
        const requestData = {
            doc_token: docTokenGenInput.value,
            user_access_token: userTokenGenInput.value
        };
        
        try {
            // 发送生成请求
            const response = await fetch('/generate-test-cases', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });
            
            // 处理响应
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '生成测试用例请求失败');
            }
            
            const data = await response.json();
            
            // 显示生成结果
            displayGenerationResult(data.test_cases_json);
        } catch (error) {
            console.error('生成测试用例过程出错:', error);
            alert(`生成失败: ${error.message}`);
        } finally {
            // 隐藏加载动画
            loadingGen.style.display = 'none';
        }
    });
    
    // 评估测试用例按钮点击事件
    evaluateBtn.addEventListener('click', async function() {
        // 验证输入
        if (!llmTestCasesTextarea.value) {
            alert('请输入LLM生成的测试用例');
            llmTestCasesTextarea.focus();
            return;
        }
        
        if (!goldenTestCasesTextarea.value) {
            alert('请输入标准测试用例');
            goldenTestCasesTextarea.focus();
            return;
        }
        
        // 显示加载动画
        loadingEval.style.display = 'block';
        resultContainerMd.style.display = 'none';
        
        // 准备请求数据
        const requestData = {
            llm_test_cases: llmTestCasesTextarea.value,
            golden_test_cases: goldenTestCasesTextarea.value
        };
        
        try {
            // 先获取JSON格式评估结果
            const jsonResponse = await fetch('/evaluate-test-cases-only', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });
            
            // 处理JSON响应
            if (!jsonResponse.ok) {
                const errorData = await jsonResponse.json();
                throw new Error(errorData.detail || '评估测试用例请求失败');
            }
            
            const jsonData = await jsonResponse.json();
            
            // 再获取Markdown格式评估报告
            const mdResponse = await fetch('/generate-markdown-report', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });
            
            // 处理Markdown响应
            if (!mdResponse.ok) {
                const errorData = await mdResponse.json();
                throw new Error(errorData.detail || '生成评估报告请求失败');
            }
            
            const mdData = await mdResponse.json();
            
            // 将JSON评估结果添加到Markdown报告中
            const enhancedMarkdown = mdData.report_markdown + 
                '\n\n## 原始评估数据 (JSON格式)\n\n```json\n' + 
                JSON.stringify(JSON.parse(jsonData.evaluation_json), null, 2) + 
                '\n```';
            
            // 显示增强的Markdown评估报告
            displayMarkdownReport(enhancedMarkdown);
        } catch (error) {
            console.error('评估过程出错:', error);
            alert(`评估失败: ${error.message}`);
        } finally {
            // 隐藏加载动画
            loadingEval.style.display = 'none';
        }
    });
    
    // 复制结果按钮点击事件
    copyResultBtn.addEventListener('click', function() {
        const textToCopy = testCasesResult.textContent;
        
        navigator.clipboard.writeText(textToCopy)
            .then(() => {
                const originalText = copyResultBtn.innerText;
                copyResultBtn.innerText = '已复制!';
                setTimeout(() => {
                    copyResultBtn.innerText = originalText;
                }, 2000);
            })
            .catch(err => {
                console.error('复制失败:', err);
                alert('复制到剪贴板失败，请手动复制。');
            });
    });
    
    // 复制Markdown按钮点击事件
    copyMdBtn.addEventListener('click', function() {
        const textToCopy = markdownReport.getAttribute('data-raw-markdown') || '';
        
        navigator.clipboard.writeText(textToCopy)
            .then(() => {
                const originalText = copyMdBtn.innerText;
                copyMdBtn.innerText = '已复制!';
                setTimeout(() => {
                    copyMdBtn.innerText = originalText;
                }, 2000);
            })
            .catch(err => {
                console.error('复制失败:', err);
                alert('复制到剪贴板失败，请手动复制。');
            });
    });
    
    // 显示生成结果函数
    function displayGenerationResult(jsonString) {
        try {
            // 尝试格式化JSON
            const jsonObject = JSON.parse(jsonString);
            const formattedJson = JSON.stringify(jsonObject, null, 2);
            
            // 设置结果内容
            testCasesResult.textContent = formattedJson;
            
            // 应用代码高亮
            hljs.highlightElement(testCasesResult);
            
            // 显示结果容器
            resultContainerGen.style.display = 'block';
            
            // 自动填充评估表单中的LLM测试用例
            llmTestCasesTextarea.value = formattedJson;
        } catch (error) {
            console.error('解析JSON失败:', error);
            
            // 如果解析失败，直接显示原始内容
            testCasesResult.textContent = jsonString;
            resultContainerGen.style.display = 'block';
        }
    }
    
    // 显示Markdown评估报告函数
    function displayMarkdownReport(markdownString) {
        try {
            // 将Markdown渲染为HTML
            const htmlContent = marked.parse(markdownString);
            
            // 保存原始Markdown以便复制
            markdownReport.setAttribute('data-raw-markdown', markdownString);
            
            // 设置Markdown报告内容
            markdownReport.innerHTML = htmlContent;
            
            // 应用代码高亮（如果报告中包含代码块）
            document.querySelectorAll('#markdown-report pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
            
            // 显示Markdown报告容器
            resultContainerMd.style.display = 'block';
        } catch (error) {
            console.error('解析Markdown失败:', error);
            
            // 如果解析失败，直接显示原始内容
            markdownReport.textContent = markdownString;
            resultContainerMd.style.display = 'block';
        }
    }
}); 