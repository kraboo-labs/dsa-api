import sentry_sdk

from core.config import Settings


def init_sentry(settings: Settings) -> None:
    """No-op if DSA_SENTRY_DSN is unset. Otherwise wires up sentry-sdk.

    sentry-sdk auto-detects FastAPI and stdlib logging, so init() alone is
    enough for both the API process and the scraper CronJob — unhandled
    exceptions, HTTP errors, and ERROR-level log records all flow to Sentry.
    """
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        # Conservative until we see real traffic; bump once Sentry quota allows.
        traces_sample_rate=0.1,
        # Don't ship request headers / cookies / IPs by default — the public API
        # doesn't process PII but emails are organizational and arguably borderline.
        send_default_pii=False,
    )
