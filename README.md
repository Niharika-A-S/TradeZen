# TradeZen - Paper-Trading & Behavioral Coaching Platform

> **TradeZen** is a cross-platform paper-trading simulation, live market data feed, and behavioral coaching system for Indian stock traders (NSE Equities). It tracks orders, positions, and psychological rule breaks, incorporating historical 1-minute price replays, Upstox V3 Market Data Feed, and XGBoost machine learning risk detection.

---

## Quickstart & Installation (Windows, macOS, Linux)

### Prerequisites
* **Python**: Python 3.11 or 3.12 (`python3 --version`)
* **Node.js**: Node.js 18+ LTS or 20+ LTS with npm (`node --version`)
* **Database**: PostgreSQL 14+ running locally on port 5432 (or use Docker)

---

### Option 1: Automated Script Setup (Recommended)

#### On Windows:
1. Double-click or run:
   ```cmd
   setup.bat
   ```
   *Creates `.venv`, installs requirements, runs `npm install`, creates database tables, and loads sample data.*
2. Start the full application:
   ```cmd
   run.bat
   ```
   *Opens FastAPI backend on http://localhost:8000 and React frontend on http://localhost:5173.*

#### On macOS / Linux:
1. Grant execute permissions and run setup:
   ```bash
   chmod +x setup.sh run.sh
   ./setup.sh
   ```
2. Start the full application:
   ```bash
   ./run.sh
   ```

---

### Option 2: Docker Compose (One-Command Setup)

To run TradeZen with PostgreSQL, backend, and frontend fully containerized:
```bash
docker compose up --build
```
* **Frontend Dashboard**: http://localhost:5173
* **Backend API & Swagger Docs**: http://localhost:8000/docs
* **PostgreSQL Database**: Port 5432 (`user: postgres`, `password: postgres`, `db: tradezen`)

---

### Option 3: Manual Step-by-Step Setup

1. **Clone & Configure Environment**:
   ```bash
   # Windows
   copy .env.example .env
   # macOS / Linux
   cp .env.example .env
   ```
   *Edit `.env` to match your local PostgreSQL credentials.*

2. **Set up Python Virtual Environment**:
   ```bash
   python -m venv .venv

   # Windows
   .\.venv\Scripts\activate.bat
   # macOS / Linux
   source .venv/bin/activate

   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Install Frontend Dependencies**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Initialize Database & Seed Account**:
   ```bash
   python -m scripts.init_db
   ```

5. **Load Historical Price Data**:
   ```bash
   python -m scripts.load_data
   ```

6. **Start Backend & Frontend**:
   * Terminal 1 (Backend):
     ```bash
     uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
     ```
   * Terminal 2 (Frontend):
     ```bash
     cd frontend
     npm run dev
     ```

---

## Downloading Kaggle Historical Market Data

The 1-minute historical equity data files for the 5 supported NSE stocks (`INFY`, `RELIANCE`, `TCS`, `HDFCBANK`, `SBIN`) total ~270 MB and are deliberately excluded from Git via `.gitignore`.

### Dataset Details
* **Source**: [Kaggle: NIFTY 50 Minute Data (2015 - Present)](https://www.kaggle.com/) or any NSE 1-minute OHLCV dataset.
* **Target Symbols**:
  * `INFY` (Infosys Ltd)
  * `RELIANCE` (Reliance Industries Ltd)
  * `TCS` (Tata Consultancy Services Ltd)
  * `HDFCBANK` (HDFC Bank Ltd)
  * `SBIN` (State Bank of India)
* **Required CSV Schema**:
  ```csv
  date,open,high,low,close,volume
  2015-02-02 09:15:00,535.17,535.37,532.08,532.5,308332
  ```

### Placement
Download the 5 CSV files and place them directly into the `./Data/` (or `./data/`) folder:
```
TradeZen/
└── Data/
    ├── INFY_minute.csv
    ├── RELIANCE_minute.csv
    ├── TCS_minute.csv
    ├── HDFCBANK_minute.csv
    └── SBIN_minute.csv
```
Once placed, bulk-load the bars into PostgreSQL:
```bash
python -m scripts.load_data
```

---

## Core System Architecture

### 1. MarketClock & Upstox Live Mode
* **Replay Mode**: High-performance minute-by-minute historical playback across all 5 symbols.
* **Live Mode**: Read-only WebSocket integration with Upstox Market Data Feed V3 using dynamic Protocol Buffer (Protobuf) message decoding.
* In LIVE mode, returns fresh real-time quotes; if offline or stale (>15s), raises `LiveQuoteUnavailableError` without falling back to historical data.

### 2. Paper-Trading Engine
* Initial fake cash: **10,00,000 INR** (10 Lakhs).
* Supports `MARKET` orders (with 0.05% realistic slippage) and `LIMIT` orders.
* Position tracking: Weighted average price, FIFO lot matching, realized and unrealized P&L.
* Intraday auto-square off at 15:15 cutoff.

### 3. Rules Engine & Behavioral Coaching
* Formula for risk:
  $$\text{risk per trade} = |\text{entry\_price} - \text{stop\_loss}| \times \text{quantity}$$
  $$\text{risk\_pct} = \left(\frac{\text{risk per trade}}{\text{capital}}\right) \times 100$$
* Pre-trade checks (`POST /paper/orders/pre-check`) prevent risky entries before execution.
* Real-time detectors flag rule breaks:
  * `MAX_RISK_EXCEEDED`
  * `REQUIRE_STOP_LOSS`
  * `OVERTRADING_AFTER_LOSS` ($\ge 2$ losses and $\ge 5$ trades in 30 mins)
  * `REVENGE_TRADING` ($>1.5\times$ position size within 10 mins of loss)
  * `LATE_BREAKOUT_CHASE` (BUY placed after 14:30 on $\ge +4\%$ surge)

### 4. Machine Learning Behavioral Risk Predictor
* Trained on a 24,000-row behavioral dataset generated by 20 programmed bots across 4 trader personalities (Disciplined, Overtrader, RevengeTrader, StopLossIgnorer).
* Model: XGBoost Classifier with 95.27% accuracy and 0.9919 ROC-AUC.
* WebSocket Alert Stream (`/ws/alerts/{user_id}`) broadcasts alerts and explainable AI coaching rationale.

---

## Running the Complete Test Suite

Run all **76 automated unit and integration tests**:
```bash
pytest -v
```

All 76 tests verify:
* REST API endpoints & CORS headers
* Application lifespan & Upstox service integration
* MarketClock LIVE and REPLAY modes
* CSV data loading & inspection
* Paper-trading P&L accounting & slippage
* Behavioral rules & pre-trade checks
* XGBoost model predictions & SHAP explanations
* Protobuf frame decoding & exponential backoff

---

## TradeZen Coach (Chatbot Module)

TradeZen includes an integrated educational AI coach powered by the Gemini API and localized RAG (Retrieval-Augmented Generation) within the application database.

### Environment Variables
Configure the following keys in your backend `.env`:
* `GEMINI_API_KEY`: Google AI Studio API key (optional; system falls back gracefully to limited mode with keyword search if omitted)
* `GEMINI_CHAT_MODEL`: Chat model identifier (default: `gemini-2.5-flash`)
* `GEMINI_EMBED_MODEL`: Embedding model identifier (default: `gemini-embedding-001`)
* `EMBED_DIMENSIONS`: Output embedding dimensionality (default: `768`)
* `RAG_TOP_K`: Number of context passages retrieved per question (default: `4`)
* `RAG_MIN_SIMILARITY`: Cosine similarity cutoff threshold (default: `0.55`)
* `LLM_TIMEOUT_SECONDS`: Request timeout for LLM calls (default: `20`)
* `CHAT_RATE_LIMIT_PER_MIN`: Maximum chat requests allowed per user per minute (default: `20`)
* `CHAT_MAX_MESSAGE_CHARS`: Maximum message length (default: `1000`)
* `HELPLINE_NUMBER`: Distress support helpline number (default: `14416`)

### Chatbot CLI Commands
Run commands using the chatbot module CLI:
```bash
# 1. Ingest markdown knowledge base into the database
python -m chatbot.cli ingest [--force]

# 2. Evaluate RAG retrieval hit rate and tune RAG_MIN_SIMILARITY
python -m chatbot.cli eval

# 3. Check chatbot operational health & configuration
python -m chatbot.cli health
```

### Adding or Editing Knowledge Files
1. Add or edit any `.md` file inside `chatbot/knowledge/` (e.g. under `mistakes/`).
2. Include the YAML frontmatter (`id`, `title`, `type`, `source_title`, `evidence`).
3. Structure sections using `## ` headings (target 80 to 250 words per section).
4. Re-run `python -m chatbot.cli ingest` to automatically compute content hashes (SHA-256) and update changed chunks.

### Tuning RAG_MIN_SIMILARITY
Run `python -m chatbot.cli eval`. The script will output the hit rate at top-K and the similarity scores of the correct vs. incorrect chunks for all questions in `eval_questions.json`. If relevant chunks are excluded, lower `RAG_MIN_SIMILARITY` in increments of 0.05.

### Troubleshooting Table
| Symptom | Likely Cause | Solution |
| :--- | :--- | :--- |
| **Every reply says limited mode** | `GEMINI_API_KEY` missing in backend `.env` or model deprecated | Set key in `.env` or update `GEMINI_CHAT_MODEL` |
| **429 errors in log** | Free-tier quota exceeded on Gemini project | Wait 60s for circuit breaker to recover, or check limits in Google AI Studio |
| **Concept questions say no reliable source** | Ingestion not run or `RAG_MIN_SIMILARITY` threshold too high | Run `python -m chatbot.cli ingest` and tune threshold via `eval` |
| **Rupee sign displays corrupted** | File opened without `utf-8` encoding | Ensure text files are opened with `encoding='utf-8'` |
| **Zero knowledge chunks in health check** | Knowledge folder missing or empty | Verify `chatbot/knowledge/` contains `.md` files and re-run `ingest` |

