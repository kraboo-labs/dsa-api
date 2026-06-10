import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.routers import waitlist
from core.config import Settings, get_settings


def _resend_settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://x:x@localhost/x",
        "redis_url": "redis://localhost:6379/0",
        "resend_api_key": "re_test_key",
        "resend_audience_id": "aud_123",
    }
    return Settings(**{**defaults, **overrides})


def test_root_omits_waitlist_when_unset(monkeypatch):
    monkeypatch.delenv("DSA_WAITLIST_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        body = client.get("/").json()
    assert "waitlist" not in body
    get_settings.cache_clear()


def test_root_and_docs_expose_waitlist_when_set(monkeypatch):
    url = "https://tally.so/r/test"
    monkeypatch.setenv("DSA_WAITLIST_URL", url)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/").json()["waitlist"] == url
        # The CTA (with the URL) is woven into the OpenAPI description shown in docs.
        assert url in client.get("/openapi.json").json()["info"]["description"]
    get_settings.cache_clear()


# --- POST /v1/waitlist (Resend-backed) ---


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_subscribe_creates_contact():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(201, json={"id": "c_1"})

    ok = await waitlist.subscribe(
        "dev@platform.eu", _resend_settings(), client=_mock_client(handler)
    )
    assert ok is True
    assert seen["url"] == "https://api.resend.com/audiences/aud_123/contacts"
    assert seen["auth"] == "Bearer re_test_key"
    assert b"dev@platform.eu" in seen["body"]


@pytest.mark.asyncio
async def test_subscribe_treats_existing_contact_as_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"name": "conflict"})

    ok = await waitlist.subscribe(
        "dev@platform.eu", _resend_settings(), client=_mock_client(handler)
    )
    assert ok is True


@pytest.mark.asyncio
async def test_subscribe_returns_false_on_resend_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"name": "server_error"})

    ok = await waitlist.subscribe(
        "dev@platform.eu", _resend_settings(), client=_mock_client(handler)
    )
    assert ok is False


@pytest.mark.asyncio
async def test_subscribe_sends_confirmation_when_from_is_set():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(201, json={"id": "x"})

    settings = _resend_settings(resend_from="dsa-api <hello@dsa-api.com>")
    ok = await waitlist.subscribe("dev@platform.eu", settings, client=_mock_client(handler))
    assert ok is True
    assert requests == [
        "https://api.resend.com/audiences/aud_123/contacts",
        "https://api.resend.com/emails",
    ]


@pytest.mark.asyncio
async def test_subscribe_confirmation_failure_does_not_fail_signup():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/emails":
            return httpx.Response(403, json={"name": "domain_not_verified"})
        return httpx.Response(201, json={"id": "x"})

    settings = _resend_settings(resend_from="dsa-api <hello@dsa-api.com>")
    ok = await waitlist.subscribe("dev@platform.eu", settings, client=_mock_client(handler))
    assert ok is True


def test_endpoint_404_when_resend_not_configured(monkeypatch):
    for var in ("DSA_RESEND_API_KEY", "DSA_RESEND_AUDIENCE_ID"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/waitlist", json={"email": "dev@platform.eu"})
    assert r.status_code == 404
    get_settings.cache_clear()


def test_endpoint_subscribes_when_configured(monkeypatch):
    monkeypatch.setenv("DSA_RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("DSA_RESEND_AUDIENCE_ID", "aud_123")
    get_settings.cache_clear()

    async def fake_subscribe(email, settings, **kwargs):
        fake_subscribe.called_with = email
        return True

    monkeypatch.setattr(waitlist, "subscribe", fake_subscribe)
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/waitlist", json={"email": "dev@platform.eu"})
    assert r.status_code == 202
    assert r.json() == {"status": "subscribed"}
    assert fake_subscribe.called_with == "dev@platform.eu"
    get_settings.cache_clear()


def test_endpoint_502_when_resend_fails(monkeypatch):
    monkeypatch.setenv("DSA_RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("DSA_RESEND_AUDIENCE_ID", "aud_123")
    get_settings.cache_clear()

    async def fake_subscribe(email, settings, **kwargs):
        return False

    monkeypatch.setattr(waitlist, "subscribe", fake_subscribe)
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/waitlist", json={"email": "dev@platform.eu"})
    assert r.status_code == 502
    get_settings.cache_clear()


def test_endpoint_rejects_invalid_email(monkeypatch):
    monkeypatch.setenv("DSA_RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("DSA_RESEND_AUDIENCE_ID", "aud_123")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422
    get_settings.cache_clear()
