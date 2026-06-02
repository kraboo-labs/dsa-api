# dsa-api — Kubernetes deploy

Target cluster: **DO Kubernetes (fra1)** · public hostname **api.dsa-api.com**

Four workloads share one image:

| Workload | Kind | Schedule | Command |
|---|---|---|---|
| `dsa-api` | Deployment | continuous (2 replicas) | `uvicorn apps.api.main:app …` |
| `dsa-api-migrations` | Job | one-shot per deploy | `alembic upgrade head` |
| `dsa-api-scraper` | CronJob | `0 */6 * * *` (UTC) | `python -m apps.scraper` |
| `dsa-api-watchdog` | CronJob | `0 * * * *` (UTC) | `python -m apps.scraper.watchdog` |

Prereqs on the cluster (already installed for `lumed`, reused here):
- `ingress-nginx` (IngressClass `nginx`)
- `cert-manager` with a `ClusterIssuer` named `letsencrypt-prod`
- DO Container Registry connected to the cluster (cluster-wide image pull secret)

## One-time setup

The deploy is fully driven by `.github/workflows/deploy.yml`. There is
no manual `kubectl` step — everything (namespace, secrets, migrations,
deployments, ingress, rollout) happens inside the workflow. You only
need to populate **repository secrets**.

### 1. Generate the deploy SSH key for `kraboo-labs/dsa-data`

The scraper CronJob pushes the data export to the `dsa-data` repo.
Generate a dedicated key (do NOT reuse a personal key):

```bash
ssh-keygen -t ed25519 -C 'dsa-api scraper push key' -N '' -f /tmp/dsa-data-key
```

Add the **public** part as a **deploy key with write access** at
`https://github.com/kraboo-labs/dsa-data/settings/keys/new`:

```bash
cat /tmp/dsa-data-key.pub          # paste into the GitHub UI
```

The **private** part goes into a repo secret on the API repo (next step).

### 2. Set repository secrets on `kraboo-labs/dsa-api`

`https://github.com/kraboo-labs/dsa-api/settings/secrets/actions`

| Secret | Required | Source |
|---|---|---|
| `DIGITALOCEAN_ACCESS_TOKEN` | yes | DO API token, **Registry + Kubernetes** scopes only |
| `KUBE_CONFIG` | yes | `base64 -i ~/.kube/config` (NOT `-i k8s-…-do-…-kubeconfig.yaml` because gitleaks already complained about that file living locally — same content, different filename) |
| `DSA_DATABASE_URL` | yes | DO Managed Postgres — paste the raw connection string (`postgresql://user:pass@host:25060/dbname?sslmode=require`) as-is. `core.config.normalize_database_url` rewrites the scheme to `+asyncpg` and `sslmode`→`ssl` at load time so the asyncpg driver accepts it. |
| `DSA_REDIS_URL` | yes | DO Managed Redis, format `rediss://default:pass@host:25061/0` |
| `DSA_DATA_SSH_KEY` | yes | Paste the **full content** of `/tmp/dsa-data-key` (include the OpenSSH header and footer lines so the secret value is a valid PEM-formatted private key) |
| `DSA_SENTRY_DSN` | no | sentry.io project DSN |
| `DSA_SLACK_WEBHOOK_URL` | no | Slack incoming webhook (alerts on scrape failures + stale-data watchdog) |

Or via `gh` CLI:

```bash
gh secret set DIGITALOCEAN_ACCESS_TOKEN -R kraboo-labs/dsa-api          # paste DO token
gh secret set KUBE_CONFIG -R kraboo-labs/dsa-api < <(base64 -i ~/.kube/config)
gh secret set DSA_DATABASE_URL -R kraboo-labs/dsa-api                   # paste DB URL
gh secret set DSA_REDIS_URL -R kraboo-labs/dsa-api                      # paste Redis URL
gh secret set DSA_DATA_SSH_KEY -R kraboo-labs/dsa-api < /tmp/dsa-data-key
gh secret set DSA_SENTRY_DSN -R kraboo-labs/dsa-api                     # optional, paste or skip
gh secret set DSA_SLACK_WEBHOOK_URL -R kraboo-labs/dsa-api              # optional, paste or skip
```

Then shred the local copy of the SSH key:

```bash
shred -u /tmp/dsa-data-key /tmp/dsa-data-key.pub
```

Non-secret env vars (rate limits, source URL, user agent, environment,
snapshot/export paths, committer identity, GIT_SSH_COMMAND) are pinned
inline in the manifests — they don't change between deploys.

### 3. Trigger the first deploy

`https://github.com/kraboo-labs/dsa-api/actions/workflows/deploy.yml`

Click **Run workflow → main → Run workflow**. The workflow will:

1. Run CI (ruff + format + pytest) against postgres/redis service containers.
2. Build the image, push as `sha-<short>` + `latest` to DO Container Registry.
3. Apply the namespace.
4. **Reconcile `dsa-api-secrets` and `dsa-data-ssh-key` from the repo secrets.**
5. Run the `dsa-api-migrations` Job (`alembic upgrade head`) and wait.
6. Apply `api-deployment`, `service`, `scraper-cronjob`, `watchdog-cronjob`, `ingress`.
7. `kubectl set image` to the freshly-pushed tag and wait on rollout.
8. Garbage-collect old image tags (keeps the most recent 5).

Subsequent deploys (any change merged to `main` + manual trigger)
re-reconcile secrets, so rotating any value is "update the repo secret
+ run workflow" — no local `kubectl` needed.

### 4. Watch cert-manager finish issuing TLS

```bash
kubectl get certificate -n dsa-api
# dsa-api-tls       Ready=True   (api.dsa-api.com)
# dsa-api-docs-tls  Ready=True   (docs.dsa-api.com)
```

Once both are `Ready=True`, hit https://api.dsa-api.com/v1/health.

### DNS

| Host | Type | Value | Purpose |
|---|---|---|---|
| `api.dsa-api.com` | A | `<ingress-nginx LB IPv4>` | REST API |
| `docs.dsa-api.com` | A | `<same LB IPv4>` | Hitting `/` 307s to Swagger UI |

> Do NOT add AAAA records. DO LB is IPv4-only; a stale AAAA breaks the
> Let's Encrypt HTTP-01 challenge.

The `klarita.sk` ingress already proves the LB exists — look up the IP
with `kubectl get svc -n ingress-nginx`. dsa-api.com DNS is currently
managed at GoDaddy.

## Updates

Pushes to `main` trigger `.github/workflows/deploy.yml` (added in K.6) —
builds linux/amd64, tags `sha-<short>` + `latest`, pushes to DO registry,
runs migrations job, rolls out the API.

Manual rollout from local:

```bash
TAG=sha-$(git rev-parse --short HEAD)
docker build --platform linux/amd64 \
  -t registry.digitalocean.com/agent-search/dsa-api:$TAG \
  -t registry.digitalocean.com/agent-search/dsa-api:latest .
doctl registry login
docker push registry.digitalocean.com/agent-search/dsa-api:$TAG
docker push registry.digitalocean.com/agent-search/dsa-api:latest

kubectl delete job dsa-api-migrations -n dsa-api --ignore-not-found
kubectl apply -f k8s/migrations-job.yaml
kubectl wait --for=condition=complete --timeout=5m \
  job/dsa-api-migrations -n dsa-api

kubectl set image deployment/dsa-api dsa-api=registry.digitalocean.com/agent-search/dsa-api:$TAG -n dsa-api
kubectl rollout status deployment/dsa-api -n dsa-api
```

## Scaling

- The API is stateless. Bump `replicas` in `api-deployment.yaml` and
  apply. There's nothing to coordinate across pods (rate-limit state lives
  in Redis, DB sessions are per-request).
- The scraper is single-instance by `concurrencyPolicy: Forbid`. If a run
  takes longer than 6h (it shouldn't — current p95 is ~0.5s end-to-end),
  the next one is skipped. Bump CPU/memory in the CronJob spec if needed.

## Operational notes

- **Manual scraper run** (e.g. to trigger a republish without waiting for
  the next slot):
  ```bash
  kubectl create job --from=cronjob/dsa-api-scraper \
    dsa-api-scraper-manual-$(date +%s) -n dsa-api
  ```
- **HTML snapshots** land in the pod's emptyDir at `/var/snapshots`. They
  vanish when the pod ends — provenance lives in `dsa-data` instead.
  Move snapshots to DO Spaces or commit them under
  `data/source-snapshots/` in `dsa-data` if you start needing them for
  audit.
- **First-time DB schema**: handled by the migrations Job. Subsequent
  schema changes follow the same pattern (autogenerate locally, commit
  the new revision under `migrations/versions/`, the next deploy
  applies it).
- **Sentry**: optional. The DSN is pulled with `optional: true` so a
  missing secret key doesn't block startup.

## GitHub Actions secrets

See "One-time setup → Step 2" above. Quick recap:

- `DIGITALOCEAN_ACCESS_TOKEN`, `KUBE_CONFIG` — DO + cluster auth
- `DSA_DATABASE_URL`, `DSA_REDIS_URL` — managed DB / Redis connection strings
- `DSA_DATA_SSH_KEY` — private SSH deploy key (public part registered on
  kraboo-labs/dsa-data as a write-access deploy key)
- `DSA_SENTRY_DSN`, `DSA_SLACK_WEBHOOK_URL` — optional observability

Workflow reconciles `dsa-api-secrets` and `dsa-data-ssh-key` from these on
every deploy. Rotation: update the repo secret + run the workflow.

## Phase 1 follow-ups

- ✅ `docs.dsa-api.com` — wired in this ingress; root route in
      apps/api/main.py 307s to /docs when the host header matches.
- [ ] `status.dsa-api.com` — either an upptime board on GitHub Pages
      (free, on-brand) or a betterstack-hosted page
- [ ] Move HTML snapshots from emptyDir to either DO Spaces or
      `dsa-data/data/source-snapshots/YYYY-MM-DD.html` per PRD §7
- ✅ Slack: scraper hard-failure notifies on the configured webhook;
      `dsa-api-watchdog` CronJob alerts hourly if the last successful
      scrape is older than 24h. Add `DSA_SLACK_WEBHOOK_URL` to
      `dsa-api-secrets` to activate; missing key = silent.
