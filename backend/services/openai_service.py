import json

import httpx

from config import settings


SYSTEM_PROMPT = """
Bạn là AI Sale BOT cho shop online. Hãy tư vấn ngắn gọn, thân thiện bằng tiếng Việt.
Nếu khách đã chốt mua hoặc cung cấp đủ thông tin đặt hàng, trả về intent là order_confirmed.
Luôn trả về JSON hợp lệ với các field:
reply, intent, customer_name, phone, address, product, quantity, note.
Nếu chưa có thông tin thì để null, quantity mặc định 1.
""".strip()


class OpenAIService:
    async def generate_reply(self, message_text: str, sender_id: str) -> dict:
        if not settings.openai_api_key:
            return {
                "reply": "Shop đã nhận tin nhắn của bạn. Bạn cho shop xin sản phẩm, số lượng, số điện thoại và địa chỉ nhận hàng nhé ạ.",
                "intent": "needs_more_info",
                "customer_name": None,
                "phone": None,
                "address": None,
                "product": None,
                "quantity": 1,
                "note": "OPENAI_API_KEY is not configured",
            }

        payload = {
            "model": settings.openai_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"sender_id={sender_id}\nmessage={message_text}"},
            ],
        }
        headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"reply": content, "intent": "unknown"}

        data.setdefault("reply", "Cảm ơn bạn, shop đã nhận thông tin ạ.")
        data.setdefault("intent", "unknown")
        data.setdefault("quantity", 1)
        return data
