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

    source_url: str = "https://digital-strategy.ec.europa.eu/en/policies/trusted-flaggers-under-dsa"
    user_agent: str = "dsa-api-scraper/0.1 (+https://dsa-api.com)"

    sentry_dsn: str | None = None

    # Slack incoming webhook URL (https://hooks.slack.com/services/...).
    # When set, the scraper posts on hard failures and the watchdog CronJob
    # alerts if the last successful scrape is older than 24h.
    slack_webhook_url: str | None = None

    # Directory (relative to cwd) where the scraper drops captured HTML snapshots
    # in dev. In prod this should point at a path mounted from object storage.
    snapshot_dir: str = "snapshots"

    # Local clone (or just a directory in dev) of the dsa-data open-data repo
    # the scraper exports trusted-flaggers.json/csv and changelog.json into
    # after each successful run.
    data_export_dir: str = "dsa-data"

    # When set, the scraper commits+pushes the dsa-data dir on every scrape
    # that produced at least one created/updated/removed/restored row.
    # Leave unset in dev to skip publishing.
    data_export_remote: str | None = None
    data_export_branch: str = "main"
    data_export_committer_name: str = "dsa-api bot"
    data_export_committer_email: str = "bot@dsa-api.com"

    # PRD §6: per-IP sliding window.
    rate_limit_per_minute: int = 60
    rate_limit_per_day: int = 5000

    disclaimer: str = "not-a-source-of-truth-see-source-url"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
