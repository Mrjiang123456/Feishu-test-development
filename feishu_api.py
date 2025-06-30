import os
import re
import httpx
import logging
from urllib.parse import urlparse, parse_qs

# 日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 飞书应用配置（请自行配置环境变量或替换默认值）
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID") or "cli_a8d4ea8f8efcd00c"
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET") or "VSi6TL9ansJFJsUVYJUPrkTLCmoqataV"
FEISHU_APP_USER_ACCESS_TOKEN = os.environ.get("FEISHU_APP_USER_ACCESS_TOKEN") or "u-dMvdhjiYR7nXbut..MoDbk1l7bSx0karXww040082HMX"

def is_docx_url(url: str) -> bool:
    """判断是否是飞书docx/docs文档链接"""
    return "feishu.cn/docx/" in url or "feishu.cn/docs/" in url

def is_wiki_url(url: str) -> bool:
    """判断是否是飞书wiki链接"""
    return "feishu.cn/wiki/" in url

def extract_doc_token(url: str) -> str:
    """从链接中提取doc_token或wiki的node_token"""
    logger.info(f"提取doc token，处理链接: {url}")
    match = re.search(r'/(docx|docs|wiki)/([a-zA-Z0-9]+)', url)
    if match:
        token = match.group(2)
        logger.info(f"成功提取token: {token}")
        return token
    error_msg = "无法从链接中提取token，请确认链接格式"
    logger.error(error_msg)
    raise ValueError(error_msg)

def extract_user_access_token(url: str) -> str:
    """从URL的查询参数中提取user_access_token，若无则返回全局默认"""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    token_list = query.get("userAccessToken") or query.get("user_access_token")
    token = token_list[0] if token_list else FEISHU_APP_USER_ACCESS_TOKEN
    logger.info(f"提取user_access_token: {token} (来自链接: {url})")
    return token

def extract_image_links_from_markdown(md: str) -> list[str]:
    """从Markdown内容中用正则提取所有图片链接"""
    images = re.findall(r'!\[.*?\]\((.*?)\)', md)
    logger.info(f"从markdown中提取到图片链接数量: {len(images)}")
    return images

async def get_tenant_access_token() -> str:
    """请求获取tenant_access_token，用于docx文档调用"""
    logger.info("请求tenant_access_token开始")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
        )
        resp.raise_for_status()
        data = resp.json()
        if "tenant_access_token" not in data:
            error_msg = f"获取tenant_access_token失败: {data}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        token = data["tenant_access_token"]
        logger.info("获取tenant_access_token成功")
        return token

async def get_feishu_doc_content(url: str) -> dict:
    """
    根据链接类型（docx/docs/wiki）获取飞书文档内容和图片链接。
    返回字典：{"text": markdown文本, "images": 图片链接列表}
    """
    logger.info(f"开始获取飞书文档内容，URL: {url}")

    if is_docx_url(url):
        # 处理docx/docs文档
        logger.info("识别为 docx/docs 文档")
        doc_token = extract_doc_token(url)
        tenant_token = await get_tenant_access_token()
        headers = {"Authorization": f"Bearer {tenant_token}"}
        params = {
            "doc_token": doc_token,
            "doc_type": "docx",
            "content_type": "markdown",
            "lang": "zh"
        }
        async with httpx.AsyncClient(timeout=10) as client:
            logger.info("调用 docs/v1/content 接口获取文档内容")
            resp = await client.get("https://open.feishu.cn/open-apis/docs/v1/content", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            markdown_content = data["data"]["content"]
            images = extract_image_links_from_markdown(markdown_content)
            logger.info("成功获取文档内容及图片链接")
            return {"text": markdown_content, "images": images}

    elif is_wiki_url(url):
        # 处理wiki文档
        logger.info("识别为 wiki 文档")
        user_access_token = extract_user_access_token(url)
        headers = {"Authorization": f"Bearer {user_access_token}"}
        node_token = extract_doc_token(url)

        async with httpx.AsyncClient(timeout=10) as client:
            logger.info("获取知识库空间列表")
            space_resp = await client.get("https://open.feishu.cn/open-apis/wiki/v2/spaces", headers=headers)
            space_resp.raise_for_status()
            spaces = space_resp.json().get("data", {}).get("items", [])
            if not spaces:
                error_msg = "未找到任何知识库空间"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            space_id = None
            matched_node = None
            logger.info(f"查找 node_token={node_token} 所属空间和节点")
            for space in spaces:
                sid = space["space_id"]
                node_resp = await client.get(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{sid}/nodes", headers=headers)
                node_resp.raise_for_status()
                nodes = node_resp.json().get("data", {}).get("items", [])
                for node in nodes:
                    if node.get("node_token") == node_token:
                        space_id = sid
                        matched_node = node
                        logger.info(f"匹配到空间ID: {space_id}，节点: {node_token}")
                        break
                if space_id:
                    break

            if not matched_node:
                error_msg = f"未找到 node_token={node_token} 所属空间或节点"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            obj_token = matched_node.get("obj_token")
            if not obj_token:
                error_msg = "未找到对应节点的 obj_token"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

            params = {
                "doc_token": obj_token,
                "doc_type": "docx",
                "content_type": "markdown",
                "lang": "zh"
            }
            logger.info("调用 docs/v1/content 接口获取 wiki 内容")
            content_resp = await client.get("https://open.feishu.cn/open-apis/docs/v1/content", headers=headers, params=params)
            content_resp.raise_for_status()
            markdown_content = content_resp.json()["data"]["content"]
            images = extract_image_links_from_markdown(markdown_content)
            logger.info("成功获取 wiki 文档内容及图片链接")
            return {"text": markdown_content, "images": images}

    else:
        error_msg = "链接不是合法的飞书 docx 或 wiki 文档"
        logger.error(error_msg)
        raise ValueError(error_msg)
