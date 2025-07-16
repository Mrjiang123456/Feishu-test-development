document.addEventListener('DOMContentLoaded', function() {
    // 获取元素引用
    const evaluateBtn = document.getElementById('evaluate-btn');
    const loadingElem = document.getElementById('loading');
    const reportContainer = document.getElementById('report-container');
    const humanCases = document.getElementById('human-cases');
    const llmCases = document.getElementById('llm-cases');
    const copyReportBtn = document.getElementById('copy-report-btn');
    const downloadReportBtn = document.getElementById('download-report-btn');
    const markdownContent = document.getElementById('markdown-content');
    
    // 添加评估按钮事件监听器
    if (evaluateBtn) {
        evaluateBtn.addEventListener('click', async function() {
            // 验证输入
            if (!llmCases.value) {
                showToast('请输入LLM生成的测试用例', 'danger');
                return;
            }
            
            // 显示加载状态
            loadingElem.style.display = 'block';
            reportContainer.style.display = 'none';
            
            try {
                // 读取人工测试用例（黄金标准）和LLM测试用例
                const goldenCasesText = humanCases.value;
                const aiCasesText = llmCases.value;
                
                // 验证JSON格式
                try {
                    if (aiCasesText) JSON.parse(aiCasesText);
                    if (goldenCasesText) JSON.parse(goldenCasesText);
                } catch (e) {
                    showToast('JSON格式错误: ' + e.message, 'danger');
                    loadingElem.style.display = 'none';
                    return;
                }
                
                // 准备请求数据
                const requestData = {
                    ai_test_cases: aiCasesText
                };
                
                // 如果有人工测试用例，添加到请求中
                if (goldenCasesText) {
                    requestData.golden_test_cases = goldenCasesText;
                }
                
                // 发送评估请求
                const response = await fetch('/compare-test-cases', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(requestData)
                });
                
                const result = await response.json();
                
                // 隐藏加载状态
                loadingElem.style.display = 'none';
                
                if (result.success) {
                    // 显示评估结果
                    if (result.report) {
                        markdownContent.innerHTML = marked.parse(result.report);
                        // 保存原始Markdown文本，用于复制和下载
                        markdownContent.setAttribute('data-markdown', result.report);
                    } else if (result.evaluation_result) {
                        markdownContent.innerHTML = '<h2>评估结果</h2><pre class="bg-light p-3 rounded">' + 
                            JSON.stringify(result.evaluation_result, null, 2) + '</pre>';
                    } else {
                        markdownContent.innerHTML = '<div class="alert alert-info">评估完成，查看详细报告请点击下方链接</div>';
                    }
                    
                    // 添加报告链接
                    if (result.files) {
                        const linksHTML = `
                            <div class="mt-4 p-3 border rounded bg-light">
                                <h5 class="mb-3"><i class="fas fa-link me-2"></i>报告文件</h5>
                                <div class="list-group">
                                    <a href="${result.files.report_md}" target="_blank" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                                        <div><i class="fas fa-file-alt me-2"></i>Markdown报告</div>
                                        <i class="fas fa-external-link-alt"></i>
                                    </a>
                                    <a href="${result.files.report_json}" target="_blank" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                                        <div><i class="fas fa-file-code me-2"></i>JSON报告</div>
                                        <i class="fas fa-external-link-alt"></i>
                                    </a>
                                </div>
                            </div>
                        `;
                        markdownContent.innerHTML += linksHTML;
                    }
                    
                    reportContainer.style.display = 'block';
                    
                    // 保存黄金标准测试用例（如果提供了）
                    if (goldenCasesText) {
                        try {
                            await saveGoldenCases(goldenCasesText);
                            showToast('黄金标准测试用例已自动保存', 'success');
                        } catch (e) {
                            console.error('保存黄金标准测试用例失败:', e);
                        }
                    }
                } else {
                    // 显示错误信息
                    markdownContent.innerHTML = `
                        <div class="alert alert-danger">
                            <h5><i class="fas fa-exclamation-triangle me-2"></i>评估失败</h5>
                            <p class="mb-0">${result.error || '未知错误'}</p>
                        </div>
                    `;
                    reportContainer.style.display = 'block';
                }
            } catch (error) {
                // 隐藏加载状态并显示错误
                loadingElem.style.display = 'none';
                markdownContent.innerHTML = `
                    <div class="alert alert-danger">
                        <h5><i class="fas fa-exclamation-triangle me-2"></i>请求错误</h5>
                        <p class="mb-0">${error.message}</p>
                    </div>
                `;
                reportContainer.style.display = 'block';
            }
        });
    }
    
    // 添加复制报告按钮事件
    if (copyReportBtn) {
        copyReportBtn.addEventListener('click', function() {
            const markdown = markdownContent.getAttribute('data-markdown') || markdownContent.innerText;
            
            navigator.clipboard.writeText(markdown)
                .then(() => {
                    showToast('报告已复制到剪贴板', 'success');
                    
                    // 按钮效果
                    const originalText = copyReportBtn.innerHTML;
                    copyReportBtn.innerHTML = '<i class="fas fa-check me-1"></i> 已复制';
                    copyReportBtn.classList.add('btn-success');
                    copyReportBtn.classList.remove('btn-outline-primary');
                    
                    setTimeout(() => {
                        copyReportBtn.innerHTML = originalText;
                        copyReportBtn.classList.remove('btn-success');
                        copyReportBtn.classList.add('btn-outline-primary');
                    }, 2000);
                })
                .catch(err => {
                    console.error('复制失败:', err);
                    showToast('复制失败，请手动复制', 'danger');
                });
        });
    }
    
    // 添加下载报告按钮事件
    if (downloadReportBtn) {
        downloadReportBtn.addEventListener('click', function() {
            const markdown = markdownContent.getAttribute('data-markdown') || markdownContent.innerText;
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
            const originalText = downloadReportBtn.innerHTML;
            downloadReportBtn.innerHTML = '<i class="fas fa-check me-1"></i> 已下载';
            downloadReportBtn.classList.add('btn-success');
            downloadReportBtn.classList.remove('btn-outline-secondary');
            
            setTimeout(() => {
                downloadReportBtn.innerHTML = originalText;
                downloadReportBtn.classList.remove('btn-success');
                downloadReportBtn.classList.add('btn-outline-secondary');
            }, 2000);
        });
    }
    
    // 保存黄金标准测试用例的辅助函数
    async function saveGoldenCases(goldenCasesText) {
        try {
            const response = await fetch('/api/save-golden-cases', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    golden_test_cases: goldenCasesText
                })
            });
            
            const result = await response.json();
            if (result.success) {
                console.log('黄金标准测试用例已保存');
                return true;
            } else {
                console.error('保存黄金标准测试用例失败:', result.error);
                return false;
            }
        } catch (error) {
            console.error('保存黄金标准测试用例时发生错误:', error);
            throw error;
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
