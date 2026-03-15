#!/bin/bash

# =============================================================================
# Delphi - Local Development Launcher
# =============================================================================
# Starts PostgreSQL (Docker), backend API, frontend, and background worker
#
# Usage:
#   ./launch_app.sh              # Start everything
#   ./launch_app.sh --no-worker  # Don't start background worker
#   ./launch_app.sh --no-frontend # Don't start frontend
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
    echo -e "${CYAN}Loading .env file...${NC}"
    set -a
    source .env
    set +a
fi

# Set defaults
export DATABASE_URL="${DATABASE_URL:-postgresql://synsc:synsc@localhost:5432/synsc}"
export SYNSC_API_PORT="${SYNSC_API_PORT:-8742}"
export SYNSC_REQUIRE_AUTH="${SYNSC_REQUIRE_AUTH:-false}"

# Check if PostgreSQL is running
echo -e "${CYAN}Checking PostgreSQL connection...${NC}"
if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
    echo -e "${YELLOW}PostgreSQL not running locally. Starting via Docker...${NC}"
    docker compose up -d postgres
    echo -e "${CYAN}Waiting for PostgreSQL to be ready...${NC}"
    for i in {1..30}; do
        if pg_isready -h localhost -p 5432 -q 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi

echo -e "${GREEN}PostgreSQL is ready.${NC}"

# Start backend API
echo -e "${CYAN}Starting backend API on port ${SYNSC_API_PORT}...${NC}"
uv run synsc-context-http &
PIDS+=($!)

# Start worker
if [ "$START_WORKER" = true ]; then
    echo -e "${CYAN}Starting background worker...${NC}"
    uv run synsc-context-worker &
    PIDS+=($!)
fi

# Start frontend
if [ "$START_FRONTEND" = true ]; then
    if [ -d "frontend" ]; then
        echo -e "${CYAN}Starting frontend on port 3000...${NC}"
        cd frontend
        npm run dev &
        PIDS+=($!)
        cd "$SCRIPT_DIR"
    else
        echo -e "${YELLOW}No frontend directory found, skipping.${NC}"
    fi
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Delphi is running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  API:      ${CYAN}http://localhost:${SYNSC_API_PORT}${NC}"
if [ "$START_FRONTEND" = true ]; then
echo -e "  Frontend: ${CYAN}http://localhost:3000${NC}"
fi
echo -e "  Health:   ${CYAN}http://localhost:${SYNSC_API_PORT}/health${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

# Wait for all background processes
wait
