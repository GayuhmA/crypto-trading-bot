"""
bot.py — the main thing that runs the bot tbh.

ngl it basically connects everything together like frankenstein.
grabs candles, does some math, opens trades, and prays that the pressure
and self-correction stuff doesn't blow up my account 💀 

how to run (pls use testnet or u will get liquidated):
    python bot.py --exchange bybit --symbol BTC/USDT:USDT --timeframe 15m
"""

from __future__ import annotations

import argparse
import time
import traceback
from datetime import datetime, timezone

from config import BotConfig
from exchange import ExchangeClient
from indicators import compute_indicators, IndicatorSnapshot
from logger import get_logger, print_banner, print_status_panel
from performance import PerformanceTracker
from pressure import PressureManager
from self_correction import SelfCorrectionEngine
from signal_engine import SignalEngine, Signal
from trade_manager import TradeManager, Position

log = get_logger("bot")


# ─────────────────────────────────────────────────────────────────────────────
# BIG MOMMA BOT CLASS (DO NOT TOUCH)
# ─────────────────────────────────────────────────────────────────────────────

class TradingBot:
    """
    the big brain that controls perfectly nothing.

    i just injected everything in the __init__ so i can pass my unit tests.
    professor said coupling is bad so i guess this is good??? idk tbh 😭
    """

    def __init__(self, cfg: BotConfig) -> None:
        self.cfg = cfg

        # ── Core sub-systems (copy pasted from SO tbh) ────────────────────
        self.exchange       = ExchangeClient(cfg)
        self.performance    = PerformanceTracker()
        self.pressure       = PressureManager(cfg, self.performance)
        self.self_correction= SelfCorrectionEngine(cfg)
        self.signal_engine  = SignalEngine(cfg, self.self_correction)
        self.trade_manager  = TradeManager(cfg, self.exchange)

        # ── Random state variables I need ──────────────────────────────────
        self.iteration:     int      = 0
        self.last_candle_ts: float   = 0.0   # hack to stop infinite loops lmao
        self.current_position: Position | None = None

    # ─────────────────────────────────────────────────────────────────────
    # THE INFINITE LOOP OF DOOM
    # ─────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """while True go brrrrr. polls the exchange and sleeps."""
        print_banner(self.cfg)
        log.info("Bot started — symbol=%s  tf=%s  leverage=%sx",
                 self.cfg.symbol, self.cfg.timeframe, self.cfg.leverage)

        while True:
            try:
                self.iteration += 1
                self._tick()
            except KeyboardInterrupt:
                log.warning("KeyboardInterrupt received — shutting down gracefully.")
                self._shutdown()
                break
            except Exception as exc:  # noqa: BLE001
                log.error("Unhandled exception in tick #%d: %s", self.iteration, exc)
                log.debug(traceback.format_exc())

            # ── Wait before next poll ────────────────────────────────────
            time.sleep(self.cfg.poll_interval_seconds)

    # ─────────────────────────────────────────────────────────────────────
    # ONE TICK = ONE HEART ATTACK
    # ─────────────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        """
        the loop iteration. step-by-step logic:
        1. pull candles (hope api doesn't rate limit me)
        2. if same candle, skip.
        3. do math (indicators)
        4. check if i'm losing money (manage position)
        5. check if i should lose money (evaluate entry)
        6. print the cool ui
        """
        # ── 1. Fetch candles (god pls no timeout) ─────────────────────────
        candles = self.exchange.fetch_ohlcv(
            symbol    = self.cfg.symbol,
            timeframe = self.cfg.timeframe,
            limit     = self.cfg.candle_limit,
        )
        if not candles:
            log.warning("Empty candle response — skipping tick.")
            return

        latest_ts: float = candles[-1][0]   # timestamp of last *closed* candle

        # ── 2. Pls don't double count the same candle ─────────────────────
        if latest_ts == self.last_candle_ts:
            log.debug("No new closed candle — waiting.")
            return
        self.last_candle_ts = latest_ts

        log.info("─" * 60)
        log.info("Tick #%d  |  Candle: %s",
                 self.iteration,
                 datetime.fromtimestamp(latest_ts / 1_000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

        # ── 3. Compute indicators ─────────────────────────────────────────
        snapshot: IndicatorSnapshot = compute_indicators(candles, self.cfg)
        log.info("Indicators  →  EMA_fast=%.2f  EMA_slow=%.2f  RSI=%.1f  MACD_hist=%.4f",
                 snapshot.ema_fast, snapshot.ema_slow,
                 snapshot.rsi,      snapshot.macd_histogram)

        # ── 4. Manage open position ───────────────────────────────────────
        if self.current_position is not None:
            self._manage_open_position(snapshot)

        # ── 5. Evaluate entry if flat ─────────────────────────────────────
        if self.current_position is None:
            self._evaluate_entry(snapshot)

        # ── 6. Refresh terminal panel ─────────────────────────────────────
        print_status_panel(
            snapshot    = snapshot,
            performance = self.performance,
            pressure    = self.pressure,
            position    = self.current_position,
        )

    # ─────────────────────────────────────────────────────────────────────
    # GAMBLING MANAGEMENT / STOP LOSS PRAYERS
    # ─────────────────────────────────────────────────────────────────────

    def _manage_open_position(self, snapshot: IndicatorSnapshot) -> None:
        """
        Checks if we hit TP (yay) or SL (rip account).
        Also if we hit SL it complains to the self_correction engine so it stops doing stupid things.
        """
        assert self.current_position is not None

        pos     = self.current_position
        price   = snapshot.close_price
        closed  = False
        pnl     = 0.0
        reason  = ""

        if pos.side == "long":
            if price >= pos.take_profit:
                pnl, reason, closed = pos.calculate_pnl(price), "TP HIT", True
            elif price <= pos.stop_loss:
                pnl, reason, closed = pos.calculate_pnl(price), "SL HIT", True
        else:  # short
            if price <= pos.take_profit:
                pnl, reason, closed = pos.calculate_pnl(price), "TP HIT", True
            elif price >= pos.stop_loss:
                pnl, reason, closed = pos.calculate_pnl(price), "SL HIT", True

        # ── Exit signal from strategy (panic selling before SL) ──────────
        if not closed:
            exit_signal = self.signal_engine.evaluate_exit(snapshot, pos)
            if exit_signal:
                pnl, reason, closed = pos.calculate_pnl(price), "SIGNAL EXIT", True

        if closed:
            log.info("Position CLOSED  |  reason=%-12s  pnl=%+.4f USDT", reason, pnl)

            # Record in performance tracker → tracking my downfall
            self.performance.record_trade(
                pnl          = pnl,
                entry_price  = pos.entry_price,
                exit_price   = price,
                side         = pos.side,
                reason       = reason,
            )

            # ── Self-Correction: "i will never do this again" ────────────────
            if reason == "SL HIT":
                log.warning("SL hit — feeding Self-Correction engine.")
                self.self_correction.record_bad_trade(snapshot)

            # ── Pressure: stressing out after every trade ────────────────────
            self.pressure.evaluate(self.performance)

            # ── Close on exchange (hope the fee isn't too high) ───────────
            self.trade_manager.close_position(pos, price)
            self.current_position = None

    # ─────────────────────────────────────────────────────────────────────
    # ENTRY EVALUATION (AKA "SHOULD I PRESS BUY?")
    # ─────────────────────────────────────────────────────────────────────

    def _evaluate_entry(self, snapshot: IndicatorSnapshot) -> None:
        """
        Ask the signal engine if we should ape in.
        If pressure system is triggered, we sit on our hands.
        """
        # ── Pressure gate: "i'm too stressed to trade rn" ─────────────────
        if not self.pressure.allow_trading():
            log.warning("[PRESSURE] Trading paused — cooldown active.  "
                        "Resuming in %ds.", self.pressure.cooldown_remaining())
            return

        signal: Signal = self.signal_engine.evaluate_entry(snapshot)

        if signal == Signal.NONE:
            log.info("Signal: NONE — no trade.")
            return

        log.info("Signal: %s — preparing order.", signal.name)

        # ── Fetch effective risk params (stress level adjustments) ────────
        effective_leverage   = self.pressure.effective_leverage()
        effective_risk_pct   = self.pressure.effective_risk_pct()

        log.info("Risk params  →  leverage=%sx  risk_pct=%.2f%%",
                 effective_leverage, effective_risk_pct * 100)

        # ── Set leverage (plz no 100x liquidations) ───────────────────────
        self.exchange.set_leverage(self.cfg.symbol, effective_leverage)

        # ── Size the position (doing math in python feels wrong) ──────────
        balance  = self.exchange.fetch_balance_usdt()
        qty      = self.trade_manager.calculate_qty(
            balance      = balance,
            risk_pct     = effective_risk_pct,
            entry_price  = snapshot.close_price,
            stop_loss_pct= self.cfg.stop_loss_pct,
        )

        if qty <= 0:
            log.error("Calculated qty=%s — skipping trade.", qty)
            return

        # ── Place order ───────────────────────────────────────────────────
        position = self.trade_manager.open_position(
            signal   = signal,
            snapshot = snapshot,
            qty      = qty,
        )

        if position:
            self.current_position = position
            log.info("Position OPENED  |  side=%s  entry=%.4f  sl=%.4f  tp=%.4f  qty=%s",
                     position.side, position.entry_price,
                     position.stop_loss, position.take_profit, position.qty)

    # ─────────────────────────────────────────────────────────────────────
    # CTRL+C PANIC BUTTON
    # ─────────────────────────────────────────────────────────────────────

    def _shutdown(self) -> None:
        """Called when I hit Ctrl+C. Sells everything and cries."""
        log.info("Shutting down — cancelling open orders if any.")
        if self.current_position is not None:
            price = self.exchange.fetch_ticker_price(self.cfg.symbol)
            self.trade_manager.close_position(self.current_position, price)

        log.info("═" * 60)
        log.info("FINAL PERFORMANCE SUMMARY")
        log.info("═" * 60)
        summary = self.performance.summary()
        for k, v in summary.items():
            log.info("  %-22s : %s", k, v)
        log.info("═" * 60)
        self.self_correction.persist()


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crypto Futures Trading Bot")
    p.add_argument("--exchange",  default="bybit",          help="CCXT exchange id")
    p.add_argument("--symbol",    default="BTC/USDT:USDT",  help="Futures market symbol")
    p.add_argument("--timeframe", default="15m",            help="Candle timeframe")
    p.add_argument("--leverage",  default=5, type=int,      help="Default leverage")
    p.add_argument("--testnet",   action="store_true",      help="Use testnet endpoints")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = BotConfig(
        exchange_id = args.exchange,
        symbol      = args.symbol,
        timeframe   = args.timeframe,
        leverage    = args.leverage,
        testnet     = args.testnet,
    )
    bot = TradingBot(config)
    bot.run()