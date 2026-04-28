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

# Deps-only sync first so the heavy torch/transformers layer caches across
# source changes. `--no-install-project` skips trying to build the synsc
# wheel (source isn't here yet).
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null \
    || uv sync --no-dev --no-install-project

# torch ships with `test/` (~150 MB) and `include/` (C++ headers, ~30 MB)
# baked into the wheel. They're only used for compiling extensions / running
# torch's own test suite — useless at runtime. Same for __pycache__ and .pyc
# files which uv has already populated. Stripping them shaves 250–400 MB off
# the image and keeps Docker Desktop's default VM from hitting ENOSPC during
# layer export.
RUN set -eux; \
    find .venv -type d -name '__pycache__' -prune -exec rm -rf {} + ; \
    find .venv -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete ; \
    rm -rf .venv/lib/python*/site-packages/torch/test \
           .venv/lib/python*/site-packages/torch/include \
           .venv/lib/python*/site-packages/torch/utils/benchmark/utils/valgrind_wrapper \
           .venv/lib/python*/site-packages/functorch/test \
           .venv/lib/python*/site-packages/torch/onnx/_internal/fx/passes/_tests ; \
    true

# The sentence-transformers model (~420 MB) is downloaded lazily on first
# request rather than baked into the image — keeps build smaller and avoids
# blowing up disk-constrained installs (Docker Desktop default VM is tight).
# Users on API-based providers (EMBEDDING_PROVIDER=gemini|openai) never pay
# for it at all.

COPY synsc/ ./synsc/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Now that the source is in place, install the synsc package itself into
# the venv as a real wheel. Without this the runtime stage has dist-info
# but no actual `synsc/` package on the import path, and entry-point
# scripts (`synsc-context`, `uvicorn synsc...`) fail with ModuleNotFoundError.
RUN uv sync --frozen --no-dev --no-editable 2>/dev/null \
    || uv sync --no-dev --no-editable

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

RUN mkdir -p /tmp/synsc-context /home/synsc/.cache/huggingface \
 && chown -R synsc:synsc /tmp/synsc-context /home/synsc/.cache

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
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

# Use the module-level `app` (wraps FastAPI in _MCPMiddleware to expose /mcp).
# The `:create_app --factory` form returns the bare FastAPI app and skips the
# /mcp mount, leaving the synsc-context-proxy with HTTP 404 on every call.
CMD ["sh", "-c", "alembic upgrade head && uvicorn synsc.api.http_server:app --host 0.0.0.0 --port 8742"]

# ---------------------------------------------------------------------------
# Target: worker
# ---------------------------------------------------------------------------
FROM runtime AS worker

CMD ["synsc-context", "worker"]
