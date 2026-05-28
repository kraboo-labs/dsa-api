from datetime import UTC, date, datetime

import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.deps import get_db_session
from apps.api.main import create_app
from core.db import TrustedFlaggerORM
from core.enums import AreaEnum, TFStatus
from core.models import derive_stable_id


def _tf(
    name: str,
    country: str,
    dsc_country: str,
    areas: list[AreaEnum],
    status: TFStatus = TFStatus.active,
) -> TrustedFlaggerORM:
    now = datetime.now(UTC)
    return TrustedFlaggerORM(
        id=derive_stable_id(name, f"DSC ({dsc_country})", date(2025, 1, 1)),
        name=name,
        country_code=country,
        dsc_name=f"DSC ({dsc_country})",
        dsc_country_code=dsc_country,
        areas_of_expertise_raw=[],
        areas_of_expertise=[a.value for a in areas],
        designation_date=date(2025, 1, 1),
        status=status.value,
        first_seen_at=now,
        last_seen_at=now,
        source_hash=f"h-{name}",
    )


@pytest_asyncio.fixture
async def app_with_db(db_session_factory):
    async def _override():
        async with db_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, db_session_factory


async def _seed(factory, *objs):
    async with factory() as session:
        for o in objs:
            session.add(o)
        await session.commit()


async def test_stats_empty_db(app_with_db):
    client, _ = app_with_db
    body = (await client.get("/v1/stats")).json()
    assert body["data"]["total"] == 0
    assert body["data"]["by_country"] == {}
    assert body["data"]["by_area"] == {}
    assert body["data"]["by_dsc_country"] == {}
    assert body["meta"]["scope"] == "active"


async def test_stats_counts_by_country_area_and_dsc_for_active_only(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _tf("A", "DE", "DE", [AreaEnum.ip_infringement]),
        _tf("B", "DE", "DE", [AreaEnum.illegal_speech, AreaEnum.ip_infringement]),
        _tf("C", "FR", "FR", [AreaEnum.csam]),
        _tf("D", "SK", "SK", [AreaEnum.illegal_speech], status=TFStatus.removed),
    )
    body = (await client.get("/v1/stats")).json()
    assert body["data"]["total"] == 3
    assert body["data"]["by_country"] == {"DE": 2, "FR": 1}
    assert body["data"]["by_dsc_country"] == {"DE": 2, "FR": 1}
    # by_area unnests JSONB arrays — B contributes to both ip and speech
    assert body["data"]["by_area"] == {
        AreaEnum.ip_infringement.value: 2,
        AreaEnum.illegal_speech.value: 1,
        AreaEnum.csam.value: 1,
    }
