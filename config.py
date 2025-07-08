import os
import datetime

# --- 创建必要的目录结构 ---
os.makedirs("goldenset", exist_ok=True)
os.makedirs("testset", exist_ok=True)
os.makedirs("log", exist_ok=True)
os.makedirs("output_evaluation/evaluation_json", exist_ok=True)
os.makedirs("output_evaluation/evaluation_markdown", exist_ok=True)

# --- 配置区 ---
# API的URL，从curl命令中获取
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
#API_URL = "https://api.siliconflow.cn/v1/chat/completions"

#MODEL_NAME = "doubao-seed-1-6-thinking-250615"
MODEL_NAME = "deepseek-r1-250528"
#MODEL_NAME = "deepseek-ai/DeepSeek-R1"

# VOLC_BEARER_TOKEN = os.getenv("VOLC_BEARER_TOKEN")
VOLC_BEARER_TOKEN = "0333e8a0-55c7-4597-b3c2-702ee8516cba"  # 直接在这里写入你的密钥
#VOLC_BEARER_TOKEN = "sk-tcjwmakxpmqtggsqiwrufqwazoggqjdutrzojmbsmchteehx"

# LLM生成参数
LLM_TEMPERATURE = 0.2  # 评测时使用低temperature确保结果一致性
LLM_TEMPERATURE_REPORT = 0.4  # 生成报告时使用稍高的temperature

# 输入文件名
AI_CASES_FILE = "testset/test_cases.json"  # 从testset文件夹读取
GOLDEN_CASES_FILE = "goldenset/golden_cases.json"  # 从goldenset文件夹读取

# 输出报告文件名 - 改为函数，每次调用时获取当前时间
def get_report_file_paths():
    """获取带有当前时间戳的报告文件路径"""
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    report_file = f"output_evaluation/evaluation_markdown/evaluation_report-{current_time}.md"
    report_json_file = f"output_evaluation/evaluation_json/evaluation_report-{current_time}.json"
    return report_file, report_json_file

# 固定路径
FORMATTED_AI_CASES_FILE = "testset/formatted_test_cases.json"  # 保存在testset文件夹
FORMATTED_GOLDEN_CASES_FILE = "goldenset/formatted_golden_cases.json"  # 保存在goldenset文件夹
LOG_FILE = "log/evaluation_log.txt"  # 日志文件保存在log文件夹

# --- 优化配置 ---
# 并行处理配置
MAX_CONCURRENT_REQUESTS = 16  # 增加最大并发LLM请求数
MAX_CASES_COUNT = None  # 不限制处理的测试用例数量
FORMAT_CASES_LIMIT = None  # 格式化时不限制测试用例数量
MAX_TOKEN_SIZE = 8000  # LLM处理的最大文本长度

# --- 网络优化配置 ---
# aiohttp连接池配置
AIOHTTP_CONNECTOR_LIMIT = 30  # 增加连接池大小
AIOHTTP_CONNECTOR_TTL = 900  # 增加连接TTL时间（秒）
AIOHTTP_TIMEOUT = 360  # 增加请求超时时间（秒）

# --- 缓存配置 ---
LLM_CACHE_SIZE = 200  # 增加LLM请求缓存大小
DUPLICATE_SIMILARITY_THRESHOLD = 0.8  # 重复检测相似度阈值