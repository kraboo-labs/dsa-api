from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session, get_redis
from apps.api.routers import changes, stats, trusted_flaggers
from core.config import Settings, get_settings
from core.observability import init_sentry
from core.ratelimit import LimitConfig, check_limit
from core.timestamps import read_data_updated_at


def _client_ip(request: Request) -> str:
    """Caller IP, honoring the first hop in X-Forwarded-For if present.
    Behind a trusted proxy in prod we should restrict whose header we trust;
    for MVP this is fine."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def create_app() -> FastAPI:
    settings = get_settings()
    # Must run before FastAPI() so the integration picks up the app on init.
    init_sentry(settings)
    description = (
        "Machine-readable mirror of the EU Trusted Flaggers register "
        "(DSA Article 22(5)). Not a source of truth — see X-Source-URL."
    )
    if settings.waitlist_url:
        description += (
            "\n\n🔔 **Coming soon — Pro tier:** webhooks on register changes, "
            "point-in-time audit, bulk export, and higher rate limits. "
            f"[Join the waitlist]({settings.waitlist_url})."
        )
    app = FastAPI(
        title="DSA Trusted Flaggers API",
        description=description,
        version="0.0.1",
    )

    minute_limit = LimitConfig("minute", 60, settings.rate_limit_per_minute)
    day_limit = LimitConfig("day", 86400, settings.rate_limit_per_day)

    # Operational endpoints are exempt from rate limiting. The k8s liveness
    # (/v1/version) and readiness (/v1/health) probes hit these every 10-30s
    # from a single node IP — metering them exhausts that IP's per-day quota
    # (5000) within hours, after which the pod 429s its OWN probes and
    # CrashLoops. They carry no data, so there's nothing to meter anyway.
    unmetered_paths = {"/v1/health", "/v1/version"}

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        # Only meter the public v1 data surface; /docs, /openapi.json, the
        # health/version probes, etc. stay free.
        if not request.url.path.startswith("/v1/") or request.url.path in unmetered_paths:
            return await call_next(request)
        redis = get_redis()
        ip = _client_ip(request)
        for cfg in (minute_limit, day_limit):
            decision = await check_limit(redis, ip, cfg)
            if not decision.allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"rate limit exceeded ({cfg.name})",
                        "limit": cfg.max_requests,
                        "window_seconds": cfg.window_seconds,
                    },
                    headers={"Retry-After": str(decision.retry_after)},
                )
        response = await call_next(request)
        # Surface remaining headroom for the tighter (minute) window.
        # Best-effort: another request may have landed between the check and now.
        response.headers["X-RateLimit-Limit"] = str(minute_limit.max_requests)
        response.headers["X-RateLimit-Window-Seconds"] = str(minute_limit.window_seconds)
        return response

    @app.middleware("http")
    async def add_source_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Source-URL"] = settings.source_url
        response.headers["X-Disclaimer"] = settings.disclaimer
        # X-Data-Updated-At is populated by the scraper into Redis after each
        # successful run; missing key just means no header (per PRD it's
        # informational, not load-bearing).
        try:
            updated_at = await read_data_updated_at(get_redis())
        except Exception:
            updated_at = None
        if updated_at:
            response.headers["X-Data-Updated-At"] = updated_at
        return response

    @app.get("/v1/health")
    async def health(
        response: Response,
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict:
        try:
            result = await session.execute(text("SELECT 1"))
            db_ok = result.scalar() == 1
        except Exception:
            db_ok = False

        if not db_ok:
            response.status_code = 503

        return {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "error",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    @app.get("/v1/version")
    async def version(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
        return {
            "version": app.version,
            "environment": settings.environment,
        }

    @app.get("/", include_in_schema=False, response_model=None)
    async def root(request: Request) -> RedirectResponse | dict:
        # When the host is docs.dsa-api.com, send users straight to Swagger UI.
        # On any other host (api.dsa-api.com, localhost, internal) return a
        # small pointer document instead of FastAPI's default 404.
        host = request.headers.get("host", "").lower()
        if host.startswith("docs."):
            return RedirectResponse(url="/docs", status_code=307)
        body = {
            "name": "DSA Trusted Flaggers API",
            "version": app.version,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "source": settings.source_url,
        }
        if settings.waitlist_url:
            body["waitlist"] = settings.waitlist_url
        return body

    # Public, read-only open-data API: any browser origin may call it. There's
    # no auth or cookies, so credentials stay off (also required when
    # allow_origins is "*"). Expose our informational headers so browser JS can
    # read the source/disclaimer/freshness + rate-limit metadata. Added last so
    # it's the outermost middleware — preflight OPTIONS are answered before the
    # rate limiter and CORS headers land on every response, including errors.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
        expose_headers=[
            "X-Source-URL",
            "X-Disclaimer",
            "X-Data-Updated-At",
            "X-RateLimit-Limit",
            "X-RateLimit-Window-Seconds",
        ],
    )

    app.include_router(trusted_flaggers.router)
    app.include_router(changes.router)
    app.include_router(stats.router)

    return app


app = create_app()
