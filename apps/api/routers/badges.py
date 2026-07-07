"""Shields.io endpoint badges — live count + data freshness for READMEs.

https://shields.io/badges/endpoint-badge — returns the small JSON shields
expects. Cached by shields for cacheSeconds, so this is cheap even when many
READMEs render it.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session
from core.db import ScrapeRunORM, TrustedFlaggerORM
from core.enums import ScrapeRunStatus, TFStatus

router = APIRouter(prefix="/v1/badge", tags=["badge"])

_CACHE_SECONDS = 1800


def _shield(label: str, message: str, color: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": color,
        "cacheSeconds": _CACHE_SECONDS,
    }


@router.get("/flaggers")
async def badge_flaggers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Count of active trusted flaggers, as a shields endpoint badge."""
    total = (
        await session.execute(
            select(func.count()).where(TrustedFlaggerORM.status == TFStatus.active.value)
        )
    ).scalar_one()
    return _shield("trusted flaggers", str(total), "blue")


@router.get("/freshness")
async def badge_freshness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """How long ago the register was last synced, as a shields endpoint badge."""
    ts = (
        await session.execute(
            select(ScrapeRunORM.completed_at)
            .where(
                ScrapeRunORM.status.in_(
                    [ScrapeRunStatus.success.value, ScrapeRunStatus.partial.value]
                )
            )
            .order_by(ScrapeRunORM.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if ts is None:
        return _shield("last sync", "unknown", "lightgrey")

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - ts).total_seconds()
    hours = seconds / 3600
    if hours < 1:
        message = f"{max(1, int(seconds // 60))}m ago"
    elif hours < 48:
        message = f"{int(hours)}h ago"
    else:
        message = f"{int(hours // 24)}d ago"
    color = "brightgreen" if hours < 12 else "yellow" if hours < 36 else "red"
    return _shield("last sync", message, color)
