import sentry_sdk

from core.config import Settings
from core.observability import init_sentry


def _settings(dsn: str | None) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost/0",
        sentry_dsn=dsn,
    )


def test_init_sentry_noop_when_dsn_missing(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.append(kwargs))
    init_sentry(_settings(None))
    assert captured == []


def test_init_sentry_initialises_when_dsn_set(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.append(kwargs))
    dsn = "https://public@o0.ingest.sentry.io/1"
    init_sentry(_settings(dsn))
    assert len(captured) == 1
    assert captured[0]["dsn"] == dsn
    assert captured[0]["send_default_pii"] is False
    assert 0.0 <= captured[0]["traces_sample_rate"] <= 1.0
