import os
import re
import httpx
from urllib.parse import urlparse, parse_qs

# 飞书 app 配置
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID") or "cli_a8d4ea8f8efcd00c"
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET") or "VSi6TL9ansJFJsUVYJUPrkTLCmoqataV"
FEISHU_APP_USER_ACCESS_TOKEN = os.environ.get("FEISHU_APP_user_access_token") or "u-c9ieeutTZ0c832QN31JK_olg4WPg0kajj200114Gy6Of"

def is_docx_url(url: str) -> bool:
    return "feishu.cn/docx/" in url or "feishu.cn/docs/" in url

def is_wiki_url(url: str) -> bool:
    return "feishu.cn/wiki/" in url

# 从 docx/docs/wiki 链接中提取 token
def extract_doc_token(url: str) -> str:
    match = re.search(r'/(docx|docs|wiki)/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(2)
    raise ValueError("无法从链接中提取 token，请确认链接格式")

# 从 URL 查询参数提取 user_access_token，如果没有则用全局默认
def extract_user_access_token(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    token_list = query.get("userAccessToken") or query.get("user_access_token")
    return token_list[0] if token_list else FEISHU_APP_USER_ACCESS_TOKEN

# 从 Markdown 中提取图片链接
def extract_image_links_from_markdown(md: str) -> list[str]:
    return re.findall(r'!\\[.*?\\]\\((.*?)\\)', md)

# 获取 tenant_access_token，用于调用租户级 API（docx 类型）
async def get_tenant_access_token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
        )
        resp.raise_for_status()
        data = resp.json()
        if "tenant_access_token" not in data:
            raise RuntimeError(f"获取tenant_access_token失败: {data}")
        return data["tenant_access_token"]

async def get_feishu_doc_content(url: str) -> dict:
    if is_docx_url(url):
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
            resp = await client.get("https://open.feishu.cn/open-apis/docs/v1/content", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            markdown_content = data["data"]["content"]
            images = extract_image_links_from_markdown(markdown_content)
            return {"text": markdown_content, "images": images}

    elif is_wiki_url(url):
        user_access_token = extract_user_access_token(url)
        headers = {"Authorization": f"Bearer {user_access_token}"}
        node_token = extract_doc_token(url)

        async with httpx.AsyncClient(timeout=10) as client:
            space_resp = await client.get("https://open.feishu.cn/open-apis/wiki/v2/spaces", headers=headers)
            space_resp.raise_for_status()
            spaces = space_resp.json().get("data", {}).get("items", [])
            if not spaces:
                raise RuntimeError("未找到任何知识库空间")

            space_id = None
            matched_node = None
            for space in spaces:
                sid = space["space_id"]
                node_resp = await client.get(f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{sid}/nodes", headers=headers)
                node_resp.raise_for_status()
                nodes = node_resp.json().get("data", {}).get("items", [])
                for node in nodes:
                    if node.get("node_token") == node_token:
                        space_id = sid
                        matched_node = node
                        break
                if space_id:
                    break

            if not matched_node:
                raise RuntimeError(f"未找到 node_token={node_token} 所属空间或节点")

            obj_token = matched_node.get("obj_token")
            if not obj_token:
                raise RuntimeError("未找到对应节点的 obj_token")

            params = {
                "doc_token": obj_token,
                "doc_type": "docx",
                "content_type": "markdown",
                "lang": "zh"
            }
            content_resp = await client.get("https://open.feishu.cn/open-apis/docs/v1/content", headers=headers, params=params)
            content_resp.raise_for_status()
            markdown_content = content_resp.json()["data"]["content"]
            images = extract_image_links_from_markdown(markdown_content)
            return {"text": markdown_content, "images": images}

    else:
        raise ValueError("链接不是合法的飞书 docx 或 wiki 文档")
