import csv
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import TrustedFlaggerEventORM, TrustedFlaggerORM

logger = logging.getLogger(__name__)

CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "country_code",
    "dsc_country_code",
    "dsc_name",
    "email",
    "email_domain",
    "website",
    "areas_of_expertise",
    "areas_of_expertise_raw",
    "designation_date",
    "status",
    "first_seen_at",
    "last_seen_at",
)


def _tf_to_dict(row: TrustedFlaggerORM) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "legal_form": row.legal_form,
        "website": row.website,
        "email": row.email,
        "email_domain": row.email_domain,
        "address_raw": row.address_raw,
        "country_code": row.country_code,
        "city": row.city,
        "postal_code": row.postal_code,
        "dsc_name": row.dsc_name,
        "dsc_country_code": row.dsc_country_code,
        "areas_of_expertise_raw": row.areas_of_expertise_raw,
        "areas_of_expertise": row.areas_of_expertise,
        "designation_date": row.designation_date.isoformat() if row.designation_date else None,
        "status": row.status,
        "first_seen_at": row.first_seen_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
        "source_hash": row.source_hash,
    }


def _event_to_dict(row: TrustedFlaggerEventORM) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "tf_id": str(row.tf_id),
        "event_type": row.event_type,
        "diff": row.diff,
        "snapshot": row.snapshot,
        "scrape_run_id": str(row.scrape_run_id),
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


def _flatten_for_csv(d: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for col in CSV_COLUMNS:
        value = d.get(col)
        # JSON arrays get joined for CSV readability; everything else is str-able.
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        flat[col] = "" if value is None else value
    return flat


async def export_all(session: AsyncSession, output_dir: Path) -> dict[str, Path]:
    """Write trusted-flaggers.json/.csv and changelog.json under output_dir/data/.

    Returns a dict {kind: path} for callers that want to log it.
    """
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    tf_rows = (
        (await session.execute(select(TrustedFlaggerORM).order_by(TrustedFlaggerORM.name)))
        .scalars()
        .all()
    )
    event_rows = (
        (
            await session.execute(
                select(TrustedFlaggerEventORM).order_by(TrustedFlaggerEventORM.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    tf_dicts = [_tf_to_dict(r) for r in tf_rows]
    json_path = data_dir / "trusted-flaggers.json"
    json_path.write_text(
        json.dumps(tf_dicts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = data_dir / "trusted-flaggers.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for d in tf_dicts:
            writer.writerow(_flatten_for_csv(d))

    changelog_path = data_dir / "changelog.json"
    changelog_path.write_text(
        json.dumps(
            [_event_to_dict(r) for r in event_rows],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info("exported %d TFs + %d events to %s", len(tf_rows), len(event_rows), data_dir)
    return {
        "json": json_path,
        "csv": csv_path,
        "changelog": changelog_path,
    }
