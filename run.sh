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
if [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
    echo "[INFO] Using virtual environment at .venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON_CMD=".venv/Scripts/python.exe"
    echo "[INFO] Using virtual environment at .venv/Scripts/python.exe"
elif command -v python >/dev/null 2>&1 && python -c "import uvicorn" >/dev/null 2>&1; then
    PYTHON_CMD="python"
    echo "[INFO] Using system Python environment (python)"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import uvicorn" >/dev/null 2>&1; then
    PYTHON_CMD="python3"
    echo "[INFO] Using system Python environment (python3)"
else
    echo "[ERROR] Virtual environment or system uvicorn not found."
    echo "Please run ./setup.sh or run 'pip install -r requirements.txt' first."
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
"$PYTHON_CMD" -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload &

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
