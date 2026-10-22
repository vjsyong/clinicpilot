# syntax=docker/dockerfile:1.7
#
# ClinicPilot production image: one CPU-only application container that serves
# the built React workbench and the FastAPI API beneath a runtime-configured
# prefix. No production secret or prefix is baked into any layer.

FROM node:24-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# frontend sources import the pinned design system through ../../vendor/triage.
COPY vendor/triage /app/vendor/triage
RUN npm run build


FROM python:3.12-slim-bookworm AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    PATH=/app/backend/.venv/bin:$PATH \
    HOME=/tmp \
    HF_HOME=/opt/hf \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_DISABLE_TELEMETRY=1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes \
        ca-certificates libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --frozen --no-dev

COPY backend/app backend/app

# Prewarm the pinned FastEmbed models so readiness never depends on a download.
# The revision strings in app.settings identify the ONNX snapshots cached here.
RUN /app/backend/.venv/bin/python -c "\
from app.retrieval.embeddings import FastEmbedder; \
from app.retrieval.reranker import FastEmbedReranker; \
FastEmbedder('Qwen/Qwen3-Embedding-0.6B', 'af95f2c416ffe9379369ad64f9113e865db6112c', threads=8).embed_texts(['warmup']); \
FastEmbedReranker('jinaai/jina-reranker-v1-turbo-en', 'b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2', threads=8).prewarm()"

# The runtime is offline for model assets; everything needed was fetched above.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY backend/alembic.ini backend/alembic.ini
COPY backend/migrations backend/migrations
COPY dkl_ai_interview_data dkl_ai_interview_data
COPY --from=frontend-build /app/frontend/dist frontend/dist
# Login page styling is served from the pinned design-system copy, so the
# runtime image needs it as well as the frontend build stage.
COPY vendor/triage vendor/triage

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --home-dir /app \
        --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app/data /opt/hf /opt/fastembed

COPY --chmod=0755 <<'ENTRYPOINT' /usr/local/bin/clinicpilot-entrypoint
#!/bin/bash
set -euo pipefail
cd /app
alembic -c backend/alembic.ini upgrade head
python -m app.db.seed
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --workers 1
ENTRYPOINT

USER 10001:10001
WORKDIR /app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).read()"]

ENTRYPOINT ["/usr/local/bin/clinicpilot-entrypoint"]
