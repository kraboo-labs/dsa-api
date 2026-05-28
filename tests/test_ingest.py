from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from apps.scraper.ingest import apply_diff, compute_diff
from apps.scraper.parse import normalize_rows, parse_api_response
from core.config import get_settings
from core.db import (
    Base,
    TrustedFlaggerEventORM,
    TrustedFlaggerORM,
    make_engine,
    make_session_factory,
)
from core.enums import EventType, TFStatus
from core.models import ScrapedTrustedFlagger, derive_stable_id

FIXTURE_DIR = Path(__file__).parent / "fixtures"
EU_API_JSON = FIXTURE_DIR / "trusted_flaggers_api.json"


@pytest_asyncio.fixture
async def db_session_factory():
    """Fresh schema per test. Function scope keeps each ingest test fully isolated."""
    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=1, max_overflow=0)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()


def _make_scraped(
    name: str = "Foo NGO",
    dsc_name: str = "Test DSC (DE)",
    designation_year: int = 2026,
    source_hash: str = "hash-1",
    areas_raw: list[str] | None = None,
) -> ScrapedTrustedFlagger:
    designation_date = date(designation_year, 1, 1)
    return ScrapedTrustedFlagger(
        id=derive_stable_id(name, dsc_name, designation_date),
        name=name,
        country_code="DE",
        dsc_name=dsc_name,
        dsc_country_code="DE",
        areas_of_expertise_raw=areas_raw or ["Illegal Speech"],
        areas_of_expertise=[],
        designation_date=designation_date,
        source_hash=source_hash,
    )


def test_compute_diff_finds_changed_fields():
    a = {"name": "Foo", "email": "old@x.com", "country_code": "DE"}
    b = {"name": "Foo Renamed", "email": "old@x.com", "country_code": "DE"}
    diff = compute_diff(a, b)
    assert diff == {"name": {"from": "Foo", "to": "Foo Renamed"}}


def test_compute_diff_empty_when_equal():
    assert compute_diff({"a": 1}, {"a": 1}) == {}


def test_compute_diff_handles_missing_keys():
    diff = compute_diff({"a": 1}, {"b": 2})
    assert diff == {"a": {"from": 1, "to": None}, "b": {"from": None, "to": 2}}


async def test_apply_diff_creates_new_tf_and_event(db_session_factory):
    run_id = uuid4()
    scraped_at = datetime.now(UTC)
    scraped = _make_scraped()

    async with db_session_factory() as session:
        c, u, r, rest = await apply_diff(session, [scraped], run_id=run_id, scraped_at=scraped_at)
        await session.commit()
    assert (c, u, r, rest) == (1, 0, 0, 0)

    async with db_session_factory() as session:
        tfs = (await session.execute(select(TrustedFlaggerORM))).scalars().all()
        events = (await session.execute(select(TrustedFlaggerEventORM))).scalars().all()

    assert len(tfs) == 1
    assert tfs[0].id == scraped.id
    assert tfs[0].status == TFStatus.active.value
    assert tfs[0].first_seen_at == scraped_at
    assert tfs[0].last_seen_at == scraped_at
    assert len(events) == 1
    assert events[0].event_type == EventType.created.value
    assert events[0].scrape_run_id == run_id
    snapshot = events[0].snapshot
    assert snapshot["name"] == scraped.name


async def test_apply_diff_full_lifecycle(db_session_factory):
    """Three scrape passes: verify created → updated → removed → restored transitions."""
    run_id_1 = uuid4()
    scrape_t1 = datetime.now(UTC)

    tf_a = _make_scraped(name="A NGO", source_hash="a-v1")
    tf_b = _make_scraped(name="B NGO", source_hash="b-v1")

    # First pass: both new
    async with db_session_factory() as session:
        c, u, r, rest = await apply_diff(
            session, [tf_a, tf_b], run_id=run_id_1, scraped_at=scrape_t1
        )
        await session.commit()
    assert (c, u, r, rest) == (2, 0, 0, 0)

    # Verify state after pass 1
    async with db_session_factory() as session:
        tfs = (await session.execute(select(TrustedFlaggerORM))).scalars().all()
        events = (await session.execute(select(TrustedFlaggerEventORM))).scalars().all()
    assert len(tfs) == 2
    assert all(tf.status == TFStatus.active.value for tf in tfs)
    assert all(tf.first_seen_at == scrape_t1 for tf in tfs)
    assert {e.event_type for e in events} == {EventType.created.value}

    # Second pass: A is updated, B is gone. derive_stable_id is over (name, dsc, date),
    # so to exercise "update on same id" we keep the natural key and change source_hash.
    run_id_2 = uuid4()
    scrape_t2 = datetime.now(UTC)
    tf_a_v2_same_id = _make_scraped(name="A NGO", source_hash="a-v2-real")

    async with db_session_factory() as session:
        c, u, r, rest = await apply_diff(
            session, [tf_a_v2_same_id], run_id=run_id_2, scraped_at=scrape_t2
        )
        await session.commit()
    assert c == 0
    assert u == 1  # A updated
    assert r == 1  # B removed
    assert rest == 0

    # Verify
    async with db_session_factory() as session:
        tfs = {tf.id: tf for tf in (await session.execute(select(TrustedFlaggerORM))).scalars()}
        events = (await session.execute(select(TrustedFlaggerEventORM))).scalars().all()
    a_row = tfs[tf_a_v2_same_id.id]
    b_row = tfs[tf_b.id]
    assert a_row.source_hash == "a-v2-real"
    assert a_row.status == TFStatus.active.value
    assert a_row.last_seen_at == scrape_t2
    assert a_row.first_seen_at == scrape_t1  # never moves once set
    assert b_row.status == TFStatus.removed.value
    assert b_row.last_seen_at == scrape_t1  # not touched in pass 2

    event_types = [e.event_type for e in events]
    assert event_types.count(EventType.created.value) == 2
    assert event_types.count(EventType.updated.value) == 1
    assert event_types.count(EventType.removed.value) == 1

    # Third pass: B comes back → restored, A unchanged
    run_id_3 = uuid4()
    scrape_t3 = datetime.now(UTC)
    async with db_session_factory() as session:
        c, u, r, rest = await apply_diff(
            session, [tf_a_v2_same_id, tf_b], run_id=run_id_3, scraped_at=scrape_t3
        )
        await session.commit()
    assert (c, u, r, rest) == (0, 0, 0, 1)

    async with db_session_factory() as session:
        tfs = {tf.id: tf for tf in (await session.execute(select(TrustedFlaggerORM))).scalars()}
    assert tfs[tf_b.id].status == TFStatus.active.value
    assert tfs[tf_b.id].last_seen_at == scrape_t3


async def test_apply_diff_against_real_fixture_inserts_all_rows(db_session_factory):
    """Pipe the captured EU snapshot through ingest; expect one row per parsed entry."""
    raw_rows = parse_api_response(EU_API_JSON.read_bytes())
    normalized, errors = normalize_rows(raw_rows)
    assert not errors

    run_id = uuid4()
    scraped_at = datetime.now(UTC)
    async with db_session_factory() as session:
        c, u, r, rest = await apply_diff(session, normalized, run_id=run_id, scraped_at=scraped_at)
        await session.commit()

    assert c == len(normalized)
    assert u == r == rest == 0

    async with db_session_factory() as session:
        count = len((await session.execute(select(TrustedFlaggerORM))).scalars().all())
    assert count == len(normalized)
