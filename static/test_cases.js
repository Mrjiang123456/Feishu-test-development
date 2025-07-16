document.addEventListener('DOMContentLoaded', function() {
    // 页签切换已由Bootstrap 5自动处理，不需要手动添加事件处理程序
    // 但我们可以添加一些额外的处理逻辑
    
    // 获取所有标签页，以便根据URL参数激活正确的标签页
    const tabGenerate = document.getElementById('tab-generate');
    const tabEvaluate = document.getElementById('tab-evaluate');
    const generateSection = document.getElementById('generate-section');
    const evaluateSection = document.getElementById('evaluate-section');
    
    // 根据URL参数选择初始标签页
    const urlParams = new URLSearchParams(window.location.search);
    const activeTab = urlParams.get('tab');
    
    if (activeTab === 'evaluate') {
        // 通过Bootstrap API激活评估标签页
        const evaluateTabTrigger = new bootstrap.Tab(tabEvaluate);
        evaluateTabTrigger.show();
    }
    
    // 添加标签页切换事件监听器，以便更新URL
    tabGenerate.addEventListener('shown.bs.tab', function(event) {
        history.replaceState(null, null, '?tab=generate');
    });
    
    tabEvaluate.addEventListener('shown.bs.tab', function(event) {
        history.replaceState(null, null, '?tab=evaluate');
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
    const downloadMdBtn = document.getElementById('download-md-btn');
    
    // 生成测试用例按钮点击事件
    generateBtn.addEventListener('click', async function() {
        // 验证输入
        if (!docTokenGenInput.value) {
            showToast('请输入飞书文档Token', 'danger');
            docTokenGenInput.focus();
            return;
        }
        
        if (!userTokenGenInput.value) {
            showToast('请输入用户访问Token', 'danger');
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
            showToast(`生成失败: ${error.message}`, 'danger');
        } finally {
            // 隐藏加载动画
            loadingGen.style.display = 'none';
        }
    });
    
    // 评估测试用例按钮点击事件
    evaluateBtn.addEventListener('click', async function() {
        // 验证输入
        if (!llmTestCasesTextarea.value) {
            showToast('请输入LLM生成的测试用例', 'danger');
            llmTestCasesTextarea.focus();
            return;
        }
        
        if (!goldenTestCasesTextarea.value) {
            showToast('请输入标准测试用例', 'danger');
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
            showToast('评估报告生成成功', 'success');
        } catch (error) {
            console.error('评估过程出错:', error);
            showToast(`评估失败: ${error.message}`, 'danger');
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
                showToast('已复制到剪贴板', 'success');
                
                // 按钮效果
                const originalText = copyResultBtn.innerHTML;
                copyResultBtn.innerHTML = '<i class="fas fa-check me-1"></i> 已复制';
                copyResultBtn.classList.add('btn-success');
                copyResultBtn.classList.remove('btn-outline-primary');
                
                setTimeout(() => {
                    copyResultBtn.innerHTML = originalText;
                    copyResultBtn.classList.remove('btn-success');
                    copyResultBtn.classList.add('btn-outline-primary');
                }, 2000);
            })
            .catch(err => {
                console.error('复制失败:', err);
                showToast('复制失败，请手动复制', 'danger');
            });
    });
    
    // 复制Markdown按钮点击事件
    copyMdBtn.addEventListener('click', function() {
        const textToCopy = markdownReport.getAttribute('data-raw-markdown') || '';
        
        navigator.clipboard.writeText(textToCopy)
            .then(() => {
                showToast('已复制到剪贴板', 'success');
                
                // 按钮效果
                const originalText = copyMdBtn.innerHTML;
                copyMdBtn.innerHTML = '<i class="fas fa-check me-1"></i> 已复制';
                copyMdBtn.classList.add('btn-success');
                copyMdBtn.classList.remove('btn-outline-primary');
                
                setTimeout(() => {
                    copyMdBtn.innerHTML = originalText;
                    copyMdBtn.classList.remove('btn-success');
                    copyMdBtn.classList.add('btn-outline-primary');
                }, 2000);
            })
            .catch(err => {
                console.error('复制失败:', err);
                showToast('复制失败，请手动复制', 'danger');
            });
    });
    
    // 下载Markdown报告按钮点击事件
    if (downloadMdBtn) {
        downloadMdBtn.addEventListener('click', function() {
            const markdown = markdownReport.getAttribute('data-raw-markdown') || '';
            if (!markdown) {
                showToast('没有可下载的报告内容', 'warning');
                return;
            }
            
            const blob = new Blob([markdown], {type: 'text/markdown'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            
            // 生成文件名
            const date = new Date();
            const timestamp = date.toISOString().replace(/[:.]/g, '-').substring(0, 19);
            const filename = `test_case_evaluation_report_${timestamp}.md`;
            
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            
            // 清理
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 0);
            
            // 按钮效果
            const originalText = downloadMdBtn.innerHTML;
            downloadMdBtn.innerHTML = '<i class="fas fa-check me-1"></i> 已下载';
            downloadMdBtn.classList.add('btn-success');
            downloadMdBtn.classList.remove('btn-outline-secondary');
            
            setTimeout(() => {
                downloadMdBtn.innerHTML = originalText;
                downloadMdBtn.classList.remove('btn-success');
                downloadMdBtn.classList.add('btn-outline-secondary');
            }, 2000);
            
            showToast(`报告已下载: ${filename}`, 'success');
        });
    }
    
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
            
            // 显示切换到评估标签页的提示
            showToast('测试用例生成成功！已自动填充到评估表单，可以点击"评估测试用例"标签页进行评估', 'success');
        } catch (error) {
            console.error('解析JSON失败:', error);
            
            // 如果解析失败，直接显示原始内容
            testCasesResult.textContent = jsonString;
            resultContainerGen.style.display = 'block';
            showToast('生成的内容不是有效的JSON格式', 'warning');
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
            
            // 显示结果容器
            resultContainerMd.style.display = 'block';
        } catch (error) {
            console.error('解析Markdown失败:', error);
            
            // 如果解析失败，直接显示原始内容
            markdownReport.innerHTML = `<div class="alert alert-warning">
                <h5><i class="fas fa-exclamation-triangle me-2"></i>Markdown解析失败</h5>
                <p>以下是原始内容:</p>
                <pre class="bg-light p-3 mt-3">${markdownString}</pre>
            </div>`;
            resultContainerMd.style.display = 'block';
        }
    }
    
    // 显示Toast消息的辅助函数
    function showToast(message, type = 'info') {
        // 检查是否已经存在toast容器，如果没有则创建
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'position-fixed bottom-0 end-0 p-3';
            toastContainer.style.zIndex = '1050';
            document.body.appendChild(toastContainer);
        }
        
        // 创建toast元素ID
        const toastId = 'toast-' + Date.now();
        
        // 创建toast HTML
        const toastHTML = `
            <div id="${toastId}" class="toast align-items-center text-white bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        
        // 添加toast到容器
        toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        
        // 初始化bootstrap toast
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, {
            animation: true,
            autohide: true,
            delay: 3000
        });
        
        // 显示toast
        toast.show();
        
        // Toast关闭后移除元素
        toastElement.addEventListener('hidden.bs.toast', function() {
            toastElement.remove();
        });
    }
}); 
