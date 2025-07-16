import os
import json
import glob
import aiohttp
import asyncio
import argparse
import traceback
import uuid  # 添加uuid模块导入
from config import (
    FORMATTED_AI_CASES_FILE,
    FORMATTED_GOLDEN_CASES_FILE,
    get_report_file_paths,
    API_URL,
    MODEL_NAME,
    AIOHTTP_TIMEOUT,
    AIOHTTP_CONNECTOR_LIMIT,
    AIOHTTP_CONNECTOR_TTL,
    MAX_CONCURRENT_REQUESTS
)
from logger import log, log_error, start_logging, end_logging
from formatter import format_test_cases
from evaluator import evaluate_test_cases, generate_markdown_report, evaluate_and_generate_report
from llm_api import clear_cache  # 导入清除缓存函数


# --- 主程序 ---
async def async_main(ai_cases_data=None, golden_cases_data=None, is_iteration=False, prev_iteration_data=None):
    """
    主程序的异步版本

    :param ai_cases_data: AI生成的测试用例数据（可选），JSON字符串
    :param golden_cases_data: 黄金标准测试用例数据（可选），JSON字符串
    :param is_iteration: 是否启用迭代前后对比功能
    :param prev_iteration_data: 上一次迭代的测试用例数据（可选），JSON字符串
    """
    # 清除之前的LLM API调用缓存，确保每次评测都是全新的
    clear_cache()

    # 生成会话唯一标识符，避免文件缓存问题
    session_id = str(uuid.uuid4())
    formatted_ai_cases_file = FORMATTED_AI_CASES_FILE.replace('.json', f'_{session_id}.json')
    formatted_golden_cases_file = FORMATTED_GOLDEN_CASES_FILE.replace('.json', f'_{session_id}.json')
    
    # 如果启用迭代对比，创建上一次迭代的格式化文件路径
    if is_iteration and prev_iteration_data:
        formatted_prev_iteration_file = FORMATTED_AI_CASES_FILE.replace('.json', f'_prev_{session_id}.json')
    else:
        formatted_prev_iteration_file = None

    start_logging()
    log("启动测试用例评测流程", important=True)
    if is_iteration:
        log("已启用迭代前后对比功能", important=True)

    # 添加小延迟，确保日志顺序
    await asyncio.sleep(0.05)

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
        # 并行加载AI测试用例、黄金标准测试用例和上一次迭代测试用例（如果启用）
        async def load_ai_cases():
            if ai_cases_data is None:
                log("从文件加载AI测试用例", important=True)
                try:
                    with open(FORMATTED_AI_CASES_FILE, 'r', encoding='utf-8') as f:
                        ai_text = f.read()
                        log(f"AI测试用例文件大小: {len(ai_text)} 字节")
                        return ai_text
                except FileNotFoundError:
                    error_info = {
                        "file_path": os.path.abspath(FORMATTED_AI_CASES_FILE),
                        "current_dir": os.getcwd(),
                        "available_files": os.listdir(os.path.dirname(FORMATTED_AI_CASES_FILE)) if os.path.exists(
                            os.path.dirname(FORMATTED_AI_CASES_FILE)) else "目录不存在"
                    }
                    log_error(f"找不到AI测试用例文件 {FORMATTED_AI_CASES_FILE}", error_info)
                    return None
                except Exception as e:
                    log_error(f"读取AI测试用例文件 {FORMATTED_AI_CASES_FILE} 失败", e)
                    return None
            else:
                log("使用传入的AI测试用例数据", important=True)
                return ai_cases_data

        async def load_golden_cases():
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
                    return None

                # 默认使用第一个找到的文件
                golden_file = golden_files[0]
                log(f"使用黄金标准测试用例文件: {golden_file}", important=True)

                try:
                    with open(golden_file, 'r', encoding='utf-8') as f:
                        golden_text = f.read()
                        log(f"黄金标准测试用例文件大小: {len(golden_text)} 字节")
                        return golden_text
                except FileNotFoundError:
                    error_info = {
                        "file_path": os.path.abspath(golden_file),
                        "current_dir": os.getcwd()
                    }
                    log_error(f"找不到黄金标准测试用例文件 {golden_file}", error_info)
                    return None
                except Exception as e:
                    log_error(f"读取黄金标准测试用例文件 {golden_file} 失败", e)
                    return None
            else:
                log("使用传入的黄金标准测试用例数据", important=True)
                return golden_cases_data
                
        async def load_prev_iteration():
            if prev_iteration_data is None:
                log("没有提供上一次迭代的测试用例数据", level="WARNING")
                return None
            else:
                log("使用传入的上一次迭代测试用例数据", important=True)
                return prev_iteration_data

        # 创建任务列表
        tasks = [
            asyncio.create_task(load_ai_cases()),
            asyncio.create_task(load_golden_cases())
        ]
        
        # 如果启用迭代对比，添加加载上一次迭代数据的任务
        if is_iteration:
            tasks.append(asyncio.create_task(load_prev_iteration()))

        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        # 解析结果
        if is_iteration:
            ai_cases_raw_text, golden_cases_raw_text, prev_iteration_raw_text = results
        else:
            ai_cases_raw_text, golden_cases_raw_text = results
            prev_iteration_raw_text = None

        if ai_cases_raw_text is None:
            end_logging()
            return {
                "success": False,
                "error": "加载AI测试用例失败"
            }

        if golden_cases_raw_text is None:
            end_logging()
            return {
                "success": False,
                "error": "加载黄金标准测试用例失败"
            }
            
        if is_iteration and prev_iteration_raw_text is None:
            log("警告：无法加载上一次迭代的测试用例数据，迭代对比功能将被禁用", level="WARNING")
            is_iteration = False

        # 检查是否需要处理双重转义的JSON字符串
        try:
            json.loads(ai_cases_raw_text)
        except json.JSONDecodeError:
            log("检测到可能的双重转义JSON字符串，尝试处理", level="WARNING")
            try:
                # 尝试使用eval处理
                parsed_data = eval(ai_cases_raw_text)
                if isinstance(parsed_data, dict):
                    ai_cases_raw_text = json.dumps(parsed_data)
                    log("成功处理双重转义的JSON字符串", important=True)
            except Exception as e:
                log_error(f"处理双重转义JSON失败: {str(e)}")
                # 保持原样
                
        # 如果启用迭代对比，同样检查上一次迭代数据
        if is_iteration and prev_iteration_raw_text:
            try:
                json.loads(prev_iteration_raw_text)
            except json.JSONDecodeError:
                log("检测到上一次迭代数据可能是双重转义JSON字符串，尝试处理", level="WARNING")
                try:
                    # 尝试使用eval处理
                    parsed_data = eval(prev_iteration_raw_text)
                    if isinstance(parsed_data, dict):
                        prev_iteration_raw_text = json.dumps(parsed_data)
                        log("成功处理上一次迭代数据的双重转义JSON字符串", important=True)
                except Exception as e:
                    log_error(f"处理上一次迭代数据的双重转义JSON失败: {str(e)}")
                    # 保持原样

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

    # 创建aiohttp会话，使用配置文件中的优化参数设置
    # 生成唯一的会话ID，确保每次评测使用新的会话
    session_id = str(uuid.uuid4())
    log(f"创建新的评测会话: {session_id}", important=True)

    timeout = aiohttp.ClientTimeout(total=AIOHTTP_TIMEOUT)
    connector = aiohttp.TCPConnector(
        limit=AIOHTTP_CONNECTOR_LIMIT,
        ttl_dns_cache=AIOHTTP_CONNECTOR_TTL,
        force_close=True,  # 强制关闭连接，避免复用
        enable_cleanup_closed=True  # 自动清理关闭的连接
    )

    async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"Connection": "close", "X-Session-ID": session_id}  # 修改为不保持连接
    ) as session:
        try:
            # 2. 格式化测试用例 - 并行执行
            log("开始格式化测试用例", important=True)

            # 创建格式化任务列表
            format_tasks = [
                format_test_cases(session, ai_cases_raw_text, "AI"),
                format_test_cases(session, golden_cases_raw_text, "Golden")
            ]
            
            # 如果启用迭代对比，添加格式化上一次迭代数据的任务
            if is_iteration and prev_iteration_raw_text:
                format_tasks.append(format_test_cases(session, prev_iteration_raw_text, "Previous"))

            # 并行执行格式化任务
            formatted_results = await asyncio.gather(*format_tasks)
            
            # 解析结果
            if is_iteration and prev_iteration_raw_text:
                formatted_ai_cases, formatted_golden_cases, formatted_prev_iteration = formatted_results
            else:
                formatted_ai_cases, formatted_golden_cases = formatted_results
                formatted_prev_iteration = None

            if not formatted_ai_cases:
                log_error("格式化AI测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "格式化AI测试用例失败"
                }

            # 保存格式化后的AI测试用例（使用会话唯一文件名）
            try:
                os.makedirs(os.path.dirname(formatted_ai_cases_file), exist_ok=True)
                with open(formatted_ai_cases_file, 'w', encoding='utf-8') as f:
                    json.dump(formatted_ai_cases, f, ensure_ascii=False, indent=2)
                log(f"格式化后的AI测试用例已保存到 {formatted_ai_cases_file}", important=True)
            except Exception as e:
                log_error(f"保存格式化后的AI测试用例到 {formatted_ai_cases_file} 失败", e)
                # 继续执行，不中断流程

            if not formatted_golden_cases:
                log_error("格式化黄金标准测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "格式化黄金标准测试用例失败"
                }

            # 保存格式化后的黄金标准测试用例（使用会话唯一文件名）
            try:
                os.makedirs(os.path.dirname(formatted_golden_cases_file), exist_ok=True)
                with open(formatted_golden_cases_file, 'w', encoding='utf-8') as f:
                    json.dump(formatted_golden_cases, f, ensure_ascii=False, indent=2)
                log(f"格式化后的黄金标准测试用例已保存到 {formatted_golden_cases_file}", important=True)
            except Exception as e:
                log_error(f"保存格式化后的黄金标准测试用例到 {formatted_golden_cases_file} 失败", e)
                # 继续执行，不中断流程
                
            # 如果启用迭代对比，保存格式化后的上一次迭代测试用例
            if is_iteration and formatted_prev_iteration and formatted_prev_iteration_file:
                try:
                    with open(formatted_prev_iteration_file, 'w', encoding='utf-8') as f:
                        json.dump(formatted_prev_iteration, f, ensure_ascii=False, indent=2)
                    log(f"格式化后的上一次迭代测试用例已保存到 {formatted_prev_iteration_file}", important=True)
                except Exception as e:
                    log_error(f"保存格式化后的上一次迭代测试用例到 {formatted_prev_iteration_file} 失败", e)
                    # 继续执行，不中断流程

            # 3. 评测测试用例和生成报告 - 并行执行
            log("开始评测测试用例和准备报告生成", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.05)

            # 启动评测任务
            evaluation_task = asyncio.create_task(
                evaluate_test_cases(
                    session, 
                    formatted_ai_cases, 
                    formatted_golden_cases,
                    is_iteration=is_iteration,
                    prev_iteration_cases=formatted_prev_iteration
                )
            )

            # 等待评测完成
            evaluation_result = await evaluation_task

            if not evaluation_result:
                log_error("评测测试用例失败，退出评测")
                end_logging()
                return {
                    "success": False,
                    "error": "评测测试用例失败"
                }

            # 保存JSON格式的评测结果
            try:
                # 确保JSON文件保存在正确的目录
                json_file_dir = os.path.dirname(report_json_file)
                os.makedirs(json_file_dir, exist_ok=True)
                
                with open(report_json_file, 'w', encoding='utf-8') as f:
                    json.dump(evaluation_result, f, ensure_ascii=False, indent=2)
                log(f"JSON格式的评测结果已保存到 {report_json_file}", important=True)
                # 添加小延迟，确保日志顺序
                await asyncio.sleep(0.05)
            except Exception as e:
                log_error(f"保存JSON格式的评测结果到 {report_json_file} 失败", e)
                # 继续执行，不中断流程

            # 4. 生成Markdown格式的报告
            log("开始生成Markdown格式报告", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.05)

            # 调用evaluate_and_generate_report函数，传递迭代参数和已有的评测结果
            report_result = await evaluate_and_generate_report(
                session, 
                formatted_ai_cases, 
                formatted_golden_cases,
                report_file,
                is_iteration=is_iteration,
                prev_iteration_cases=formatted_prev_iteration,
                evaluation_result=evaluation_result  # 传递已有的评测结果
            )

            if not report_result.get("success", False):
                log_error("生成报告失败", important=True)
                # 继续执行，不中断流程

            # 处理可能的Markdown报告格式问题
            markdown_report = None
            markdown_report_iteration = None
            
            # 提取标准报告
            if report_result.get("report"):
                markdown_report = report_result["report"]
            elif report_result.get("markdown_report"):
                markdown_report = report_result["markdown_report"]
                
            # 提取迭代报告
            if report_result.get("report_iteration"):
                markdown_report_iteration = report_result["report_iteration"]
                
            # 处理标准报告格式
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
            
            # 对迭代报告做类似的处理
            if markdown_report_iteration:
                # 如果是字典格式的结果，提取文本内容
                if isinstance(markdown_report_iteration, dict) and "text" in markdown_report_iteration:
                    markdown_report_iteration = markdown_report_iteration["text"]

                # 清理Markdown报告，确保没有"markdown"前缀
                if markdown_report_iteration.strip().startswith("markdown"):
                    markdown_report_iteration = markdown_report_iteration.strip().replace("markdown", "", 1).strip()
                    log("已删除迭代报告中的'markdown'前缀", important=True)

                # 处理可能的空行前缀
                if markdown_report_iteration.startswith("\n") and not markdown_report_iteration.strip().startswith("#"):
                    markdown_report_iteration = markdown_report_iteration.lstrip()
                    log("已删除迭代报告中的前导空行", important=True)

                # 处理可能包含的代码块标记
                if "```markdown" in markdown_report_iteration:
                    # 提取代码块内容
                    try:
                        markdown_report_iteration = markdown_report_iteration.split("```markdown")[1].split("```")[0].strip()
                        log("已从迭代报告markdown代码块中提取内容", important=True)
                    except:
                        log_error("处理迭代报告markdown代码块失败，保留原始内容")
                elif "```" in markdown_report_iteration and not "```json" in markdown_report_iteration:
                    # 可能是通用代码块
                    try:
                        parts = markdown_report_iteration.split("```")
                        if len(parts) >= 3 and len(parts[0].strip()) == 0:
                            # 如果第一个分割是空的，取第二个部分（代码块内容）
                            markdown_report_iteration = parts[1].strip()
                            log("已从迭代报告代码块中提取内容", important=True)
                    except:
                        log_error("处理迭代报告代码块失败，保留原始内容")

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
                                                fixed_parts.append(
                                                    f"\n```mermaid\n{chart_type}{chart_content}\n```\n{rest_content}")
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

                    # 修复饼图中的冒号语法错误
                    import re
                    log("正在修复饼图语法错误...", important=True)

                    # 查找所有饼图内容
                    pie_chart_pattern = r"```mermaid\s*\npie[\s\S]*?```"
                    pie_charts = re.findall(pie_chart_pattern, markdown_report)

                    for pie_chart in pie_charts:
                        # 修复冒号语法错误（将全角冒号 "：" 替换为半角冒号 ":" ）
                        fixed_chart = pie_chart.replace("：", ":")
                        # 修复中文双引号问题（将中文双引号 "" 替换为英文双引号 ""）
                        fixed_chart = fixed_chart.replace(""", "\"").replace(""", "\"")
                        # 修复冒号前后的空格问题（如"键 : 值"改为"键": 值）
                        fixed_chart = re.sub(r'("[^"]+")(\s*):(\s*)(\d+\.?\d*)', r'\1: \4', fixed_chart)
                        # 应用修复后的图表
                        markdown_report = markdown_report.replace(pie_chart, fixed_chart)

                    log("已修复饼图语法错误和双引号问题", important=True)

                    # 修复合并建议图中的双引号语法错误
                    log("正在修复合并建议图中的双引号语法错误...", important=True)
                    merge_chart_pattern = r"```mermaid\s*\ngraph LR[\s\S]*?```"
                    merge_charts = re.findall(merge_chart_pattern, markdown_report)

                    for merge_chart in merge_charts:
                        # 查找并修复格式为 ID["文本"] 的模式
                        node_pattern = r'(\w+(?:-\w+)*)\["([^"]+)"\]'
                        fixed_chart = re.sub(node_pattern, r'\1[\2]', merge_chart)
                        # 应用修复后的图表
                        markdown_report = markdown_report.replace(merge_chart, fixed_chart)

                    log("已修复合并建议图中的双引号语法错误", important=True)

                    # 修复评测流程框架图中的冒号语法错误
                    log("正在修复评测流程框架图中的语法错误...", important=True)
                    framework_chart_pattern = r"```mermaid\s*\ngraph TD[\s\S]*?```"
                    framework_charts = re.findall(framework_chart_pattern, markdown_report)

                    for framework_chart in framework_charts:
                        # 修复全角冒号为半角冒号
                        fixed_chart = framework_chart.replace("：", ":")
                        # 修复冒号前后的空格问题
                        fixed_chart = re.sub(r'(\w+)(\s*):(\s*)(\w+)', r'\1: \4', fixed_chart)
                        # 应用修复后的图表
                        markdown_report = markdown_report.replace(framework_chart, fixed_chart)

                    log("已修复评测流程框架图中的语法错误", important=True)

                    # 修复所有其他mermaid图表中可能存在的冒号问题
                    log("正在修复所有mermaid图表中的冒号和双引号问题...", important=True)
                    all_mermaid_pattern = r"```mermaid[\s\S]*?```"
                    all_mermaid_charts = re.findall(all_mermaid_pattern, markdown_report)

                    for chart in all_mermaid_charts:
                        # 修复全角冒号为半角冒号
                        fixed_chart = chart.replace("：", ":")
                        # 修复中文双引号问题
                        fixed_chart = fixed_chart.replace(""", "\"").replace(""", "\"")
                        # 应用修复后的图表
                        if fixed_chart != chart:
                            markdown_report = markdown_report.replace(chart, fixed_chart)

                    log("已修复所有mermaid图表中的冒号和双引号问题", important=True)

                    # 移除安全与经济性部分的图表
                    import re
                    log("正在移除安全与经济性部分的图表...", important=True)

                    # 移除安全与经济性部分的图表
                    # 匹配模式：从"### 🛡️ 安全与经济性"或类似标题开始，到下一个图表结束
                    security_chart_pattern = r"(### (?:🛡️ )?安全与经济性.*?)(```mermaid[\s\S]*?```)"
                    markdown_report = re.sub(security_chart_pattern, r"\1", markdown_report)

                    # 移除可能存在的多余空行
                    markdown_report = re.sub(r'\n{3,}', '\n\n', markdown_report)

                    log("已移除安全与经济性部分的图表", important=True)

                except Exception as e:
                    log_error(f"修复Mermaid图表时出错: {e}")
                    # 继续处理，不中断流程

                # 更新页脚为实时时间和自定义评估中心名称
                try:
                    from datetime import datetime
                    # 确保使用实时时间
                    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                    new_footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                    # 查找并替换原有页脚，使用更宽松的正则表达式匹配任何格式的日期、占位符或时间戳
                    import re
                    footer_pattern = r"\*\*生成时间：(.*?)(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                    placeholder_patterns = [
                        r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                        r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                        r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                    ]
                    
                    # 先检查是否有明确的占位符
                    placeholder_found = False
                    for pattern in placeholder_patterns:
                        if re.search(pattern, markdown_report):
                            markdown_report = re.sub(pattern, new_footer, markdown_report)
                            placeholder_found = True
                            log("已替换页脚中的明确占位符为实时时间", important=True)
                            break
                    
                    # 如果没有找到明确的占位符，尝试使用通用模式
                    if not placeholder_found and re.search(footer_pattern, markdown_report):
                        markdown_report = re.sub(footer_pattern, new_footer, markdown_report)
                        log("已替换页脚中的日期为实时时间", important=True)
                    elif not placeholder_found:
                        # 如果没有找到页脚，则添加到报告末尾
                        markdown_report = markdown_report.rstrip() + "\n\n---\n" + new_footer + "\n"
                        log("未找到页脚，已添加带有实时时间的页脚", important=True)

                    log("已更新报告页脚为实时时间和自定义评估中心名称", important=True)
                except Exception as e:
                    log_error(f"更新页脚时出错: {e}")
                    # 继续处理，不中断流程

            # 保存Markdown格式的报告
            try:
                # 确保markdown_report是字符串
                if not isinstance(markdown_report, str):
                    markdown_report = str(markdown_report)

                # 在保存前进行最终的占位符检查和替换
                from datetime import datetime
                current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                new_footer = f"**生成时间：{current_time} • gogogo出发喽评估中心**"

                import re
                placeholder_patterns = [
                    r"\*\*生成时间：DATETIME_PLACEHOLDER • gogogo出发喽评估中心\*\*",
                    r"\*\*生成时间：DATETIME_PLACEHOLDER(?:•|·|\*) *gogogo出发喽评估中心\*\*",
                    r"\*\*生成时间：<.*?>(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                ]

                # 检查并替换占位符
                placeholder_found = False
                for pattern in placeholder_patterns:
                    if re.search(pattern, markdown_report):
                        markdown_report = re.sub(pattern, new_footer, markdown_report)
                        placeholder_found = True
                        log("保存前已替换报告中的占位符为实时时间", important=True)
                        break

                if not placeholder_found:
                    # 如果没有找到占位符，检查是否有其他格式的时间戳需要更新
                    footer_pattern = r"\*\*生成时间：(.*?)(?:•|·|\*) *gogogo出发喽评估中心\*\*"
                    if re.search(footer_pattern, markdown_report):
                        markdown_report = re.sub(footer_pattern, new_footer, markdown_report)
                        log("保存前已更新报告中的时间戳为实时时间", important=True)
                    else:
                        log("保存前未在报告中找到时间戳，将添加页脚", level="WARNING")
                        markdown_report = markdown_report.rstrip() + "\n\n---\n" + new_footer + "\n"

                # 确保目录存在
                os.makedirs(os.path.dirname(report_file), exist_ok=True)

                # 使用utf-8编码保存文件
                with open(report_file, 'w', encoding='utf-8') as f:
                    f.write(markdown_report)

                log(f"Markdown格式的评测报告已保存到 {report_file}", important=True)
                # 添加小延迟，确保日志顺序
                await asyncio.sleep(0.05)
            except Exception as e:
                log_error(f"保存Markdown格式的评测报告到 {report_file} 失败", e)
                # 继续执行，不中断流程

            # 结合评测结果和生成的Markdown格式报告返回最终结果
            result = {
                "success": True,
                "evaluation_result": evaluation_result,
                "files": {
                    "report_md": report_file,
                    "report_json": report_json_file
                }
            }

            # 添加标准报告
            if markdown_report:
                result["report"] = markdown_report
                result["markdown_report"] = markdown_report
                log("已添加标准报告到结果", important=True)

            # 添加迭代报告
            if is_iteration and markdown_report_iteration:
                result["report_iteration"] = markdown_report_iteration
                log(f"已添加迭代报告到结果，长度: {len(markdown_report_iteration)}", important=True)
            elif is_iteration:
                log("迭代模式已启用但迭代报告为空，未能添加迭代报告", level="WARNING")
            
            # 记录最终返回的字段
            log(f"最终结果包含以下字段: {', '.join(result.keys())}", important=True)

            log("测试用例评测流程完成！", important=True)
            # 添加小延迟，确保日志顺序
            await asyncio.sleep(0.05)
            end_logging()

            # 清理临时文件
            try:
                if os.path.exists(formatted_ai_cases_file):
                    os.remove(formatted_ai_cases_file)
                if os.path.exists(formatted_golden_cases_file):
                    os.remove(formatted_golden_cases_file)
                if formatted_prev_iteration_file and os.path.exists(formatted_prev_iteration_file):
                    os.remove(formatted_prev_iteration_file)
                log("已清理临时格式化文件", level="INFO")
            except Exception as e:
                log_error(f"清理临时文件失败: {str(e)}", level="WARNING")

            return result
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


def main(ai_cases_file=None, golden_cases_file=None, is_iteration=False, prev_iteration_file=None):
    """
    兼容原有入口点的主函数

    :param ai_cases_file: AI测试用例文件路径（可选）
    :param golden_cases_file: 黄金标准测试用例文件路径（可选）
    :param is_iteration: 是否启用迭代前后对比功能
    :param prev_iteration_file: 上一次迭代的测试用例文件路径（可选），仅在is_iteration为true时有效
    """
    # 如果是Windows平台，需要显式设置事件循环策略
    if os.name == 'nt':
        log("设置Windows事件循环策略")
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    ai_cases_data = None
    golden_cases_data = None
    prev_iteration_data = None

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
            
    if is_iteration and prev_iteration_file:
        try:
            with open(prev_iteration_file, 'r', encoding='utf-8') as f:
                prev_iteration_data = f.read()
            log(f"从文件 {prev_iteration_file} 读取上一次迭代测试用例数据")
        except Exception as e:
            log_error(f"读取上一次迭代测试用例文件 {prev_iteration_file} 失败", e)
            log("迭代前后对比功能将被禁用", level="WARNING")
            is_iteration = False

    # 运行异步主函数
    return asyncio.run(async_main(ai_cases_data, golden_cases_data, is_iteration, prev_iteration_data))
