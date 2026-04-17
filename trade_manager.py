"""
trade_manager.py — calculates how much to bet.

risk amount = balance * risk_pct (so we don't lose it all at once).
then places MARKET orders everywhere bc LIMIT orders make my brain hurt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    """our active gamble."""

    side:        str    # "long" | "short"
    entry_price: float
    qty:         float  # position size in base currency
    stop_loss:   float
    take_profit: float
    opened_at:   str   = field(default_factory=lambda: datetime.utcnow().strftime("%H:%M:%S"))
    order_id:    str   = ""

    def calculate_pnl(self, current_price: float) -> float:
        """
        did i make money?
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
    pushes the buy/sell button.
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
        how much dogecoin do i buy with $10 risk?
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
        yolo.
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
        )

    # ─────────────────────────────────────────────────────────────────────
    # CLOSE POSITION
    # ─────────────────────────────────────────────────────────────────────

    def close_position(self, position: Position, current_price: float) -> None:
        """
        sells it.
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