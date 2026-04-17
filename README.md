# 🤖 Crypto Futures Trading Bot

A modular, production-ready Python trading bot for crypto futures (Bybit / Binance Testnet)
with a **Pressure system**, **Self-Correction ML feedback loop**, and a clean terminal UI.

---

## 📁 Folder Structure

```
trading_bot/
├── bot.py                #  Main entry point — orchestrates the trading loop
├── config.py             #  All configuration parameters (one place)
├── exchange.py           # CCXT exchange wrapper (Bybit / Binance)
├── indicators.py         # EMA, RSI, MACD calculations (pure numpy)
├── signal_engine.py      # Entry / exit signal logic
├── performance.py        # Trade tracking, win/loss rate, PnL
├── pressure.py           # Dynamic risk management (Pressure system)
├── self_correction.py    # ML feedback loop (Self-Correction engine)
├── trade_manager.py      # Position sizing, SL/TP, order placement
├── logger.py             # Coloured terminal logging + status panel
├── requirements.txt
├── state/
│   └── self_correction.json  # Auto-created — learned thresholds
└── logs/
    └── bot_YYYY-MM-DD.log    # Auto-created — plain-text log file
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set API credentials
```bash
export EXCHANGE_API_KEY="your_testnet_api_key"
export EXCHANGE_API_SECRET="your_testnet_api_secret"
```
> ⚠️ **Never hardcode keys in source files.**

### 3. Run on Bybit Testnet (default)
```bash
python bot.py --exchange bybit --symbol BTC/USDT:USDT --timeframe 15m --leverage 5 --testnet
```

### 4. Run on Binance Testnet
```bash
python bot.py --exchange binanceusdm --symbol BTC/USDT --timeframe 1h --testnet
```

---

## ⚙️ Configuration (`config.py`)

All parameters are in `BotConfig`. Key values:

| Parameter | Default | Description |
|---|---|---|
| `leverage` | `5` | Default leverage |
| `risk_pct` | `0.01` | Risk 1% of balance per trade |
| `stop_loss_pct` | `0.005` | SL = 0.5% away from entry |
| `take_profit_rr` | `2.0` | TP = 2× the SL distance |
| `ema_fast_period` | `9` | Fast EMA period |
| `ema_slow_period` | `21` | Slow EMA period |
| `rsi_oversold` | `30` | RSI long entry threshold |
| `rsi_overbought` | `70` | RSI short entry threshold |
| `pressure_consecutive_loss_threshold` | `3` | Losses before Pressure kicks in |
| `pressure_cooldown_seconds` | `900` | Pause duration in HIGH PRESSURE (15m) |

---

## 📊 Strategy Logic

### Entry (LONG)
All 4 conditions must be true:
1. `EMA(9) > EMA(21)` — bullish trend
2. `RSI < 30` (adjustable by Self-Correction) — oversold pullback
3. `MACD histogram > min_threshold` — momentum recovering
4. `EMA spread > min_spread` — trend has enough strength

### Entry (SHORT)
Mirror conditions for bearish setups.

### Exit
- Hard TP / SL levels
- Optional early exit: EMA cross reversal or RSI extreme

---

## 🔴 Pressure System

```
NORMAL ──[loss_rate > win_rate OR 3 consec losses]──▶ REDUCED
REDUCED ──[continues to deteriorate]──────────────────▶ HIGH (paused 15m)
HIGH ──[cooldown expires]─────────────────────────────▶ REDUCED
REDUCED ──[2 consecutive wins]────────────────────────▶ NORMAL
```

In **REDUCED** state:
- Leverage is halved (`pressure_leverage_multiplier = 0.5`)
- Risk % is halved (`pressure_risk_multiplier = 0.5`)

In **HIGH** state:
- Trading is fully paused for `pressure_cooldown_seconds`

---

## 🔁 Self-Correction Engine

When a trade hits its **Stop-Loss**, the engine:

1. **Records** the indicator snapshot at entry (RSI, EMA spread, MACD histogram)
2. **Analyses** whether the values were near the edge of entry thresholds
3. **Tightens** thresholds incrementally:
   - RSI oversold: raised (e.g., 30 → 32 → 34…, capped at 30 + 10 = 40)
   - MACD minimum histogram: raised
   - Minimum EMA spread: raised
4. **Persists** to `state/self_correction.json` on shutdown

This means after repeated losses in weak-momentum, low-RSI setups, the bot
will stop taking them without human intervention.

---

## 🧪 Testing Without Real Money

1. Use `--testnet` flag (routes to exchange sandbox)
2. Get free testnet USDT from Bybit/Binance faucets
3. Watch the terminal panel refresh each candle

---

## 📋 Terminal Output

```
╔══════════════════════════════════════════════════════════════╗
║  CRYPTO BOT STATUS PANEL          2025-01-15  14:32:07 UTC  ║
╠══════════════════════════════════════════════════════════════╣
║   PRICE 43250.1200  RSI 28.4  MACD_H +0.00312  EMA Δ +12.4 ║
╠══════════════════════════════════════════════════════════════╣
║   Trades 12  PnL +38.4200 USDT                              ║
║   WIN   58.3%  ████████████░░░░░░░░                         ║
║   LOSS  41.7%  ████████░░░░░░░░░░░░                         ║
╠══════════════════════════════════════════════════════════════╣
║   PRESSURE: NORMAL   Lev: 5x   Risk: 1.00%                  ║
╠══════════════════════════════════════════════════════════════╣
║   POSITION: LONG  Entry=43250.1  SL=43033.9  TP=43683.2     ║
║   Unrealised PnL: +24.5000 USDT                             ║
╚══════════════════════════════════════════════════════════════╝
```

---

## ⚠️ Disclaimer

This is educational software. Futures trading carries significant risk of loss.
Always test thoroughly on testnets before risking real capital.