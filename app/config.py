"""Configuration loaded from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = "change-me"
    telegram_allowed_user_ids: str = ""  # comma-separated

    # Vision
    vision_provider: str = "gemini"  # "gemini" | "openai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Google Sheets
    google_sheets_credentials_file: str = "./service-account.json"
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet_name: str = "Meals"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = "sqlite:///./fooder.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def allowed_user_ids(self) -> set[int]:
        raw = (self.telegram_allowed_user_ids or "").strip()
        if not raw:
            return set()
        return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


settings = Settings()
