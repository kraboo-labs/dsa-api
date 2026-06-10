# DSA Trusted Flaggers API — Monetization PRD

**Owner:** Martin
**Brand umbrella:** ibuildtoday
**GitHub org:** kraboo-labs
**Status:** Draft v1.0.0
**Last updated:** 2026-06-02
**Target:** Phase 2 (post Phase-0/1 — API is live in production)

**Context:** The core API is live (`api.dsa-api.com`, docs, open data, scraper, monitoring). The base PRD (`PRD_dsa-flaggers-api.md`) deliberately deferred "API keys, accounts, billing" until traction was validated and committed to "validate paid-tier demand within 2–3 months". This PRD defines **how to charge** for the service without paywalling the underlying public data.

**Analysis Reference:** Live system as built — FastAPI app (`apps/api`), Redis sliding-window rate limiter keyed by IP (`core/ratelimit.py`), Postgres with `trusted_flaggers` + `trusted_flagger_events` (change history already captured), scraper diffing on every run. Base PRD §6 (rate limiting), §7 (open data / CC-BY), §3 (use cases — note UC-4 "point-in-time audit" and UC-5 "change monitoring").

---

## Strategic analysis

### The core constraint
The data is **public EU open data**, and we ourselves republish it free under **CC-BY 4.0** at `kraboo-labs/dsa-data`. **We cannot sell the data** — anyone can clone the raw JSON/CSV. We sell the **managed service around it**: availability, structured/queryable access, change notifications, point-in-time audit, higher throughput, and support/SLA. This is the same model as every "open data as a service" business (it must be honest about the free source — already enforced via `X-Disclaimer`).

### What customers will actually pay for (value ladder)
1. **Convenience & reliability** — a maintained, documented, always-on API vs. self-hosting the open dataset.
2. **Higher / guaranteed quotas** — beyond the free anonymous limit.
3. **Webhooks** — push notification when a flagger is added/modified/removed, instead of polling (UC-5).
4. **Point-in-time audit** — "was entity X a designated Trusted Flagger on date Y?" with a verifiable response (UC-4). This is the **highest-value, hardest-to-self-host** feature for compliance defensibility, and the event history to back it already exists.
5. **Bulk / historical export** and **lookup-at-scale** (by email/domain).
6. **SLA + support** for business buyers.

### Go-to-market options (lowest build → highest control)
- **A. Demand validation first** — waitlist (already planned) + optionally list on an **API marketplace (RapidAPI)** which handles keys, metering, billing for ~20% cut. Near-zero build; proves willingness to pay before investing.
- **B. Self-serve freemium** — own API-key auth + tiers + **Stripe** subscriptions + a thin customer portal. Full control and margin; the real product. Builds directly on the existing rate-limit infra (re-key from IP → API key).
- **C. Sponsorship/public-good** — GitHub Sponsors / donations layered on the free tier. Weak as primary revenue; fine as a supplement given the public-good framing.

**Recommendation:** Run **A** to validate (cheap), build **B** as the product, keep the **free anonymous tier** permanently (adoption, SEO, credibility, and it's the honest open-data face). Reserve **C** as a supplement. This PRD scopes **B** as the buildable target, with **A** as the gating pre-step.

---

## User Stories (P0)

**US-001:** As an API consumer, I want to sign up and get an API key, so that I can authenticate and access a paid tier.
- **AC1:** Self-serve signup issues a usable API key shown once — Verify via: E2E
- **AC2:** Requests with a valid key are authenticated; invalid/revoked keys return `401` — Verify via: Integration
- **Priority:** P0 | **Effort:** M

**US-002:** As a paying customer, I want my rate limit/quota tied to my plan, so that I get the throughput I pay for.
- **AC1:** An authenticated key is metered against its plan's limits, not the shared IP limit — Verify via: Integration
- **AC2:** Anonymous (no key) traffic still works on the free IP-based limit — Verify via: Integration
- **AC3:** Exceeding the plan quota returns `429` with `Retry-After` — Verify via: Integration
- **Priority:** P0 | **Effort:** M

**US-003:** As the operator, I want subscription billing, so that plan changes map to entitlements automatically.
- **AC1:** Completing Stripe Checkout activates the corresponding plan within 60s — Verify via: E2E (Stripe test mode)
- **AC2:** Cancellation/non-payment downgrades the key to free tier at period end — Verify via: Integration (simulated Stripe webhooks)
- **Priority:** P0 | **Effort:** L

**US-004:** As a customer, I want a portal to manage keys, view usage, and manage billing, so that I'm self-sufficient.
- **AC1:** Portal lists keys, current plan, and month-to-date usage — Verify via: E2E
- **AC2:** Customer can rotate/revoke a key; revoked keys stop working within 60s — Verify via: Integration
- **Priority:** P0 | **Effort:** M

**US-005:** As a compliance engineer, I want webhooks on flagger changes, so that I'm notified without polling. *(value-add)*
- **AC1:** A subscribed endpoint receives a signed payload on each created/updated/removed/restored event — Verify via: Integration
- **AC2:** Failed deliveries retry with backoff and are visible in the portal — Verify via: Integration
- **Priority:** P1 | **Effort:** M

**US-006:** As a compliance engineer, I want a point-in-time audit endpoint, so that I can prove a flagger's status on a past date. *(value-add)*
- **AC1:** `status as of {date}` for a flagger is reconstructed from event history and returned deterministically — Verify via: Integration against seeded history
- **Priority:** P1 | **Effort:** M

---

## Functional Requirements

| ID | Requirement | Priority | Effort | Verification | Status |
|----|-------------|----------|--------|--------------|--------|
| REQ-001 | API-key authentication accepted via `Authorization: Bearer` and/or `X-API-Key`; keys stored hashed, never logged | P0 | M | Integration + Security review | 📋 |
| REQ-002 | Rate limiter keys on API key when present, else falls back to client IP (free tier); reuses the existing Redis sliding-window mechanism | P0 | S | Integration | 📋 |
| REQ-003 | Plan model with configurable per-tier limits (per-minute, per-day, feature flags) | P0 | M | Unit + Integration | 📋 |
| REQ-004 | Per-key usage metering (request counts, period-to-date) persisted for billing + portal display | P0 | M | Integration | 📋 |
| REQ-005 | Stripe Checkout for subscription purchase; webhook handler maps subscription lifecycle → plan entitlement, idempotently | P0 | L | E2E (Stripe test) + Integration | 📋 |
| REQ-006 | Customer portal: signup/login, key create/rotate/revoke, usage view, link to Stripe billing portal | P0 | L | E2E | 📋 |
| REQ-007 | Free anonymous tier preserved unchanged (no key required, IP-limited) | P0 | S | Integration | 📋 |
| REQ-008 | Per-tier response: include plan + remaining-quota headers for authenticated keys | P0 | S | Integration | 📋 |
| REQ-009 | Webhook subscriptions: register endpoint, deliver signed (HMAC) change events, retry with backoff, dead-letter after N attempts | P1 | M | Integration | 📋 |
| REQ-010 | Point-in-time status endpoint: reconstruct a flagger's status as of a given date from `trusted_flagger_events` | P1 | M | Integration | 📋 |
| REQ-011 | Bulk/historical export (full dataset + changelog) gated to paid tiers | P1 | S | Integration | 📋 |
| REQ-012 | ToS + pricing page stating the data is free/public (CC-BY) and we charge for the service; disclaimer headers retained | P0 | S | Manual (legal review) | 📋 |
| REQ-013 | Demand-validation step (waitlist conversion and/or RapidAPI listing) gating the build of REQ-005/006 | P0 | S | Manual (metric gate) | 📋 |

---

## Non-Functional Requirements

| ID | NFR | Category | Target | Signal / Metric | Status |
|----|-----|----------|--------|-----------------|--------|
| NFR-001 | API-key auth overhead | Performance | <10ms p95 added latency (key lookup cached in Redis) | APM auth-middleware latency | 📋 |
| NFR-002 | Keys at rest | Security | Stored as salted hashes; plaintext shown once at creation only | Security review + code audit | 📋 |
| NFR-003 | Stripe webhook integrity | Security | 100% of billing webhooks signature-verified; replay-safe (idempotent) | Webhook handler logs / monitoring | 📋 |
| NFR-004 | Metering accuracy | Reliability | Usage counts within ±1% of gateway counts over a billing period | Reconciliation check | 📋 |
| NFR-005 | Paid-tier availability | Reliability | 99.9% monthly for `/v1/*` | Upptime + alerting | 📋 |
| NFR-006 | Customer-account data | Compliance | GDPR: minimal PII (email + billing via Stripe), deletable on request | DPA / data-map review | 📋 |
| NFR-007 | Webhook delivery | Reliability | ≥99% of events delivered within 5 min (incl. retries) | Delivery success metric | 📋 |
| NFR-008 | Billing→entitlement propagation | Reliability | Plan change reflected in quota within 60s | E2E timing test | 📋 |

---

## Out of Scope (this PRD / release)

- Per-request **metered/usage-based overage** billing (start with flat subscription tiers; revisit after data).
- **Enterprise SSO / SAML**, custom contracts, on-prem licensing.
- **Coverage expansion** (DSCs, VLOPs, ODS bodies) — separate roadmap item.
- **Compliance guarantees, certifications, legal advice** — explicitly never sold (base PRD non-goal).
- **Reseller / white-label** API.
- Building a **custom payment processor** — Stripe (or marketplace) only.

---

## Risks & Mitigations

| Risk | Severity | Owner | Mitigation | Rollback |
|------|----------|-------|------------|----------|
| Low willingness to pay (data is free) | **H** | Product | Gate build on REQ-013 demand validation; differentiate on webhooks/audit/SLA, not data | Stay free-only; keep open dataset |
| Legal/perception: "charging for public gov data" | M | Product/Legal | Sell service not data; keep CC-BY dataset free; explicit ToS + disclaimer headers (REQ-012) | Revert to free tier; dataset stays public |
| Self-hosting undercuts paid tiers | M | Product | Lean into convenience + webhooks + point-in-time audit + SLA that are costly to self-run | n/a |
| Billing bugs / double-charge | **H** | Dev | Stripe as source of truth; idempotent webhook handling (REQ-005, NFR-003); test-mode E2E before launch | Disable paid signup; manual refunds |
| API-key leakage / abuse | M | Dev/Infra | Hashed keys, rotation/revocation (REQ-006), per-key limits, anomaly alerts | Revoke key; rotate |
| Scope creep delays revenue | M | Product | Ship REQ-001–008 (auth+tiers+billing) first; webhooks/audit (P1) after | Descope P1 |
| Cluster capacity for new components (portal, webhook worker) | M | Infra | Right-size; reuse existing namespace; webhooks as a small worker; mind RAM headroom (known constraint) | Scale down / defer webhooks |

---

## Success Metrics

**Definition of Done (DoD) — paid MVP (P0):**
- REQ-001–008 + REQ-012–013 implemented, tested, deployed; free tier verified intact.
- Stripe test-mode E2E green; at least one real paid signup completes end-to-end in production.

**Success Metrics (post-release):**
- **Demand gate (pre-build):** ≥25 waitlist signups OR ≥X RapidAPI subscribers in validation window (REQ-013).
- **Conversion:** ≥3 paying customers within 60 days of paid launch; ≥1 Business-tier within 90 days.
- **Revenue:** first €100 MRR within 90 days (validation, not scale).
- **Retention:** <10% logo churn/month over first quarter.
- **Free→paid funnel:** ≥2% of active free keys upgrade within 30 days of hitting the limit.
- **Reliability:** paid-tier uptime ≥99.9% (NFR-005); zero billing-correctness incidents.

---

## Release Plan

**Phasing:**
- **Phase A — Validate (gate):** waitlist live + optional RapidAPI listing. No paid build until REQ-013 metric met.
- **Phase B — Paid MVP:** REQ-001–008, 012 (auth, tiers, metering, Stripe, portal, free tier intact).
- **Phase C — Value-add:** REQ-009 (webhooks), REQ-010 (point-in-time audit), REQ-011 (bulk export).

**Feature Flags:** `paid_tiers_enabled`, `webhooks_enabled`. Free tier never behind a flag.

**Rollout:** Phase B to a private beta cohort first, then public. Stripe in test mode until E2E green.

**NFR Monitoring Mapping:**
- Performance → auth-middleware p95 (NFR-001)
- Reliability → `/v1/*` uptime, webhook delivery rate, billing-propagation timing (NFR-005/007/008)
- Security → Stripe webhook signature failures, key-auth failure rate (NFR-002/003)
- Compliance → data-deletion request handling (NFR-006)

**Abort Criteria (measurable):**
- Any billing-correctness incident (double-charge / wrong entitlement) → halt paid signups immediately.
- Auth middleware adds >50ms p95 latency → roll back auth layer.
- Stripe webhook signature-verification failures >0 in production → halt.

**Rollback Trigger:**
- Paid flow causes free-tier regression (free traffic failing) → disable `paid_tiers_enabled`, free tier must keep serving.
- Customer PII exposure → incident response + disable portal.

---

## Implementation Handoff

**Must-Have (P0):** REQ-001 (key auth), REQ-002 (re-key limiter IP→key, small delta on existing infra), REQ-003 (plans), REQ-004 (metering), REQ-005 (Stripe), REQ-006 (portal), REQ-007 (free tier intact), REQ-012 (ToS/pricing), REQ-013 (demand gate).

**Flexible (P1):** REQ-009 webhooks, REQ-010 point-in-time audit, REQ-011 bulk export.

**Key NFR Risks:** NFR-003 (billing webhook integrity) and NFR-004 (metering accuracy) are the highest-stakes — billing correctness is a trust/abort issue.

**Test Focus Areas:**
- Edge cases: revoked-key mid-quota, plan downgrade at period boundary, Stripe webhook replay/out-of-order, anonymous vs keyed limiter selection.
- Failure modes: Stripe outage during checkout, Redis unavailable (limiter/metering degradation), webhook endpoint down (retry/dead-letter).

**Note:** Effort estimates (S/M/L) are Product proposals — to be validated by Developer before this PRD moves to Approved.

---

## Version History

**v1.0.0** (2026-06-02) — Initial monetization PRD: freemium + API keys + Stripe tiers, value-add webhooks/point-in-time audit, demand-validation gate.
