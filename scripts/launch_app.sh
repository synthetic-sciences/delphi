#!/bin/bash

# =============================================================================
# Delphi — Local Development Launcher
# =============================================================================
# One command to start everything: PostgreSQL, backend, frontend, worker.
#
# Usage (run from anywhere — paths are resolved from the script's location):
#   ./scripts/launch_app.sh              # Start everything
#   ./scripts/launch_app.sh --no-worker  # Skip background worker
#   ./scripts/launch_app.sh --no-frontend # Skip frontend
#   ./scripts/launch_app.sh --docker     # Use docker-compose for everything
#   ./scripts/launch_app.sh --help       # Show all options
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
ORANGE='\033[0;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Defaults
START_WORKER=true
START_FRONTEND=true
USE_DOCKER=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-worker)
            START_WORKER=false
            shift
            ;;
        --no-frontend)
            START_FRONTEND=false
            shift
            ;;
        --docker)
            USE_DOCKER=true
            shift
            ;;
        --help)
            echo "Usage: ./launch_app.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-worker    Don't start background indexing worker"
            echo "  --no-frontend  Don't start Next.js frontend"
            echo "  --docker       Use docker-compose for all services"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Banner
echo ""
echo -e "${ORANGE}   ███████╗██╗   ██╗███╗   ██╗███████╗ ██████╗${NC}"
echo -e "${ORANGE}   ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔════╝${NC}"
echo -e "${ORANGE}   ███████╗ ╚████╔╝ ██╔██╗ ██║███████╗██║     ${NC}"
echo -e "${ORANGE}   ╚════██║  ╚██╔╝  ██║╚██╗██║╚════██║██║     ${NC}"
echo -e "${ORANGE}   ███████║   ██║   ██║ ╚████║███████║╚██████╗${NC}"
echo -e "${ORANGE}   ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝ ╚═════╝${NC}"
echo -e "${DIM}   synsc delphi — open-source mcp server for ai agents${NC}"
echo ""

# Cleanup function
PIDS=()
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    echo -e "${GREEN}All services stopped.${NC}"
}
trap cleanup EXIT INT TERM

# Docker-compose mode
if [ "$USE_DOCKER" = true ]; then
    echo -e "${CYAN}Starting all services via docker-compose...${NC}"
    docker compose up --build
    exit 0
fi

# Load .env if exists
if [ -f .env ]; then
    echo -e "${DIM}Loading .env...${NC}"
    set -a
    source .env
    set +a
else
    echo -e "${YELLOW}No .env file found. Copy env.example to .env and configure it:${NC}"
    echo -e "${DIM}  cp env.example .env${NC}"
    echo ""
    echo -e "${DIM}Loading defaults...${NC}"
fi

# Set defaults
# Derive DATABASE_URL from POSTGRES_* if it isn't pinned explicitly. Without
# this, the docker-managed Postgres container is created with whatever
# POSTGRES_PASSWORD .env supplies, but DATABASE_URL would still default to
# synsc:synsc and auth would fail.
export POSTGRES_USER="${POSTGRES_USER:-synsc}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-synsc}"
export POSTGRES_DB="${POSTGRES_DB:-synsc}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export DATABASE_URL="${DATABASE_URL:-postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}}"
export SYNSC_API_PORT="${SYNSC_API_PORT:-8742}"
export SYNSC_REQUIRE_AUTH="${SYNSC_REQUIRE_AUTH:-false}"

# ── Dependencies ─────────────────────────────────────────────────────────────

# Check Python deps (pyproject lives under backend/ after the restructure)
if [ ! -d "$BACKEND_DIR/.venv" ] || ! (cd "$BACKEND_DIR" && uv run python -c "import synsc") 2>/dev/null; then
    echo -e "${CYAN}Installing Python dependencies...${NC}"
    (cd "$BACKEND_DIR" && uv sync --extra dev)
fi

# Check frontend deps
if [ "$START_FRONTEND" = true ] && [ -d "$FRONTEND_DIR" ] && [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo -e "${CYAN}Installing frontend dependencies...${NC}"
    (cd "$FRONTEND_DIR" && npm install)
fi

# ── PostgreSQL ───────────────────────────────────────────────────────────────

echo -e "${DIM}Checking PostgreSQL...${NC}"
if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
    echo -e "${YELLOW}PostgreSQL not running locally. Starting via Docker...${NC}"
    docker compose up -d postgres
    echo -e "${DIM}Waiting for PostgreSQL...${NC}"
    for i in {1..30}; do
        if pg_isready -h localhost -p 5432 -q 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi
echo -e "${GREEN}PostgreSQL ready.${NC}"

# ── Migrations ───────────────────────────────────────────────────────────────
# Run after Postgres is up. Creates research_jobs + docs_sources tables on top
# of the setup_local.sql baseline (which Alembic 001 stamps idempotently).

echo -e "${DIM}Applying database migrations...${NC}"
(cd "$BACKEND_DIR" && uv run alembic upgrade head) || \
    echo -e "${YELLOW}Migrations failed or skipped. Continuing — fix and rerun if endpoints 500.${NC}"

# ── Services ─────────────────────────────────────────────────────────────────

echo -e "${CYAN}Starting API server on port ${SYNSC_API_PORT}...${NC}"
(cd "$BACKEND_DIR" && uv run synsc-context-http) &
PIDS+=($!)

if [ "$START_WORKER" = true ]; then
    echo -e "${CYAN}Starting background worker...${NC}"
    (cd "$BACKEND_DIR" && uv run synsc-context-worker) &
    PIDS+=($!)
fi

if [ "$START_FRONTEND" = true ] && [ -d "$FRONTEND_DIR" ]; then
    FRONTEND_PORT="${FRONTEND_PORT:-3000}"
    API_PORT="${SYNSC_API_PORT:-8742}"
    echo -e "${CYAN}Starting frontend on port ${FRONTEND_PORT}...${NC}"
    (cd "$FRONTEND_DIR" && \
        NEXT_PUBLIC_API_URL="http://localhost:${API_PORT}" PORT="$FRONTEND_PORT" npm run dev) &
    PIDS+=($!)
fi

# ── Ready ────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}  ──────────────────────────────────────${NC}"
echo -e "${GREEN}  delphi is running${NC}"
echo -e "${GREEN}  ──────────────────────────────────────${NC}"
echo -e "  ${DIM}api${NC}       ${CYAN}http://localhost:${SYNSC_API_PORT}${NC}"
if [ "$START_FRONTEND" = true ]; then
echo -e "  ${DIM}dashboard${NC} ${CYAN}http://localhost:${FRONTEND_PORT:-3000}${NC}"
fi
echo -e "  ${DIM}health${NC}    ${CYAN}http://localhost:${SYNSC_API_PORT}/health${NC}"
echo ""
echo -e "${DIM}  press ctrl+c to stop all services${NC}"

wait
