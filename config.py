import os
import datetime

# --- 创建必要的目录结构 ---
os.makedirs("goldenset", exist_ok=True)
os.makedirs("testset", exist_ok=True)
os.makedirs("log", exist_ok=True)
os.makedirs("output_evaluation/evaluation_json", exist_ok=True)
os.makedirs("output_evaluation/evaluation_markdown", exist_ok=True)
os.makedirs("cache", exist_ok=True)  # 创建缓存目录

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

# --- 多评委委员会配置 ---
ENABLE_MULTI_JUDGES = True  # 启用多评委评测
# 评委模型列表
JUDGE_MODELS = [
    "deepseek-v3-250324",       # DeepSeek-V3
    "doubao-seed-1-6-250615",  # DoubaoSeed
]

# --- CollabEval框架配置 ---
ENABLE_COLLAB_EVAL = False  # 启用CollabEval三阶段评测框架
CHAIRMAN_MODEL = "deepseek-r1-250528"  # 主席模型
#CHAIRMAN_MODEL = "doubao-seed-1-6-250615"  # 主席模型
LOW_CONSENSUS_THRESHOLD = 0.5  # 低共识阈值，方差大于此值触发辩论
HIGH_DISAGREEMENT_THRESHOLD = 1.0  # 高争议阈值，方差大于此值标记为高争议
DEBATE_MAX_ROUNDS = 1  # 最大辩论轮数

# 评测维度及权重配置
EVALUATION_DIMENSIONS = {
    "功能覆盖度": 0.30,
    "缺陷发现能力": 0.25,
    "工程效率": 0.20,
    "语义质量": 0.15,
    "安全与经济性": 0.10
}
# 最大并行评委数
MAX_JUDGES_CONCURRENCY = 8  # 增加最大并行评委数

# 批处理评测配置
ENABLE_BATCH_PROCESSING = True  # 启用批处理评测功能
BATCH_SIZE = 200  # 增加批处理大小
BATCH_CONCURRENCY = 5  # 增加批处理并发数

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
MAX_CONCURRENT_REQUESTS = 128  # 增加最大并发LLM请求数
MAX_CASES_COUNT = None  # 不限制处理的测试用例数量
FORMAT_CASES_LIMIT = None  # 格式化时不限制测试用例数量
MAX_TOKEN_SIZE = 8000  # LLM处理的最大文本长度

# --- 网络优化配置 ---
# aiohttp连接池配置
AIOHTTP_CONNECTOR_LIMIT = 150  # 增加连接池大小
AIOHTTP_CONNECTOR_TTL = 3600  # 增加连接TTL时间（秒）
AIOHTTP_TIMEOUT = 300  # 优化请求超时时间（秒）

# --- 缓存配置 ---
LLM_CACHE_SIZE = 2000  # 增加LLM请求缓存大小
LLM_CACHE_ENABLED = False  # 禁用LLM API调用缓存，确保每次请求都是全新的
DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # 重复检测相似度阈值

# --- 测试覆盖率分析配置 ---
# 测试覆盖率分析阈值
COVERAGE_FULL_THRESHOLD = 3  # 至少需要几个测试用例才认为是完全覆盖
COVERAGE_PARTIAL_THRESHOLD = 1  # 至少需要几个测试用例才认为是部分覆盖

# 测试覆盖率分析关键词
COVERAGE_KEYWORDS = {
    "功能验证": ["功能", "流程", "正常", "基本", "基础", "主流程", "核心功能", "FUNC", "function", "feature"],
    "异常处理": ["异常", "错误", "失败", "出错", "故障", "问题", "报错", "exception", "error", "EXCEP", "fail"],
    "边界测试": ["边界", "极限", "边缘", "临界", "极端", "boundary", "limit", "edge", "BOUND"],
    "输入验证": ["输入", "验证", "校验", "检查", "有效性", "无效", "合法", "非法", "validate", "input", "check"],
    "超时处理": ["超时", "timeout", "time-out", "等待", "延迟", "wait", "delay"],
    "安全检查": ["安全", "攻击", "漏洞", "注入", "越权", "安全漏洞", "xss", "csrf", "sql注入", "security", "attack", "vulnerability", "SEC"],
    "最大值测试": ["最大", "上限", "最高", "max", "maximum", "上边界", "最大值"],
    "最小值测试": ["最小", "下限", "最低", "min", "minimum", "下边界", "最小值"]
}
