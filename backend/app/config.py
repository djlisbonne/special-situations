from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = ""  # blank = default (https://api.openai.com/v1)
    openai_organization: str = ""

    sec_edgar_user_agent: str = "Greenblatt Tool research@example.com"

    # Massive (formerly Polygon.io). The `massive` SDK handles base URL
    # routing itself (api.massive.com with api.polygon.io still supported).
    polygon_api_key: str = ""

    # Relative to the working directory (backend/ when run per the docs).
    # On the Pi, override with an absolute path — see DEPLOY.md.
    database_url: str = "sqlite:///./data/greenblatt.db"

    scan_lookback_days: int = 30
    scan_cron_hour: int = 21
    scan_cron_minute: int = 15

    # Heavy model: filing extraction, scoring, chat
    openai_model_primary: str = "gpt-4o"
    # Fast model: cheap classification / fallback
    openai_model_fast: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
