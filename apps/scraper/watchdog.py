"""Hourly liveness check on the scraper CronJob.

Reads dsa:last_scrape_completed_at from Redis (written by the scraper after
each successful run) and pings Slack if the value is missing or older than
24 hours. Runs as its own CronJob on the cluster (k8s/watchdog-cronjob.yaml)
so it stays alive when the scraper itself is dead.

Exit code 0 in both the OK and "raised an alert" paths — this is an
operational notifier, not part of the build pipeline.
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

from apps.api.deps import get_redis
from core.config import get_settings
from core.notify import notify_slack
from core.observability import init_sentry
from core.timestamps import read_data_updated_at

logger = logging.getLogger("apps.scraper.watchdog")

STALE_THRESHOLD = timedelta(hours=24)


async def _amain() -> int:
    settings = get_settings()
    redis = get_redis()
    last = await read_data_updated_at(redis)

    if last is None:
        message = ":warning: dsa-api watchdog: no successful scrape recorded in Redis"
        logger.warning(message)
        await notify_slack(settings.slack_webhook_url, message)
        return 0

    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        logger.error("unparseable timestamp in Redis: %r", last)
        await notify_slack(
            settings.slack_webhook_url,
            f":warning: dsa-api watchdog: unparseable last_scrape timestamp in Redis: {last!r}",
        )
        return 0

    age = datetime.now(UTC) - last_dt
    if age > STALE_THRESHOLD:
        message = (
            f":warning: dsa-api watchdog: last successful scrape was "
            f"{age} ago (threshold 24h, last_scrape={last})"
        )
        logger.warning(message)
        await notify_slack(settings.slack_webhook_url, message)
    else:
        logger.info("scrape is fresh: last_scrape=%s, age=%s", last, age)

    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_sentry(get_settings())
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
