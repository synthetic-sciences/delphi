# =============================================================================
# Synsc Context – Production Dockerfile
# Multi-stage build optimised for Render / Railway / Fly.io / any VPS
# =============================================================================
# Builds two targets:
#   docker build --target api  -t synsc-api    .   # HTTP API server
#   docker build --target worker -t synsc-worker .  # Background indexing worker
#
# Default (no --target) builds the API server.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: build – install Python deps via uv into a virtual-env
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifest first (for layer caching)
COPY pyproject.toml uv.lock* README.md ./

# Install production deps only (no dev extras)
RUN uv sync --frozen --no-dev --no-editable 2>/dev/null \
    || uv sync --no-dev --no-editable

# Pre-download the sentence-transformers model (~420 MB) so the first
# paper-indexing request doesn't trigger a cold-start download.
RUN uv run python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')"

# Copy application source
COPY synsc/ ./synsc/
COPY setup_supabase.sql ./
COPY migrations/ ./migrations/

# ---------------------------------------------------------------------------
# Stage 2: runtime – slim image with only what we need
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd --gid 1000 synsc && \
    useradd  --uid 1000 --gid synsc --create-home synsc

WORKDIR /app

# Copy virtual env + source from build stage
COPY --from=build /app /app

# Copy the pre-downloaded HuggingFace model cache
COPY --from=build /root/.cache/huggingface /home/synsc/.cache/huggingface
RUN chown -R synsc:synsc /home/synsc/.cache

# Temp dir for cloned repos / PDFs
RUN mkdir -p /tmp/synsc-context && chown synsc:synsc /tmp/synsc-context

# ---------- environment defaults ----------
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
# Target: api (default) – Gunicorn + Uvicorn workers
# ---------------------------------------------------------------------------
FROM runtime AS api

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8742/health || exit 1

# Gunicorn with Uvicorn workers – tune WEB_CONCURRENCY for your instance size
CMD ["uv", "run", "gunicorn", "synsc.api.http_server:create_app()", \
     "--bind", "0.0.0.0:8742", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--access-logfile", "-"]

# ---------------------------------------------------------------------------
# Target: worker – background indexing worker
# ---------------------------------------------------------------------------
FROM runtime AS worker

# No health-check port; the worker is a long-running process
CMD ["uv", "run", "synsc-context", "worker"]
