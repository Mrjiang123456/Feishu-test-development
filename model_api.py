import os
import httpx

# 模型参数配置
ARK_API_KEY = os.environ.get("ARK_API_KEY") or "82cb3741-9d83-46fe-aeee-faad19eaf765"
ARK_MODEL_ID = "doubao-seed-1-6-250615"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


# 调用豆包多模态模型，支持图片+文本联合推理
async def call_doubao_model(prompt: str, img_urls=None) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ARK_API_KEY}"
    }

    message_content = []

    # 如果提供了图片 URL，则添加图片的内容
    if img_urls:
        for url in img_urls:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

    # 添加文本 prompt
    message_content.append({
        "type": "text",
        "text": prompt
    })

    payload = {
        "model": ARK_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": message_content
            }
        ]
    }
    # 发送 POST 请求调用模型
    async with httpx.AsyncClient(timeout=100000.0) as client:
        response = await client.post(f"{ARK_BASE_URL}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
