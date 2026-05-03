"""Configuration loaded from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = "change-me"

    # Vision
    vision_provider: str = "gemini"  # "gemini" | "openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-exp"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Fitbit
    fitbit_client_id: str = ""
    fitbit_client_secret: str = ""
    fitbit_redirect_uri: str = "http://localhost:8000/fitbit/callback"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite:///./fooder.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
