from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db_session
from core.config import Settings, get_settings
from core.db import ScrapeRunORM, TrustedFlaggerORM
from core.enums import ScrapeRunStatus, TFStatus

router = APIRouter(prefix="/v1/stats", tags=["stats"])


async def _data_updated_at(session: AsyncSession) -> datetime | None:
    stmt = (
        select(ScrapeRunORM.completed_at)
        .where(
            ScrapeRunORM.status.in_([ScrapeRunStatus.success.value, ScrapeRunStatus.partial.value])
        )
        .order_by(ScrapeRunORM.completed_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("")
async def get_stats(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Aggregate counts of *active* TFs by country / area / DSC.

    Computed on each request. Redis caching is a separate commit.
    """
    active_filter = TrustedFlaggerORM.status == TFStatus.active.value

    total = (await session.execute(select(func.count()).where(active_filter))).scalar_one()

    by_country_rows = (
        await session.execute(
            select(TrustedFlaggerORM.country_code, func.count())
            .where(active_filter)
            .group_by(TrustedFlaggerORM.country_code)
        )
    ).all()
    by_country = dict(by_country_rows)

    by_dsc_rows = (
        await session.execute(
            select(TrustedFlaggerORM.dsc_country_code, func.count())
            .where(active_filter)
            .group_by(TrustedFlaggerORM.dsc_country_code)
        )
    ).all()
    by_dsc = {dsc: n for dsc, n in by_dsc_rows if dsc is not None}

    # areas_of_expertise is a JSONB array; we need a lateral over
    # jsonb_array_elements_text. SQLAlchemy's column_valued() doesn't reach
    # the surrounding FROM, so use a raw lateral here.
    by_area_rows = (
        await session.execute(
            text(
                "SELECT element AS area, COUNT(*) AS n "
                "FROM trusted_flaggers, "
                "     jsonb_array_elements_text(areas_of_expertise) AS element "
                "WHERE status = :status "
                "GROUP BY element"
            ),
            {"status": TFStatus.active.value},
        )
    ).all()
    by_area = {row.area: row.n for row in by_area_rows}

    data_updated_at = await _data_updated_at(session)

    return {
        "data": {
            "total": total,
            "by_country": by_country,
            "by_area": by_area,
            "by_dsc_country": by_dsc,
        },
        "meta": {
            "scope": "active",
            "data_updated_at": data_updated_at.isoformat() if data_updated_at else None,
            "source_url": settings.source_url,
        },
    }
