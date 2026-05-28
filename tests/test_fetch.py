import hashlib

import httpx
import pytest

from apps.scraper.fetch import FetchError, fetch


def _make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_returns_body_status_and_sha256():
    body = b'{"ok": true}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _make_client(handler) as client:
        result = await fetch("https://example.test/data.json", client=client)

    assert result.status_code == 200
    assert result.body == body
    assert result.content_hash == hashlib.sha256(body).hexdigest()


async def test_fetch_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    async with _make_client(handler) as client:
        result = await fetch(
            "https://example.test/x", client=client, max_attempts=3, backoff_base=0
        )

    assert result.status_code == 200
    assert calls["n"] == 3


async def test_fetch_does_not_retry_4xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    async with _make_client(handler) as client:
        with pytest.raises(FetchError, match="client error 404"):
            await fetch("https://example.test/x", client=client, max_attempts=3, backoff_base=0)

    assert calls["n"] == 1


async def test_fetch_raises_after_max_attempts_on_persistent_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502)

    async with _make_client(handler) as client:
        with pytest.raises(FetchError, match="failed after 2 attempts"):
            await fetch("https://example.test/x", client=client, max_attempts=2, backoff_base=0)

    assert calls["n"] == 2


async def test_fetch_sends_user_agent_header():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(200, content=b"")

    async with _make_client(handler) as client:
        await fetch("https://example.test/x", client=client, user_agent="dsa-test/1.0")

    assert captured["ua"] == "dsa-test/1.0"
