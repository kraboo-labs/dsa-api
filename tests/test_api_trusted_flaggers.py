from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest_asyncio
from httpx import ASGITransport

from apps.api.deps import get_db_session
from apps.api.main import create_app
from core.db import ScrapeRunORM, TrustedFlaggerEventORM, TrustedFlaggerORM
from core.enums import AreaEnum, EventType, ScrapeRunStatus, TFStatus
from core.models import derive_stable_id


def _new_tf(
    *,
    name: str,
    country_code: str = "DE",
    dsc_country_code: str = "DE",
    dsc_name: str = "Test DSC (DE)",
    designation_date: date | None = None,
    status: str = TFStatus.active.value,
    areas: list[AreaEnum] | None = None,
    address_raw: str | None = None,
    email: str | None = None,
) -> TrustedFlaggerORM:
    designation_date = designation_date or date(2025, 6, 1)
    now = datetime.now(UTC)
    return TrustedFlaggerORM(
        id=derive_stable_id(name, dsc_name, designation_date),
        name=name,
        country_code=country_code,
        dsc_name=dsc_name,
        dsc_country_code=dsc_country_code,
        areas_of_expertise_raw=[],
        areas_of_expertise=[a.value for a in (areas or [AreaEnum.illegal_speech])],
        designation_date=designation_date,
        status=status,
        first_seen_at=now,
        last_seen_at=now,
        source_hash=f"hash-{name}",
        address_raw=address_raw,
        email=email,
    )


@pytest_asyncio.fixture
async def app_with_db(db_session_factory):
    """ASGI client + session factory. The override yields sessions from the
    same engine the factory uses, so all DB work stays on one event loop."""

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


async def test_list_returns_empty_envelope_when_db_is_empty(app_with_db):
    client, _ = app_with_db
    response = await client.get("/v1/trusted-flaggers")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0
    assert body["meta"]["limit"] == 50
    assert body["meta"]["offset"] == 0
    assert body["meta"]["data_updated_at"] is None
    assert body["meta"]["source_url"].endswith("/trusted-flaggers-under-dsa")
    assert response.headers["X-Source-URL"]
    assert response.headers["X-Disclaimer"]


async def test_list_returns_rows_ordered_by_name(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="B Org"),
        _new_tf(name="A Org"),
        _new_tf(name="C Org"),
    )
    response = await client.get("/v1/trusted-flaggers")
    body = response.json()
    assert [r["name"] for r in body["data"]] == ["A Org", "B Org", "C Org"]
    assert body["meta"]["total"] == 3


async def test_list_excludes_non_active_by_default_and_includes_them_with_status_all(
    app_with_db,
):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="Active Org", status=TFStatus.active.value),
        _new_tf(name="Removed Org", status=TFStatus.removed.value),
    )
    default = (await client.get("/v1/trusted-flaggers")).json()
    all_resp = (await client.get("/v1/trusted-flaggers?status=all")).json()
    assert [r["name"] for r in default["data"]] == ["Active Org"]
    assert {r["name"] for r in all_resp["data"]} == {"Active Org", "Removed Org"}


async def test_list_filters_by_country_repeatable(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="DE Org", country_code="DE"),
        _new_tf(name="FR Org", country_code="FR"),
        _new_tf(name="SK Org", country_code="SK"),
    )
    response = await client.get("/v1/trusted-flaggers?country=DE&country=SK")
    names = {r["name"] for r in response.json()["data"]}
    assert names == {"DE Org", "SK Org"}


async def test_list_filters_by_dsc_country(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="A", country_code="DE", dsc_country_code="DE"),
        _new_tf(name="B", country_code="DE", dsc_country_code="IE"),
    )
    response = await client.get("/v1/trusted-flaggers?dsc_country=IE")
    assert [r["name"] for r in response.json()["data"]] == ["B"]


async def test_list_filters_by_designation_date_range(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="Old", designation_date=date(2024, 1, 1)),
        _new_tf(name="Middle", designation_date=date(2025, 6, 1)),
        _new_tf(name="New", designation_date=date(2026, 5, 1)),
    )
    response = await client.get(
        "/v1/trusted-flaggers?designated_after=2025-01-01&designated_before=2025-12-31"
    )
    assert [r["name"] for r in response.json()["data"]] == ["Middle"]


async def test_list_filters_by_area_any_match(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="IP only", areas=[AreaEnum.ip_infringement]),
        _new_tf(name="Speech only", areas=[AreaEnum.illegal_speech]),
        _new_tf(name="Multi", areas=[AreaEnum.csam, AreaEnum.ip_infringement]),
    )
    response = await client.get("/v1/trusted-flaggers?area=ip_infringement&area=csam")
    names = {r["name"] for r in response.json()["data"]}
    assert names == {"IP only", "Multi"}


async def test_list_full_text_q_matches_name_or_address(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="Foo NGO", address_raw="Berlin, Germany"),
        _new_tf(name="Other", address_raw="Paris, France"),
    )
    by_name = (await client.get("/v1/trusted-flaggers?q=foo")).json()
    by_addr = (await client.get("/v1/trusted-flaggers?q=Paris")).json()
    assert [r["name"] for r in by_name["data"]] == ["Foo NGO"]
    assert [r["name"] for r in by_addr["data"]] == ["Other"]


async def test_list_paginates_with_limit_and_offset(app_with_db):
    client, factory = app_with_db
    await _seed(factory, *(_new_tf(name=f"Org {i:02d}") for i in range(5)))
    first = (await client.get("/v1/trusted-flaggers?limit=2&offset=0")).json()
    second = (await client.get("/v1/trusted-flaggers?limit=2&offset=2")).json()
    third = (await client.get("/v1/trusted-flaggers?limit=2&offset=4")).json()
    assert first["meta"]["total"] == 5
    assert [r["name"] for r in first["data"]] == ["Org 00", "Org 01"]
    assert [r["name"] for r in second["data"]] == ["Org 02", "Org 03"]
    assert [r["name"] for r in third["data"]] == ["Org 04"]


async def test_list_rejects_limit_above_max(app_with_db):
    client, _ = app_with_db
    response = await client.get("/v1/trusted-flaggers?limit=500")
    assert response.status_code == 422


async def test_lookup_requires_exactly_one_param(app_with_db):
    client, _ = app_with_db
    none_resp = await client.get("/v1/trusted-flaggers/lookup")
    assert none_resp.status_code == 400
    two_resp = await client.get("/v1/trusted-flaggers/lookup?email=a@b.org&domain=b.org")
    assert two_resp.status_code == 400


async def test_lookup_by_email_finds_match(app_with_db):
    client, factory = app_with_db
    await _seed(
        factory,
        _new_tf(name="Match", email="notices@addictions-france.org"),
        _new_tf(name="No match", email="other@example.com"),
    )
    response = await client.get("/v1/trusted-flaggers/lookup?email=notices@addictions-france.org")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == "Match"


async def test_lookup_by_email_is_case_insensitive(app_with_db):
    client, factory = app_with_db
    await _seed(factory, _new_tf(name="Match", email="foo@Example.org"))
    response = await client.get("/v1/trusted-flaggers/lookup?email=FOO@example.ORG")
    assert response.json()["meta"]["total"] == 1


async def test_lookup_by_domain_matches_email_domain(app_with_db):
    client, factory = app_with_db
    tf = _new_tf(name="Match", email="x@example.org")
    tf.email_domain = "example.org"
    await _seed(factory, tf, _new_tf(name="Other", email=None))
    response = await client.get("/v1/trusted-flaggers/lookup?domain=example.org")
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["name"] == "Match"


async def test_lookup_by_website_extracts_host_and_matches_email_domain(app_with_db):
    client, factory = app_with_db
    tf = _new_tf(name="Match")
    tf.email_domain = "bar.org"
    await _seed(factory, tf)
    response = await client.get("/v1/trusted-flaggers/lookup?website=https://bar.org/contact/us")
    assert response.json()["meta"]["total"] == 1


async def test_lookup_returns_empty_when_no_match(app_with_db):
    client, factory = app_with_db
    await _seed(factory, _new_tf(name="X", email="x@a.org"))
    response = await client.get("/v1/trusted-flaggers/lookup?email=ghost@z.org")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_lookup_rejects_bogus_website(app_with_db):
    client, _ = app_with_db
    response = await client.get("/v1/trusted-flaggers/lookup?website=")
    # Empty value is treated as "not provided" — 400 because nothing was supplied.
    assert response.status_code == 400


async def test_get_single_returns_tf_by_id(app_with_db):
    client, factory = app_with_db
    tf = _new_tf(name="Single Org", country_code="SK")
    await _seed(factory, tf)
    response = await client.get(f"/v1/trusted-flaggers/{tf.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["id"] == str(tf.id)
    assert body["data"]["name"] == "Single Org"
    assert body["data"]["country_code"] == "SK"
    assert body["meta"]["source_url"]
    assert response.headers["X-Source-URL"]


async def test_get_single_returns_404_when_not_found(app_with_db):
    client, _ = app_with_db
    response = await client.get(f"/v1/trusted-flaggers/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "trusted flagger not found"


async def test_get_single_returns_422_on_malformed_uuid(app_with_db):
    client, _ = app_with_db
    response = await client.get("/v1/trusted-flaggers/not-a-uuid")
    assert response.status_code == 422


async def test_history_returns_events_for_tf_newest_first(app_with_db):
    client, factory = app_with_db
    tf = _new_tf(name="History Org")
    older = TrustedFlaggerEventORM(
        tf_id=tf.id,
        event_type=EventType.created.value,
        snapshot={"name": "History Org"},
        scrape_run_id=uuid4(),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = TrustedFlaggerEventORM(
        tf_id=tf.id,
        event_type=EventType.updated.value,
        diff={"name": {"from": "Old", "to": "History Org"}},
        snapshot={"name": "History Org"},
        scrape_run_id=uuid4(),
        occurred_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    await _seed(factory, tf, older, newer)
    body = (await client.get(f"/v1/trusted-flaggers/{tf.id}/history")).json()
    assert body["meta"]["total"] == 2
    assert body["meta"]["tf_id"] == str(tf.id)
    assert [e["event_type"] for e in body["data"]] == [
        EventType.updated.value,
        EventType.created.value,
    ]
    assert body["data"][0]["diff"] == {"name": {"from": "Old", "to": "History Org"}}


async def test_history_returns_404_when_tf_does_not_exist(app_with_db):
    client, _ = app_with_db
    response = await client.get(f"/v1/trusted-flaggers/{uuid4()}/history")
    assert response.status_code == 404


async def test_history_returns_empty_for_tf_without_events(app_with_db):
    client, factory = app_with_db
    tf = _new_tf(name="Bare")
    await _seed(factory, tf)
    body = (await client.get(f"/v1/trusted-flaggers/{tf.id}/history")).json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_list_meta_data_updated_at_uses_latest_successful_scrape(app_with_db):
    client, factory = app_with_db
    old_run = ScrapeRunORM(
        id=uuid4(),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        status=ScrapeRunStatus.success.value,
        source_url="x",
    )
    new_run = ScrapeRunORM(
        id=uuid4(),
        started_at=datetime(2026, 5, 28, 10, tzinfo=UTC),
        completed_at=datetime(2026, 5, 28, 10, tzinfo=UTC),
        status=ScrapeRunStatus.partial.value,
        source_url="x",
    )
    failed_run = ScrapeRunORM(
        id=uuid4(),
        started_at=datetime(2026, 5, 28, 11, tzinfo=UTC),
        completed_at=datetime(2026, 5, 28, 11, tzinfo=UTC),
        status=ScrapeRunStatus.failed.value,
        source_url="x",
    )
    await _seed(factory, old_run, new_run, failed_run)
    body = (await client.get("/v1/trusted-flaggers")).json()
    # Failed run should not bump data_updated_at; the partial run from 10:00 wins.
    assert body["meta"]["data_updated_at"] == "2026-05-28T10:00:00+00:00"
