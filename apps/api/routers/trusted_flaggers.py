from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session
from core.config import Settings, get_settings
from core.db import ScrapeRunORM, TrustedFlaggerORM
from core.enums import AreaEnum, ScrapeRunStatus
from core.models import TrustedFlagger

router = APIRouter(prefix="/v1/trusted-flaggers", tags=["trusted-flaggers"])

StatusFilter = Literal["active", "suspended", "revoked", "removed", "all"]


async def _data_updated_at(session: AsyncSession) -> datetime | None:
    """Timestamp of the most recent scrape_run that produced data (success or partial)."""
    stmt = (
        select(ScrapeRunORM.completed_at)
        .where(
            ScrapeRunORM.status.in_([ScrapeRunStatus.success.value, ScrapeRunStatus.partial.value])
        )
        .order_by(ScrapeRunORM.completed_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _meta(
    total: int, limit: int, offset: int, data_updated_at: datetime | None, source_url: str
) -> dict[str, Any]:
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data_updated_at": data_updated_at.isoformat() if data_updated_at else None,
        "source_url": source_url,
    }


def _serialize(row: TrustedFlaggerORM) -> dict[str, Any]:
    return TrustedFlagger.model_validate(row).model_dump(mode="json")


@router.get("")
async def list_trusted_flaggers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    country: Annotated[
        list[str] | None,
        Query(description="ISO alpha-2, repeatable. Filters by country_code."),
    ] = None,
    area: Annotated[
        list[AreaEnum] | None,
        Query(description="Normalized area enum, repeatable. Any-match against areas."),
    ] = None,
    dsc_country: Annotated[
        str | None, Query(description="ISO alpha-2 of the designating DSC.")
    ] = None,
    status: Annotated[
        StatusFilter,
        Query(description="Default 'active'. Pass 'all' to include suspended/revoked/removed."),
    ] = "active",
    designated_after: Annotated[date | None, Query(description="ISO date, inclusive.")] = None,
    designated_before: Annotated[date | None, Query(description="ISO date, inclusive.")] = None,
    q: Annotated[str | None, Query(description="Substring match on name + address_raw.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    stmt = select(TrustedFlaggerORM)

    if status != "all":
        stmt = stmt.where(TrustedFlaggerORM.status == status)
    if country:
        stmt = stmt.where(TrustedFlaggerORM.country_code.in_([c.upper() for c in country]))
    if dsc_country:
        stmt = stmt.where(TrustedFlaggerORM.dsc_country_code == dsc_country.upper())
    if designated_after:
        stmt = stmt.where(TrustedFlaggerORM.designation_date >= designated_after)
    if designated_before:
        stmt = stmt.where(TrustedFlaggerORM.designation_date <= designated_before)
    if area:
        # JSONB ?| any-of-keys/elements; areas_of_expertise stores ["enum_value", ...].
        stmt = stmt.where(
            text("areas_of_expertise ?| :areas").bindparams(areas=[a.value for a in area])
        )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                TrustedFlaggerORM.name.ilike(like),
                TrustedFlaggerORM.address_raw.ilike(like),
            )
        )

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    page_stmt = stmt.order_by(TrustedFlaggerORM.name).limit(limit).offset(offset)
    rows = (await session.execute(page_stmt)).scalars().all()
    data_updated_at = await _data_updated_at(session)

    return {
        "data": [_serialize(row) for row in rows],
        "meta": _meta(total, limit, offset, data_updated_at, settings.source_url),
    }


@router.get("/{tf_id}")
async def get_trusted_flagger(
    tf_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    row = await session.get(TrustedFlaggerORM, tf_id)
    if row is None:
        raise HTTPException(status_code=404, detail="trusted flagger not found")
    data_updated_at = await _data_updated_at(session)
    return {
        "data": _serialize(row),
        "meta": {
            "data_updated_at": data_updated_at.isoformat() if data_updated_at else None,
            "source_url": settings.source_url,
        },
    }
