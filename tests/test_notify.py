import httpx

from core.notify import notify_slack


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_notify_slack_returns_false_when_url_missing():
    assert await notify_slack(None, "anything") is False
    assert await notify_slack("", "anything") is False


async def test_notify_slack_posts_text_payload_to_webhook():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, text="ok")

    async with _client(handler) as c:
        ok = await notify_slack(
            "https://hooks.slack.com/services/T/B/abc",
            "scrape failed",
            client=c,
        )

    assert ok is True
    assert captured["url"].endswith("/services/T/B/abc")
    assert '"text"' in captured["body"]
    assert "scrape failed" in captured["body"]


async def test_notify_slack_swallows_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _client(handler) as c:
        ok = await notify_slack("https://hooks.slack.com/services/T/B/x", "msg", client=c)
    assert ok is False


async def test_notify_slack_swallows_transport_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    async with _client(handler) as c:
        ok = await notify_slack("https://hooks.slack.com/services/T/B/x", "msg", client=c)
    assert ok is False
