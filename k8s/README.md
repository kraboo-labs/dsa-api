# dsa-api — Kubernetes deploy

Target cluster: **DO Kubernetes (fra1)** · public hostname **api.dsa-api.com**

Three workloads share one image:

| Workload | Kind | Schedule | Command |
|---|---|---|---|
| `dsa-api` | Deployment | continuous (2 replicas) | `uvicorn apps.api.main:app …` |
| `dsa-api-migrations` | Job | one-shot per deploy | `alembic upgrade head` |
| `dsa-api-scraper` | CronJob | `0 */6 * * *` (UTC) | `python -m apps.scraper` |

Prereqs on the cluster (already installed for `lumed`, reused here):
- `ingress-nginx` (IngressClass `nginx`)
- `cert-manager` with a `ClusterIssuer` named `letsencrypt-prod`
- DO Container Registry connected to the cluster (cluster-wide image pull secret)

## One-time setup

### 1. DSA deploy SSH key for `kraboo-labs/dsa-data`

The scraper CronJob pushes the daily data export to the `dsa-data` repo.
Generate a dedicated SSH key (do NOT reuse a personal key):

```bash
ssh-keygen -t ed25519 -C 'dsa-api scraper push key' -N '' -f /tmp/dsa-data-key
```

Add the **public** part as a **deploy key with write access** on
`https://github.com/kraboo-labs/dsa-data/settings/keys`:

```bash
cat /tmp/dsa-data-key.pub          # paste this into GitHub
```

Then create the k8s secret holding the **private** part:

```bash
kubectl create secret generic dsa-data-ssh-key -n dsa-api \
  --from-file=id_ed25519=/tmp/dsa-data-key
```

…and shred the local copy:

```bash
shred -u /tmp/dsa-data-key /tmp/dsa-data-key.pub
```

### 2. App secrets

Schema (env vars the app expects):

| key | required | source |
|---|---|---|
| `DSA_DATABASE_URL` | yes | DO Managed Postgres, format `postgresql+asyncpg://user:pass@host:25060/dbname?sslmode=require` |
| `DSA_REDIS_URL` | yes | DO Managed Redis, format `rediss://default:pass@host:25061/0` |
| `DSA_SENTRY_DSN` | no | sentry.io project DSN |

Non-secret env vars (rate limits, source URL, user agent, environment,
snapshot/export paths, committer identity, GIT_SSH_COMMAND) are pinned
inline in the manifests — they don't change between deploys.

Create the secret:

```bash
kubectl create secret generic dsa-api-secrets -n dsa-api \
  --from-literal=DSA_DATABASE_URL='postgresql+asyncpg://...' \
  --from-literal=DSA_REDIS_URL='rediss://default:...' \
  --from-literal=DSA_SENTRY_DSN='https://...@sentry.io/...'
```

The `DSA_SENTRY_DSN` key is marked `optional` in the manifests; if you
omit it from the secret it just won't be injected.

### 3. First deploy

Order matters — namespace before everything, migrations before the API
rollout, ingress last so cert-manager only starts issuing once the
service is actually backing it.

```bash
kubectl apply -f k8s/namespace.yaml

# Tear down any leftover Job from a previous run so the new one can be
# applied cleanly (Jobs are immutable once created).
kubectl delete job dsa-api-migrations -n dsa-api --ignore-not-found
kubectl apply -f k8s/migrations-job.yaml
kubectl wait --for=condition=complete --timeout=5m \
  job/dsa-api-migrations -n dsa-api

kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/scraper-cronjob.yaml
kubectl apply -f k8s/api-ingress.yaml
```

cert-manager will issue the TLS cert in ~1–2 min. Watch:

```bash
kubectl get certificate -n dsa-api
kubectl describe certificate dsa-api-tls -n dsa-api
```

Once `Ready=True`, hit https://api.dsa-api.com/v1/health.

### DNS

| Host | Type | Value |
|---|---|---|
| `api.dsa-api.com` | A | `<ingress-nginx LB IPv4>` (same LB as `klarita.sk`) |

> Do NOT add an AAAA record. DO LB is IPv4-only; a stale AAAA breaks the
> Let's Encrypt HTTP-01 challenge.

The `klarita.sk` ingress already proves the LB exists — look up the IP
with `kubectl get svc -n ingress-nginx`.

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

## GitHub Actions secrets to set

In `https://github.com/kraboo-labs/dsa-api/settings/secrets/actions`:

- `DIGITALOCEAN_ACCESS_TOKEN` — DO API token, **registry** + **kubernetes**
  scopes only (not full-access).
- `KUBE_CONFIG` — base64-encoded kubeconfig for the cluster:
  ```bash
  base64 -i ~/.kube/config | pbcopy    # macOS
  base64 -w0 ~/.kube/config             # linux
  ```

## Phase 1 follow-ups

- [ ] `docs.dsa-api.com` redirect/host serving FastAPI's `/docs` directly
      (Swagger UI is currently reachable at `api.dsa-api.com/docs`)
- [ ] `status.dsa-api.com` — either an upptime board on GitHub Pages
      (free, on-brand) or a betterstack-hosted page
- [ ] Move HTML snapshots from emptyDir to either DO Spaces or
      `dsa-data/data/source-snapshots/YYYY-MM-DD.html` per PRD §7
- [ ] Slack webhook alerts when a CronJob fails or the source page
      structure changes (see `apps/scraper/parse.py::HtmlStructureError`)
