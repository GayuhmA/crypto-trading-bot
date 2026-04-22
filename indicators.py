"""
indicators.py — math stuff

professor said to use pure numpy without pandas so here we are.
i don't really know how the math works tbh i just copied the formulas
from investopedia and prayed to the compiler gods.

list of things my bot looks at to lose money:
- EMA (fast and slow)
- RSI
- MACD
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# RESULT DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IndicatorSnapshot:
    """
    snapshot of the math.

    we just pass this bucket around so we don't recalculate things and lag
    the matrix.
    """
    timestamp:      float   # Unix ms of the closed candle
    close_price:    float   # Last close price

    # EMA
    ema_fast:       float   # EMA(fast_period) value
    ema_slow:       float   # EMA(slow_period) value
    ema_spread:     float   # ema_fast - ema_slow  (+ = fast above slow)

    # RSI
    rsi:            float   # 0–100

    # MACD
    macd_line:      float   # MACD line
    macd_signal:    float   # Signal line
    macd_histogram: float   # MACD line − signal line (+ = bullish momentum)

    # ML Learning Features
    hour_of_day:       float
    candle_volatility: float


    @property
    def bullish_ema(self) -> bool:
        """stonks going up?"""
        return self.ema_spread > 0

    @property
    def bearish_ema(self) -> bool:
        """stonks going down?"""
        return self.ema_spread < 0


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL INDICATOR FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    """
    Exponential Moving Average.

    has a k factor thing. tbh if someone asks me how this works in the 
    presentation next week, i will just fake a cough.
    """
    k      = 2.0 / (period + 1)
    result = np.full_like(prices, np.nan, dtype=float)

    # Seed with simple average of first `period` values (chatgpt told me to do this)
    if len(prices) < period:
        return result

    result[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)

    return result


def _rsi(prices: np.ndarray, period: int) -> np.ndarray:
    """
    RSI (Wilder's method idk).

    this is supposed to tell us if it's overbought or oversold.
    """
    result  = np.full_like(prices, np.nan, dtype=float)
    deltas  = np.diff(prices)

    gains   = np.where(deltas > 0, deltas, 0.0)
    losses  = np.where(deltas < 0, -deltas, 0.0)

    if len(gains) < period:
        return result

    # First average gain/loss (simple mean bc im bad at math)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs            = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def _macd(
    prices:     np.ndarray,
    fast:       int,
    slow:       int,
    signal_p:   int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    MACD line, signal line, and histogram.

    returns 3 things. don't mix them up.
    """
    ema_fast   = _ema(prices, fast)
    ema_slow   = _ema(prices, slow)
    macd_line  = ema_fast - ema_slow

    # Signal is an EMA of the MACD line (nan pruning giving me a headache)
    valid_mask  = ~np.isnan(macd_line)
    signal_full = np.full_like(macd_line, np.nan)

    if np.sum(valid_mask) >= signal_p:
        valid_macd = macd_line[valid_mask]
        signal_vals = _ema(valid_macd, signal_p)
        signal_full[valid_mask] = signal_vals

    histogram = macd_line - signal_full
    return macd_line, signal_full, histogram


# ─────────────────────────────────────────────────────────────────────────────
# TOP-LEVEL FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def compute_indicators(
    candles: list[list],   # CCXT OHLCV format: [[ts, o, h, l, c, v], ...]
    cfg,                   # BotConfig — avoid circular import with string
) -> IndicatorSnapshot:
    """
    extract close prices and do the math.

    we literally throw away all historical data after indexing the last one.
    so much memory waste. sad!
    """
    closes = np.array([c[4] for c in candles], dtype=float)  # index 4 = close
    highs  = np.array([c[2] for c in candles], dtype=float)  # index 2 = high
    lows   = np.array([c[3] for c in candles], dtype=float)  # index 3 = low

    ema_f    = _ema(closes, cfg.ema_fast_period)
    ema_s    = _ema(closes, cfg.ema_slow_period)
    rsi_arr  = _rsi(closes, cfg.rsi_period)
    macd_l, macd_sig, macd_hist = _macd(closes, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    
    # Calculate volatility of the last candle as a percentage of close
    last_close = closes[-1]
    volatility = ((highs[-1] - lows[-1]) / last_close) * 100 if last_close > 0 else 0.0
    
    # Extract hour of day from timestamp (UTC)
    timestamp_ms = float(candles[-1][0])
    hour = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).hour

    def last(arr: np.ndarray) -> float:
        """gets the last valid number without crashing."""
        valid = arr[~np.isnan(arr)]
        return float(valid[-1]) if len(valid) else 0.0

    return IndicatorSnapshot(
        timestamp      = float(candles[-1][0]),
        close_price    = float(closes[-1]),
        ema_fast       = last(ema_f),
        ema_slow       = last(ema_s),
        ema_spread     = last(ema_f) - last(ema_s),
        rsi            = last(rsi_arr),
        macd_line      = last(macd_l),
        macd_signal    = last(macd_sig),
        macd_histogram = last(macd_hist),
        hour_of_day    = float(hour),
        candle_volatility = float(volatility),
    )