#!/bin/bash

# =============================================================================
# Delphi — Local Development Launcher
# =============================================================================
# One command to start everything: PostgreSQL, backend, frontend, worker.
#
# Usage:
#   ./launch_app.sh              # Start everything
#   ./launch_app.sh --no-worker  # Skip background worker
#   ./launch_app.sh --no-frontend # Skip frontend
#   ./launch_app.sh --docker     # Use docker-compose for everything
#   ./launch_app.sh --help       # Show all options
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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
export DATABASE_URL="${DATABASE_URL:-postgresql://synsc:synsc@localhost:5432/synsc}"
export SYNSC_API_PORT="${SYNSC_API_PORT:-8742}"
export SYNSC_REQUIRE_AUTH="${SYNSC_REQUIRE_AUTH:-false}"

# ── Dependencies ─────────────────────────────────────────────────────────────

# Check Python deps
if [ ! -d ".venv" ] || ! uv run python -c "import synsc" 2>/dev/null; then
    echo -e "${CYAN}Installing Python dependencies...${NC}"
    uv sync
fi

# Check frontend deps
if [ "$START_FRONTEND" = true ] && [ -d "frontend" ] && [ ! -d "frontend/node_modules" ]; then
    echo -e "${CYAN}Installing frontend dependencies...${NC}"
    cd frontend && npm install && cd "$SCRIPT_DIR"
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

# ── Services ─────────────────────────────────────────────────────────────────

echo -e "${CYAN}Starting API server on port ${SYNSC_API_PORT}...${NC}"
uv run synsc-context-http &
PIDS+=($!)

if [ "$START_WORKER" = true ]; then
    echo -e "${CYAN}Starting background worker...${NC}"
    uv run synsc-context-worker &
    PIDS+=($!)
fi

if [ "$START_FRONTEND" = true ] && [ -d "frontend" ]; then
    FRONTEND_PORT="${FRONTEND_PORT:-3000}"
    API_PORT="${SYNSC_API_PORT:-8742}"
    echo -e "${CYAN}Starting frontend on port ${FRONTEND_PORT}...${NC}"
    cd frontend
    NEXT_PUBLIC_API_URL="http://localhost:${API_PORT}" PORT="$FRONTEND_PORT" npm run dev &
    PIDS+=($!)
    cd "$SCRIPT_DIR"
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
