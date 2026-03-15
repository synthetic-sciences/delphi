#!/bin/bash

# =============================================================================
# Synsc Context - Local Development Launcher
# =============================================================================
# Starts Supabase (local), backend API, frontend, and background worker
#
# Usage:
#   ./launch_app.sh              # Start with cloud Supabase (from .env)
#   ./launch_app.sh --local      # Start with local Supabase
#   ./launch_app.sh --no-worker  # Don't start background worker
#   ./launch_app.sh --help       # Show all options
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default settings
USE_LOCAL_SUPABASE=false
START_WORKER=true
START_FRONTEND=true
WORKER_THREADS=4
BACKEND_PORT=8742
FRONTEND_PORT=3000

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            USE_LOCAL_SUPABASE=true
            shift
            ;;
        --no-worker)
            START_WORKER=false
            shift
            ;;
        --no-frontend)
            START_FRONTEND=false
            shift
            ;;
        --worker-threads)
            WORKER_THREADS="$2"
            shift 2
            ;;
        --backend-port)
            BACKEND_PORT="$2"
            shift 2
            ;;
        --frontend-port)
            FRONTEND_PORT="$2"
            shift 2
            ;;
        -h|--help)
            echo -e "${CYAN}Synsc Context - Local Development Launcher${NC}"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --local, -l         Use local Supabase (starts supabase if needed)"
            echo "  --no-worker         Don't start the background indexing worker"
            echo "  --no-frontend       Don't start the Next.js frontend"
            echo "  --worker-threads N  Number of parallel threads for worker (default: 4)"
            echo "  --backend-port P    Backend API port (default: 8742)"
            echo "  --frontend-port P   Frontend port (default: 3000)"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --local              # Full local development"
            echo "  $0 --local --no-worker  # Local without indexing worker"
            echo "  $0                       # Use cloud Supabase from .env"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help to see available options"
            exit 1
            ;;
    esac
done
clear
echo -e "${CYAN}════════════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   ███████╗██╗   ██╗███╗   ██╗███████╗ ██████╗██╗${NC}"
echo -e "${CYAN}   ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔════╝██║${NC}"
echo -e "${CYAN}   ███████╗ ╚████╔╝ ██╔██╗ ██║███████╗██║     ██║${NC}"
echo -e "${CYAN}   ╚════██║  ╚██╔╝  ██║╚██╗██║╚════██║██║     ██║${NC}"
echo -e "${CYAN}   ███████║   ██║   ██║ ╚████║███████║╚██████╗██║${NC}"
echo -e "${CYAN}   ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}         Unified Code & Research Context Platform${NC}"
echo ""

# -----------------------------------------------------------------------------
# Check for required tools
# -----------------------------------------------------------------------------
check_tool() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}✗ Required tool '$1' not found.${NC}"
        echo -e "  Install it with: $2"
        exit 1
    fi
}

echo -e "${YELLOW}→ Checking required tools...${NC}"

# Check for uv (Python package manager)
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}⚠ 'uv' not found. Installing...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi
echo -e "  ${GREEN}✓${NC} uv"

# Check for Node.js/npm
if [ "$START_FRONTEND" = true ]; then
    check_tool "node" "nvm install 20 or visit https://nodejs.org"
    check_tool "npm" "comes with Node.js"
    echo -e "  ${GREEN}✓${NC} node $(node --version)"
fi

# Check for Supabase CLI if using local
if [ "$USE_LOCAL_SUPABASE" = true ]; then
    # Prefer npx supabase, fall back to global supabase CLI
    if command -v supabase &> /dev/null; then
        SUPABASE_CMD="supabase"
        echo -e "  ${GREEN}✓${NC} supabase CLI (global)"
    else
        # Use npx supabase (will auto-install if needed)
        SUPABASE_CMD="npx supabase"
        echo -e "  ${GREEN}✓${NC} supabase via npx"
    fi
    
    # Check for Docker (required for local Supabase)
    check_tool "docker" "https://docs.docker.com/get-docker/"
    if ! docker info &> /dev/null; then
        echo -e "${RED}✗ Docker daemon is not running.${NC}"
        echo -e "  Please start Docker and try again."
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} docker"
fi

echo ""

# -----------------------------------------------------------------------------
# Setup local Supabase (if --local flag)
# -----------------------------------------------------------------------------
setup_local_supabase() {
    echo -e "${YELLOW}→ Setting up local Supabase...${NC}"
    
    # Initialize Supabase if not already done
    if [ ! -d "supabase" ]; then
        echo -e "  ${BLUE}Initializing Supabase project...${NC}"
        $SUPABASE_CMD init
    fi
    
    # Check if Supabase is already running
    if $SUPABASE_CMD status &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Supabase is already running"
    else
        echo -e "  ${BLUE}Starting Supabase services...${NC}"
        $SUPABASE_CMD start
    fi
    
    # Get Supabase credentials
    echo -e "  ${BLUE}Fetching Supabase credentials...${NC}"
    SUPABASE_STATUS=$($SUPABASE_CMD status 2>/dev/null)
    
    # Parse the status output (handles both old and new format)
    export SUPABASE_URL=$(echo "$SUPABASE_STATUS" | grep -E "Project URL|API URL" | awk '{print $NF}')
    export SUPABASE_ANON_KEY=$(echo "$SUPABASE_STATUS" | grep -E "Publishable|anon key" | awk '{print $NF}')
    export SUPABASE_SECRET_KEY=$(echo "$SUPABASE_STATUS" | grep -E "Secret|service_role" | head -1 | awk '{print $NF}')
    export SUPABASE_DATABASE_URL=$(echo "$SUPABASE_STATUS" | grep -E "URL.*postgresql|DB URL" | awk '{print $NF}')
    
    # Fallback to common local defaults if parsing fails
    if [ -z "$SUPABASE_URL" ]; then
        export SUPABASE_URL="http://127.0.0.1:54321"
    fi
    if [ -z "$SUPABASE_DATABASE_URL" ]; then
        export SUPABASE_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    fi
    
    # Also set NEXT_PUBLIC_ variants for frontend
    export NEXT_PUBLIC_SUPABASE_URL="$SUPABASE_URL"
    export NEXT_PUBLIC_SUPABASE_ANON_KEY="$SUPABASE_ANON_KEY"
    
    echo -e "  ${GREEN}✓${NC} Supabase URL: $SUPABASE_URL"
    echo -e "  ${GREEN}✓${NC} Database ready"
    
    # Run migrations if they exist
    if [ -d "supabase/migrations" ] && [ "$(ls -A supabase/migrations 2>/dev/null)" ]; then
        echo -e "  ${BLUE}Running database migrations...${NC}"
        $SUPABASE_CMD db push --local || true
        echo -e "  ${GREEN}✓${NC} Migrations applied"
    fi
    
    echo ""
}

# -----------------------------------------------------------------------------
# Load environment
# -----------------------------------------------------------------------------
if [ "$USE_LOCAL_SUPABASE" = true ]; then
    setup_local_supabase
else
    # Load .env file if it exists
    if [ -f ".env" ]; then
        echo -e "${YELLOW}→ Loading environment from .env${NC}"
        set -a
        source .env
        set +a
        echo -e "${GREEN}✓ Environment loaded${NC}"
    else
        echo -e "${RED}════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ✗ No .env file found!${NC}"
        echo -e "${RED}════════════════════════════════════════════════${NC}"
        echo ""
        echo -e "  Create one from the template:"
        echo -e "    ${CYAN}cp .env.example .env${NC}"
        echo ""
        echo -e "  Or use local Supabase:"
        echo -e "    ${CYAN}$0 --local${NC}"
        echo ""
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Validate configuration
# -----------------------------------------------------------------------------
check_config() {
    local missing=()
    
    if [ -z "$SUPABASE_URL" ]; then
        missing+=("SUPABASE_URL")
    fi
    
    if [ -z "$SUPABASE_SECRET_KEY" ] && [ -z "$SUPABASE_SERVICE_KEY" ] && [ -z "$SUPABASE_SERVICE_ROLE_KEY" ]; then
        missing+=("SUPABASE_SECRET_KEY")
    fi
    
    if [ -z "$SUPABASE_DATABASE_URL" ]; then
        missing+=("SUPABASE_DATABASE_URL")
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ✗ Missing required configuration!${NC}"
        echo -e "${RED}════════════════════════════════════════════════${NC}"
        echo ""
        echo -e "  Missing variables:"
        for var in "${missing[@]}"; do
            echo -e "    ${YELLOW}• $var${NC}"
        done
        echo ""
        exit 1
    fi
    
    # Normalize secret key names
    if [ -z "$SUPABASE_SECRET_KEY" ]; then
        if [ -n "$SUPABASE_SERVICE_KEY" ]; then
            export SUPABASE_SECRET_KEY="$SUPABASE_SERVICE_KEY"
        elif [ -n "$SUPABASE_SERVICE_ROLE_KEY" ]; then
            export SUPABASE_SECRET_KEY="$SUPABASE_SERVICE_ROLE_KEY"
        fi
    fi
    
    if [ -z "$SUPABASE_ANON_KEY" ] && [ -n "$SUPABASE_PUBLISHABLE_KEY" ]; then
        export SUPABASE_ANON_KEY="$SUPABASE_PUBLISHABLE_KEY"
    fi
    
    # Ensure NEXT_PUBLIC_ variants are set for the frontend (cloud + local)
    export NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-$SUPABASE_URL}"
    export NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-${SUPABASE_ANON_KEY:-$SUPABASE_PUBLISHABLE_KEY}}"
    
    echo -e "${GREEN}✓ Configuration validated${NC}"
}

check_config
echo ""

# -----------------------------------------------------------------------------
# Install dependencies
# -----------------------------------------------------------------------------
echo -e "${YELLOW}→ Installing Python dependencies...${NC}"
uv sync
echo -e "${GREEN}✓ Python dependencies installed${NC}"

if [ "$START_FRONTEND" = true ]; then
    echo -e "${YELLOW}→ Installing frontend dependencies...${NC}"
    cd frontend
    npm install --silent
    cd ..
    echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
fi
echo ""

# -----------------------------------------------------------------------------
# Cleanup function
# -----------------------------------------------------------------------------
BACKEND_PID=""
FRONTEND_PID=""
WORKER_PID=""
CLEANUP_IN_PROGRESS=false

graceful_kill() {
    local pid=$1
    local name=$2
    local timeout=5

    if [ -z "$pid" ] || ! kill -0 $pid 2>/dev/null; then
        return 0
    fi

    # Send SIGTERM for graceful shutdown
    kill -TERM $pid 2>/dev/null || return 0

    # Wait for process to exit (with timeout)
    local elapsed=0
    while kill -0 $pid 2>/dev/null; do
        if [ $elapsed -ge $timeout ]; then
            # Force kill if still running after timeout
            kill -KILL $pid 2>/dev/null
            echo -e "  ${YELLOW}⚠${NC} $name force-killed after timeout"
            return 1
        fi
        sleep 0.2
        elapsed=$((elapsed + 1))
    done

    echo -e "  ${GREEN}✓${NC} $name stopped gracefully"
    return 0
}

cleanup() {
    # Prevent multiple cleanup calls
    if [ "$CLEANUP_IN_PROGRESS" = true ]; then
        return
    fi
    CLEANUP_IN_PROGRESS=true

    echo ""
    echo -e "${YELLOW}→ Shutting down all services...${NC}"

    # Send SIGTERM to all tracked processes
    graceful_kill "$WORKER_PID" "Worker"
    graceful_kill "$FRONTEND_PID" "Frontend"
    graceful_kill "$BACKEND_PID" "Backend"

    # Kill any remaining background jobs from this script
    local remaining_jobs=$(jobs -p 2>/dev/null)
    if [ -n "$remaining_jobs" ]; then
        echo "$remaining_jobs" | while read -r job_pid; do
            kill -TERM "$job_pid" 2>/dev/null || true
        done
        sleep 1
        # Force kill any stragglers
        echo "$remaining_jobs" | while read -r job_pid; do
            kill -KILL "$job_pid" 2>/dev/null || true
        done
    fi

    # Optionally stop local Supabase
    if [ "$USE_LOCAL_SUPABASE" = true ]; then
        echo -e "${YELLOW}→ Local Supabase still running${NC}"
        echo -e "  ${BLUE}(Run 'supabase stop' to fully stop containers)${NC}"
    fi

    echo -e "${GREEN}✓ All services stopped${NC}"
    exit 0
}

# Trap signals for graceful shutdown
trap cleanup SIGINT SIGTERM EXIT

# -----------------------------------------------------------------------------
# Start services
# -----------------------------------------------------------------------------

# Start backend server
echo -e "${YELLOW}→ Starting backend API server on http://localhost:${BACKEND_PORT}${NC}"
SYNSC_API_PORT=$BACKEND_PORT uv run python -m synsc.cli serve http --port $BACKEND_PORT &
BACKEND_PID=$!

# Wait for backend to be ready
echo -e "${YELLOW}→ Waiting for backend to start...${NC}"
for i in {1..30}; do
    if curl -s "http://localhost:${BACKEND_PORT}/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend ready!${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Backend failed to start!${NC}"
        echo -e "  Check the logs above for errors."
        exit 1
    fi
    sleep 1
done

# Start frontend server
if [ "$START_FRONTEND" = true ]; then
    echo -e "${YELLOW}→ Starting frontend on http://localhost:${FRONTEND_PORT}${NC}"
    cd frontend
    PORT=$FRONTEND_PORT npm run dev &
    FRONTEND_PID=$!
    cd ..
    
    # Wait a moment for frontend to start
    sleep 3
    echo -e "${GREEN}✓ Frontend starting...${NC}"
fi

# Start background indexing worker
if [ "$START_WORKER" = true ]; then
    echo -e "${YELLOW}→ Starting background worker (${WORKER_THREADS} threads)${NC}"
    uv run python -m synsc.cli worker --max-workers $WORKER_THREADS &
    WORKER_PID=$!
    echo -e "${GREEN}✓ Worker started (PID: $WORKER_PID)${NC}"
fi

# -----------------------------------------------------------------------------
# Print status
# -----------------------------------------------------------------------------
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ All services are running!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}URLs:${NC}"
if [ "$START_FRONTEND" = true ]; then
    echo -e "    Frontend:   ${BLUE}http://localhost:${FRONTEND_PORT}${NC}"
    echo -e "    Login:      ${BLUE}http://localhost:${FRONTEND_PORT}/login${NC}"
    echo -e "    Dashboard:  ${BLUE}http://localhost:${FRONTEND_PORT}/overview${NC}"
fi
echo -e "    Backend:    ${BLUE}http://localhost:${BACKEND_PORT}${NC}"
echo -e "    API Docs:   ${BLUE}http://localhost:${BACKEND_PORT}/docs${NC}"
if [ "$USE_LOCAL_SUPABASE" = true ]; then
    echo -e "    Supabase:   ${BLUE}http://127.0.0.1:54323${NC} (Studio)"
fi
echo ""
echo -e "  ${MAGENTA}Services:${NC}"
echo -e "    • Backend API     (PID: $BACKEND_PID)"
if [ "$START_FRONTEND" = true ]; then
    echo -e "    • Frontend        (PID: $FRONTEND_PID)"
fi
if [ -n "$WORKER_PID" ]; then
    echo -e "    • Indexing Worker (PID: $WORKER_PID, ${WORKER_THREADS} threads)"
else
    echo -e "    • Indexing Worker ${YELLOW}(disabled)${NC}"
fi
if [ "$USE_LOCAL_SUPABASE" = true ]; then
    echo -e "    • Supabase        ${GREEN}(local)${NC}"
fi
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

# Wait for background processes
wait
