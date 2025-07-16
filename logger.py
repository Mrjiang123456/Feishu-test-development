import time
import datetime
import os
import json
from config import LOG_FILE, MODEL_NAME
import threading
import queue

# --- 日志记录功能 ---
start_time = None
step_times = {}
ERROR_LOG_FILE = "log/error_log.txt"  # 错误日志专用文件

# 日志缓冲区
_log_buffer = queue.Queue(maxsize=200)  # 增加缓冲区大小
_error_log_buffer = queue.Queue(maxsize=40)  # 增加错误日志缓冲区大小
_log_writer_thread = None
_log_write_interval = 0.5  # 减少日志写入间隔（秒）
_log_buffer_lock = threading.Lock()
_shutdown_flag = False


def _log_writer_worker():
    """后台线程：批量写入日志"""
    while not _shutdown_flag:
        try:
            # 收集普通日志缓冲区中的所有消息
            normal_logs = []
            try:
                while not _log_buffer.empty():
                    normal_logs.append(_log_buffer.get_nowait())
                    _log_buffer.task_done()
            except queue.Empty:
                pass

            # 批量写入普通日志
            if normal_logs:
                try:
                    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write("\n".join(normal_logs) + "\n")
                except Exception as e:
                    print(f"写入日志文件出错: {e}")

            # 收集错误日志缓冲区中的所有消息
            error_logs = []
            try:
                while not _error_log_buffer.empty():
                    error_logs.append(_error_log_buffer.get_nowait())
                    _error_log_buffer.task_done()
            except queue.Empty:
                pass

            # 批量写入错误日志
            if error_logs:
                try:
                    os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
                    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write("\n".join(error_logs) + "\n")
                except Exception as e:
                    print(f"写入错误日志文件出错: {e}")

            # 如果没有日志要处理，等待一段时间
            if not normal_logs and not error_logs:
                time.sleep(_log_write_interval)
            else:
                # 有日志处理完成后短暂等待，减少CPU占用
                time.sleep(0.01)

        except Exception as e:
            print(f"日志写入工作线程出错: {e}")
            # 短暂休眠，避免出错时CPU占用过高
            time.sleep(0.2)


def _ensure_log_writer():
    """确保日志写入线程正在运行"""
    global _log_writer_thread
    if _log_writer_thread is None or not _log_writer_thread.is_alive():
        _log_writer_thread = threading.Thread(
            target=_log_writer_worker,
            daemon=True
        )
        _log_writer_thread.start()


def log(message, step=None, important=False, level="INFO", model_name=None):
    """
    记录日志，包含时间信息

    :param message: 日志消息
    :param step: 步骤名称
    :param important: 是否为重要日志
    :param level: 日志级别 (INFO, WARNING, ERROR, CRITICAL)
    :param model_name: 模型名称，如果为None则使用配置中的MODEL_NAME
    """
    global start_time, step_times

    current_time = time.time()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 如果是首次调用，初始化开始时间
    if start_time is None:
        start_time = current_time

    # 计算从开始到现在的总时间
    total_elapsed = current_time - start_time

    # 使用传入的model_name或配置中的MODEL_NAME
    model_display = model_name if model_name else MODEL_NAME

    # 构建日志信息，包含模型名称和日志级别
    log_message = f"[{timestamp}] [{level}] [模型: {model_display}] [总计: {total_elapsed:.1f}s] {message}"

    # 只打印重要日志或错误日志
    if important or level in ["ERROR", "CRITICAL"]:
        print(log_message)

    # 确保日志写入线程已启动
    _ensure_log_writer()

    # 将日志放入缓冲区
    try:
        _log_buffer.put_nowait(log_message)
    except queue.Full:
        # 如果缓冲区已满，直接写入文件
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_message + "\n")
        except Exception as e:
            print(f"写入日志文件出错: {e}")


def log_error(message, error_details=None, important=True, model_name=None):
    """
    记录错误日志，包含详细的错误信息

    :param message: 错误消息
    :param error_details: 错误详情，可以是异常对象或字典
    :param important: 是否为重要日志
    :param model_name: 模型名称，如果为None则使用配置中的MODEL_NAME
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
            important=important, level="ERROR", model_name=model_name)

        # 记录详细错误信息
        error_log_message = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [ERROR] [详细错误信息]: {json.dumps(error_info, ensure_ascii=False)}"

        # 确保日志写入线程已启动
        _ensure_log_writer()

        # 将错误日志放入错误缓冲区
        try:
            _error_log_buffer.put_nowait(error_log_message)
        except queue.Full:
            # 如果缓冲区已满，直接写入文件
            try:
                os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
                with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(error_log_message + "\n")
            except Exception as e:
                print(f"写入错误日志文件出错: {e}")
    else:
        log(message, important=important, level="ERROR", model_name=model_name)


def start_logging():
    """开始日志记录"""
    global start_time, _shutdown_flag
    start_time = time.time()
    _shutdown_flag = False

    # 确保日志写入线程已启动
    _ensure_log_writer()

    # 创建分隔符，使用追加模式
    log_message = f"\n=== 评测日志开始 [{MODEL_NAME}] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n"

    # 直接写入文件，确保开始标记立即可见
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_message)
    except Exception as e:
        print(f"写入日志文件出错: {e}")

    log("日志记录开始", important=True)


def end_logging():
    """结束日志记录，显示总时间"""
    global _shutdown_flag

    if start_time:
        total_time = time.time() - start_time
        log(f"评测完成，总执行时间: {total_time:.1f}秒", important=True)

        # 等待日志缓冲区处理完毕
        try:
            _log_buffer.join(timeout=2.0)
            _error_log_buffer.join(timeout=1.0)
        except:
            pass

        # 增加一点延迟，确保所有日志都已写入
        time.sleep(0.1)

        # 直接写入文件，确保结束标记立即可见
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"=== 评测日志结束 [{MODEL_NAME}] {timestamp}，总执行时间: {total_time:.1f}秒 ===\n\n")
        except Exception as e:
            print(f"写入日志文件出错: {e}")
    else:
        log("日志结束，但未找到开始时间记录")

    # 设置关闭标志，停止日志写入线程
    _shutdown_flag = True
