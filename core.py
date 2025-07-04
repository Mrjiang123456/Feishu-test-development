import os
import json
import glob
import aiohttp
import asyncio
import argparse
import traceback
from config import (
    FORMATTED_AI_CASES_FILE, 
    FORMATTED_GOLDEN_CASES_FILE, 
    get_report_file_paths,
    API_URL,
    MODEL_NAME
)
from logger import log, log_error, start_logging, end_logging
from formatter import format_test_cases
from evaluator import evaluate_test_cases, generate_markdown_report

# --- 主程序 ---
async def async_main(ai_cases_data=None, golden_cases_data=None):
    """
    主程序的异步版本
    
    :param ai_cases_data: AI生成的测试用例数据（可选），JSON字符串
    :param golden_cases_data: 黄金标准测试用例数据（可选），JSON字符串
    """
    start_logging()
    log("启动测试用例评测流程", important=True)
    
    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.1)
    
    # 获取带有当前时间戳的报告文件路径
    report_file, report_json_file = get_report_file_paths()
    log(f"本次评测报告将保存为: {report_file}", important=True)
    log(f"本次评测JSON结果将保存为: {report_json_file}", important=True)
    
    # 记录系统环境信息，用于诊断
    try:
        import platform
        import sys
        env_info = {
            "platform": platform.platform(),
            "python_version": sys.version,
            "api_url": API_URL,
            "model": MODEL_NAME,
        }
        log(f"系统环境信息: {json.dumps(env_info, ensure_ascii=False)}")
    except Exception as e:
        log_error("获取系统环境信息失败", e)
    
    # 1. 加载用例数据
    try:
        # 如果没有提供AI测试用例数据，则从文件读取
        if ai_cases_data is None:
            log("从文件加载AI测试用例", important=True)
            try:
                with open(FORMATTED_AI_CASES_FILE, 'r', encoding='utf-8') as f:
                    ai_cases_raw_text = f.read()
                    log(f"AI测试用例文件大小: {len(ai_cases_raw_text)} 字节")
                    
                    # 尝试检测文件编码
                    import chardet
                    encoding_result = chardet.detect(ai_cases_raw_text[:1000].encode())
                    log(f"检测到的文件编码: {encoding_result}")
            except FileNotFoundError:
                error_info = {
                    "file_path": os.path.abspath(FORMATTED_AI_CASES_FILE),
                    "current_dir": os.getcwd(),
                    "available_files": os.listdir(os.path.dirname(FORMATTED_AI_CASES_FILE)) if os.path.exists(os.path.dirname(FORMATTED_AI_CASES_FILE)) else "目录不存在"
                }
                log_error(f"找不到AI测试用例文件 {FORMATTED_AI_CASES_FILE}", error_info)
                end_logging()
                return {
                    "success": False,
                    "error": f"找不到AI测试用例文件: {FORMATTED_AI_CASES_FILE}",
                    "error_details": error_info
                }
            except Exception as e:
                log_error(f"读取AI测试用例文件 {FORMATTED_AI_CASES_FILE} 失败", e)
                end_logging()
                return {
                    "success": False,
                    "error": f"读取AI测试用例文件失败: {str(e)}"
                }
        else:
            log("使用传入的AI测试用例数据", important=True)
            ai_cases_raw_text = ai_cases_data
        
        # 如果没有提供黄金标准测试用例数据，则从文件读取
        if golden_cases_data is None:
            log("从文件加载黄金标准测试用例", important=True)
            # 查找goldenset文件夹中的所有golden_cases*.json文件
            golden_files = glob.glob("goldenset/golden_cases*.json")
            
            if not golden_files:
                error_info = {
                    "search_pattern": "goldenset/golden_cases*.json",
                    "current_dir": os.getcwd(),
                    "goldenset_exists": os.path.exists("goldenset"),
                    "goldenset_files": os.listdir("goldenset") if os.path.exists("goldenset") else "目录不存在"
                }
                log_error("在goldenset文件夹中找不到黄金标准测试用例文件", error_info)
                end_logging()
                return {
                    "success": False,
                    "error": "在goldenset文件夹中找不到黄金标准测试用例文件",
                    "error_details": error_info
                }
            
            # 默认使用第一个找到的文件
            golden_file = golden_files[0]
            log(f"使用黄金标准测试用例文件: {golden_file}", important=True)
            
            try:
                with open(golden_file, 'r', encoding='utf-8') as f:
                    golden_cases_raw_text = f.read()
                    log(f"黄金标准测试用例文件大小: {len(golden_cases_raw_text)} 字节")
            except FileNotFoundError:
                error_info = {
                    "file_path": os.path.abspath(golden_file),
                    "current_dir": os.getcwd()
                }
                log_error(f"找不到黄金标准测试用例文件 {golden_file}", error_info)
                end_logging()
                return {
                    "success": False,
                    "error": f"找不到黄金标准测试用例文件: {golden_file}",
                    "error_details": error_info
                }
            except Exception as e:
                log_error(f"读取黄金标准测试用例文件 {golden_file} 失败", e)
                end_logging()
                return {
                    "success": False,
                    "error": f"读取黄金标准测试用例文件失败: {str(e)}"
                }
        else:
            log("使用传入的黄金标准测试用例数据", important=True)
            golden_cases_raw_text = golden_cases_data
        
        log(f"成功加载测试用例数据", important=True)
    except Exception as e:
        log_error("加载数据时发生未知错误", e)
        end_logging()
        return {
            "success": False,
            "error": f"加载数据时发生未知错误: {str(e)}",
            "traceback": traceback.format_exc()
        }
    
    # 确保输出目录存在
    try:
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        os.makedirs(os.path.dirname(report_json_file), exist_ok=True)
    except Exception as e:
        log_error("创建输出目录失败", e)
        end_logging()
        return {
            "success": False,
            "error": f"创建输出目录失败: {str(e)}"
        }
    
    # 创建aiohttp会话，设置超时和重试策略
    timeout = aiohttp.ClientTimeout(total=300)  # 5分钟总超时
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
    
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        try:
            # 2. 格式化测试用例
            log("开始格式化测试用例", important=True)
            
            # 格式化AI测试用例
            formatted_ai_cases = await format_test_cases(session, ai_cases_raw_text, "AI")
            if not formatted_ai_cases:
                log_error("格式化AI测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "格式化AI测试用例失败"
                }
            
            # 保存格式化后的AI测试用例
            try:
                os.makedirs(os.path.dirname(FORMATTED_AI_CASES_FILE), exist_ok=True)
                with open(FORMATTED_AI_CASES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(formatted_ai_cases, f, ensure_ascii=False, indent=2)
                log(f"格式化后的AI测试用例已保存到 {FORMATTED_AI_CASES_FILE}", important=True)
            except Exception as e:
                log_error(f"保存格式化后的AI测试用例到 {FORMATTED_AI_CASES_FILE} 失败", e)
                # 继续执行，不中断流程
            
            # 格式化黄金标准测试用例
            formatted_golden_cases = await format_test_cases(session, golden_cases_raw_text, "Golden")
            if not formatted_golden_cases:
                log_error("格式化黄金标准测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "格式化黄金标准测试用例失败"
                }
            
            # 保存格式化后的黄金标准测试用例
            try:
                os.makedirs(os.path.dirname(FORMATTED_GOLDEN_CASES_FILE), exist_ok=True)
                with open(FORMATTED_GOLDEN_CASES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(formatted_golden_cases, f, ensure_ascii=False, indent=2)
                log(f"格式化后的黄金标准测试用例已保存到 {FORMATTED_GOLDEN_CASES_FILE}", important=True)
            except Exception as e:
                log_error(f"保存格式化后的黄金标准测试用例到 {FORMATTED_GOLDEN_CASES_FILE} 失败", e)
                # 继续执行，不中断流程
            
            # 3. 评测测试用例
            log("开始评测测试用例", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.1)
            
            evaluation_result = await evaluate_test_cases(session, formatted_ai_cases, formatted_golden_cases)
            if not evaluation_result:
                log_error("评测测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "评测测试用例失败"
                }
            
            # 保存JSON格式的评测结果
            try:
                with open(report_json_file, 'w', encoding='utf-8') as f:
                    json.dump(evaluation_result, f, ensure_ascii=False, indent=2)
                log(f"JSON格式的评测结果已保存到 {report_json_file}", important=True)
                # 添加小延迟，确保日志顺序
                await asyncio.sleep(0.1)
            except Exception as e:
                log_error(f"保存JSON格式的评测结果到 {report_json_file} 失败", e)
                # 继续执行，不中断流程
            
            # 4. 生成Markdown格式的报告
            log("开始生成Markdown格式报告", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.1)
            
            markdown_report = await generate_markdown_report(session, evaluation_result)
            
            # 处理可能的Markdown报告格式问题
            if markdown_report:
                # 如果是字典格式的结果，提取文本内容
                if isinstance(markdown_report, dict) and "text" in markdown_report:
                    markdown_report = markdown_report["text"]
                
                # 清理Markdown报告，确保没有"markdown"前缀
                if markdown_report.strip().startswith("markdown"):
                    markdown_report = markdown_report.strip().replace("markdown", "", 1).strip()
                    log("已删除最终报告中的'markdown'前缀", important=True)
                
                # 处理可能的空行前缀
                if markdown_report.startswith("\n") and not markdown_report.strip().startswith("#"):
                    markdown_report = markdown_report.lstrip()
                    log("已删除最终报告中的前导空行", important=True)
                
                # 处理可能包含的代码块标记
                if "```markdown" in markdown_report:
                    # 提取代码块内容
                    try:
                        markdown_report = markdown_report.split("```markdown")[1].split("```")[0].strip()
                        log("已从markdown代码块中提取内容", important=True)
                    except:
                        log_error("处理markdown代码块失败，保留原始内容")
                elif "```" in markdown_report and not "```json" in markdown_report:
                    # 可能是通用代码块
                    try:
                        parts = markdown_report.split("```")
                        if len(parts) >= 3 and len(parts[0].strip()) == 0:
                            # 如果第一个分割是空的，取第二个部分（代码块内容）
                            markdown_report = parts[1].strip()
                            log("已从代码块中提取内容", important=True)
                    except:
                        log_error("处理代码块失败，保留原始内容")
                
                # 检查并修复Mermaid图表
                try:
                    # 确保mermaid图表格式正确
                    if "```mermaid" not in markdown_report:
                        # 检查是否包含Mermaid图表关键词
                        chart_keywords = [
                            "flowchart ", "graph ", "pie", "piechart", "bar", "barchart",
                            "sequenceDiagram", "classDiagram", "stateDiagram", "gantt"
                        ]
                        
                        # 检查是否需要修复图表语法
                        needs_fix = False
                        for keyword in chart_keywords:
                            if f"\n{keyword}" in markdown_report:
                                needs_fix = True
                                break
                        
                        if needs_fix:
                            # 更新图表语法 - 使用更现代的命名
                            replacements = {
                                "graph TD": "flowchart TD",
                                "graph LR": "flowchart LR",
                                "pie": "piechart",
                                "bar": "barchart"
                            }
                            
                            for old, new in replacements.items():
                                markdown_report = markdown_report.replace(f"\n{old}", f"\n{new}")
                            
                            # 修复图表结构
                            for chart_type in chart_keywords:
                                pattern = f"\n{chart_type}"
                                if pattern in markdown_report:
                                    parts = markdown_report.split(pattern)
                                    fixed_parts = []
                                    for i, part in enumerate(parts):
                                        if i == 0:
                                            fixed_parts.append(part)
                                        else:
                                            # 查找这部分内容的结束位置
                                            lines = part.split("\n")
                                            end_index = 0
                                            for j, line in enumerate(lines):
                                                if line.strip() == "" and j > 0:
                                                    end_index = j
                                                    break
                                            
                                            if end_index > 0:
                                                chart_content = "\n".join(lines[:end_index])
                                                rest_content = "\n".join(lines[end_index:])
                                                fixed_parts.append(f"\n```mermaid\n{chart_type}{chart_content}\n```\n{rest_content}")
                                            else:
                                                fixed_parts.append(f"\n```mermaid\n{chart_type}{part}\n```")
                                    
                                    markdown_report = "".join(fixed_parts)
                            
                            log("已修复Mermaid图表语法", important=True)
                            
                            # 第二阶段修复 - 确保使用通用图表语法
                            log("正在将图表转换为更通用的语法格式...", important=True)
                            backward_replacements = {
                                "flowchart TD": "graph TD",
                                "flowchart LR": "graph LR",
                                "piechart": "pie",
                                "barchart": "bar"
                            }
                            
                            for new_syntax, old_syntax in backward_replacements.items():
                                markdown_report = markdown_report.replace(new_syntax, old_syntax)
                            
                            log("已完成图表语法通用性转换", important=True)
                except Exception as e:
                    log_error(f"修复Mermaid图表时出错: {e}")
                    # 继续处理，不中断流程
                    
                # 更新页脚为实时时间和自定义评估中心名称
                try:
                    from datetime import datetime
                    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                    new_footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"
                    
                    # 查找并替换原有页脚
                    import re
                    footer_pattern = r"\*\*生成时间：.*评估中心\*\*"
                    if re.search(footer_pattern, markdown_report):
                        markdown_report = re.sub(footer_pattern, new_footer, markdown_report)
                    else:
                        # 如果没有找到页脚，则添加到报告末尾
                        markdown_report = markdown_report.rstrip() + "\n\n---\n" + new_footer + "\n"
                    
                    log("已更新报告页脚为实时时间和自定义评估中心名称", important=True)
                except Exception as e:
                    log_error(f"更新页脚时出错: {e}")
                    # 继续处理，不中断流程
            
            # 保存Markdown格式的报告
            try:
                with open(report_file, 'w', encoding='utf-8') as f:
                    f.write(markdown_report)
                log(f"Markdown格式的评测报告已保存到 {report_file}", important=True)
                # 添加小延迟，确保日志顺序
                await asyncio.sleep(0.1)
            except Exception as e:
                log_error(f"保存Markdown格式的评测报告到 {report_file} 失败", e)
                # 继续执行，不中断流程
            
            log("测试用例评测流程完成！", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.1)
            end_logging()
            
            return {
                "success": True,
                "evaluation_result": evaluation_result,
                "markdown_report": markdown_report,
                "files": {
                    "report_md": report_file,
                    "report_json": report_json_file
                }
            }
        except aiohttp.ClientError as e:
            log_error("API请求错误", e)
            end_logging()
            return {
                "success": False,
                "error": f"API请求错误: {str(e)}",
                "error_type": "network_error"
            }
        except asyncio.TimeoutError as e:
            log_error("API请求超时", {"error_message": "请求超时，可能是网络问题或服务器响应时间过长"})
            end_logging()
            return {
                "success": False,
                "error": "API请求超时，请检查网络连接或稍后重试",
                "error_type": "timeout"
            }
        except Exception as e:
            log_error("执行过程中发生未知错误", e)
            end_logging()
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "error_type": "unknown"
            }

def main(ai_cases_file=None, golden_cases_file=None):
    """
    兼容原有入口点的主函数
    
    :param ai_cases_file: AI测试用例文件路径（可选）
    :param golden_cases_file: 黄金标准测试用例文件路径（可选）
    """
    # 如果是Windows平台，需要显式设置事件循环策略
    if os.name == 'nt':
        log("设置Windows事件循环策略")
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    ai_cases_data = None
    golden_cases_data = None
    
    # 如果提供了文件路径，则从指定文件读取数据
    if ai_cases_file:
        try:
            with open(ai_cases_file, 'r', encoding='utf-8') as f:
                ai_cases_data = f.read()
            log(f"从文件 {ai_cases_file} 读取AI测试用例数据")
        except Exception as e:
            log_error(f"读取AI测试用例文件 {ai_cases_file} 失败", e)
            return {"success": False, "error": f"读取AI测试用例文件失败: {e}"}
    
    if golden_cases_file:
        try:
            with open(golden_cases_file, 'r', encoding='utf-8') as f:
                golden_cases_data = f.read()
            log(f"从文件 {golden_cases_file} 读取黄金标准测试用例数据")
        except Exception as e:
            log_error(f"读取黄金标准测试用例文件 {golden_cases_file} 失败", e)
            return {"success": False, "error": f"读取黄金标准测试用例文件失败: {e}"}
    
    # 运行异步主函数
    return asyncio.run(async_main(ai_cases_data, golden_cases_data)) 