import os
import sys
import argparse
import uvicorn
import subprocess
import time
import signal
import threading
from logger import log
from core import main


# 启动frp服务的函数
def start_frp_service():
    """启动frp服务，将本地服务映射到外网"""
    log("正在启动frp服务...", important=True)
    try:
        # 检查frpc可执行文件是否存在
        frpc_path = "./frpc"
        if not os.path.exists(frpc_path):
            log("未找到frpc可执行文件，尝试使用系统frpc命令", important=True)
            frpc_path = "frpc"

        # 启动frp客户端
        frp_process = subprocess.Popen(
            [frpc_path, "-c", "frpc.toml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 检查frp是否成功启动
        time.sleep(2)
        if frp_process.poll() is None:
            log("frp服务启动成功，本地服务已映射到外网", important=True)
            return frp_process
        else:
            stdout, stderr = frp_process.communicate()
            log(f"frp服务启动失败: {stderr}", important=True)
            return None
    except Exception as e:
        log(f"启动frp服务时出错: {str(e)}", important=True)
        return None


# 监控frp服务输出的线程函数
def monitor_frp_output(process):
    """监控frp服务的输出"""
    while process and process.poll() is None:
        try:
            output = process.stdout.readline()
            if output:
                log(f"FRP: {output.strip()}")
        except:
            break


# 确保必要的目录存在
def ensure_directories():
    """确保所有必要的目录存在"""
    directories = [
        "goldenset",
        "testset",
        "log",
        "output_evaluation/evaluation_json",
        "output_evaluation/evaluation_markdown",
        "templates",
        "static"
    ]
    for dir_path in directories:
        os.makedirs(dir_path, exist_ok=True)
    log("已确保所有必要的目录存在", important=True)


if __name__ == "__main__":
    # 确保必要的目录存在
    ensure_directories()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        # 命令行模式
        log("以命令行模式运行...", important=True)
        parser = argparse.ArgumentParser(description="测试用例比较工具")
        parser.add_argument("--ai", help="AI生成的测试用例文件路径")
        parser.add_argument("--golden", help="黄金标准测试用例文件路径")
        parser.add_argument("--iteration", action="store_true", help="是否启用迭代前后对比功能")
        parser.add_argument("--prev", help="上一次迭代的测试用例文件路径，仅在--iteration为true时有效")
        args = parser.parse_args(sys.argv[2:])
        main(args.ai, args.golden, is_iteration=args.iteration, prev_iteration_file=args.prev)
    else:
        # API模式（默认）
        try:
            from api_server import app

            if app:
                log("启动API服务器...", important=True)

                # 启动frp服务
                frp_process = start_frp_service()

                # 如果frp服务启动成功，创建监控线程
                if frp_process:
                    monitor_thread = threading.Thread(
                        target=monitor_frp_output,
                        args=(frp_process,),
                        daemon=True
                    )
                    monitor_thread.start()


                    # 注册清理函数，确保在程序退出时关闭frp进程
                    def cleanup(signum, frame):
                        log("正在关闭frp服务...", important=True)
                        if frp_process and frp_process.poll() is None:
                            frp_process.terminate()
                            frp_process.wait(timeout=5)
                        sys.exit(0)


                    # 注册信号处理
                    signal.signal(signal.SIGINT, cleanup)
                    signal.signal(signal.SIGTERM, cleanup)

                # 启动uvicorn服务器
                log("本地API服务地址: http://127.0.0.1:8000", important=True)
                log("可访问黄金标准测试用例页面: http://127.0.0.1:8000/golden-cases", important=True)
                if frp_process:
                    with open("frpc.toml", "r") as f:
                        content = f.read()
                        server_addr = None
                        server_port = None
                        remote_port = None

                        # 解析frpc.toml文件获取服务器地址和端口
                        for line in content.split("\n"):
                            if "serverAddr" in line and "=" in line:
                                server_addr = line.split("=")[1].strip().strip('"')
                            elif "serverPort" in line and "=" in line:
                                server_port = line.split("=")[1].strip().strip('"')
                            elif "remotePort" in line and "=" in line:
                                remote_port = line.split("=")[1].strip().strip('"')

                        if server_addr and remote_port:
                            log(f"外网访问地址: http://{server_addr}:{remote_port}", important=True)
                            log(f"外网黄金标准测试用例页面: http://{server_addr}:{remote_port}/golden-cases", important=True)

                uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)
            else:
                log("错误：API服务器初始化失败", important=True)
                log("请确保已安装所需库: pip install fastapi uvicorn aiohttp chardet python-multipart", important=True)
        except ImportError:
            log("错误：未安装FastAPI和uvicorn，无法启动API服务", important=True)
            log("请安装所需库: pip install fastapi uvicorn aiohttp chardet python-multipart", important=True)
            log("如需以命令行模式运行，请使用: python main.py --cli", important=True) 
