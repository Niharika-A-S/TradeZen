# TradeZen Frontend (Step 6)

A high-performance React + Tailwind CSS dashboard designed for the TradeZen paper-trading and behavioral coaching engine.

## Official Dark Mode Design System
Strictly configured with the TradeZen fintech color palette:
- **Backgrounds**: Primary (`#0E1116`), Secondary (`#1A1F29`), Tertiary (`#11161F`)
- **Text**: Primary (`#F9FAFB`), Secondary (`#D1D5DB`), Tertiary (`#9CA3AF`)
- **Borders**: Default (`#2A313C`), Strong (`#374151`)
- **Accent**: Primary Blue (`#3B82F6`), Hover (`#60A5FA`), Muted (`#1E3A5F`)
- **Profit / Loss**: Gain (`#34D399`), Loss (`#F87171`)
- **Alerts**: Warning (`#FBBF24`), Warning Bg (`#3A2E0F`), Info (`#60A5FA`), Success (`#34D399`)
- **Charts**: Grid (`#2A313C`), Axis (`#9CA3AF`)

## Features
1. **Replay Clock Controls**:
   - Replay clock status (date, time, market open/closed indicator).
   - Fast time advances (`+1m`, `+5m`, `+15m`, `+30m`) and date picker.
2. **Trading Screen**:
   - Stock selector across the 5 universe stocks: `INFY`, `RELIANCE`, `TCS`, `HDFCBANK`, `SBIN`.
   - Real-time 1-minute candlestick chart with OHLC tooltip and live price line.
   - Order placement for `BUY` / `SELL`, `MARKET` / `LIMIT`, quantity, and stop-loss.
   - Interactive pre-trade rule check modal if the order violates discipline rules.
3. **Portfolio & Trades**:
   - Equity cards: Cash Balance, Portfolio Value, Unrealized P&L, Realized P&L.
   - Open Positions table with live unrealized P&L and Square-Off action.
   - Executed Trades ledger with timestamps, execution prices, charges (₹20), and realized P&L.
4. **Live Alerts Panel**:
   - Streaming WebSocket connection (`ws://localhost:8000/ws/alerts/1`).
   - Color-coded severity tags (`CRITICAL`, `WARNING`, `INFO`).
   - Detailed rule violation breakdown and XGBoost coaching rationale.
5. **Rules Setup**:
   - Configure `max_trades_per_day`, `max_risk_per_trade_pct`, `max_consecutive_losses`, `max_daily_loss`, `require_stop_loss`.
6. **SEBI Disclaimer**:
   - Prominent disclaimer header: *"TradeZen is behavioral coaching, not SEBI-registered advice. Never let the UI tell users to buy or sell a specific stock."*

## How to Run

### 1. Start FastAPI Backend (Port 8000)
In the root directory:
```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Start Frontend Dev Server (Port 5173)
In the `frontend/` directory:
```bash
npm run dev
```

Visit [http://localhost:5173](http://localhost:5173) in your browser.

### 3. Production Build
```bash
npm run build
npm run preview
```
