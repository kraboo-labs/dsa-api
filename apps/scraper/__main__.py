import asyncio
import logging
import sys
from pathlib import Path

from apps.api.deps import get_redis, get_session_factory
from apps.scraper.ingest import run_ingest
from core.config import get_settings
from core.enums import ScrapeRunStatus

logger = logging.getLogger("apps.scraper")


async def _amain() -> int:
    settings = get_settings()
    snapshot_dir = Path(settings.snapshot_dir)
    factory = get_session_factory()
    redis = get_redis()
    try:
        result = await run_ingest(settings, factory, snapshot_dir=snapshot_dir, redis=redis)
    except Exception:
        # run_ingest already logged + marked the run failed.
        return 1
    logger.info(
        "done: status=%s run_id=%s seen=%d created=%d updated=%d removed=%d restored=%d "
        "parse_errors=%d snapshot=%s",
        result.status.value,
        result.run_id,
        result.rows_seen,
        result.rows_created,
        result.rows_updated,
        result.rows_removed,
        result.rows_restored,
        len(result.parse_errors),
        result.snapshot_path,
    )
    # Exit 2 on partial (some rows failed normalization) so CI/k8s can alert.
    if result.status is ScrapeRunStatus.partial:
        return 2
    return 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
