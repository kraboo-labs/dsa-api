import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from apps.scraper.export import CSV_COLUMNS, export_all
from core.db import TrustedFlaggerEventORM, TrustedFlaggerORM
from core.enums import AreaEnum, EventType, TFStatus
from core.models import derive_stable_id


def _tf(name: str, country: str = "DE") -> TrustedFlaggerORM:
    now = datetime.now(UTC)
    return TrustedFlaggerORM(
        id=derive_stable_id(name, "DSC (DE)", date(2025, 1, 1)),
        name=name,
        country_code=country,
        dsc_name="DSC (DE)",
        dsc_country_code="DE",
        areas_of_expertise_raw=["Illegal Speech"],
        areas_of_expertise=[AreaEnum.illegal_speech.value],
        designation_date=date(2025, 1, 1),
        status=TFStatus.active.value,
        first_seen_at=now,
        last_seen_at=now,
        source_hash=f"h-{name}",
    )


async def test_export_writes_json_csv_and_changelog(db_session_factory, tmp_path: Path):
    a = _tf("A Org")
    b = _tf("B Org", country="SK")
    ev = TrustedFlaggerEventORM(
        tf_id=a.id,
        event_type=EventType.created.value,
        snapshot={"name": "A Org"},
        scrape_run_id=uuid4(),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    async with db_session_factory() as session:
        session.add_all([a, b, ev])
        await session.commit()

    async with db_session_factory() as session:
        paths = await export_all(session, tmp_path)

    json_path = paths["json"]
    csv_path = paths["csv"]
    changelog_path = paths["changelog"]

    # JSON: ordered by name, expected fields present, internal scrape-time
    # operational fields (first_seen_at, last_seen_at, source_hash) omitted to
    # keep dsa-data diffs reviewable.
    tfs = json.loads(json_path.read_text(encoding="utf-8"))
    assert [t["name"] for t in tfs] == ["A Org", "B Org"]
    assert tfs[0]["areas_of_expertise"] == [AreaEnum.illegal_speech.value]
    assert tfs[1]["country_code"] == "SK"
    for field in ("first_seen_at", "last_seen_at", "source_hash"):
        assert (
            field not in tfs[0]
        ), f"{field} must not appear in the dsa-data export (changes every scrape)"

    # CSV: headers match CSV_COLUMNS, semicolon-joined arrays.
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == list(CSV_COLUMNS)
        rows = list(reader)
    assert rows[0]["name"] == "A Org"
    assert rows[0]["areas_of_expertise"] == AreaEnum.illegal_speech.value

    # Changelog: one event entry, ordered ascending by occurred_at.
    events = json.loads(changelog_path.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["event_type"] == EventType.created.value
    assert events[0]["tf_id"] == str(a.id)


async def test_export_creates_data_subdirectory(db_session_factory, tmp_path: Path):
    async with db_session_factory() as session:
        paths = await export_all(session, tmp_path)
    for p in paths.values():
        assert p.parent == tmp_path / "data"


async def test_export_handles_empty_db(db_session_factory, tmp_path: Path):
    async with db_session_factory() as session:
        paths = await export_all(session, tmp_path)
    assert json.loads(paths["json"].read_text(encoding="utf-8")) == []
    assert json.loads(paths["changelog"].read_text(encoding="utf-8")) == []
    with paths["csv"].open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rest = list(reader)
    assert header == list(CSV_COLUMNS)
    assert rest == []
