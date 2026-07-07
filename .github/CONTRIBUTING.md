# Contributing to dsa-api

Thanks for helping improve the open mirror of the EU Trusted Flaggers register.

## Ways to contribute

- **Report a data problem** — a wrong, missing, or stale flagger. Use the
  [📊 Data issue](https://github.com/kraboo-labs/dsa-api/issues/new?template=data_issue.yml)
  template and link the [official EU register](https://digital-strategy.ec.europa.eu/en/policies/trusted-flaggers-under-dsa).
  This is the most valuable contribution — the mirror is only as good as its parsing.
- **Report a bug** in the API or scraper — [🐛 Bug report](https://github.com/kraboo-labs/dsa-api/issues/new?template=bug_report.yml).
- **Suggest a feature** — [💡 Feature request](https://github.com/kraboo-labs/dsa-api/issues/new?template=feature_request.yml).
- **Open a PR** — bug fixes and parser improvements welcome.

## Local setup

Requires Python 3.12 and Docker.

```bash
docker compose up -d                 # Postgres + Redis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head                 # create schema
uvicorn apps.api.main:app --reload   # http://localhost:8000/docs
python -m apps.scraper               # run the scraper once
```

## Before you open a PR

```bash
ruff check .          # lint
ruff format .         # format
pytest                # tests (needs Postgres + Redis)
pre-commit install    # ruff + gitleaks + hygiene on every commit
```

- Keep PRs focused; one concern per PR.
- Add or update tests for behaviour changes.
- CI (ruff + format-check + pytest) must pass.
- The scraper must stay defensive: never crash the pipeline on a single
  malformed row — log and skip, so one bad entry can't stall the whole sync.

## Data model changes

Schema changes go through Alembic migrations (`migrations/`). Don't hand-edit
the database. The normalized `areas_of_expertise` enum lives in the code — when
the EU introduces a new label, map it and preserve the raw string alongside.

## Questions

Open a [discussion](https://github.com/kraboo-labs/dsa-api/discussions) or email
**hello@dsa-api.com**.
