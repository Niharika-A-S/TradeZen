---
id: platform_guide
type: platform
title: TradeZen Platform Guide
source_title: TradeZen platform implementation
source_url:
evidence: platform
last_reviewed: 2026-11-08
---

## Replay and Live Modes
TradeZen operates in two primary market clock modes: Replay mode and Live mode. In Replay mode, historical 1-minute OHLCV candlestick data is played back bar-by-bar at controlled speeds, enabling realistic backtesting and practice without risking capital. In Live mode, TradeZen connects to real-time market data feeds via the Upstox API feed to stream tick updates.

## Paper Broker and Orders
The TradeZen paper broker manages virtual cash balances, simulated portfolio positions, orders, and executions. When an order is submitted (MARKET or LIMIT, BUY or SELL, MIS intraday or CNC delivery), the broker checks margin requirements, applies pre-trade rule validation, and models realistic slippage and statutory transaction charges. Virtual starting capital defaults to ₹10,00,000.

## Behavioral Rules and Rule Engine
TradeZen includes an active Rule Engine that inspects user activities in real time. Configurable parameters include maximum daily loss, maximum trades per day, maximum risk per trade percentage, mandatory stop-loss requirement, and intraday square-off cutoff time. When an order or trading pattern breaches a configured rule, real-time warning alerts are triggered and persisted.

## Practice Sessions and Scenarios
TradeZen supports practice sessions across historical market dates and pre-configured market regimes. Traders can test their emotional discipline across 15 distinct scenario sessions (such as high-volatility breakout days, ranging grind days, or gap-down recovery sessions), with options to generate or add more custom scenarios. TODO(team): verify full registry of scenario IDs and completion rewards.

## Account Reset and P&L Tracking
Users can reset their paper trading account balance back to the default ₹10,00,000 virtual balance at any time from the account settings. Portfolio views display realised P&L from closed positions, unrealised P&L from open positions calculated against the active market price quote, win rates, and trade logs.
