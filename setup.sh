#!/usr/bin/env bash
set -e

# Resolve script root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================================"
echo "                TradeZen Automated Setup"
echo "========================================================"
echo ""

# 1. Detect Python 3 (prefer python3.11, python3.12, or python3)
PYTHON_CMD=""
for cmd in python3.11 python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python 3 not found in PATH!"
    echo "Please install Python 3.11 or 3.12 and ensure it is available in your PATH."
    exit 1
fi
echo "[INFO] Using Python: $($PYTHON_CMD --version)"

# 2. Create fresh virtual environment (.venv)
if [ -d ".venv" ]; then
    echo "[1/5] Removing existing .venv..."
    rm -rf .venv
fi
echo "[1/5] Creating fresh Python virtual environment (.venv)..."
"$PYTHON_CMD" -m venv .venv

# 3. Install Python requirements
echo "[2/5] Installing Python dependencies from requirements.txt..."
source .venv/bin/activate
pip install --default-timeout=100 --retries 5 -r requirements.txt

# 4. Ensure .env exists
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

# 5. Install Frontend dependencies
if [ -f "frontend/package.json" ]; then
    echo "[3/5] Installing frontend dependencies via npm install..."
    cd frontend
    npm install
    cd ..
else
    echo "[WARNING] frontend directory not found. Skipping npm install."
fi

# 6. Initialize database tables
echo "[4/5] Initializing database tables and default user seed data..."
python -m scripts.init_db || {
    echo "[WARNING] Database initialization failed. Please ensure PostgreSQL is running and DATABASE_URL in .env is correct."
}

# 7. Load historical market data
echo "[5/5] Loading historical stock price data..."
python -m scripts.load_data || {
    echo "[WARNING] Data loading failed or CSV files missing in ./Data or ./data."
    echo "Please verify the Kaggle 1-minute CSVs are in ./Data or ./data before running replays."
}

echo ""
echo "========================================================"
echo "TradeZen setup complete!"
echo "To start the application, run: ./run.sh"
echo "========================================================"
