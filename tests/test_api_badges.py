from datetime import UTC, date, datetime

import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.deps import get_db_session
from apps.api.main import create_app
from core.db import TrustedFlaggerORM
from core.enums import AreaEnum, TFStatus
from core.models import derive_stable_id


def _tf(name: str, status: TFStatus = TFStatus.active) -> TrustedFlaggerORM:
    now = datetime.now(UTC)
    return TrustedFlaggerORM(
        id=derive_stable_id(name, "DSC (DE)", date(2025, 1, 1)),
        name=name,
        country_code="DE",
        dsc_name="DSC (DE)",
        dsc_country_code="DE",
        areas_of_expertise_raw=[],
        areas_of_expertise=[AreaEnum.illegal_speech.value],
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


async def test_badge_flaggers_counts_active_only(app_with_db):
    client, factory = app_with_db
    await _seed(factory, _tf("A"), _tf("B"), _tf("C", status=TFStatus.removed))
    body = (await client.get("/v1/badge/flaggers")).json()
    assert body["schemaVersion"] == 1
    assert body["label"] == "trusted flaggers"
    assert body["message"] == "2"


async def test_badge_freshness_unknown_when_no_runs(app_with_db):
    client, _ = app_with_db
    body = (await client.get("/v1/badge/freshness")).json()
    assert body["schemaVersion"] == 1
    assert body["label"] == "last sync"
    assert body["message"] == "unknown"
