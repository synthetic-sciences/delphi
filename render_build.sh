#!/usr/bin/env bash
# =============================================================================
# Synsc Context — Render Build Script
# =============================================================================
# Called by Render during the build phase for native (non-Docker) deployments.
#
# Render sets:  PYTHON_VERSION, POETRY_VERSION, etc.
# We use uv for fast dependency installation.
#
# Usage (Render dashboard → Build Command):
#   ./render_build.sh
# =============================================================================
set -euo pipefail

echo "=== Synsc Context: Build phase ==="

# ── 1. Install uv if not present ─────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "→ Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "→ uv version: $(uv --version)"

# ── 2. Install Python dependencies (production only) ─────────────────────────
echo "→ Installing Python dependencies..."
uv sync --frozen --no-dev --no-editable 2>/dev/null \
    || uv sync --no-dev --no-editable

# ── 3. Pre-download the sentence-transformers model ──────────────────────────
# This avoids a ~420 MB download on the first paper-indexing request.
echo "→ Pre-downloading sentence-transformers model..."
uv run python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')" \
    2>&1 | tail -5

# ── 4. Verify critical imports ───────────────────────────────────────────────
# NOTE: We cannot import http_server here because it calls create_app() at
# module level, which connects to the database — unavailable during build.
echo "→ Verifying imports..."
uv run python -c "
import synsc
from synsc.config import get_config
from synsc.workers.indexing_worker import IndexingWorker
print(f'  synsc v{synsc.__version__} — imports OK')
"

echo "=== Build complete ==="
