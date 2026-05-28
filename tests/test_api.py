from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from apps.api.deps import get_db_session
from apps.api.main import create_app


class _FakeResult:
    def scalar(self) -> int:
        return 1


class _FakeSession:
    async def execute(self, _stmt) -> _FakeResult:
        return _FakeResult()


async def _ok_session() -> AsyncIterator[_FakeSession]:
    yield _FakeSession()


def test_health_returns_ok_when_db_ok():
    app = create_app()
    app.dependency_overrides[get_db_session] = _ok_session
    with TestClient(app) as client:
        response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert response.headers["X-Source-URL"]
    assert response.headers["X-Disclaimer"] == "not-a-source-of-truth-see-source-url"


def test_version_returns_200():
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.0.1"
    assert body["environment"]
