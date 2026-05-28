from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session
from apps.api.routers import changes, trusted_flaggers
from core.config import Settings, get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DSA Trusted Flaggers API",
        description=(
            "Machine-readable mirror of the EU Trusted Flaggers register "
            "(DSA Article 22(5)). Not a source of truth — see X-Source-URL."
        ),
        version="0.0.1",
    )

    @app.middleware("http")
    async def add_source_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Source-URL"] = settings.source_url
        response.headers["X-Disclaimer"] = settings.disclaimer
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

    app.include_router(trusted_flaggers.router)
    app.include_router(changes.router)

    return app


app = create_app()
