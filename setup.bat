@echo off
setlocal enabledelayedexpansion
title TradeZen Setup
cd /d "%~dp0"

echo ========================================================
echo                 TradeZen Automated Setup
echo ========================================================
echo.

:: 1. Verify Python is installed and accessible
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in your PATH!
    echo Please install Python 3.11 or 3.12 and ensure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

:: 2. Create fresh virtual environment (.venv)
if exist ".venv\" (
    echo [1/5] Removing existing .venv...
    rmdir /s /q ".venv"
)
echo [1/5] Creating fresh Python virtual environment at .venv...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment!
    pause
    exit /b 1
)

:: 3. Install Python requirements
echo [2/5] Installing dependencies from requirements.txt...
call .\.venv\Scripts\activate.bat
pip install --default-timeout=100 --retries 5 -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies!
    if not "%1"=="--no-pause" pause
    exit /b 1
)

:: 4. Ensure .env exists
if not exist ".env" (
    echo [INFO] Creating .env from .env.example...
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    )
)

:: 5. Install Frontend dependencies
if exist "frontend\package.json" (
    echo [3/5] Installing frontend dependencies via npm install...
    cd frontend
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed in frontend!
        cd ..
        pause
        exit /b 1
    )
    cd ..
) else (
    echo [WARNING] frontend directory not found. Skipping npm install.
)

:: 6. Initialize database tables
echo [4/5] Initializing database tables and default user seed data...
python -m scripts.init_db
if errorlevel 1 (
    echo [WARNING] Database initialization failed.
    echo Please ensure PostgreSQL is running and DATABASE_URL in .env is correct.
)

:: 7. Load historical market data
echo [5/5] Loading historical stock price data...
python -m scripts.load_data
if errorlevel 1 (
    echo [WARNING] Market data loading failed or CSV files missing in ./Data.
    echo Please verify the Kaggle 1-minute CSVs are in ./Data before running replays.
)

echo.
echo ========================================================
echo TradeZen setup complete!
echo To start the application, run: run.bat
echo ========================================================
echo.
if not "%1"=="--no-pause" pause
