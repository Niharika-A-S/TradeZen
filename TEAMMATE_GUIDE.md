# 🚀 TradeZen — Teammate Setup & Quickstart Guide

Welcome to **TradeZen**! This guide will help you run the entire project on your computer smoothly in under 5 minutes.

---

## 📋 1. Prerequisites (Check Before Starting)

Make sure you have these three tools installed on your computer:

1. **Python (3.11 or 3.12 recommended)**
   - Download: [python.org/downloads](https://www.python.org/downloads/)
   - ⚠️ **Important (Windows):** Check the box **"Add python.exe to PATH"** during installation!
   - Verify in terminal: `python --version`

2. **Node.js (v18, v20, or v22)**
   - Download: [nodejs.org](https://nodejs.org/) (LTS version)
   - Verify in terminal: `node -v` and `npm -v`

3. **PostgreSQL (v14+)**
   - Download: [postgresql.org/download](https://www.postgresql.org/download/)
   - Default port is `5432`. Remember the password you set for the `postgres` user during installation (default is usually `postgres`).
   - Make sure the PostgreSQL service is running.

---

## ⚡ 2. How to Run (One-Command Setup)

### On Windows 🪟:

1. **Unzip** the project folder onto your computer (e.g., your Desktop or Projects folder).
2. Open the unzipped `TradeZen` folder.
3. **Double-click `setup.bat`** (or open Command Prompt / PowerShell in this folder and run `.\setup.bat`).
   - This automatically:
     - Creates a clean Python virtual environment (`.venv`)
     - Installs all backend packages from `requirements.txt`
     - Installs all React frontend packages (`npm install`)
     - Creates the PostgreSQL database (`tradezen`) and tables
     - Loads the historical market price data
4. **Double-click `run.bat`** (or run `.\run.bat` in Command Prompt).
   - This launches both:
     - ⚙️ **Backend FastAPI server** on `http://localhost:8000` (API docs at `http://localhost:8000/docs`)
     - 💻 **Frontend React app** on `http://localhost:5173`
5. Open your browser and go to:
   👉 **`http://localhost:5173`**

---

### On Mac / Linux 🍎 🐧:

1. Open your terminal and navigate to the project directory:
   ```bash
   cd TradeZen
   ```
2. Make scripts executable and run setup:
   ```bash
   chmod +x setup.sh run.sh
   ./setup.sh
   ```
3. Start the application:
   ```bash
   ./run.sh
   ```
4. Open your browser at:
   👉 **`http://localhost:5173`**

---

### Alternative: Run with Docker 🐳 (Zero Setup)

If you have Docker Desktop installed, you don't need to install Python, Node, or PostgreSQL manually:
```bash
docker compose up --build
```
Once started, access the app at `http://localhost:5173`.

---

## 🛠️ 3. Troubleshooting & Common Questions

### Q1: "Database initialization failed" during `setup.bat`
- **Cause:** PostgreSQL service isn't running, or your postgres user password is not `postgres`.
- **Fix:**
  1. Open the file `.env` in any text editor (Notepad, VS Code).
  2. Find line 10:
     ```env
     DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/tradezen
     ```
  3. Replace `YOUR_PASSWORD` with the password you set when installing PostgreSQL.
  4. Save the file and run `setup.bat` again.

### Q2: `API Error: Failed to fetch` or Red Error Banner on frontend
- **Cause:** The backend server on port 8000 is not running or was closed.
- **Fix:** Keep the backend command prompt window open! `run.bat` opens two windows: one for the backend (port 8000) and one for frontend (port 5173). Both must remain open while using the app.

### Q3: "Python is not recognized as an internal or external command"
- **Fix:** Re-run the Python installer, click "Modify", and make sure **"Add Python to PATH"** is selected. Then restart your terminal.

### Q4: Running tests to verify everything is working
Open terminal in the project root and run:
```bash
.\.venv\Scripts\pytest -q
```
You should see all 76 tests passing!

---

## 📂 Project Architecture Quick Tour

- `app/` — FastAPI backend:
  - `app/simulator/` — 30-bot trading simulator (5 trader personalities)
  - `app/ml/` — Machine learning models (behavioral violation prediction & SHAP explanations)
  - `app/clock/` — Market clock (tick-by-tick market replay)
  - `app/api/` — REST API endpoints and WebSockets
- `frontend/` — React + Tailwind dashboard (trading panel, risk telemetry, ML alerts)
- `Data/` — Market price CSVs and behavioral dataset
- `models/` — Pre-trained ML model joblib files
