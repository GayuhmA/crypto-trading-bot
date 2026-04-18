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
        returns LONG, SHORT, or NONE (aka boring).
        """
        # Pull dynamic thresholds from Self-Correction engine
        rsi_oversold    = self.sc.get_threshold("rsi_oversold",    self.cfg.rsi_oversold)
        rsi_overbought  = self.sc.get_threshold("rsi_overbought",  self.cfg.rsi_overbought)
        min_macd_hist   = self.sc.get_threshold("min_macd_hist",   0.0)
        min_ema_spread  = self.sc.get_threshold("min_ema_spread",  0.0)

        log.debug(
            "Entry thresholds → rsi_oversold=%.1f  rsi_overbought=%.1f  "
            "min_macd_hist=%.5f  min_ema_spread=%.5f",
            rsi_oversold, rsi_overbought, min_macd_hist, min_ema_spread,
        )

        # ── LONG conditions ───────────────────────────────────────────────
        long_ema    = s.bullish_ema                                  # fast > slow
        long_rsi    = rsi_oversold <= s.rsi <= rsi_overbought        # RSI in neutral zone (pullback)
        long_macd   = s.macd_histogram > min_macd_hist               # positive / recovering hist
        long_spread = s.ema_spread >= min_ema_spread                  # spread wide enough

        # ── SHORT conditions ──────────────────────────────────────────────
        short_ema    = s.bearish_ema                                 # fast < slow
        short_rsi    = rsi_oversold <= s.rsi <= rsi_overbought       # RSI in neutral zone (bounce)
        short_macd   = s.macd_histogram < -min_macd_hist             # negative hist
        short_spread = s.ema_spread <= -min_ema_spread

        log.debug(
            "LONG  → ema=%s rsi=%s macd=%s spread=%s",
            long_ema, long_rsi, long_macd, long_spread,
        )
        log.debug(
            "SHORT → ema=%s rsi=%s macd=%s spread=%s",
            short_ema, short_rsi, short_macd, short_spread,
        )

        if long_ema and long_rsi and long_macd and long_spread:
            return Signal.LONG

        if short_ema and short_rsi and short_macd and short_spread:
            return Signal.SHORT

        return Signal.NONE

    # ─────────────────────────────────────────────────────────────────────
    # EXIT SIGNAL
    # ─────────────────────────────────────────────────────────────────────

    def evaluate_exit(self, s: IndicatorSnapshot, pos: Position) -> bool:
        """
        panic sell method. returns True if we should run away.
        """
        if pos.side == "long":
            ema_reversal = s.bearish_ema          # trend has flipped
            rsi_extreme  = s.rsi > 70             # overbought — take profit
            return ema_reversal or rsi_extreme

        else:  # short
            ema_reversal = s.bullish_ema
            rsi_extreme  = s.rsi < 30             # oversold — take profit
            return ema_reversal or rsi_extreme