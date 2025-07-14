import os
import httpx
from typing import List, Optional

ARK_API_KEY = os.environ.get("ARK_API_KEY") or "ac7c2d46-edf5-4a90-b83e-c89cf078d5b9"
ARK_MODEL_ID = "deepseek-r1-250528"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


async def call_model3(prompt: str, img_urls: Optional[List[str]] = None, temperature: float = 0.7) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ARK_API_KEY}"
    }

    message_content = []

    if img_urls:
        for url in img_urls:
            message_content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

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
        ],
        "temperature": temperature
    }

    try:
        async with httpx.AsyncClient(timeout=1000.0) as client:
            response = await client.post(f"{ARK_BASE_URL}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        print(f"Request error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
