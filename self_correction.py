"""
self_correction.py — "Machine Learning" 

Concept:
Every time we take an L, we write down the indicators so we don't do it again.
Basically, if RSI was 30 and we still hit Stop Loss, next time we wait for RSI 28.
Same for MACD and EMA.

Persistence:
Saves to JSON so when I accidentally close the terminal my bot still remembers
its traumas.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from config import BotConfig
from indicators import IndicatorSnapshot
from logger import get_logger

log = get_logger("self_correction")


# ─────────────────────────────────────────────────────────────────────────────
# BAD TRADE RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BadTradeRecord:
    """screenshot of the indicators right before disaster struck."""
    rsi:            float
    ema_spread:     float
    macd_histogram: float
    close_price:    float


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class SelfCorrectionEngine:
    """
    learns from stop-loss hits so my balance doesn't hit 0.
    """

    def __init__(self, cfg: BotConfig) -> None:
        self.cfg = cfg

        # Ring buffer: keeps only the last N bad trade snapshots
        self._bad_trades: deque[BadTradeRecord] = deque(maxlen=cfg.sc_max_memory)

        # Dynamic thresholds — keys must match names used in get_threshold()
        self._thresholds: dict[str, float] = {
            "rsi_oversold":   cfg.rsi_oversold,    # can only increase (tighten)
            "rsi_overbought": cfg.rsi_overbought,  # can only decrease
            "min_macd_hist":  0.0,                 # minimum |histogram| for entry
            "min_ema_spread": 0.0,                 # minimum |EMA spread| for entry
        }

        # Load persisted state from disk (survives restarts)
        self._load()

    # ─────────────────────────────────────────────────────────────────────
    # RECORD A BAD TRADE
    # ─────────────────────────────────────────────────────────────────────

    def record_bad_trade(self, snapshot: IndicatorSnapshot) -> None:
        """
        logs the L and tightens the rules.
        """
        record = BadTradeRecord(
            rsi            = snapshot.rsi,
            ema_spread     = snapshot.ema_spread,
            macd_histogram = snapshot.macd_histogram,
            close_price    = snapshot.close_price,
        )
        self._bad_trades.append(record)

        log.warning(
            "[SC] Bad trade recorded  RSI=%.1f  EMA_spread=%.5f  MACD_hist=%.5f  "
            "Total bad trades in memory: %d",
            record.rsi, record.ema_spread, record.macd_histogram,
            len(self._bad_trades),
        )

        # ── Adjust thresholds based on the new evidence ───────────────────
        self._adjust_thresholds(record)

        # ── Log updated thresholds ────────────────────────────────────────
        log.info(
            "[SC] Updated thresholds  rsi_oversold=%.1f  rsi_overbought=%.1f  "
            "min_macd_hist=%.5f  min_ema_spread=%.5f",
            self._thresholds["rsi_oversold"],
            self._thresholds["rsi_overbought"],
            self._thresholds["min_macd_hist"],
            self._thresholds["min_ema_spread"],
        )

    # ─────────────────────────────────────────────────────────────────────
    # GET THRESHOLD — used by SignalEngine
    # ─────────────────────────────────────────────────────────────────────

    def get_threshold(self, name: str, default: float) -> float:
        """
        gets the new strict threshold bc the default one was trash.
        """
        return self._thresholds.get(name, default)

    # ─────────────────────────────────────────────────────────────────────
    # ADJUSTMENT LOGIC
    # ─────────────────────────────────────────────────────────────────────

    def _adjust_thresholds(self, bad: BadTradeRecord) -> None:
        """
        makes the rules stricter based on our traumas.
        """
        rsi_step   = self.cfg.sc_rsi_tighten_step
        macd_step  = self.cfg.sc_macd_penalty_step
        ema_step   = self.cfg.sc_ema_spread_penalty_pct * bad.close_price

        cur_oversold   = self._thresholds["rsi_oversold"]
        cur_overbought = self._thresholds["rsi_overbought"]
        cur_macd_min   = self._thresholds["min_macd_hist"]
        cur_ema_min    = self._thresholds["min_ema_spread"]

        # ── RSI: tighten if SL occurred while RSI was near the threshold ──
        if bad.rsi <= cur_oversold + 5:   # long entry zone
            new_oversold = min(
                cur_oversold + rsi_step,
                self.cfg.rsi_oversold + self.cfg.sc_max_rsi_tighten,
            )
            if new_oversold != cur_oversold:
                self._thresholds["rsi_oversold"] = new_oversold
                log.info("[SC] RSI oversold tightened: %.1f → %.1f", cur_oversold, new_oversold)

        if bad.rsi >= cur_overbought - 5:  # short entry zone
            new_overbought = max(
                cur_overbought - rsi_step,
                self.cfg.rsi_overbought - self.cfg.sc_max_rsi_tighten,
            )
            if new_overbought != cur_overbought:
                self._thresholds["rsi_overbought"] = new_overbought
                log.info("[SC] RSI overbought tightened: %.1f → %.1f", cur_overbought, new_overbought)

        # ── MACD: raise minimum if histogram was weak ──────────────────────
        if abs(bad.macd_histogram) < cur_macd_min + macd_step * 3:
            self._thresholds["min_macd_hist"] = cur_macd_min + macd_step
            log.info("[SC] min_macd_hist raised: %.5f → %.5f",
                     cur_macd_min, self._thresholds["min_macd_hist"])

        # ── EMA spread: raise minimum if spread was shallow ───────────────
        if abs(bad.ema_spread) < cur_ema_min + ema_step * 3:
            self._thresholds["min_ema_spread"] = cur_ema_min + ema_step
            log.info("[SC] min_ema_spread raised: %.5f → %.5f",
                     cur_ema_min, self._thresholds["min_ema_spread"])

    # ─────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────

    def persist(self) -> None:
        """saves the trauma to json file."""
        os.makedirs(os.path.dirname(self.cfg.sc_persist_path), exist_ok=True)
        payload: dict[str, Any] = {
            "thresholds": self._thresholds,
            "bad_trades": [asdict(bt) for bt in self._bad_trades],
        }
        with open(self.cfg.sc_persist_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.info("[SC] State persisted → %s", self.cfg.sc_persist_path)

    def _load(self) -> None:
        """loads the trauma back in."""
        path = self.cfg.sc_persist_path
        if not os.path.exists(path):
            log.info("[SC] No persisted state found — starting fresh.")
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)

            # Restore thresholds
            for k, v in payload.get("thresholds", {}).items():
                self._thresholds[k] = float(v)

            # Restore bad-trade memory
            for raw in payload.get("bad_trades", []):
                self._bad_trades.append(BadTradeRecord(**raw))

            log.info(
                "[SC] State loaded from %s  (%d bad trades in memory)",
                path, len(self._bad_trades),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.error("[SC] Failed to load persisted state: %s — starting fresh.", exc)