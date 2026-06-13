#!/usr/bin/env bash
# ============================================================
# start_server.sh — Launch AquaVir-KB FastAPI web server
# Usage: bash start_server.sh [--port PORT] [--host HOST]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Parse optional --port and --host arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# Ensure dependencies are installed
if ! python -c "import fastapi, uvicorn, jinja2" 2>/dev/null; then
    echo "[INFO] Installing required packages..."
    pip install -r requirements.txt
fi

# Set a default API key for development if not set
export AQUAVIR_API_KEY="${AQUAVIR_API_KEY:-dev-key-change-in-production}"

echo "============================================"
echo " AquaVir-KB Web Server"
echo "--------------------------------------------"
echo " Host:     ${HOST}"
echo " Port:     ${PORT}"
echo " Database: crustacean_virus_core.db"
echo " API Docs: http://localhost:${PORT}/docs"
echo " Dashboard: http://localhost:${PORT}/"
echo "============================================"

exec python -m uvicorn backend:app \
    --host "${HOST}" \
    --port "${PORT}" \
    --workers 1 \
    --log-level info
