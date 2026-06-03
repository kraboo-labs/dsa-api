from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.config import get_settings


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
