from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session

from config import settings
from database import Base, engine, get_db
from services.facebook_service import FacebookService
from services.openai_service import OpenAIService
from services.order_service import OrderService

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MetaCRM AI Sale BOT", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/webhook")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.verify_token:
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else hub_challenge
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    payload = await request.json()
    facebook = FacebookService()
    openai = OpenAIService()
    orders = OrderService(db)

    try:
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event.get("sender", {}).get("id")
                message_text = event.get("message", {}).get("text")

                if not sender_id or not message_text:
                    continue

                ai_result = await openai.generate_reply(message_text=message_text, sender_id=sender_id)
                reply_text = ai_result.get("reply") or "Cảm ơn bạn đã nhắn tin. Shop sẽ phản hồi ngay ạ."

                await facebook.send_text_message(recipient_id=sender_id, text=reply_text)

                if ai_result.get("intent") == "order_confirmed":
                    orders.create_order_from_ai(sender_id=sender_id, customer_message=message_text, ai_result=ai_result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {exc}") from exc

    return {"status": "received"}


@app.get("/orders")
def list_orders(db: Session = Depends(get_db)):
    return OrderService(db).list_orders()
