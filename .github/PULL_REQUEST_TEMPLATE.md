## What & why

<!-- What does this change, and what problem does it solve? Link any issue. -->

Closes #

## Checklist

- [ ] `ruff check .` and `ruff format .` pass
- [ ] `pytest` passes (Postgres + Redis up via `docker compose`)
- [ ] Added/updated tests for behaviour changes
- [ ] Scraper changes stay defensive (log-and-skip a bad row, never crash the run)
- [ ] Schema changes have an Alembic migration
- [ ] Docs/README updated if the API surface changed
