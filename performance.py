"""
performance.py — Trade performance tracker.

Tracks win/loss counts, PnL, consecutive losses,
and provides statistics for the pressure system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from logger import get_logger

log = get_logger("performance")


# ─────────────────────────────────────────────────────────────────────────────
# TRADE RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """Record of a completed trade with its outcome."""
    timestamp:   str
    side:        str    # "long" or "short"
    entry_price: float
    exit_price:  float
    pnl:         float  # realised PnL in quote currency (USDT)
    reason:      str    # "TP HIT" | "SL HIT" | "SIGNAL EXIT"

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def is_loss(self) -> bool:
        return self.pnl <= 0


# ─────────────────────────────────────────────────────────────────────────────
# TRACKER
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceTracker:
    """
    Tracks all trade results and computes statistics.
    Single-threaded (runs in one event loop).
    """

    def __init__(self) -> None:
        self._trades:           list[TradeRecord] = []
        self._consecutive_losses: int             = 0

    # ─────────────────────────────────────────────────────────────────────
    # RECORD A CLOSED TRADE
    # ─────────────────────────────────────────────────────────────────────

    def record_trade(
        self,
        pnl:         float,
        entry_price: float,
        exit_price:  float,
        side:        str,
        reason:      str,
    ) -> None:
        """
        Record a completed trade and log the result.
        """
        record = TradeRecord(
            timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            side        = side,
            entry_price = entry_price,
            exit_price  = exit_price,
            pnl         = pnl,
            reason      = reason,
        )
        self._trades.append(record)

        # ── Update consecutive loss counter ───────────────────────────────
        if record.is_loss:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # ── Log trade result ──────────────────────────────────────────────
        win_r  = self.win_rate
        loss_r = self.loss_rate
        emoji  = "✅" if record.is_win else "❌"

        log.info(
            "%s Trade #%d  side=%-5s  entry=%.4f  exit=%.4f  "
            "pnl=%+.4f  reason=%-12s  "
            "WinRate=%.1f%%  LossRate=%.1f%%  Streak=%d",
            emoji,
            len(self._trades),
            side,
            entry_price,
            exit_price,
            pnl,
            reason,
            win_r  * 100,
            loss_r * 100,
            self._consecutive_losses if record.is_loss else 0,
        )

    # ─────────────────────────────────────────────────────────────────────
    # STATISTICS
    # ─────────────────────────────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return len(self._trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self._trades if t.is_win)

    @property
    def losses(self) -> int:
        return sum(1 for t in self._trades if t.is_loss)

    @property
    def win_rate(self) -> float:
        """Win percentage (0.0 if no trades)."""
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def loss_rate(self) -> float:
        """Loss percentage."""
        return self.losses / self.total_trades if self.total_trades else 0.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self._trades)

    @property
    def consecutive_losses(self) -> int:
        """Current consecutive loss streak."""
        return self._consecutive_losses

    @property
    def loss_exceeds_win(self) -> bool:
        """Returns True if loss rate exceeds win rate (min 4 trades)."""
        return self.total_trades >= 4 and self.loss_rate > self.win_rate

    def summary(self) -> dict[str, Any]:
        """Dumps dictionary for the UI panel."""
        return {
            "total_trades":       self.total_trades,
            "wins":               self.wins,
            "losses":             self.losses,
            "win_rate":           self.win_rate,
            "loss_rate":          self.loss_rate,
            "total_pnl":          round(self.total_pnl, 6),
            "consecutive_losses": self.consecutive_losses,
        }