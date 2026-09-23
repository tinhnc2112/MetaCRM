import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    page_access_token: str = os.getenv("PAGE_ACCESS_TOKEN", "")
    verify_token: str = os.getenv("VERIFY_TOKEN", "change-me")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ai_sale_bot.db")
    facebook_graph_url: str = "https://graph.facebook.com/v19.0/me/messages"
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


settings = Settings()
