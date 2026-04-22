"""
trade_manager.py — Position sizing and order execution.

Calculates position size based on risk percentage and stop-loss distance,
then places market orders via the exchange client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import BotConfig
from indicators import IndicatorSnapshot
from logger import get_logger
from signal_engine import Signal

log = get_logger("trade_manager")


# ─────────────────────────────────────────────────────────────────────────────
# POSITION DATACLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """Represents an active trading position."""

    side:        str    # "long" | "short"
    entry_price: float
    qty:         float  # position size in base currency
    stop_loss:   float
    take_profit: float
    opened_at:   str   = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%H:%M:%S"))
    order_id:    str   = ""
    entry_snapshot: IndicatorSnapshot | None = None

    def calculate_pnl(self, current_price: float) -> float:
        """
        Calculate unrealised PnL at the given price.
        """
        if self.side == "long":
            return (current_price - self.entry_price) * self.qty
        else:
            return (self.entry_price - current_price) * self.qty


# ─────────────────────────────────────────────────────────────────────────────
# TRADE MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class TradeManager:
    """
    Handles position sizing, opening, and closing of trades.
    """

    def __init__(self, cfg: BotConfig, exchange) -> None:
        self.cfg      = cfg
        self.exchange = exchange

    # ─────────────────────────────────────────────────────────────────────
    # POSITION SIZING
    # ─────────────────────────────────────────────────────────────────────

    def calculate_qty(
        self,
        balance:       float,
        risk_pct:      float,
        entry_price:   float,
        stop_loss_pct: float,
    ) -> float:
        """
        Calculate position size based on risk amount and stop-loss distance.
        """
        if entry_price <= 0 or stop_loss_pct <= 0:
            log.error("Invalid inputs for qty calc: entry=%.4f  sl_pct=%.4f",
                      entry_price, stop_loss_pct)
            return 0.0

        risk_amount = balance * risk_pct
        sl_distance = entry_price * stop_loss_pct
        qty         = risk_amount / sl_distance

        log.debug("Sizing  balance=%.2f  risk_pct=%.3f  risk_amount=%.4f  "
                  "sl_dist=%.4f  qty=%.6f",
                  balance, risk_pct, risk_amount, sl_distance, qty)
        return round(qty, 6)

    # ─────────────────────────────────────────────────────────────────────
    # OPEN POSITION
    # ─────────────────────────────────────────────────────────────────────

    def open_position(
        self,
        signal:   Signal,
        snapshot: IndicatorSnapshot,
        qty:      float,
    ) -> Position | None:
        """
        Place a market order and return the Position object.
        """
        side  = "long" if signal == Signal.LONG else "short"
        price = snapshot.close_price

        sl_dist = price * self.cfg.stop_loss_pct
        tp_dist = sl_dist * self.cfg.take_profit_rr

        if side == "long":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        # ── Place market order on exchange ────────────────────────────────
        order_id = self.exchange.place_market_order(
            symbol = self.cfg.symbol,
            side   = side,
            qty    = qty,
        )

        if order_id is None:
            log.error("Order placement FAILED — no position opened.")
            return None

        return Position(
            side        = side,
            entry_price = price,
            qty         = qty,
            stop_loss   = round(sl, 4),
            take_profit = round(tp, 4),
            order_id    = order_id,
            entry_snapshot = snapshot,
        )

    # ─────────────────────────────────────────────────────────────────────
    # CLOSE POSITION
    # ─────────────────────────────────────────────────────────────────────

    def close_position(self, position: Position, current_price: float) -> None:
        """
        Close the given position with a market order.
        """
        close_side = "sell" if position.side == "long" else "buy"

        self.exchange.place_market_order(
            symbol    = self.cfg.symbol,
            side      = close_side,
            qty       = position.qty,
            reduce_only = True,
        )

        log.info("Close order sent  side=%s  qty=%s  price≈%.4f",
                 close_side, position.qty, current_price)