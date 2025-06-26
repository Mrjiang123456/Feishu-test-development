import re
import httpx
from bs4 import BeautifulSoup


# 文本清洗函数：去除多余空格与换行
def clean_text(text: str) -> str:
    """清洗文本，去除多余空格和特殊符号"""
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# 网页抓取函数：提取页面文字和图片地址，用于多模态模型输入
async def fetch_webpage_content(url: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    # 抽取文字内容
    tags = soup.find_all(['p', 'div', 'li', 'span'])
    text = "\n".join(tag.get_text(strip=True) for tag in tags if tag.get_text(strip=True))
    # 抽取图片地址
    images = soup.find_all("img")
    image_urls = [img.get("src") for img in images if img.get("src")]

    result = f"网页正文内容：\n{text}\n\n网页包含的图片链接如下：\n"
    result += "\n".join(image_urls[:5])  # 最多显示前5张，防止太多

    return result
