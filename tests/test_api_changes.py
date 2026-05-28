from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.deps import get_db_session
from apps.api.main import create_app
from core.db import TrustedFlaggerEventORM, TrustedFlaggerORM
from core.enums import AreaEnum, EventType, TFStatus
from core.models import derive_stable_id


def _new_tf(name: str, country_code: str = "DE") -> TrustedFlaggerORM:
    now = datetime.now(UTC)
    designation = date(2025, 1, 1)
    return TrustedFlaggerORM(
        id=derive_stable_id(name, "DSC (DE)", designation),
        name=name,
        country_code=country_code,
        dsc_name="DSC (DE)",
        dsc_country_code="DE",
        areas_of_expertise_raw=[],
        areas_of_expertise=[AreaEnum.illegal_speech.value],
        designation_date=designation,
        status=TFStatus.active.value,
        first_seen_at=now,
        last_seen_at=now,
        source_hash=f"h-{name}",
    )


def _event(tf_id, event_type: EventType, occurred_at: datetime) -> TrustedFlaggerEventORM:
    return TrustedFlaggerEventORM(
        tf_id=tf_id,
        event_type=event_type.value,
        snapshot={"name": "snap"},
        scrape_run_id=uuid4(),
        occurred_at=occurred_at,
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


async def test_changes_default_window_is_last_30_days(app_with_db):
    client, factory = app_with_db
    tf = _new_tf("Org")
    fresh = _event(tf.id, EventType.updated, datetime.now(UTC) - timedelta(days=5))
    stale = _event(tf.id, EventType.created, datetime.now(UTC) - timedelta(days=90))
    await _seed(factory, tf, fresh, stale)
    body = (await client.get("/v1/changes")).json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["event_type"] == EventType.updated.value
    assert body["meta"]["since"]


async def test_changes_respects_since_query(app_with_db):
    client, factory = app_with_db
    tf = _new_tf("Org")
    a = _event(tf.id, EventType.created, datetime(2026, 1, 1, tzinfo=UTC))
    b = _event(tf.id, EventType.updated, datetime(2026, 4, 1, tzinfo=UTC))
    c = _event(tf.id, EventType.removed, datetime(2026, 5, 1, tzinfo=UTC))
    await _seed(factory, tf, a, b, c)
    body = (await client.get("/v1/changes?since=2026-03-01T00:00:00Z")).json()
    assert body["meta"]["total"] == 2
    types = [e["event_type"] for e in body["data"]]
    assert types == [EventType.removed.value, EventType.updated.value]


async def test_changes_joins_tf_name_and_country(app_with_db):
    client, factory = app_with_db
    tf = _new_tf("Joined Org", country_code="SK")
    ev = _event(tf.id, EventType.created, datetime.now(UTC))
    await _seed(factory, tf, ev)
    body = (await client.get("/v1/changes")).json()
    assert body["data"][0]["tf_name"] == "Joined Org"
    assert body["data"][0]["tf_country_code"] == "SK"


async def test_changes_returns_empty_when_no_events_in_window(app_with_db):
    client, _ = app_with_db
    body = (await client.get("/v1/changes")).json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0
