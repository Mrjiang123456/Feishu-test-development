import json
import time
import aiohttp
import asyncio
import traceback
import re
import uuid
import threading
from typing import Optional, Dict, List
from config import API_URL, VOLC_BEARER_TOKEN, MODEL_NAME, MAX_TOKEN_SIZE, LLM_CACHE_SIZE, LLM_TEMPERATURE, LLM_CACHE_ENABLED, AIOHTTP_TIMEOUT
from logger import log, log_error
from functools import lru_cache
import hashlib
import itertools
import os
import pickle
from typing import Dict, List, Optional
import atexit


# 全局变量，用于存储缓存
LLM_CACHE = {}
LRU_QUEUE = []
MAX_CACHE_SIZE = LLM_CACHE_SIZE  # 使用配置文件中的缓存大小
CACHE_FILE = "cache/llm_cache.pkl"

# 确保缓存目录存在
os.makedirs("cache", exist_ok=True)

# 加载持久化缓存
def load_cache():
    global LLM_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'rb') as f:
                cached_data = pickle.load(f)
                LLM_CACHE = cached_data
                # 移除启动时的日志打印，避免多次显示
                return True
        except Exception as e:
            log_error(f"加载缓存失败: {str(e)}")
    return False

# 保存持久化缓存
def save_cache():
    if LLM_CACHE:
        try:
            with open(CACHE_FILE, 'wb') as f:
                pickle.dump(LLM_CACHE, f)
            log(f"已保存{len(LLM_CACHE)}个缓存项", important=True)
            return True
        except Exception as e:
            log_error(f"保存缓存失败: {str(e)}")
    return False

# 尝试加载缓存
load_cache()

# 在程序退出时保存缓存
atexit.register(save_cache)


# 简单的LRU缓存装饰器，用于缓存计算过的哈希值
@lru_cache(maxsize=LLM_CACHE_SIZE)
def _compute_hash(text):
    """计算文本的哈希值，用于缓存键"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


# 缓存字典，存储API调用结果
_api_cache = {}
_MAX_CACHE_SIZE = LLM_CACHE_SIZE  # 从配置中读取缓存大小
_CACHE_ENABLED = LLM_CACHE_ENABLED  # 从配置中读取缓存启用状态
_cache_lock = threading.Lock()  # 添加线程锁，确保线程安全


# 优化缓存更新函数
def _update_cache(key, value):
    """更新API缓存，如果缓存过大则移除最旧的项目"""
    if not LLM_CACHE_ENABLED:
        return  # 如果缓存被禁用，不执行缓存操作

    with _cache_lock:  # 使用线程锁确保线程安全
        _api_cache[key] = value
        # 如果缓存超过最大大小，移除最旧的条目
        if len(_api_cache) > _MAX_CACHE_SIZE:
            # 批量移除25%的旧缓存项，减少频繁清理
            items_to_remove = int(_MAX_CACHE_SIZE * 0.25)
            oldest_keys = list(itertools.islice(_api_cache.keys(), items_to_remove))
            for old_key in oldest_keys:
                _api_cache.pop(old_key, None)


def clear_cache():
    """清除API调用缓存"""
    global _api_cache
    with _cache_lock:  # 使用线程锁确保线程安全
        _api_cache = {}
    log("已清除LLM API调用缓存", important=True)


def extract_valid_json(text):
    """
    从文本中提取有效的JSON对象

    :param text: 可能包含JSON的文本
    :return: 提取的JSON对象，失败则返回None
    """
    # 首先尝试查找第一个{和最后一个}之间的内容
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            potential_json = text[start_idx:end_idx + 1]
            return json.loads(potential_json)
    except json.JSONDecodeError:
        pass

    # 如果上面失败，尝试使用正则表达式匹配完整的JSON对象
    try:
        json_pattern = re.compile(r'(\{.*?\})', re.DOTALL)
        matches = json_pattern.findall(text)

        # 尝试解析每个匹配的内容
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
    except Exception:
        pass

    # 如果所有尝试都失败，返回None
    return None


async def async_call_llm(
        session: aiohttp.ClientSession,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        retries: int = 3,
        temperature: float = None,
        model_name: str = None,
        use_cache: bool = True  # 默认启用缓存
) -> Optional[Dict]:
    """
    异步调用LLM API

    :param session: aiohttp会话
    :param prompt: 用户输入的提示
    :param system_prompt: 系统角色提示
    :param retries: 重试次数
    :param temperature: 温度参数，控制生成内容的随机性
    :param model_name: 模型名称，如果未指定则使用默认值
    :param use_cache: 是否使用缓存，默认为False
    :return: 解析后的JSON对象，失败则返回None
    """
    # 使用默认temperature或传入的temperature
    if temperature is None:
        temperature = LLM_TEMPERATURE

    # 使用传入的model_name或配置的默认模型
    if model_name is None:
        model_name = MODEL_NAME

    # 为每个请求生成唯一的请求ID，确保不同请求不会使用相同的缓存
    request_id = str(uuid.uuid4())  # 使用完整的UUID，增加唯一性
    timestamp = str(int(time.time() * 1000))  # 毫秒级时间戳

    # 构建唯一的缓存键，包含时间戳和请求ID以确保每次评测的唯一性
    cache_key = _compute_hash(f"{prompt}|{system_prompt}|{model_name}|{temperature}|{request_id}|{timestamp}")
    
    # 只有在显式启用缓存且缓存中存在时才使用缓存
    if use_cache and LLM_CACHE_ENABLED:
        with _cache_lock:
            if cache_key in LLM_CACHE:
                log(f"从缓存返回LLM响应，prompt长度={len(prompt)}, 模型={model_name}", model_name=model_name)
                return LLM_CACHE[cache_key]

    log(f"调用LLM: prompt长度={len(prompt)}, temperature={temperature}, 模型={model_name}, 请求ID={request_id}", model_name=model_name)

    if not VOLC_BEARER_TOKEN:
        log_error("VOLC_BEARER_TOKEN未设置", model_name=model_name)
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_BEARER_TOKEN}",
        "Connection": "keep-alive",  # 添加连接复用设置
        "X-Request-ID": request_id  # 添加请求ID到请求头，帮助追踪和避免服务器端缓存
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature  # 添加temperature参数
    }

    # 记录请求信息，用于诊断
    request_info = {
        "api_url": API_URL,
        "model": model_name,
        "headers": {"Authorization": "Bearer ***[MASKED]***"},
        "prompt_length": len(prompt),
        "system_prompt_length": len(system_prompt),
        "temperature": temperature,
        "request_id": request_id
    }

    for attempt in range(retries):
        try:
            call_start = time.time()
            log(f"尝试调用LLM API (尝试 {attempt + 1}/{retries}), 模型: {model_name}, 目标URL: {API_URL}, 请求ID: {request_id}",
                model_name=model_name)

            # 使用优化的超时设置
            async with session.post(
                    API_URL,
                    headers=headers,
                    json=payload,
                    timeout=AIOHTTP_TIMEOUT,  # 增加超时时间
                    ssl=False  # 禁用SSL验证可加速连接建立
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    error_details = {
                        "status_code": response.status,
                        "error_text": error_text,
                        "attempt": attempt + 1,
                        "request_info": request_info,
                        "headers": dict(response.headers)
                    }
                    log_error(
                        f"LLM API调用失败，模型: {model_name}，状态码: {response.status}，重试中 ({attempt + 1}/{retries})",
                        error_details, model_name=model_name)

                    # 根据错误代码调整重试策略
                    if response.status == 429:  # 速率限制
                        wait_time = 5 * (attempt + 1)
                        log(f"遇到速率限制，等待{wait_time}秒后重试", level="WARNING", model_name=model_name)
                        await asyncio.sleep(wait_time)
                    elif response.status >= 500:  # 服务器错误
                        wait_time = 2 * (attempt + 1)
                        log(f"遇到服务器错误，等待{wait_time}秒后重试", level="WARNING", model_name=model_name)
                        await asyncio.sleep(wait_time)
                    else:  # 其他错误
                        await asyncio.sleep(1 * (attempt + 1))
                    continue

                # 获取响应内容
                try:
                    response_text = await response.text()
                    if not response_text or response_text.strip() == "":
                        log_error(f"LLM API返回空响应 (尝试 {attempt + 1}/{retries}), 模型: {model_name}",
                                  {"empty_response": True}, model_name=model_name)
                        if attempt < retries - 1:
                            await asyncio.sleep(2 * (attempt + 1))
                            continue
                        else:
                            return {"text": "API返回空响应"}

                    # 尝试解析JSON响应
                    try:
                        response_json = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        log_error(f"无法解析API响应为JSON (尝试 {attempt + 1}/{retries}), 模型: {model_name}", {
                            "error": str(e),
                            "response_preview": response_text[:200] + ("..." if len(response_text) > 200 else "")
                        }, model_name=model_name)
                        if attempt < retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        else:
                            # 最后一次尝试失败，返回原始文本
                            return {"text": response_text}

                    call_time = time.time() - call_start
                    log(f"LLM调用成功，模型: {model_name}, 耗时={call_time:.1f}秒, 请求ID: {request_id}",
                        model_name=model_name)

                    try:
                        # 检查响应格式
                        if "choices" not in response_json or not response_json["choices"]:
                            log_error(f"API响应缺少choices字段, 模型: {model_name}", {"response_json": response_json},
                                      model_name=model_name)
                            if attempt < retries - 1:
                                await asyncio.sleep(1 * (attempt + 1))
                                continue
                            else:
                                # 返回整个响应JSON
                                return {"api_response": response_json}

                        content = response_json['choices'][0]['message']['content']
                        if not content or content.strip() == "":
                            log_error(f"API返回的content为空, 模型: {model_name}", {"response_json": response_json},
                                      model_name=model_name)
                            if attempt < retries - 1:
                                # 增加随机延迟，避免潜在的节流问题
                                import random
                                wait_time = (2 * (attempt + 1)) + random.uniform(0.5, 2.0)
                                log(f"遇到空内容响应，等待{wait_time:.1f}秒后添加随机参数重试", level="WARNING", model_name=model_name)

                                # 添加随机参数到请求中，避免可能的缓存问题
                                random_suffix = f"_r{random.randint(1000, 9999)}"
                                if "user" in payload["messages"][-1]["content"]:
                                    payload["messages"][-1]["content"] += f"\n\n{random_suffix}"

                                # 添加强制不使用缓存的请求头
                                headers["Cache-Control"] = "no-cache, no-store"
                                headers["X-Request-ID"] = f"{request_id}_{attempt+1}"  # 更新请求ID

                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                # 达到最大重试次数，返回一个简单的错误对象
                                log(f"达到最大重试次数({retries})，API仍返回空内容", level="ERROR", model_name=model_name)
                                return {"error": "API返回空内容，请稍后重试", "status": "content_empty"}

                        # 从Markdown代码块提取JSON
                        if "```json" in content:
                            json_content = content.split("```json")[1].split("```")[0].strip()
                        elif "```mermaid" in content:
                            # 检测到mermaid代码块，直接识别为Markdown内容
                            log(f"检测到mermaid代码块，直接返回原始内容, 模型: {model_name}", level="WARNING",
                                model_name=model_name)
                            result = {"text": content}
                            # 缓存结果（如果启用）
                            if use_cache and LLM_CACHE_ENABLED:
                                LLM_CACHE[cache_key] = result
                            return result
                        elif "```" in content:
                            # 提取代码块内容
                            code_block_content = content.split("```")[1].split("```")[0].strip()
                            # 检查代码块第一行是否表明是mermaid图表
                            if code_block_content.startswith("mermaid") or code_block_content.startswith(
                                    "graph ") or code_block_content.startswith("pie"):
                                log(f"检测到mermaid图表代码块，直接返回原始内容, 模型: {model_name}", level="WARNING",
                                    model_name=model_name)
                                result = {"text": content}
                                # 缓存结果（如果启用）
                                if use_cache and LLM_CACHE_ENABLED:
                                    LLM_CACHE[cache_key] = result
                                return result
                            json_content = code_block_content
                        else:
                            json_content = content

                        # 如果内容以'markdown'开头，去掉这个前缀
                        if json_content.strip().startswith("markdown"):
                            json_content = json_content.strip().replace("markdown", "", 1).strip()
                            log(f"检测到内容以'markdown'开头，已移除此前缀, 模型: {model_name}", level="WARNING",
                                model_name=model_name)

                        # 检查内容是否是Markdown格式（以#开头的标题）
                        is_markdown = False
                        if json_content.strip().startswith("#") or json_content.strip().startswith("\n#"):
                            is_markdown = True
                        # 检查内容是否以空行开头然后是标题
                        elif json_content.strip().startswith("\n") and "#" in json_content.split("\n", 2)[1]:
                            is_markdown = True
                        # 检查是否包含常见的Markdown标题格式
                        elif re.search(r"^(#|##|###)\s+[A-Za-z0-9\u4e00-\u9fa5]", json_content.strip(), re.MULTILINE):
                            is_markdown = True
                        # 检查是否包含mermaid图表
                        elif "mermaid" in json_content or "graph " in json_content or "pie" in json_content:
                            is_markdown = True
                            log(f"检测到内容包含mermaid图表，识别为Markdown格式, 模型: {model_name}", level="WARNING",
                                model_name=model_name)
                        # 检查内容是否是空白或几乎为空的Markdown（只有标题或很少内容）
                        elif len(json_content.strip()) < 100 and json_content.strip().startswith("#"):
                            is_markdown = True
                            log(f"检测到几乎为空的Markdown内容，内容长度: {len(json_content.strip())}字符, 模型: {model_name}", level="WARNING",
                                model_name=model_name)
                        # 如果内容非常短且不像JSON，也当作Markdown处理
                        elif len(json_content.strip()) < 50 and not (json_content.strip().startswith("{") or json_content.strip().startswith("[")):
                            is_markdown = True
                            log(f"内容非常短且不像JSON，当作Markdown处理，内容长度: {len(json_content.strip())}字符, 模型: {model_name}", level="WARNING",
                                model_name=model_name)

                        if is_markdown:
                            log(f"检测到内容是Markdown格式，不尝试解析为JSON, 模型: {model_name}", level="WARNING",
                                model_name=model_name)
                            # 如果Markdown内容为空或内容太少，添加警告信息
                            markdown_content = json_content.strip()
                            if len(markdown_content) < 10:
                                log_error(f"Markdown内容几乎为空，长度: {len(markdown_content)}字符, 模型: {model_name}", level="ERROR")
                                markdown_content += "\n\n> **警告**: 生成的内容几乎为空，可能需要重新生成。"
                            
                            result = {"text": markdown_content}
                            # 缓存结果（如果启用）
                            if use_cache and LLM_CACHE_ENABLED:
                                LLM_CACHE[cache_key] = result
                            return result

                        # 尝试解析为JSON
                        if json_content and json_content.strip():
                            try:
                                # 尝试直接解析完整的JSON
                                parsed_json = json.loads(json_content)
                                # 缓存结果（如果启用）
                                if use_cache and LLM_CACHE_ENABLED:
                                    LLM_CACHE[cache_key] = parsed_json
                                return parsed_json
                            except json.JSONDecodeError as e:
                                # 记录原始错误
                                error_details = {
                                    "error_type": "JSONDecodeError",
                                    "error_message": str(e),
                                    "content_preview": json_content[:200] + ("..." if len(json_content) > 200 else ""),
                                    "traceback": traceback.format_exc()
                                }
                                log_error(f"JSON解析错误, 尝试修复: {str(e)}", error_details, model_name=model_name)

                                # 尝试各种修复方法

                                # 1. 尝试将单引号替换为双引号
                                try:
                                    fixed_content = json_content.replace("'", "\"")
                                    parsed_json = json.loads(fixed_content)
                                    log(f"通过替换单引号成功解析JSON, 模型: {model_name}", level="WARNING",
                                        model_name=model_name)
                                    # 缓存结果（如果启用）
                                    if use_cache and LLM_CACHE_ENABLED:
                                        LLM_CACHE[cache_key] = parsed_json
                                    return parsed_json
                                except json.JSONDecodeError:
                                    log("替换单引号失败，尝试其他修复方法", level="WARNING", model_name=model_name)

                                # 2. 尝试删除前后的多余字符
                                try:
                                    match = re.search(r'(\{.*\}|\[.*\])', json_content, re.DOTALL)
                                    if match:
                                        potential_json = match.group(0)
                                        parsed_json = json.loads(potential_json)
                                        log(f"通过提取JSON对象成功解析, 模型: {model_name}", level="WARNING",
                                            model_name=model_name)
                                        # 缓存结果（如果启用）
                                        if use_cache and LLM_CACHE_ENABLED:
                                            LLM_CACHE[cache_key] = parsed_json
                                        return parsed_json
                                except (json.JSONDecodeError, re.error):
                                    log("提取JSON对象失败，尝试其他修复方法", level="WARNING", model_name=model_name)

                                # 3. 尝试提取有效的JSON部分
                                extracted_json = extract_valid_json(json_content)
                                if extracted_json:
                                    log(f"通过提取有效JSON部分成功解析, 模型: {model_name}", level="WARNING",
                                        model_name=model_name)
                                    # 缓存结果（如果启用）
                                    if use_cache and LLM_CACHE_ENABLED:
                                        LLM_CACHE[cache_key] = extracted_json
                                    return extracted_json

                                # 4. 处理"Extra data"错误 - 尝试只使用第一个有效的JSON对象
                                if "Extra data" in str(e):
                                    try:
                                        # 获取错误位置，截取到该位置的内容
                                        char_pos = int(re.search(r'char (\d+)', str(e)).group(1))
                                        truncated_json = json_content[:char_pos]
                                        parsed_json = json.loads(truncated_json)
                                        log(f"通过截取到错误位置成功解析JSON, 模型: {model_name}", level="WARNING",
                                            model_name=model_name)
                                        # 缓存结果（如果启用）
                                        if use_cache and LLM_CACHE_ENABLED:
                                            LLM_CACHE[cache_key] = parsed_json
                                        return parsed_json
                                    except (json.JSONDecodeError, AttributeError):
                                        log("截取到错误位置失败，尝试其他方法", level="WARNING", model_name=model_name)

                                # 在记录错误前，检查内容是否可能是Markdown
                                if "```mermaid" in json_content or \
                                        json_content.strip().startswith("#") or \
                                        "graph " in json_content or \
                                        "pie " in json_content or \
                                        re.search(r"^(#|##|###)\s+[A-Za-z0-9\u4e00-\u9fa5]", json_content.strip(),
                                                  re.MULTILINE):
                                    log(f"JSON解析失败，但内容看起来像是Markdown格式，直接返回文本, 模型: {model_name}",
                                        level="WARNING", model_name=model_name)
                                    result = {"text": json_content}
                                    # 缓存结果（如果启用）
                                    if use_cache and LLM_CACHE_ENABLED:
                                        LLM_CACHE[cache_key] = result
                                    return result

                                log_error(f"所有JSON解析方法均失败，返回原始文本, 模型: {model_name}",
                                          {"text": json_content}, model_name=model_name)
                                # 如果不是有效的JSON，直接返回文本内容
                                result = {"text": content}
                                # 缓存结果（如果启用）
                                if use_cache and LLM_CACHE_ENABLED:
                                    LLM_CACHE[cache_key] = result
                                return result
                        else:
                            log_error(f"提取的JSON内容为空, 模型: {model_name}", {"original_content": content[:200]},
                                      model_name=model_name)
                            result = {"text": content}
                            # 缓存结果（如果启用）
                            if use_cache and LLM_CACHE_ENABLED:
                                LLM_CACHE[cache_key] = result
                            return result

                    except (KeyError, IndexError) as e:
                        error_details = {
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "response_json": response_json,
                            "traceback": traceback.format_exc()
                        }
                        log_error(f"解析LLM响应失败, 模型: {model_name}", error_details, model_name=model_name)
                        if attempt < retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        else:
                            # 最后一次尝试，返回原始响应
                            result = {"api_response": response_json}
                            return result
                except Exception as e:
                    error_details = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "traceback": traceback.format_exc()
                    }
                    log_error(f"处理API响应时发生错误 (尝试 {attempt + 1}/{retries}), 模型: {model_name}",
                              error_details, model_name=model_name)
                    await asyncio.sleep(1 * (attempt + 1))

        except aiohttp.ClientConnectorError as e:
            error_details = {
                "error_type": "连接错误",
                "error_message": str(e),
                "api_url": API_URL,
                "model": model_name,
                "traceback": traceback.format_exc()
            }
            log_error(f"无法连接到LLM API服务器 (尝试 {attempt + 1}/{retries}), 模型: {model_name}", error_details,
                      model_name=model_name)
            await asyncio.sleep(2 * (attempt + 1))
        except aiohttp.ClientError as e:
            error_details = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "api_url": API_URL,
                "model": model_name,
                "traceback": traceback.format_exc()
            }
            log_error(f"HTTP客户端错误 (尝试 {attempt + 1}/{retries}), 模型: {model_name}", error_details,
                      model_name=model_name)
            await asyncio.sleep(1 * (attempt + 1))
        except asyncio.TimeoutError as e:
            error_details = {
                "error_type": "请求超时",
                "timeout_seconds": 180,
                "api_url": API_URL,
                "model": model_name
            }
            log_error(f"LLM API请求超时 (尝试 {attempt + 1}/{retries}), 模型: {model_name}", error_details,
                      model_name=model_name)
            await asyncio.sleep(1 * (attempt + 1))
        except Exception as e:
            error_details = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "api_url": API_URL,
                "model": model_name,
                "traceback": traceback.format_exc()
            }
            log_error(f"调用LLM API时发生未知错误 (尝试 {attempt + 1}/{retries}), 模型: {model_name}", error_details,
                      model_name=model_name)
            await asyncio.sleep(1 * (attempt + 1))

    # 所有重试都失败
    error_summary = {
        "total_attempts": retries,
        "api_url": API_URL,
        "model": model_name,
        "prompt_length": len(prompt)
    }
    log_error(f"LLM API调用失败，模型: {model_name}，已重试{retries}次，所有尝试均失败", error_summary,
              model_name=model_name)
    return {"error": "所有API调用尝试均失败，请检查网络连接和API配置"}


def extract_sample_cases(json_data, max_cases=None):
    """
    从JSON数据中提取样本测试用例

    :param json_data: 原始JSON数据
    :param max_cases: 最大提取的测试用例数量，None表示不限制
    :return: 样本测试用例
    """
    try:
        data = json.loads(json_data)

        # 提取所有测试用例
        all_cases = []

        # 处理test_cases.json格式
        if isinstance(data, dict) and "testcases" in data:
            testcases = data["testcases"]
            if isinstance(testcases, dict) and "test_cases" in testcases:
                all_cases = testcases["test_cases"] if max_cases is None else testcases["test_cases"][:max_cases]
            elif isinstance(testcases, list):
                all_cases = testcases if max_cases is None else testcases[:max_cases]

        # 处理golden_cases.json格式
        elif isinstance(data, dict) and "test_cases" in data:
            test_cases = data["test_cases"]
            if isinstance(test_cases, dict):
                # 将各类别的测试用例合并
                for category, cases in test_cases.items():
                    all_cases.extend(cases if max_cases is None else cases[:max_cases // len(test_cases.keys())])
                    if max_cases is not None and len(all_cases) >= max_cases:
                        all_cases = all_cases[:max_cases]
                        break

        # 如果找不到测试用例，尝试从顶层提取
        if not all_cases and isinstance(data, list):
            all_cases = data if max_cases is None else data[:max_cases]

        # 构建样本数据
        sample_data = {
            "success": True,
            "testcases": all_cases
        }

        return json.dumps(sample_data, ensure_ascii=False)
    except Exception as e:
        log_error("提取样本测试用例失败", e)
        return json_data[:MAX_TOKEN_SIZE]  # 返回原始数据的一部分
