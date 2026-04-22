"""
signal_engine.py — asks the math if we should ape in.

literally just a huge if-statement checking if all 4 indicators align.
if they do, we return LONG or SHORT and hope for the best.

also has an exit signal thing that panics and sells early if the trend flips.
"""

from __future__ import annotations

from enum import Enum, auto

from config import BotConfig
from indicators import IndicatorSnapshot
from logger import get_logger
from self_correction import SelfCorrectionEngine

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trade_manager import Position

log = get_logger("signal")


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL ENUM
# ─────────────────────────────────────────────────────────────────────────────

class Signal(Enum):
    NONE  = auto()
    LONG  = auto()
    SHORT = auto()


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class SignalEngine:
    """
    the if-statements of destiny.
    """

    def __init__(self, cfg: BotConfig, sc_engine: SelfCorrectionEngine) -> None:
        self.cfg = cfg
        self.sc  = sc_engine

    # ─────────────────────────────────────────────────────────────────────
    # ENTRY SIGNAL
    # ─────────────────────────────────────────────────────────────────────

    def evaluate_entry(self, s: IndicatorSnapshot) -> Signal:
        """
        Returns LONG, SHORT, or NONE based on indicator alignment
        and ML brain confidence.
        """
        # Pull thresholds from config
        rsi_oversold    = self.cfg.rsi_oversold
        rsi_overbought  = self.cfg.rsi_overbought
        min_macd_hist   = self.cfg.min_macd_histogram
        price           = s.close_price
        min_spread      = self.cfg.min_ema_spread_pct * price

        # ── LONG conditions ───────────────────────────────────────────────
        long_ema    = s.bullish_ema                                  # fast > slow
        long_rsi    = s.rsi < rsi_oversold                           # RSI oversold → bounce
        long_macd   = s.macd_histogram > min_macd_hist               # positive / recovering hist
        long_spread = s.ema_spread >= min_spread                     # spread wide enough

        # ── SHORT conditions ──────────────────────────────────────────────
        short_ema    = s.bearish_ema                                 # fast < slow
        short_rsi    = s.rsi > rsi_overbought                       # RSI overbought → drop
        short_macd   = s.macd_histogram < -min_macd_hist             # negative hist
        short_spread = s.ema_spread <= -min_spread

        log.debug(
            "LONG  → ema=%s rsi=%s macd=%s spread=%s",
            long_ema, long_rsi, long_macd, long_spread,
        )
        log.debug(
            "SHORT → ema=%s rsi=%s macd=%s spread=%s",
            short_ema, short_rsi, short_macd, short_spread,
        )

        signal = Signal.NONE
        if long_ema and long_rsi and long_macd and long_spread:
            signal = Signal.LONG
        elif short_ema and short_rsi and short_macd and short_spread:
            signal = Signal.SHORT

        if signal != Signal.NONE:
            # Check ML brain confidence
            confidence = self.sc.predict_success(s)
            threshold  = self.cfg.ml_confidence_threshold
            if confidence < threshold:
                log.info(
                    "[SC-Brain] Rejected %s (confidence=%.1f%% < %.1f%%)",
                    signal.name, confidence * 100, threshold * 100,
                )
                return Signal.NONE
            else:
                log.info(
                    "[SC-Brain] Approved %s (confidence=%.1f%% >= %.1f%%)",
                    signal.name, confidence * 100, threshold * 100,
                )

        return signal

    # ─────────────────────────────────────────────────────────────────────
    # EXIT SIGNAL
    # ─────────────────────────────────────────────────────────────────────

    def evaluate_exit(self, s: IndicatorSnapshot, pos: Position) -> bool:
        """
        Returns True if exit conditions are met.
        Requires both RSI extreme AND MACD momentum reversal.
        """
        if pos.side == "long":
            rsi_extreme  = s.rsi > 70             # overbought
            macd_turning = s.macd_histogram < 0    # momentum reversed
            return rsi_extreme and macd_turning
        else:  # short
            rsi_extreme  = s.rsi < 30             # oversold
            macd_turning = s.macd_histogram > 0    # momentum reversed
            return rsi_extreme and macd_turning