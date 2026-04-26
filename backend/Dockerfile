# =============================================================================
# Delphi (synsc-context) – Dockerfile
# =============================================================================
# Builds two targets:
#   docker build --target api    -t delphi-api    .
#   docker build --target worker -t delphi-worker .
#
# Default (no --target) builds the API server.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: build – install Python deps via uv into a virtual-env
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* README.md ./

RUN uv sync --frozen --no-dev --no-editable 2>/dev/null \
    || uv sync --no-dev --no-editable

# The sentence-transformers model (~420 MB) is downloaded lazily on first
# request rather than baked into the image — keeps build smaller and avoids
# blowing up disk-constrained installs (Docker Desktop default VM is tight).
# Users on API-based providers (EMBEDDING_PROVIDER=gemini|openai) never pay
# for it at all.

COPY synsc/ ./synsc/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 synsc && \
    useradd  --uid 1000 --gid synsc --create-home synsc

WORKDIR /app

# `--chown` writes ownership in-place; a separate `RUN chown -R` would
# duplicate the layer's inodes and was hitting ENOSPC on tight Docker VMs.
COPY --from=build --chown=synsc:synsc /app /app

RUN mkdir -p /tmp/synsc-context /home/synsc/.cache \
 && chown -R synsc:synsc /tmp/synsc-context /home/synsc/.cache

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    SYNSC_API_HOST=0.0.0.0 \
    SYNSC_API_PORT=8742 \
    SYNSC_REQUIRE_AUTH=true \
    SYNSC_LOG_LEVEL=INFO \
    SYNSC_TEMP_DIR=/tmp/synsc-context

EXPOSE 8742

USER synsc

# ---------------------------------------------------------------------------
# Target: api (default)
# ---------------------------------------------------------------------------
FROM runtime AS api

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8742/health || exit 1

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn synsc.api.http_server:create_app --factory --host 0.0.0.0 --port 8742"]

# ---------------------------------------------------------------------------
# Target: worker
# ---------------------------------------------------------------------------
FROM runtime AS worker

CMD ["uv", "run", "synsc-context", "worker"]
