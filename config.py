"""
config.py — literally where i put all the magic numbers.

if i change a number here and it breaks, i just change it back.
never hardcode api keys btw, professor said we will fail the security 
audit (and lose our tokens).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    """
    dataclass thingy holding the setup.

    defaults are paper-trading bc i don't trust my own code with real USDT.
    override from CLI if feeling lucky.
    """

    # ── Exchange ───────────────────────────────────────────────────────────
    exchange_id: str   = "bybit"           # CCXT exchange id
    symbol:      str   = "BTC/USDT:USDT"  # Perpetual futures symbol
    timeframe:   str   = "15m"            # Candle timeframe
    testnet     : bool = True             # pls leave this True im scared

    # API credentials — imported from env so i don't leak it on github again 😭
    api_key:    str    = field(default_factory=lambda: os.getenv("EXCHANGE_API_KEY",    ""))
    api_secret: str    = field(default_factory=lambda: os.getenv("EXCHANGE_API_SECRET", ""))

    # ── Risk management (trying not to get rekt) ───────────────────────────
    leverage:       int   = 5       # Default leverage multiplier
    risk_pct:       float = 0.01    # Risk 1 % of balance per trade (0.01 = 1%)
    stop_loss_pct:  float = 0.005   # SL distance as fraction of entry price (0.5%)
    take_profit_rr: float = 2.0     # Reward-to-risk ratio for TP (2 = 2×SL distance)

    # ── Indicator parameters ──────────────────────────────────────────────
    ema_fast_period:  int   = 9
    ema_slow_period:  int   = 21
    rsi_period:       int   = 14
    rsi_oversold:     float = 35.0   # RSI below this → oversold (LONG entry zone)
    rsi_overbought:   float = 65.0   # RSI above this → overbought (SHORT entry zone)
    rsi_long_min:     float = 40.0   # MIN RSI for momentum tracking (LONG)
    rsi_long_max:     float = 55.0   # MAX RSI for momentum tracking (LONG)
    rsi_short_min:    float = 45.0   # MIN RSI for momentum tracking (SHORT)
    rsi_short_max:    float = 60.0   # MAX RSI for momentum tracking (SHORT)
    momentum_spread_pct: float = 0.002 # Required EMA spread % for momentum entries
    macd_fast:        int   = 12
    macd_slow:        int   = 26
    macd_signal:      int   = 9
    min_macd_histogram: float = 0.0  # Minimum |MACD histogram| for entry
    min_ema_spread_pct: float = 0.0  # Minimum EMA spread as fraction of price

    # ── Data ───────────────────────────────────────────────────────────────
    candle_limit: int = 200   # How many candles to fetch per tick (must be > slowest period)

    # ── Polling ────────────────────────────────────────────────────────────
    poll_interval_seconds: int = 30   # How often the main loop wakes up

    # ── Pressure system ───────────────────────────────────────────────────
    # "High Pressure" pauses trading after consecutive losses.
    pressure_consecutive_loss_threshold: int   = 3
    pressure_leverage_multiplier:        float = 0.5   # leverage *= this in REDUCED/HIGH
    pressure_risk_multiplier:            float = 0.5   # risk_pct *= this in REDUCED/HIGH
    pressure_cooldown_seconds:           int   = 900   # 15-minute cooldown pause

    # ── ML Self-Correction (Logistic Regression) ──────────────────────────
    ml_learning_rate:         float = 0.01   # SGD step size (lower = more stable)
    ml_confidence_threshold:  float = 0.45   # Minimum confidence to approve a signal
    ml_warmup_trades:         int   = 10     # Allow all signals during first N trades
    ml_persist_every_n:       int   = 5      # Save weights to disk every N trades
    sc_persist_path:          str   = "state/self_correction.json"

    # ── Logging ────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir:   str = "logs"