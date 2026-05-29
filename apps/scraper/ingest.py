import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.scraper.export import export_all
from apps.scraper.fetch import fetch
from apps.scraper.parse import (
    extract_api_url,
    normalize_rows,
    parse_api_response,
)
from apps.scraper.publish import publish_changes
from core.config import Settings
from core.db import ScrapeRunORM, TrustedFlaggerEventORM, TrustedFlaggerORM
from core.enums import EventType, ScrapeRunStatus, TFStatus
from core.models import ScrapedTrustedFlagger
from core.notify import notify_slack
from core.timestamps import write_data_updated_at

logger = logging.getLogger(__name__)

# Fields copied from ScrapedTrustedFlagger onto TrustedFlaggerORM on create/update.
_SYNCED_FIELDS: tuple[str, ...] = (
    "name",
    "legal_form",
    "website",
    "email",
    "email_domain",
    "address_raw",
    "country_code",
    "city",
    "postal_code",
    "dsc_name",
    "dsc_country_code",
    "areas_of_expertise_raw",
    "areas_of_expertise",
    "designation_date",
    "source_hash",
)


@dataclass(slots=True)
class IngestResult:
    run_id: UUID
    status: ScrapeRunStatus
    rows_seen: int
    rows_created: int
    rows_updated: int
    rows_removed: int
    rows_restored: int
    parse_errors: list[str]
    snapshot_path: Path | None


def _orm_to_compare_dict(orm: TrustedFlaggerORM) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in _SYNCED_FIELDS:
        value = getattr(orm, field)
        # designation_date is a date; serialize to iso for stable comparison + diff.
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[field] = value
    return out


def _scraped_to_compare_dict(scraped: ScrapedTrustedFlagger) -> dict[str, Any]:
    dumped = scraped.model_dump(mode="json")
    return {field: dumped.get(field) for field in _SYNCED_FIELDS}


def _orm_to_snapshot(orm: TrustedFlaggerORM) -> dict[str, Any]:
    snap = _orm_to_compare_dict(orm)
    snap["id"] = str(orm.id)
    snap["status"] = orm.status
    return snap


def compute_diff(existing: dict[str, Any], scraped: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Field-level diff: {field: {"from": ..., "to": ...}} for changed fields only."""
    out: dict[str, dict[str, Any]] = {}
    for key in existing.keys() | scraped.keys():
        before, after = existing.get(key), scraped.get(key)
        if before != after:
            out[key] = {"from": before, "to": after}
    return out


def _apply_scraped_to_orm(orm: TrustedFlaggerORM, scraped: ScrapedTrustedFlagger) -> None:
    for field in _SYNCED_FIELDS:
        setattr(orm, field, getattr(scraped, field))


async def apply_diff(
    session: AsyncSession,
    normalized: list[ScrapedTrustedFlagger],
    *,
    run_id: UUID,
    scraped_at: datetime,
) -> tuple[int, int, int, int]:
    """Reconcile DB against `normalized`. Returns (created, updated, removed, restored)."""
    result = await session.execute(select(TrustedFlaggerORM))
    current = {tf.id: tf for tf in result.scalars().all()}
    scraped_by_id = {tf.id: tf for tf in normalized}

    created = updated = removed = restored = 0

    for tf_id, scraped in scraped_by_id.items():
        existing = current.get(tf_id)
        if existing is None:
            new_orm = TrustedFlaggerORM(
                id=tf_id,
                first_seen_at=scraped_at,
                last_seen_at=scraped_at,
                status=TFStatus.active.value,
            )
            _apply_scraped_to_orm(new_orm, scraped)
            session.add(new_orm)
            session.add(
                TrustedFlaggerEventORM(
                    tf_id=tf_id,
                    event_type=EventType.created.value,
                    diff=None,
                    snapshot=scraped.model_dump(mode="json"),
                    scrape_run_id=run_id,
                )
            )
            created += 1
            continue

        existing.last_seen_at = scraped_at

        if existing.status == TFStatus.removed.value:
            _apply_scraped_to_orm(existing, scraped)
            existing.status = TFStatus.active.value
            session.add(
                TrustedFlaggerEventORM(
                    tf_id=tf_id,
                    event_type=EventType.restored.value,
                    diff=None,
                    snapshot=scraped.model_dump(mode="json"),
                    scrape_run_id=run_id,
                )
            )
            restored += 1
            continue

        existing_dict = _orm_to_compare_dict(existing)
        scraped_dict = _scraped_to_compare_dict(scraped)
        if existing_dict != scraped_dict:
            diff = compute_diff(existing_dict, scraped_dict)
            _apply_scraped_to_orm(existing, scraped)
            session.add(
                TrustedFlaggerEventORM(
                    tf_id=tf_id,
                    event_type=EventType.updated.value,
                    diff=diff,
                    snapshot=scraped.model_dump(mode="json"),
                    scrape_run_id=run_id,
                )
            )
            updated += 1

    for tf_id, existing in current.items():
        if tf_id in scraped_by_id:
            continue
        if existing.status == TFStatus.removed.value:
            continue
        existing.status = TFStatus.removed.value
        session.add(
            TrustedFlaggerEventORM(
                tf_id=tf_id,
                event_type=EventType.removed.value,
                diff=None,
                snapshot=_orm_to_snapshot(existing),
                scrape_run_id=run_id,
            )
        )
        removed += 1

    await session.flush()
    return created, updated, removed, restored


async def run_ingest(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    snapshot_dir: Path | None = None,
    export_dir: Path | None = None,
    client: httpx.AsyncClient | None = None,
    redis: aioredis.Redis | None = None,
) -> IngestResult:
    """Run one scrape: fetch → parse → normalize → diff → persist. Returns IngestResult.

    On failure: updates the scrape_runs row to status=failed before re-raising.
    """
    run_id = uuid4()
    started_at = datetime.now(UTC)

    async with session_factory() as session:
        session.add(
            ScrapeRunORM(
                id=run_id,
                started_at=started_at,
                status=ScrapeRunStatus.running.value,
                source_url=settings.source_url,
            )
        )
        await session.commit()

    snapshot_path: Path | None = None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    try:
        logger.info("fetching EU page: %s", settings.source_url)
        html_result = await fetch(
            settings.source_url, client=client, user_agent=settings.user_agent
        )

        if snapshot_dir is not None:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = snapshot_dir / f"{started_at.strftime('%Y%m%dT%H%M%SZ')}_{run_id}.html"
            snapshot_path.write_bytes(html_result.body)
            logger.info("HTML snapshot saved to %s", snapshot_path)

        api_url = extract_api_url(html_result.body)
        logger.info("fetching JSON API: %s", api_url)
        json_result = await fetch(api_url, client=client, user_agent=settings.user_agent)

        raw_rows = parse_api_response(json_result.body)
        logger.info("parsed %d raw rows", len(raw_rows))

        normalized, parse_errors = normalize_rows(raw_rows)
        if parse_errors:
            logger.warning("%d row(s) failed normalization", len(parse_errors))

        async with session_factory() as session:
            created, updated, removed, restored = await apply_diff(
                session, normalized, run_id=run_id, scraped_at=started_at
            )

            run = await session.get(ScrapeRunORM, run_id)
            assert run is not None
            run.completed_at = datetime.now(UTC)
            run.status = (
                ScrapeRunStatus.partial.value if parse_errors else ScrapeRunStatus.success.value
            )
            run.source_response_status = json_result.status_code
            run.source_content_hash = json_result.content_hash
            run.rows_seen = len(raw_rows)
            run.rows_created = created
            run.rows_updated = updated
            run.rows_removed = removed
            run.error_message = "; ".join(parse_errors[:5]) if parse_errors else None
            run.raw_html_snapshot_url = str(snapshot_path) if snapshot_path else None
            completed_at = run.completed_at
            await session.commit()

        if redis is not None and completed_at is not None:
            try:
                await write_data_updated_at(redis, completed_at)
            except Exception:
                # Stale X-Data-Updated-At isn't worth crashing a successful scrape.
                logger.exception("failed to write data_updated_at to redis")

        had_changes = (created + updated + removed + restored) > 0
        if export_dir is not None:
            try:
                async with session_factory() as session:
                    await export_all(session, export_dir, source_snapshot=snapshot_path)
            except Exception:
                # Open-data export is best-effort here — scrape itself already
                # succeeded; a stale dsa-data dir is recoverable on next run.
                logger.exception("failed to export open data to %s", export_dir)
            else:
                # Only push when the diff actually changed something; idempotent
                # re-runs shouldn't fill the dsa-data history with empty commits.
                if had_changes and settings.data_export_remote:
                    try:
                        publish_changes(
                            export_dir,
                            branch=settings.data_export_branch,
                            committer_name=settings.data_export_committer_name,
                            committer_email=settings.data_export_committer_email,
                            message=(
                                f"data: {created} created, {updated} updated, "
                                f"{removed} removed, {restored} restored "
                                f"({started_at.isoformat()})"
                            ),
                        )
                    except Exception:
                        logger.exception("failed to publish dsa-data to remote")

        logger.info(
            "scrape %s: seen=%d created=%d updated=%d removed=%d restored=%d errors=%d",
            run.status,
            len(raw_rows),
            created,
            updated,
            removed,
            restored,
            len(parse_errors),
        )
        return IngestResult(
            run_id=run_id,
            status=ScrapeRunStatus(run.status),
            rows_seen=len(raw_rows),
            rows_created=created,
            rows_updated=updated,
            rows_removed=removed,
            rows_restored=restored,
            parse_errors=parse_errors,
            snapshot_path=snapshot_path,
        )
    except Exception as e:
        logger.exception("scrape failed")
        async with session_factory() as session:
            run = await session.get(ScrapeRunORM, run_id)
            if run is not None:
                run.completed_at = datetime.now(UTC)
                run.status = ScrapeRunStatus.failed.value
                run.error_message = f"{type(e).__name__}: {e}"[:1000]
                await session.commit()
        # Best-effort Slack alert on hard failure; never let a Slack outage
        # mask the underlying exception.
        await notify_slack(
            settings.slack_webhook_url,
            f":rotating_light: dsa-api scrape failed: {type(e).__name__}: {e}",
        )
        raise
    finally:
        if own_client:
            await client.aclose()
