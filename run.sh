#!/usr/bin/env bash
set -e

# Resolve project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "              TradeZen Full Stack Launcher"
echo "========================================================"
echo ""

# 1. Check Python virtual environment
if [ ! -f ".venv/bin/uvicorn" ]; then
    echo "[ERROR] Virtual environment not found at .venv/"
    echo "Please run ./setup.sh first to configure your environment."
    exit 1
fi

# 2. Check Frontend dependencies
if [ ! -d "frontend/node_modules" ]; then
    echo "[ERROR] Frontend dependencies not found in frontend/node_modules!"
    echo "Please run ./setup.sh or run 'npm install' inside ./frontend."
    exit 1
fi

# 3. Check .env
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

# Cleanup background processes on exit
cleanup() {
    echo ""
    echo "[INFO] Shutting down TradeZen services..."
    kill $(jobs -p) 2>/dev/null || true
    wait 2>/dev/null || true
    echo "[INFO] TradeZen stopped."
}
trap cleanup EXIT INT TERM

# 4. Start FastAPI Backend
echo "[1/2] Starting FastAPI Backend on http://localhost:8000..."
source .venv/bin/activate
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload &

# 5. Start React Frontend
echo "[2/2] Starting React Frontend on http://localhost:5173..."
cd frontend
npm run dev -- --host 0.0.0.0 &
cd ..

echo ""
echo "========================================================"
echo "TradeZen services running!"
echo "Backend API & Swagger: http://localhost:8000/docs"
echo "Frontend Dashboard:   http://localhost:5173"
echo "Press Ctrl+C to stop all services."
echo "========================================================"
echo ""

wait
