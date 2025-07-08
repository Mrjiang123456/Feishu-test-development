import json
import time
import aiohttp
import asyncio
import traceback
import re
from typing import Optional, Dict
from config import API_URL, VOLC_BEARER_TOKEN, MODEL_NAME, MAX_TOKEN_SIZE, LLM_CACHE_SIZE, LLM_TEMPERATURE
from logger import log, log_error
from functools import lru_cache
import hashlib


# 简单的LRU缓存装饰器，用于缓存计算过的哈希值
@lru_cache(maxsize=128)
def _compute_hash(text):
    """计算文本的哈希值，用于缓存键"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


# 缓存字典，存储API调用结果
_api_cache = {}
_MAX_CACHE_SIZE = LLM_CACHE_SIZE  # 从配置中读取缓存大小


# 优化缓存更新函数
def _update_cache(key, value):
    """更新API缓存，如果缓存过大则移除最旧的项目"""
    _api_cache[key] = value
    # 如果缓存超过最大大小，移除最旧的条目
    if len(_api_cache) > _MAX_CACHE_SIZE:
        # 批量移除20%的旧缓存项，减少频繁清理
        items_to_remove = int(_MAX_CACHE_SIZE * 0.2)
        for _ in range(items_to_remove):
            if _api_cache:
                oldest_key = next(iter(_api_cache))
                _api_cache.pop(oldest_key, None)


async def async_call_llm(
        session: aiohttp.ClientSession,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        retries: int = 3,
        temperature: float = None
) -> Optional[Dict]:
    """
    异步调用LLM API

    :param session: aiohttp会话
    :param prompt: 用户输入的提示
    :param system_prompt: 系统角色提示
    :param retries: 重试次数
    :param temperature: 温度参数，控制生成内容的随机性
    :return: 解析后的JSON对象，失败则返回None
    """
    # 使用默认temperature或传入的temperature
    if temperature is None:
        temperature = LLM_TEMPERATURE

    # 为相同的请求使用缓存，包含temperature参数
    cache_key = _compute_hash(f"{prompt}|{system_prompt}|{MODEL_NAME}|{temperature}")
    if cache_key in _api_cache:
        log(f"从缓存返回LLM响应，prompt长度={len(prompt)}")
        return _api_cache[cache_key]

    log(f"调用LLM: prompt长度={len(prompt)}, temperature={temperature}")

    if not VOLC_BEARER_TOKEN:
        log_error("VOLC_BEARER_TOKEN未设置")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_BEARER_TOKEN}",
        "Connection": "keep-alive"  # 添加连接复用设置
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature  # 添加temperature参数
    }

    # 记录请求信息，用于诊断
    request_info = {
        "api_url": API_URL,
        "model": MODEL_NAME,
        "headers": {"Authorization": "Bearer ***[MASKED]***"},
        "prompt_length": len(prompt),
        "system_prompt_length": len(system_prompt),
        "temperature": temperature
    }

    for attempt in range(retries):
        try:
            call_start = time.time()
            log(f"尝试调用LLM API (尝试 {attempt + 1}/{retries}), 目标URL: {API_URL}")

            # 使用优化的超时设置
            async with session.post(
                    API_URL,
                    headers=headers,
                    json=payload,
                    timeout=360,  # 增加超时时间
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
                    log_error(f"LLM API调用失败，状态码: {response.status}，重试中 ({attempt + 1}/{retries})",
                              error_details)

                    # 根据错误代码调整重试策略
                    if response.status == 429:  # 速率限制
                        wait_time = 5 * (attempt + 1)
                        log(f"遇到速率限制，等待{wait_time}秒后重试", level="WARNING")
                        await asyncio.sleep(wait_time)
                    elif response.status >= 500:  # 服务器错误
                        wait_time = 2 * (attempt + 1)
                        log(f"遇到服务器错误，等待{wait_time}秒后重试", level="WARNING")
                        await asyncio.sleep(wait_time)
                    else:  # 其他错误
                        await asyncio.sleep(1 * (attempt + 1))
                    continue

                # 获取响应内容
                try:
                    response_text = await response.text()
                    if not response_text or response_text.strip() == "":
                        log_error(f"LLM API返回空响应 (尝试 {attempt + 1}/{retries})", {"empty_response": True})
                        if attempt < retries - 1:
                            await asyncio.sleep(2 * (attempt + 1))
                            continue
                        else:
                            return {"text": "API返回空响应"}

                    # 尝试解析JSON响应
                    try:
                        response_json = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        log_error(f"无法解析API响应为JSON (尝试 {attempt + 1}/{retries})", {
                            "error": str(e),
                            "response_preview": response_text[:200] + ("..." if len(response_text) > 200 else "")
                        })
                        if attempt < retries - 1:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        else:
                            # 最后一次尝试失败，返回原始文本
                            return {"text": response_text}

                    call_time = time.time() - call_start
                    log(f"LLM调用成功，耗时={call_time:.1f}秒")

                    try:
                        # 检查响应格式
                        if "choices" not in response_json or not response_json["choices"]:
                            log_error("API响应缺少choices字段", {"response_json": response_json})
                            if attempt < retries - 1:
                                await asyncio.sleep(1 * (attempt + 1))
                                continue
                            else:
                                # 返回整个响应JSON
                                return {"api_response": response_json}

                        content = response_json['choices'][0]['message']['content']
                        if not content or content.strip() == "":
                            log_error("API返回的content为空", {"response_json": response_json})
                            if attempt < retries - 1:
                                await asyncio.sleep(1 * (attempt + 1))
                                continue
                            else:
                                return {"text": "API返回空内容"}

                        # 从Markdown代码块提取JSON
                        if "```json" in content:
                            json_content = content.split("```json")[1].split("```")[0].strip()
                        elif "```mermaid" in content:
                            # 检测到mermaid代码块，直接识别为Markdown内容
                            log("检测到mermaid代码块，直接返回原始内容", level="WARNING")
                            result = {"text": content}
                            # 缓存结果
                            _update_cache(cache_key, result)
                            return result
                        elif "```" in content:
                            # 提取代码块内容
                            code_block_content = content.split("```")[1].split("```")[0].strip()
                            # 检查代码块第一行是否表明是mermaid图表
                            if code_block_content.startswith("mermaid") or code_block_content.startswith(
                                    "graph ") or code_block_content.startswith("pie"):
                                log("检测到mermaid图表代码块，直接返回原始内容", level="WARNING")
                                result = {"text": content}
                                # 缓存结果
                                _update_cache(cache_key, result)
                                return result
                            json_content = code_block_content
                        else:
                            json_content = content

                        # 如果内容以'markdown'开头，去掉这个前缀
                        if json_content.strip().startswith("markdown"):
                            json_content = json_content.strip().replace("markdown", "", 1).strip()
                            log("检测到内容以'markdown'开头，已移除此前缀", level="WARNING")

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
                            log("检测到内容包含mermaid图表，识别为Markdown格式", level="WARNING")

                        if is_markdown:
                            log("检测到内容是Markdown格式，不尝试解析为JSON", level="WARNING")
                            result = {"text": json_content.strip()}
                            # 缓存结果
                            _update_cache(cache_key, result)
                            return result

                        # 尝试解析为JSON
                        if json_content and json_content.strip():
                            try:
                                parsed_json = json.loads(json_content)
                                # 缓存结果
                                _update_cache(cache_key, parsed_json)
                                return parsed_json
                            except json.JSONDecodeError as e:
                                # 尝试修复常见的JSON格式问题
                                try:
                                    # 1. 尝试将单引号替换为双引号
                                    fixed_content = json_content.replace("'", "\"")
                                    parsed_json = json.loads(fixed_content)
                                    log("通过替换单引号成功解析JSON", level="WARNING")
                                    # 缓存结果
                                    _update_cache(cache_key, parsed_json)
                                    return parsed_json
                                except json.JSONDecodeError:
                                    pass

                                try:
                                    # 2. 尝试删除前后的多余字符
                                    match = re.search(r'(\{.*\}|\[.*\])', json_content, re.DOTALL)
                                    if match:
                                        potential_json = match.group(0)
                                        parsed_json = json.loads(potential_json)
                                        log("通过提取JSON对象成功解析", level="WARNING")
                                        # 缓存结果
                                        _update_cache(cache_key, parsed_json)
                                        return parsed_json
                                except (json.JSONDecodeError, re.error):
                                    pass

                                # 记录详细的解析错误
                                error_details = {
                                    "error_type": "JSONDecodeError",
                                    "error_message": str(e),
                                    "content_preview": json_content[:100] + ("..." if len(json_content) > 100 else ""),
                                    "traceback": traceback.format_exc()
                                }

                                # 在记录错误前，检查内容是否可能是Markdown
                                if "```mermaid" in json_content or \
                                        json_content.strip().startswith("#") or \
                                        "graph " in json_content or \
                                        "pie " in json_content or \
                                        re.search(r"^(#|##|###)\s+[A-Za-z0-9\u4e00-\u9fa5]", json_content.strip(),
                                                  re.MULTILINE):
                                    log("JSON解析失败，但内容看起来像是Markdown格式，直接返回文本", level="WARNING")
                                    result = {"text": json_content}
                                    # 缓存结果
                                    _update_cache(cache_key, result)
                                    return result

                                log_error("JSON解析错误，返回原始文本", error_details)
                                # 如果不是有效的JSON，直接返回文本内容
                                result = {"text": content}
                                # 缓存结果
                                _update_cache(cache_key, result)
                                return result
                        else:
                            log_error("提取的JSON内容为空", {"original_content": content[:200]})
                            result = {"text": content}
                            # 缓存结果
                            _update_cache(cache_key, result)
                            return result

                    except (KeyError, IndexError) as e:
                        error_details = {
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "response_json": response_json,
                            "traceback": traceback.format_exc()
                        }
                        log_error("解析LLM响应失败", error_details)
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
                    log_error(f"处理API响应时发生错误 (尝试 {attempt + 1}/{retries})", error_details)
                    await asyncio.sleep(1 * (attempt + 1))

        except aiohttp.ClientConnectorError as e:
            error_details = {
                "error_type": "连接错误",
                "error_message": str(e),
                "api_url": API_URL,
                "traceback": traceback.format_exc()
            }
            log_error(f"无法连接到LLM API服务器 (尝试 {attempt + 1}/{retries})", error_details)
            await asyncio.sleep(2 * (attempt + 1))
        except aiohttp.ClientError as e:
            error_details = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "api_url": API_URL,
                "traceback": traceback.format_exc()
            }
            log_error(f"HTTP客户端错误 (尝试 {attempt + 1}/{retries})", error_details)
            await asyncio.sleep(1 * (attempt + 1))
        except asyncio.TimeoutError as e:
            error_details = {
                "error_type": "请求超时",
                "timeout_seconds": 180,
                "api_url": API_URL
            }
            log_error(f"LLM API请求超时 (尝试 {attempt + 1}/{retries})", error_details)
            await asyncio.sleep(1 * (attempt + 1))
        except Exception as e:
            error_details = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "api_url": API_URL,
                "traceback": traceback.format_exc()
            }
            log_error(f"调用LLM API时发生未知错误 (尝试 {attempt + 1}/{retries})", error_details)
            await asyncio.sleep(1 * (attempt + 1))

    # 所有重试都失败
    error_summary = {
        "total_attempts": retries,
        "api_url": API_URL,
        "model": MODEL_NAME,
        "prompt_length": len(prompt)
    }
    log_error(f"LLM API调用失败，已重试{retries}次，所有尝试均失败", error_summary)
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