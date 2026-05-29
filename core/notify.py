import logging

import httpx

logger = logging.getLogger(__name__)


async def notify_slack(
    webhook_url: str | None,
    message: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> bool:
    """POST a plain-text message to a Slack incoming webhook.

    No-op when webhook_url is None (dev runs without Slack). Best-effort
    on failure: anything other than HTTP 200 is logged and swallowed so
    a Slack outage never affects the operation that triggered the alert.
    Returns True only on a clean 200.
    """
    if not webhook_url:
        return False

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(webhook_url, json={"text": message})
        if response.status_code != 200:
            logger.warning(
                "slack webhook returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True
    except Exception:
        logger.exception("failed to POST to slack webhook")
        return False
    finally:
        if own_client:
            await client.aclose()
