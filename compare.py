"""
测试用例评测工具
此文件为向后兼容入口点，实际功能已拆分到各个模块文件中
"""

import os
import sys
import traceback
import json

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    # 从各个模块导入所需的函数和变量
    from config import *
    from logger import log, log_error, start_logging, end_logging
    from llm_api import async_call_llm, extract_sample_cases
    from formatter import format_test_cases
    from analyzer import find_duplicate_test_cases
    from evaluator import evaluate_test_cases, generate_markdown_report
    from core import async_main, main
    
    # 导入API服务器部分，如果可用
    try:
        from api_server import app
    except ImportError as e:
        error_info = {
            "error_type": "ImportError",
            "error_message": str(e),
            "missing_module": str(e).split("'")[1] if "'" in str(e) else "未知模块",
            "traceback": traceback.format_exc()
        }
        log_error("导入API服务器模块失败", error_info)
        app = None
except Exception as e:
    # 如果导入失败，记录错误并退出
    print(f"错误：导入模块失败 - {str(e)}")
    print(traceback.format_exc())
    sys.exit(1)

if __name__ == "__main__":
    try:
        # 调用主程序入口
        import argparse
        
        # 创建命令行参数解析器
        parser = argparse.ArgumentParser(description="测试用例评测工具")
        parser.add_argument("--ai", help="AI生成的测试用例文件路径")
        parser.add_argument("--golden", help="黄金标准测试用例文件路径")
        parser.add_argument("--model", help="使用的模型名称，默认使用config.py中的设置")
        
        # 解析命令行参数
        args = parser.parse_args()
        
        # 如果指定了模型名称，更新配置
        if args.model:
            MODEL_NAME = args.model
            log(f"使用指定的模型: {MODEL_NAME}", important=True)
        
        # 记录系统环境信息
        try:
            import platform
            env_info = {
                "platform": platform.platform(),
                "python_version": sys.version,
                "api_url": API_URL,
                "model": MODEL_NAME,
                "current_dir": current_dir,
                "command_line": " ".join(sys.argv)
            }
            log(f"系统环境信息: {json.dumps(env_info, ensure_ascii=False)}")
        except Exception as e:
            log_error("获取系统环境信息失败", e)
        
        # 运行主入口
        result = main(args.ai, args.golden)
        
        # 检查结果
        if not result or not result.get("success", False):
            error_msg = result.get("error", "未知错误") if result else "执行失败，未返回结果"
            log_error(f"评测失败: {error_msg}")
            sys.exit(1)
        
        log("评测成功完成", important=True)
        sys.exit(0)
    except Exception as e:
        error_info = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc()
        }
        log_error("程序执行过程中发生未处理的异常", error_info)
        print(f"错误：{str(e)}")
        sys.exit(1) 