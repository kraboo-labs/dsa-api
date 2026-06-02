from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Make a libpq-style Postgres URL safe for SQLAlchemy + asyncpg.

    DigitalOcean (and most managed Postgres) hand out connection strings like
    ``postgresql://user:pass@host:25060/db?sslmode=require``. Passed straight to
    ``create_async_engine`` that picks the sync ``psycopg2`` driver (not in the
    image) and asyncpg rejects the libpq ``sslmode`` keyword. We rewrite the
    bare scheme to the asyncpg driver and translate ``sslmode`` -> ``ssl``
    (asyncpg accepts the same value names: require/verify-ca/verify-full/...).
    Already-correct URLs (``postgresql+asyncpg://...`` with no ``sslmode``)
    pass through untouched.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    if scheme.endswith("+asyncpg") and "sslmode=" in parts.query:
        query = [
            ("ssl", v) if k == "sslmode" else (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
        ]
        new_query = urlencode(query)
    else:
        new_query = parts.query

    if scheme == parts.scheme and new_query == parts.query:
        return url
    return urlunsplit((scheme, parts.netloc, parts.path, new_query, parts.fragment))


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

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        return normalize_database_url(v)

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
