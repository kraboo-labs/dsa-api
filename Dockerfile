# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the DSA Trusted Flaggers API.
#
# Same image runs three workloads with different commands:
#   - api Deployment      → uvicorn (default CMD)
#   - scraper CronJob     → python -m apps.scraper
#   - migrations Job      → alembic upgrade head

# ---------- Stage 1: install Python deps into a user-site prefix ----------
FROM python:3.14-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---------- Stage 2: slim runtime image ----------
FROM python:3.14-slim-bookworm AS runtime
WORKDIR /app

# Non-root user (UID 1001 matches the lumed convention so a shared
# PodSecurityPolicy / SecurityContext applies uniformly).
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --home-dir /home/app app

# Runtime tools:
# - git + openssh-client: scraper publishes to kraboo-labs/dsa-data via git push
# - ca-certificates: HTTPS fetch from EU
RUN apt-get update && apt-get install -y --no-install-recommends \
        git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-trust github.com so the scraper's first push doesn't hang on the
# interactive host-key prompt. The kraboo SSH alias used in local dev is NOT
# replicated in the pod — k8s mounts a single deploy key and we point
# DSA_DATA_EXPORT_REMOTE at git@github.com:kraboo-labs/dsa-data.git directly.
RUN mkdir -p /home/app/.ssh \
    && ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> /home/app/.ssh/known_hosts \
    && chown -R app:app /home/app/.ssh \
    && chmod 700 /home/app/.ssh \
    && chmod 600 /home/app/.ssh/known_hosts

COPY --from=builder /root/.local /home/app/.local
COPY --chown=app:app apps/ ./apps/
COPY --chown=app:app core/ ./core/
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app pyproject.toml ./

USER app
ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
