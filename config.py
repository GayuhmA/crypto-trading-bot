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

    # ── Indicator parameters (copypasted from youtube) ─────────────────────
    ema_fast_period:  int   = 9
    ema_slow_period:  int   = 21
    rsi_period:       int   = 14
    rsi_oversold:     float = 30.0   # Default threshold — Self-Correction can tighten this
    rsi_overbought:   float = 70.0   # Default threshold
    macd_fast:        int   = 12
    macd_slow:        int   = 26
    macd_signal:      int   = 9

    # ── Data ───────────────────────────────────────────────────────────────
    candle_limit: int = 200   # How many candles to fetch per tick (must be > slowest period)

    # ── Polling ────────────────────────────────────────────────────────────
    poll_interval_seconds: int = 30   # How often the main loop wakes up

    # ── Pressure system (the panic button) ─────────────────────────────────
    # "High Pressure" turns on if my code loses too much money.
    # Basically tells the bot to touch grass for 15 mins.
    pressure_consecutive_loss_threshold: int   = 3
    pressure_leverage_multiplier:        float = 0.5   # leverage *= this in High Pressure
    pressure_risk_multiplier:            float = 0.5   # risk_pct *= this in High Pressure
    pressure_cooldown_seconds:           int   = 900   # 15-minute cooldown pause

    # ── Self-Correction (ML buzzword to get A+ on project) ─────────────────
    # Maximum tightening applied to RSI thresholds from learning.
    sc_max_rsi_tighten:       float = 10.0  # Oversold can be raised by up to +10 pts
    sc_rsi_tighten_step:      float = 2.0   # Each SL hit raises the threshold by 2 pts
    sc_macd_penalty_step:     float = 0.0001
    sc_ema_spread_penalty_pct: float = 0.001  # Require EMA spread >= this fraction
    sc_persist_path:          str   = "state/self_correction.json"
    sc_max_memory:            int   = 50    # Keep last N bad-trade snapshots

    # ── Logging ────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir:   str = "logs"