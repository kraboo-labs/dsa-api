# DSA Trusted Flaggers API — PRD

**Owner:** Martin
**Brand umbrella:** ibuildtoday
**GitHub org:** kraboo-labs
**Status:** Draft v2 (Phase 0 implemented)
**Last updated:** 2026-05-28

---

## 1. Overview

The European Commission is legally required by Article 22(5) of the Digital Services Act to publish the list of designated Trusted Flaggers "in an easily accessible and machine-readable format". In practice, the Commission publishes the list at `https://digital-strategy.ec.europa.eu/en/policies/trusted-flaggers-under-dsa` as a server-rendered HTML page that loads its data client-side from a webtools.europa.eu JSON endpoint configured inside a Drupal settings blob. There is no public, documented API; no JSON/CSV download; no change feed; no normalized schema; no stable identifiers; and the area-of-expertise vocabulary is free-text with one-off values.

This product provides exactly that: a developer-first, open-data, machine-readable mirror of the official EU Trusted Flaggers register, served as a REST API with 6-hour-fresh data, history, and change tracking.

**The product is a convenience layer over public data. We sell time-savings and structure, not compliance guarantees.** Authoritative source remains the EU page; this is explicitly stated in ToS, API responses (`X-Disclaimer: not-a-source-of-truth-see-source-url`), and product copy.

## 2. Goals & Non-goals

### Goals (MVP)
- Mirror the EU Trusted Flaggers list with ≤6h staleness from official publication
- Expose data as a clean REST API (JSON) and downloadable artifacts (JSON/CSV)
- Maintain immutable history of additions, modifications, and removals
- Publish open dataset under CC-BY 4.0 on GitHub with daily commits
- Build credibility and traction in the EU Trust & Safety / compliance developer community
- Validate paid-tier demand within 2–3 months

### Non-goals (MVP)
- ❌ No compliance guarantees, certifications, or legal advice
- ❌ No webhooks, API keys, accounts, or billing (defer until traction is validated)
- ❌ No notice management, statement-of-reasons submission, or moderation workflow
- ❌ No coverage of DSCs, VLOPs, or ODS bodies (Phase 2)
- ❌ No SLA commitments beyond best-effort

## 3. Users & Use Cases

### Primary user
EU mid-market online platform engineer / compliance ops engineer who has just been told by legal that "we need to handle Trusted Flagger notices with priority per Article 22" and now needs to wire something up.

### Use cases (MVP)
1. **Lookup:** "Is `notices@addictions-france.org` a designated Trusted Flagger? In which area of expertise?"
2. **Filter:** "Show me all Trusted Flaggers operating in Slovakia."
3. **Discovery:** "Give me all TFs whose area of expertise includes IP infringement."
4. **Audit:** "Was this entity a Trusted Flagger on 2026-03-15 when we received their notice?"
5. **Change monitoring:** "Show me TFs added in the last 30 days." (Polling — webhooks come in Phase 2.)

## 4. Product Scope (MVP)

### Public website
- Landing page on chosen domain (see Open Questions §14)
- Positioning: "Machine-readable mirror of the official EU Trusted Flaggers register. Free, open data, developer-first."
- Live count of TFs, last scrape timestamp, source attribution
- API documentation (OpenAPI/Swagger)
- Link to GitHub repo with raw data
- Waitlist form for "Pro tier" (webhooks, lookup API, history exports)

### GitHub data repo
- Separate public repo: `dsa-data` (or similar)
- License: CC-BY 4.0
- Daily commit: updated `trusted-flaggers.json`, `trusted-flaggers.csv`, `changelog.json`
- README explains source, schema, license, attribution requirement

### REST API
- Versioned (`/v1/`)
- Public, unauthenticated, IP-based rate limited
- See §6 for endpoint specification

### RSS feed
- `/rss/changes.xml` — TF additions, modifications, removals
- Drives SEO + lets compliance teams subscribe in their RSS reader

## 5. Data Model

### Source data flow (real, as observed 2026-05-28)
The public page does NOT contain a `<table>`. It embeds a Drupal settings JSON blob (`<script data-drupal-selector="drupal-settings-json">`) whose `cnt_description.url` points at a `webtools.europa.eu/rest/wbase/wbql/<id>/<rev>/content` endpoint. We fetch the HTML on every scrape to discover that URL (the path's cryptic id can change), then hit the JSON endpoint. Each row exposes: `name`, `country_` (ISO α2, already normalized), `date_of_certification_` (DD/MM/YYYY), `dsc_country_` (DSC name with sometimes a trailing `(CC)`), `areas_of_expertise` (single string, `; `-separated), `tf_address`, `tf_contact_` (email), `tf_contact__url` (URL-encoded mailto fallback), `tf_website`. 72 rows as of 2026-05-28; growing monthly.

### Normalized schema

```python
# ScrapedTrustedFlagger — internal model produced by parse+normalize. Lenient
# str types for url/email so EU edge cases don't break the parser.
class ScrapedTrustedFlagger(BaseModel):
    id: UUID                              # Stable, derived from (name, DSC, designation_date)
    name: str
    legal_form: Optional[str]
    website: Optional[str]                # str (not HttpUrl) — see note above
    email: Optional[str]
    email_domain: Optional[str]
    address_raw: Optional[str]
    country_code: str                     # ISO 3166-1 alpha-2
    city: Optional[str]                   # Best-effort extraction (deferred)
    postal_code: Optional[str]            # Best-effort extraction (deferred)
    dsc_name: Optional[str]
    dsc_country_code: Optional[str]
    areas_of_expertise_raw: list[str]     # Split on '; '
    areas_of_expertise: list[AreaEnum]    # Normalized to enum
    designation_date: date
    source_hash: str                      # SHA-256 over canonical raw row

# TrustedFlagger — public API contract. Adds operational fields and status.
class TrustedFlagger(ScrapedTrustedFlagger):
    status: Literal["active", "suspended", "revoked", "removed"] = "active"
    first_seen_at: datetime
    last_seen_at: datetime
    source_snapshot_url: Optional[str]


# 18 values (12 PRD baseline + 6 added 2026-05-28 from real EU data,
# closing Open Question §14.5). Unknown raw labels fall back to `other`
# and the raw string is preserved in areas_of_expertise_raw.
class AreaEnum(StrEnum):
    ip_infringement = "ip_infringement"
    illegal_speech = "illegal_speech"
    terrorist_content = "terrorist_content"     # not yet observed in live data; forward-looking
    csam = "csam"                               # not yet observed; forward-looking
    protection_of_minors = "protection_of_minors"
    cyber_violence = "cyber_violence"
    gender_based_violence = "gender_based_violence"
    scams_fraud = "scams_fraud"
    illegal_products = "illegal_products"
    consumer_protection = "consumer_protection"
    disinformation = "disinformation"           # forward-looking; EU currently labels separately
    # Added 2026-05-28:
    data_privacy = "data_privacy"               # "Data protection and privacy violations"
    public_security = "public_security"         # "Risk for public security"
    violence = "violence"                       # "Violence"
    self_harm = "self_harm"                     # "Incitement to self-harm"
    animal_welfare = "animal_welfare"           # "Animal Welfare"
    civil_discourse = "civil_discourse"         # "Negative effects on civil discourse and elections"
    other = "other"
```

**Status semantics:** `active` = currently on EU's register; `removed` = was on the register, now gone but no formal EU statement; `suspended`/`revoked` = formal DSC actions (EU does not currently publish these — forward-looking).

### Postgres schema (DigitalOcean managed)

```sql
-- Current state
CREATE TABLE trusted_flaggers (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    legal_form TEXT,
    website TEXT,
    email TEXT,
    email_domain TEXT,
    address_raw TEXT,
    country_code CHAR(2) NOT NULL,
    city TEXT,
    postal_code TEXT,
    dsc_name TEXT,
    dsc_country_code CHAR(2),
    areas_of_expertise_raw JSONB,
    areas_of_expertise JSONB,             -- normalized enum array
    designation_date DATE,
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    source_hash TEXT NOT NULL,
    source_snapshot_url TEXT
);

CREATE INDEX idx_tf_country ON trusted_flaggers (country_code);
CREATE INDEX idx_tf_email_domain ON trusted_flaggers (email_domain);
CREATE INDEX idx_tf_status ON trusted_flaggers (status);
CREATE INDEX idx_tf_areas_gin ON trusted_flaggers USING GIN (areas_of_expertise);

-- Append-only audit log
CREATE TABLE trusted_flagger_events (
    event_id BIGSERIAL PRIMARY KEY,
    tf_id UUID NOT NULL,
    event_type TEXT NOT NULL,             -- 'created' | 'updated' | 'removed' | 'restored'
    diff JSONB,                            -- field-level diff for 'updated'
    snapshot JSONB,                        -- full row snapshot at event time
    scrape_run_id UUID NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tfe_tf ON trusted_flagger_events (tf_id, occurred_at);
CREATE INDEX idx_tfe_time ON trusted_flagger_events (occurred_at);

-- Operational
CREATE TABLE scrape_runs (
    id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,                  -- 'running' | 'success' | 'failed' | 'partial'
    source_url TEXT NOT NULL,
    source_response_status INT,
    source_content_hash TEXT,
    rows_seen INT,
    rows_created INT,
    rows_updated INT,
    rows_removed INT,
    error_message TEXT,
    raw_html_snapshot_url TEXT
);
```

## 6. API Specification

Base URL: `https://api.dsa-api.com/v1`

All responses include:
- `X-Source-URL` header pointing to official EU page
- `X-Data-Updated-At` header with last successful scrape timestamp
- `X-Disclaimer` header: `not-a-source-of-truth-see-source-url`

### Endpoints

**`GET /v1/trusted-flaggers`**
List all TFs. Supports query parameters:
- `country` — ISO alpha-2, repeatable
- `area` — normalized enum, repeatable
- `dsc_country` — ISO alpha-2
- `status` — defaults to `active`; pass `all` to include suspended/revoked
- `designated_after`, `designated_before` — ISO date
- `q` — full-text search across name + address
- `limit` (default 50, max 200), `offset`

Response:
```json
{
  "data": [ { ...TrustedFlagger } ],
  "meta": {
    "total": 64,
    "limit": 50,
    "offset": 0,
    "data_updated_at": "2026-05-27T04:12:38Z",
    "source_url": "https://digital-strategy.ec.europa.eu/..."
  }
}
```

**`GET /v1/trusted-flaggers/{id}`**
Single TF by stable ID.

**`GET /v1/trusted-flaggers/lookup`**
Convenience endpoint for the "is this entity a TF?" use case. Exactly one of:
- `email=foo@bar.org`
- `domain=bar.org`
- `website=https://bar.org/contact`

Returns matched TF(s) or empty array.

**`GET /v1/trusted-flaggers/{id}/history`**
Returns event log for a single TF.

**`GET /v1/changes`**
Recent changes across all TFs. Supports `since=<ISO timestamp>`, default last 30 days.

**`GET /v1/stats`**
Aggregates: count by country, by area, by DSC. Pure read, cached aggressively.

**`GET /v1/health`** and **`GET /v1/version`**
Standard.

### Rate limiting
- Default: 60 req/min per IP, 5000 req/day per IP
- Sliding window via Redis
- 429 with `Retry-After` header on limit
- No accounts / API keys in MVP — IP only

### Versioning policy
- Breaking changes → new `/v2/` path; `/v1/` maintained for 6 months minimum
- Additive changes (new fields, new endpoints) are non-breaking
- Deprecated endpoints return `Deprecation` and `Sunset` headers

## 7. Open Data Strategy

This is the moat. Open data on GitHub is what differentiates us from Tremau's lead-gen Baserow embed and any future closed competitor.

### `dsa-data` repository
- Daily commit by CI bot containing:
  - `data/trusted-flaggers.json` — current state, pretty-printed
  - `data/trusted-flaggers.csv` — flat CSV with most useful columns
  - `data/changelog.json` — all events from inception
  - `data/source-snapshots/YYYY-MM-DD.html` — frozen copy of EU page
- README with attribution requirement, schema, "how to use without our API"
- License: CC-BY 4.0 for data, MIT for code

### Why this matters strategically
- Removes the "vendor lock-in" objection from any future paid customer
- Makes us a citable source in academic/policy research
- SEO: every GitHub commit is a fresh signal
- If we ever shut down, data remains usable — this is a trust signal that paradoxically makes customers more willing to depend on us

## 8. Technical Architecture

### Runtime
- **Language:** Python 3.12
- **Web framework:** FastAPI + uvicorn
- **Scraper:** httpx + selectolax (faster than bs4) + pydantic for parsing/validation
- **Migrations:** alembic
- **Schedule:** k8s CronJob (no in-process scheduler)
- **Containers:** Docker, multi-stage builds, distroless or slim-bookworm base

### Components (k8s)

1. **`api` Deployment** (2 replicas to start)
   - FastAPI behind ingress
   - Read-only DB access
   - Reads from Redis cache for hot endpoints

2. **`scraper` CronJob**
   - Schedule: `0 */6 * * *` (every 6 hours)
   - Idempotent: re-runs are safe (diff against current state, verified empirically — second consecutive run produces 0 writes)
   - Two-step fetch: HTML page (for the embedded JSON API URL + snapshot) → JSON API (the data)
   - HTML snapshot saved to `settings.snapshot_dir` (local disk in dev, object storage in prod) for provenance per §11
   - On parse failure (HTML missing the drupal-settings blob, JSON envelope broken, etc.): writes error to `scrape_runs`, alerts via Slack webhook, does NOT modify `trusted_flaggers` table
   - On success: writes events, updates `trusted_flaggers`, writes `dsa:last_scrape_completed_at` to Redis (powers the `X-Data-Updated-At` header), invalidates Redis cache, pushes to `dsa-data` repo via GitHub API

3. **`migrations` Job** (one-shot per deploy)
   - Alembic upgrade head
   - Runs as initContainer or via Helm hook

### External dependencies
- **DigitalOcean Managed Postgres** — connection string in k8s Secret
- **DigitalOcean Managed Redis** — for rate limiting + response cache
- **DigitalOcean Spaces (S3-compatible)** — for HTML snapshots
- **GitHub** — for open data repo (push via deploy key)
- **Sentry** — error tracking (free tier)

### Caching strategy
- List endpoints: 5 min TTL in Redis, key by query params hash
- Single-TF endpoints: 1 hour TTL, invalidated on TF event
- `/stats`: 1 hour TTL, regenerated by scraper after each run
- All cache invalidated on successful scrape that produced changes

### Security
- No PII processed — TF emails are organizational contacts, published by EU
- HTTPS only, HSTS, secure headers
- CORS: open `*` for GETs (it's a public API), no credentials
- Secrets in k8s Secrets, sealed-secrets if GitOps

## 9. Operations & SLO

### Targets (best-effort, not contractually binding in MVP)
- **Data freshness:** ≤6h from EU publication, measured by scrape cadence
- **API availability:** 99% monthly (allows ~7h downtime/month — fine for free MVP)
- **Scrape success rate:** ≥95% over rolling 7 days

### Monitoring
- Sentry for application errors
- Simple status page: scraper last-success timestamp + API health
- Slack webhook on:
  - Scrape failure
  - HTML structure change detected (e.g., column count mismatch)
  - Source page returns non-200
  - >24h since last successful scrape

### Disaster recovery
- DigitalOcean automated DB backups (daily, 7-day retention on basic tier)
- Open data repo IS the backup — full state is reconstructable from git history
- HTML snapshots in Spaces are the ultimate source of truth for "what did the EU page say on date X"

## 10. Success Metrics & Paid-Tier Trigger

### Validation phase: 2–3 months from public launch

**Vanity metrics (track, don't optimize):**
- GitHub stars on `dsa-data` and `dsa-api` repos
- Twitter/LinkedIn mentions
- Inbound press / newsletter citations

**Real signal metrics:**
- Unique IPs per month hitting API
- Requests per month per IP (distribution — looking for power users)
- Waitlist sign-ups for paid tier
- Inbound emails asking "do you have webhooks / accounts / SLA / on-prem"
- Conversion from landing → API docs view → first API call

**Trigger for building paid tier:**
- ≥500 unique IPs/mo, OR
- ≥30 waitlist sign-ups with valid corp emails, OR
- ≥5 direct emails asking about webhooks or paid tier

If none of these triggers fires within 3 months, treat as a portfolio piece + Ringier-internal utility, not a SaaS.

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| EU changes HTML structure (or moves the embedded JSON API URL) | High over 12mo | Scraper breaks | Snapshot HTML, discover the JSON API URL from the drupal-settings blob on every run, alert on `HtmlStructureError` / `ApiResponseError`, fail loudly without writing bad data |
| EU adds a new free-text area-of-expertise label | High over 12mo | New label maps to `other` until taxonomy is extended | Unknown labels are accepted and logged; raw label preserved in `areas_of_expertise_raw`; monitor scrape logs for `AreaEnum.other` rate spikes |
| EU publishes official machine-readable feed | Medium | Reduces our raw-data value | Our value shifts to history + lookup + tooling; we become a wrapper. Still defensible. |
| Competitor (Tremau, Checkstep) launches free API | Medium | Commoditization | Open-source moat + speed; we are friendlier to developers than any T&S vendor |
| TF entity requests removal | Low | Legal noise | Clear policy: data is EU-published; requests go to EU. We mirror only what is publicly designated. |
| Scraper parses incorrectly, returns wrong email for TF | Medium | Real downstream risk for customers | Schema validation, cross-check against previous snapshot, last-known-good fallback, parse-confidence flag |
| Data sovereignty / GDPR claim | Low | Reputational | TFs are legal entities, contact emails are organizational, publication is mandated by EU law. Solid ground. |

## 12. Roadmap

### Phase 0 — Internal (week 1, evenings) — ✅ COMPLETE 2026-05-28
- ✅ Repo skeleton, FastAPI app, Postgres schema, alembic
- ✅ Scraper + parser + tests against real EU snapshot (pivot: JSON API, not HTML table)
- ✅ Local docker-compose for dev (postgres on host port 5433 to coexist with brew postgres)
- ✅ End-to-end verified: 72 entries in DB, idempotent on second run, all 8 PRD §6 endpoints live, Redis rate limit middleware, `X-Data-Updated-At` header wired through

### Phase 1 — Public soft launch (week 2)
- Deploy to k8s
- Domain + landing page (single page, no marketing site yet)
- `dsa-data` GitHub repo with first commit
- API docs at `/docs` (FastAPI auto-generated)
- Status page
- Soft-share with 2–3 trusted CEE engineers for feedback

### Phase 2 — Public hard launch (week 3)
- Launch posts: LinkedIn (EU T&S circles), Twitter/X, Hacker News "Show HN", `/r/europe`
- Slovak/Czech tech press pitches (Živé.sk, Lupa.cz)
- Outreach to EU T&S newsletters (Safety Space by Tremau, Platform Governance Research Network)
- Submit to data.europa.eu as dataset
- RSS feed announced

### Phase 3 — Iterate based on signal (weeks 4–12)
- Improve area-of-expertise normalization based on real data growth
- Add DSCs registry if there is meaningful pull
- Add ODS bodies / VLOPs if same
- SEO content: "Trusted Flaggers in [Country] — full list and contact info" landing pages

### Phase 4 — Paid tier (month 3+, gated by §10 trigger)
- API keys + accounts
- Webhooks (additions, modifications, removals — filtered by country/area)
- Email/Slack alerts
- 90-day diff exports
- Stripe billing, self-serve checkout
- Pro tier €49/mo, Team tier €199/mo

## 13. Out of Scope (Explicit)

- AuthN/Z, user accounts, API keys (Phase 4)
- Payment processing (Phase 4)
- Webhooks of any kind (Phase 4)
- Notice management, statement-of-reasons submission, content moderation
- DSC / VLOP / ODS bodies registries (Phase 3 at earliest)
- AI-powered classification, legal advice, compliance certification
- White-label, on-prem, enterprise contracts
- Mobile app

## 14. Open Questions

1. ~~**Domain choice.**~~ ✅ **Decided: `dsa-api.com`** (registered). Cloudflare DNS. Subdomains: `api.`, `docs.`, `data.`, `status.`, `blog.` (later), `app.` (Phase 4). Email via Cloudflare Email Routing: `hello@`, `security@`, `abuse@`, `dpo@`, `press@` → forward to Martin's inbox.
2. **Ringier as design partner — explicit or quiet?** Are we OK to mention Ringier in case studies later, or keep this fully independent? → **Action: clarify before any public mention.**
3. ~~**GitHub org name.**~~ ✅ **Decided 2026-05-28: `kraboo-labs`**. Code repo: `github.com/kraboo-labs/dsa-api`. Data repo: `github.com/kraboo-labs/dsa-data` (not yet created — Phase 1).
4. **Status page tooling.** Self-host (`upptime` on GitHub Pages — free, ironic and on-brand), or hosted (`betterstack`, free tier)?
5. ~~**Initial area-of-expertise mapping.**~~ ✅ **Resolved 2026-05-28.** Captured all 18 distinct labels from the live 72-row dump. AreaEnum extended by 6 values: `data_privacy`, `public_security`, `violence`, `self_harm`, `animal_welfare`, `civil_discourse`. Mapping table lives in `core/normalize.py::AREA_LABEL_MAP`. Unknown labels still fall back to `other` with the raw string preserved.
6. **Should we ping the European Commission DG CONNECT** to tell them we built this? Could go either way — friendly heads-up vs. flying under the radar. My instinct: heads-up email after public launch, with offer to feed back data quality issues. Builds goodwill, signals seriousness.

---

## Appendix A — Tech stack summary

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| Web framework | FastAPI |
| ASGI server | uvicorn (gunicorn worker in prod) |
| HTTP client | httpx |
| HTML parsing | Regex over the drupal-settings-json script tag (selectolax kept as a dep for any future HTML work) |
| JSON envelope | stdlib json |
| Data validation | pydantic v2 (+ pydantic-settings for config) |
| ORM | SQLAlchemy 2.x + asyncpg |
| Migrations | alembic |
| DB | DigitalOcean Managed Postgres |
| Cache | DigitalOcean Managed Redis |
| Object storage | DigitalOcean Spaces |
| Container | Docker, slim-bookworm |
| Orchestration | Kubernetes (existing cluster) |
| Scheduler | k8s CronJob |
| CI/CD | GitHub Actions |
| Observability | Sentry (errors), Slack webhook (alerts) |
| Docs | FastAPI auto-OpenAPI + ReDoc |

## Appendix B — Initial directory layout

```
dsa-api/
├── apps/
│   ├── api/                  # FastAPI app
│   │   ├── main.py
│   │   ├── routers/
│   │   ├── deps.py
│   │   └── middleware/
│   └── scraper/              # Scrape + ingest CLI
│       ├── __main__.py
│       ├── fetch.py
│       ├── parse.py
│       └── ingest.py
├── core/                     # Shared domain
│   ├── models.py             # Pydantic
│   ├── db.py                 # SQLAlchemy
│   ├── enums.py
│   └── normalize.py
├── migrations/               # alembic
├── deploy/
│   ├── k8s/
│   │   ├── api-deployment.yaml
│   │   ├── scraper-cronjob.yaml
│   │   ├── ingress.yaml
│   │   └── secrets.example.yaml
│   └── Dockerfile
├── tests/
├── pyproject.toml
└── README.md
```
