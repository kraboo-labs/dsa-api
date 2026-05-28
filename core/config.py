from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DSA_",
        extra="ignore",
    )

    environment: str = "development"
    debug: bool = False

    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    redis_url: str

    source_url: str = "https://digital-strategy.ec.europa.eu/en/policies/trusted-flaggers"
    user_agent: str = "dsa-api-scraper/0.1 (+https://dsa-api.com)"

    sentry_dsn: str | None = None

    disclaimer: str = "not-a-source-of-truth-see-source-url"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
