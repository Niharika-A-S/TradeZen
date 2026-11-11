@echo off
setlocal enabledelayedexpansion
title TradeZen Packager
cd /d "%~dp0"

echo ========================================================
echo        TradeZen Clean Packager for Teammates
echo ========================================================
echo.
echo Packaging project while safely excluding:
echo  - Python virtual environment (.venv)
echo  - Node dependencies (node_modules)
echo  - Git repository history (.git)
echo  - Backups and cached files
echo  - Private credentials (.env)
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\package_shareable.py %*
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        python scripts\package_shareable.py %*
    ) else (
        echo [ERROR] Python not found to run packaging script!
        pause
        exit /b 1
    )
)

echo.
echo You can now send the generated TradeZen_Shareable.zip to your teammate!
echo.
pause
