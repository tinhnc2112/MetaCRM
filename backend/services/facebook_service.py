import httpx

from config import settings


class FacebookService:
    async def send_text_message(self, recipient_id: str, text: str) -> dict:
        if not settings.page_access_token:
            raise RuntimeError("PAGE_ACCESS_TOKEN is not configured")

        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text[:2000]},
        }
        params = {"access_token": settings.page_access_token}

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.facebook_graph_url, params=params, json=payload)
            response.raise_for_status()
            return response.json()
