@echo off
setlocal enabledelayedexpansion
title TradeZen Full-Stack Launcher
cd /d "%~dp0"

echo ========================================================
echo               TradeZen Full Stack Launcher
echo ========================================================
echo.

:: 1. Detect Python / Uvicorn Environment
set "PYTHON_EXE="
set "UVICORN_CMD="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    set "UVICORN_CMD=.venv\Scripts\python.exe -m uvicorn"
    echo [INFO] Using virtual environment at .venv\
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import uvicorn" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=python"
            set "UVICORN_CMD=python -m uvicorn"
            echo [INFO] Using system / active Python environment.
        ) else (
            echo [ERROR] uvicorn is not installed in your Python environment!
            echo Please install dependencies: pip install -r requirements.txt
            pause
            exit /b 1
        )
    ) else (
        echo [ERROR] Python not found in PATH!
        echo Please install Python 3.11+ and run: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

:: 2. Check Frontend Dependencies
if not exist "frontend\node_modules\" (
    echo [WARNING] Frontend dependencies not found in frontend\node_modules\
    echo Installing frontend dependencies now (npm install)...
    cd frontend
    call npm install
    cd ..
    if not exist "frontend\node_modules\" (
        echo [ERROR] Failed to install frontend dependencies. Please run 'npm install' in frontend\
        pause
        exit /b 1
    )
)

:: 3. Check Environment File (.env)
if not exist ".env" (
    echo [ERROR] No .env file found!
    echo Please create a .env file with your PostgreSQL credentials:
    echo DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/tradezen
    pause
    exit /b 1
)

:: 4. Check PostgreSQL Availability (TCP port 5432)
set "PG_RUNNING=0"
powershell -NoProfile -Command "$client = New-Object System.Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1', 5432); exit 0 } catch { exit 1 } finally { $client.Close() }" >nul 2>&1
if not errorlevel 1 (
    set "PG_RUNNING=1"
    echo [1/3] PostgreSQL is running on port 5432.
) else (
    echo [WARNING] PostgreSQL does not appear to be running on localhost:5432.
    echo Please ensure your PostgreSQL service is running before using Replay or Live mode.
    echo.
    set /p "CONTINUE_CHOICE=Continue launching TradeZen anyway? [Y/N]: "
    if /I not "!CONTINUE_CHOICE!"=="Y" (
        echo Startup aborted by user.
        pause
        exit /b 1
    )
)

:: 5. Launch FastAPI Backend in a new window
echo [2/3] Launching FastAPI Backend on http://localhost:8000...
start "TradeZen Backend (Port 8000)" powershell -NoExit -Command "cd '%~dp0'; & %UVICORN_CMD% app.api.main:app --host 127.0.0.1 --port 8000 --workers 1 --reload"

:: 6. Launch React Frontend in a new window
echo [3/3] Launching React Frontend on http://localhost:5173...
start "TradeZen Frontend (Port 5173)" powershell -NoExit -Command "cd '%~dp0frontend'; npm run dev"

echo.
echo ========================================================
echo TradeZen services successfully launched!
echo.
echo 👉 Frontend Dashboard: http://localhost:5173
echo 👉 Backend API Docs:   http://localhost:8000/docs
echo ========================================================
echo.
pause
