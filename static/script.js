document.addEventListener('DOMContentLoaded', function() {
    // 获取DOM元素
    const docTokenInput = document.getElementById('doc-token');
    const userTokenInput = document.getElementById('user-token');
    const humanCasesTextarea = document.getElementById('human-cases');
    const llmCasesTextarea = document.getElementById('llm-cases');
    const evaluateBtn = document.getElementById('evaluate-btn');
    const loadingElement = document.getElementById('loading');
    const reportContainer = document.getElementById('report-container');
    
    // 评估按钮点击事件
    evaluateBtn.addEventListener('click', async function() {
        // 验证输入
        if (!docTokenInput.value) {
            alert('请输入飞书文档Token');
            docTokenInput.focus();
            return;
        }
        
        if (!userTokenInput.value) {
            alert('请输入用户访问Token');
            userTokenInput.focus();
            return;
        }
        
        if (!humanCasesTextarea.value) {
            alert('请输入人工编写的测试用例');
            humanCasesTextarea.focus();
            return;
        }
        
        if (!llmCasesTextarea.value) {
            alert('请输入LLM生成的测试用例');
            llmCasesTextarea.focus();
            return;
        }
        
        // 显示加载动画
        loadingElement.style.display = 'block';
        reportContainer.style.display = 'none';
        
        // 准备请求数据
        const requestData = {
            doc_token: docTokenInput.value,
            user_access_token: userTokenInput.value,
            human_cases_text: humanCasesTextarea.value,
            llm_cases_text: llmCasesTextarea.value
        };
        
        try {
            // 发送评估请求
            const response = await fetch('/evaluate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });
            
            // 处理响应
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '评估请求失败');
            }
            
            const data = await response.json();
            
            // 显示评估结果
            displayResults(data);
        } catch (error) {
            console.error('评估过程出错:', error);
            alert(`评估失败: ${error.message}`);
        } finally {
            // 隐藏加载动画
            loadingElement.style.display = 'none';
        }
    });
    
    // 显示结果函数
    function displayResults(data) {
        // data 的格式是 { "report_markdown": "..." }
        const markdownContent = data.report_markdown;
        
        // 使用 marked.js 将 Markdown 字符串转换为 HTML
        const renderedHtml = marked.parse(markdownContent);
        
        // 将转换后的 HTML 设置为容器的内容
        reportContainer.innerHTML = renderedHtml;
        
        // 让容器可见
        reportContainer.style.display = 'block';
        
        // 滚动到结果区域
        reportContainer.scrollIntoView({ behavior: 'smooth' });
    }
}); 