import time
import datetime
import os
import json
from config import LOG_FILE, MODEL_NAME

# --- 日志记录功能 ---
start_time = None
step_times = {}
ERROR_LOG_FILE = "log/error_log.txt"  # 错误日志专用文件

def log(message, step=None, important=False, level="INFO"):
    """
    记录日志，包含时间信息
    
    :param message: 日志消息
    :param step: 步骤名称
    :param important: 是否为重要日志
    :param level: 日志级别 (INFO, WARNING, ERROR, CRITICAL)
    """
    global start_time, step_times
    
    current_time = time.time()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 如果是首次调用，初始化开始时间
    if start_time is None:
        start_time = current_time
    
    # 计算从开始到现在的总时间
    total_elapsed = current_time - start_time
    
    # 构建日志信息，包含模型名称和日志级别
    log_message = f"[{timestamp}] [{level}] [模型: {MODEL_NAME}] [总计: {total_elapsed:.1f}s] {message}"
    
    # 只打印重要日志或错误日志
    if important or level in ["ERROR", "CRITICAL"]:
        print(log_message)
    
    # 确保日志目录存在
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    # 写入日志文件（追加模式）
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_message + "\n")
    
    # 如果是错误日志，同时写入错误日志文件
    if level in ["ERROR", "CRITICAL"]:
        os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_message + "\n")

def log_error(message, error_details=None, important=True):
    """
    记录错误日志，包含详细的错误信息
    
    :param message: 错误消息
    :param error_details: 错误详情，可以是异常对象或字典
    :param important: 是否为重要日志
    """
    if error_details:
        if isinstance(error_details, dict):
            error_info = error_details
        elif isinstance(error_details, Exception):
            import traceback
            error_info = {
                "error_type": type(error_details).__name__,
                "error_message": str(error_details),
                "traceback": traceback.format_exc()
            }
        else:
            error_info = {"error_message": str(error_details)}
        
        # 记录基本错误信息
        log(f"{message}: {error_info.get('error_type', 'Error')} - {error_info.get('error_message', '')}", 
            important=important, level="ERROR")
        
        # 记录详细错误信息
        log(f"详细错误信息: {json.dumps(error_info, ensure_ascii=False)}", level="ERROR")
    else:
        log(message, important=important, level="ERROR")

def start_logging():
    """开始日志记录"""
    global start_time
    start_time = time.time()
    
    # 创建分隔符，使用追加模式
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"\n=== 评测日志开始 [{MODEL_NAME}] {timestamp} ===\n")
    
    log("日志记录开始", important=True)

def end_logging():
    """结束日志记录，显示总时间"""
    if start_time:
        total_time = time.time() - start_time
        log(f"评测完成，总执行时间: {total_time:.1f}秒", important=True)
        
        # 增加一点延迟，确保所有日志都已写入
        time.sleep(0.1)
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"=== 评测日志结束 [{MODEL_NAME}] {timestamp}，总执行时间: {total_time:.1f}秒 ===\n\n")
    else:
        log("日志结束，但未找到开始时间记录") 