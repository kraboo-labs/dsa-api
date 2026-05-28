from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session
from core.config import Settings, get_settings
from core.db import TrustedFlaggerEventORM, TrustedFlaggerORM

router = APIRouter(prefix="/v1/changes", tags=["changes"])

_DEFAULT_WINDOW = timedelta(days=30)


@router.get("")
async def list_changes(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    since: Annotated[
        datetime | None,
        Query(description="ISO timestamp. Defaults to 30 days ago."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    effective_since = since or (datetime.now(UTC) - _DEFAULT_WINDOW)

    base = (
        select(
            TrustedFlaggerEventORM.event_id,
            TrustedFlaggerEventORM.tf_id,
            TrustedFlaggerEventORM.event_type,
            TrustedFlaggerEventORM.diff,
            TrustedFlaggerEventORM.snapshot,
            TrustedFlaggerEventORM.scrape_run_id,
            TrustedFlaggerEventORM.occurred_at,
            TrustedFlaggerORM.name,
            TrustedFlaggerORM.country_code,
        )
        .join(TrustedFlaggerORM, TrustedFlaggerORM.id == TrustedFlaggerEventORM.tf_id)
        .where(TrustedFlaggerEventORM.occurred_at >= effective_since)
    )

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    page = base.order_by(TrustedFlaggerEventORM.occurred_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(page)).all()

    data = [
        {
            "event_id": r.event_id,
            "tf_id": str(r.tf_id),
            "tf_name": r.name,
            "tf_country_code": r.country_code,
            "event_type": r.event_type,
            "diff": r.diff,
            "snapshot": r.snapshot,
            "scrape_run_id": str(r.scrape_run_id),
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        }
        for r in rows
    ]
    return {
        "data": data,
        "meta": {
            "since": effective_since.isoformat(),
            "total": total,
            "limit": limit,
            "offset": offset,
            "source_url": settings.source_url,
        },
    }
