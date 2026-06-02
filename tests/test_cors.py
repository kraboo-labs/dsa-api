from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_cors_allows_any_origin_and_exposes_headers():
    # Hits "/" (not /v1/) so the rate limiter — and thus Redis — is skipped;
    # we only care that the CORS layer tagged the cross-origin response.
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/", headers={"Origin": "https://example.org"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    expose = r.headers.get("access-control-expose-headers", "")
    assert "X-Source-URL" in expose
    assert "X-Disclaimer" in expose


def test_cors_preflight_is_answered_without_rate_limiting():
    # A preflight OPTIONS must be short-circuited by the (outermost) CORS
    # middleware before the rate limiter runs, so it needs no Redis and returns
    # the allowed methods for the public v1 surface.
    app = create_app()
    with TestClient(app) as client:
        r = client.options(
            "/v1/trusted-flaggers",
            headers={
                "Origin": "https://example.org",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "GET" in r.headers.get("access-control-allow-methods", "")
