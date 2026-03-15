#!/usr/bin/env bash
# =============================================================================
# Synsc Context — Render Start Command
# =============================================================================
# Called by Render to start the service after a successful build.
#
# Supports three service types via the SYNSC_SERVICE_TYPE env var:
#   api    (default) — Gunicorn + Uvicorn workers (HTTP API only)
#   worker           — Background indexing worker only
#   both             — API + worker in one instance (recommended for early stage)
#
# Usage (Render dashboard → Start Command):
#   ./render_deploy.sh           # starts API server
#   SYNSC_SERVICE_TYPE=both ./render_deploy.sh   # API + worker (single instance)
#   SYNSC_SERVICE_TYPE=worker ./render_deploy.sh # worker only
# =============================================================================
set -euo pipefail

# Ensure uv is on PATH (installed during build)
export PATH="$HOME/.local/bin:$PATH"

SERVICE_TYPE="${SYNSC_SERVICE_TYPE:-api}"

# ── Validate required environment variables ──────────────────────────────────
missing=()

[ -z "${SUPABASE_URL:-}" ]          && missing+=("SUPABASE_URL")
[ -z "${SUPABASE_SECRET_KEY:-}" ]   && missing+=("SUPABASE_SECRET_KEY")
[ -z "${SUPABASE_DATABASE_URL:-}" ] && missing+=("SUPABASE_DATABASE_URL")

if [ "$SERVICE_TYPE" = "api" ] || [ "$SERVICE_TYPE" = "both" ]; then
    [ -z "${SUPABASE_JWT_SECRET:-}" ] && missing+=("SUPABASE_JWT_SECRET")
fi

if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing required environment variables:"
    for var in "${missing[@]}"; do
        echo "  - $var"
    done
    echo ""
    echo "Set these in Render dashboard → Environment."
    exit 1
fi

# ── Port configuration ───────────────────────────────────────────────────────
# Render provides $PORT; Synsc defaults to 8742.
# Use Render's PORT if available, otherwise fall back to SYNSC_API_PORT.
export SYNSC_API_PORT="${PORT:-${SYNSC_API_PORT:-8742}}"

# ── Worker configuration ─────────────────────────────────────────────────────
WORKER_THREADS="${SYNSC_WORKER_THREADS:-4}"
POLL_INTERVAL="${SYNSC_WORKER_POLL_INTERVAL:-5}"

echo "=== Synsc Context: Starting ${SERVICE_TYPE} ==="
echo "  Version: $(uv run python -c 'import synsc; print(synsc.__version__)')"

# ── Cleanup for combined mode ────────────────────────────────────────────────
WORKER_PID=""

cleanup() {
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        echo "Stopping background worker (PID: $WORKER_PID)..."
        kill "$WORKER_PID" 2>/dev/null
        wait "$WORKER_PID" 2>/dev/null || true
    fi
}
trap cleanup SIGINT SIGTERM EXIT

# ── Start services ───────────────────────────────────────────────────────────
case "$SERVICE_TYPE" in
    api)
        echo "  Port: ${SYNSC_API_PORT}"
        echo "  Workers: ${WEB_CONCURRENCY:-1}"
        echo "  CORS origins: ${SYNSC_CORS_ORIGINS:-<not set>}"
        exec uv run gunicorn "synsc.api.http_server:create_app()" \
            --bind "0.0.0.0:${SYNSC_API_PORT}" \
            --worker-class uvicorn.workers.UvicornWorker \
            --workers "${WEB_CONCURRENCY:-1}" \
            --timeout "${GUNICORN_TIMEOUT:-300}" \
            --graceful-timeout 30 \
            --keep-alive 5 \
            --access-logfile -
        ;;
    worker)
        echo "  Threads: ${WORKER_THREADS}"
        echo "  Poll interval: ${POLL_INTERVAL}s"
        exec uv run synsc-context worker \
            --max-workers "${WORKER_THREADS}" \
            --poll-interval "${POLL_INTERVAL}"
        ;;
    both)
        echo "  Port: ${SYNSC_API_PORT}"
        echo "  API workers: ${WEB_CONCURRENCY:-1}"
        echo "  CORS origins: ${SYNSC_CORS_ORIGINS:-<not set>}"
        echo "  Indexing threads: ${WORKER_THREADS}"
        echo "  Poll interval: ${POLL_INTERVAL}s"

        # Start the background worker first
        echo "  → Starting background worker..."
        uv run synsc-context worker \
            --max-workers "${WORKER_THREADS}" \
            --poll-interval "${POLL_INTERVAL}" &
        WORKER_PID=$!
        echo "  → Worker started (PID: $WORKER_PID)"

        # Start the API server in the foreground (so Render tracks it)
        echo "  → Starting API server..."
        exec uv run gunicorn "synsc.api.http_server:create_app()" \
            --bind "0.0.0.0:${SYNSC_API_PORT}" \
            --worker-class uvicorn.workers.UvicornWorker \
            --workers "${WEB_CONCURRENCY:-1}" \
            --timeout "${GUNICORN_TIMEOUT:-300}" \
            --graceful-timeout 30 \
            --keep-alive 5 \
            --access-logfile -
        ;;
    *)
        echo "ERROR: Unknown SYNSC_SERVICE_TYPE='${SERVICE_TYPE}'"
        echo "  Valid values: api, worker, both"
        exit 1
        ;;
esac
