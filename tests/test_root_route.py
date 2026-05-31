import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.main import create_app


@pytest_asyncio.fixture
async def client():
    """No DB dependency — root route doesn't open a session."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_root_on_api_host_returns_pointer_document(client):
    response = await client.get("/", headers={"host": "api.dsa-api.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["docs"] == "/docs"
    assert body["openapi"] == "/openapi.json"
    assert body["source"]
    assert body["name"] == "DSA Trusted Flaggers API"


async def test_root_on_docs_host_redirects_to_swagger(client):
    response = await client.get(
        "/",
        headers={"host": "docs.dsa-api.com"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


async def test_root_on_docs_host_is_case_insensitive(client):
    response = await client.get(
        "/",
        headers={"host": "DOCS.DSA-API.COM"},
        follow_redirects=False,
    )
    assert response.status_code == 307


async def test_root_on_unknown_host_returns_pointer(client):
    # Internal / localhost / cluster IP requests behave like the api host.
    response = await client.get("/", headers={"host": "localhost"})
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


async def test_docs_endpoint_is_actually_reachable(client):
    response = await client.get("/docs")
    assert response.status_code == 200
    # FastAPI serves the Swagger UI HTML at /docs by default.
    assert "swagger" in response.text.lower()
