import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.main import create_app
from apps.api.routers import waitlist as wl
from core.config import get_settings


def _cfg(**overrides):
    return get_settings().model_copy(update=overrides)


@pytest_asyncio.fixture
async def client_with_settings():
    def make(settings):
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        transport = ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    return make


async def test_waitlist_503_when_unconfigured(client_with_settings):
    async with client_with_settings(_cfg(resend_api_key=None, resend_audience_id=None)) as c:
        r = await c.post("/v1/waitlist", json={"email": "a@b.com"})
    assert r.status_code == 503


async def test_waitlist_422_on_bad_email(client_with_settings):
    async with client_with_settings(_cfg(resend_api_key="x", resend_audience_id="y")) as c:
        r = await c.post("/v1/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422


async def test_waitlist_subscribes_and_normalizes(client_with_settings, monkeypatch):
    seen = {}

    async def fake_add(settings, email):
        seen["email"] = email

    monkeypatch.setattr(wl, "_resend_add_contact", fake_add)
    async with client_with_settings(_cfg(resend_api_key="x", resend_audience_id="y")) as c:
        r = await c.post("/v1/waitlist", json={"email": "  New@Example.COM "})
    assert r.status_code == 202
    assert r.json()["ok"] is True
    assert seen["email"] == "new@example.com"


async def test_waitlist_honeypot_drops_silently(client_with_settings, monkeypatch):
    called = False

    async def fake_add(settings, email):
        nonlocal called
        called = True

    monkeypatch.setattr(wl, "_resend_add_contact", fake_add)
    async with client_with_settings(_cfg(resend_api_key="x", resend_audience_id="y")) as c:
        r = await c.post("/v1/waitlist", json={"email": "bot@spam.com", "company": "Acme Bots"})
    assert r.status_code == 202
    assert called is False
