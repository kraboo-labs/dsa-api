# dsa-api

A machine-readable mirror of the **EU Trusted Flaggers register** under the
Digital Services Act (DSA Article 22(5)). The European Commission publishes the
register as an HTML page; `dsa-api` scrapes it on a schedule, stores a
structured, queryable copy, exposes it as a REST API, and publishes a flat
open-data snapshot to [`kraboo-labs/dsa-data`](https://github.com/kraboo-labs/dsa-data).

> **Not a source of truth.** This is a community mirror for convenience. The
> authoritative register remains
> [the European Commission page](https://digital-strategy.ec.europa.eu/en/policies/trusted-flaggers-under-dsa).
> Every API response carries an `X-Source-URL` and `X-Disclaimer` header.

| | |
|---|---|
| **API** | https://api.dsa-api.com |
| **Docs (Swagger UI)** | https://docs.dsa-api.com/docs |
| **Status** | https://status.dsa-api.com |
| **Open data** | https://github.com/kraboo-labs/dsa-data |

## API

All endpoints are public, read-only (`GET`), unauthenticated, and CORS-enabled
for any origin. The full schema is at [`/openapi.json`](https://api.dsa-api.com/openapi.json).

| Endpoint | Purpose |
|---|---|
| `GET /v1/trusted-flaggers` | List flaggers. Filters: `country` (repeatable), `area` (repeatable), `dsc_country`, `status` (default `active`, `all` for everything), `designated_after`/`designated_before`, `q` (name/address substring). Paginated via `limit` (≤200) / `offset`. |
| `GET /v1/trusted-flaggers/lookup` | Resolve a flagger by `email`, `domain`, or `website`. |
| `GET /v1/trusted-flaggers/{id}` | A single flagger by UUID. |
| `GET /v1/trusted-flaggers/{id}/history` | Change events for one flagger. |
| `GET /v1/changes` | Changelog of created/updated/removed/restored events. `since` (ISO, default 30d ago), `limit` (≤500), `offset`. |
| `GET /v1/stats` | Aggregate counts by country, area, and DSC country. |
| `GET /v1/health` | DB-backed readiness check. |
| `GET /v1/version` | App version + environment. |

**Rate limits** (per client IP, sliding window): 60/minute and 5000/day by
default. Over the limit returns `429` with a `Retry-After` header. Responses on
the `/v1/` surface include `X-RateLimit-Limit` and `X-RateLimit-Window-Seconds`;
`X-Data-Updated-At` reflects the last successful scrape.

## Architecture

```
EU register (HTML + JSON) ──▶ scraper (CronJob, every 6h)
                                 │  parse → diff → ingest
                                 ▼
                          PostgreSQL  ◀── API (FastAPI)  ──▶ clients
                                 │                ▲
                                 │                └── Redis (rate-limit state)
                                 ▼
                       export JSON/CSV ──▶ git push ──▶ kraboo-labs/dsa-data
```

- **API** — FastAPI (`apps/api`), served by uvicorn. SQLAlchemy 2.0 async + asyncpg.
- **Scraper** — `apps/scraper`, runs as a Kubernetes CronJob every 6h: fetch →
  parse → diff against DB → ingest → export open data → push to `dsa-data`.
- **Watchdog** — hourly CronJob that alerts (Slack) if the last successful
  scrape is older than 24h.
- **Storage** — PostgreSQL (`trusted_flaggers`, `trusted_flagger_events`,
  `scrape_runs`), schema managed by Alembic (`migrations/`). Redis backs the
  rate limiter and the data-freshness timestamp.
- **Shared code** — `core/` (config, DB models, rate limiting, Slack/Sentry).

## Local development

Requires Python 3.12 and Docker.

```bash
# 1. Start Postgres + Redis
docker compose up -d

# 2. Install deps (use a venv)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 3. Configure env
cp .env.example .env        # defaults match docker-compose

# 4. Create the schema
alembic upgrade head

# 5. Run the API (http://localhost:8000/docs)
uvicorn apps.api.main:app --reload

# Run the scraper once (populates the DB)
python -m apps.scraper
```

### Quality gates

```bash
ruff check .            # lint
ruff format .           # format
pytest                  # tests (needs Postgres + Redis from docker compose)
pre-commit install      # ruff + gitleaks + hygiene on every commit
```

CI (`.github/workflows/ci.yml`) runs ruff + format-check + pytest against
service containers on every push and PR.

## Deployment

Runs on DigitalOcean Kubernetes. Pushing to `main` auto-deploys **when a change
affects what ships** (`apps/`, `core/`, `migrations/`, `k8s/`, `Dockerfile`,
`requirements*.txt`, `alembic.ini`); docs- and test-only commits are skipped.
Manual re-deploys via the `deploy.yml` workflow's "Run workflow" button.

The pipeline lints + tests, builds and pushes the image, reconciles secrets,
runs migrations, applies the manifests, and rolls out the API. Full one-time
setup (secrets, DNS, TLS) and operational notes live in
[`k8s/README.md`](k8s/README.md).
