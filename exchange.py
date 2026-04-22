"""
exchange.py — CCXT exchange wrapper.

Provides a unified interface for Bybit and Binance futures.
Handles testnet/sandbox configuration, market data fetching,
and order placement.

Errors are caught and logged — returns 0.0 or None on failure.
"""

from __future__ import annotations

from typing import Any

from config import BotConfig
from logger import get_logger

log = get_logger("exchange")

# ── Graceful ccxt import ─────────────────────────────────────────────────────
try:
    import ccxt  # type: ignore
    _CCXT_AVAILABLE = True
except ImportError:
    _CCXT_AVAILABLE = False
    log.warning("ccxt not installed — ExchangeClient will raise if used.")


class ExchangeClient:
    """
    Unified exchange client wrapping CCXT for futures trading.
    """

    def __init__(self, cfg: BotConfig) -> None:
        if not _CCXT_AVAILABLE:
            raise ImportError("Install ccxt:  pip install ccxt")

        self.cfg      = cfg
        self._exchange = self._build_exchange(cfg)

    # ─────────────────────────────────────────────────────────────────────
    # CONSTRUCTION
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_exchange(cfg: BotConfig):
        """Build and configure the CCXT exchange instance."""
        exchange_class = getattr(ccxt, cfg.exchange_id)

        params: dict[str, Any] = {
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",  # Always futures
            },
        }



        exchange = exchange_class(params)

        if cfg.testnet:
            # Binance deprecated futures sandbox → use Demo Trading (CCXT v4.5.6+)
            # Other exchanges (Bybit, etc.) still use classic sandbox mode
            if "binance" in cfg.exchange_id.lower():
                exchange.enable_demo_trading(True)
                log.info("Exchange: %s  [DEMO TRADING MODE]", cfg.exchange_id)
            else:
                exchange.set_sandbox_mode(True)
                log.info("Exchange: %s  [TESTNET / SANDBOX MODE]", cfg.exchange_id)
        else:
            log.info("Exchange: %s  [LIVE]", cfg.exchange_id)

        exchange.load_markets()
        return exchange

    # ─────────────────────────────────────────────────────────────────────
    # MARKET DATA
    # ─────────────────────────────────────────────────────────────────────

    def fetch_ohlcv(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int = 200,
    ) -> list[list]:
        """
        Fetch OHLCV candles. Drops the unclosed candle at the end.
        """
        try:
            candles = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit + 1)
            # Drop the current (unclosed) candle
            return candles[:-1] if len(candles) > 1 else candles
        except ccxt.BaseError as exc:
            log.error("fetch_ohlcv error: %s", exc)
            return []

    def fetch_ticker_price(self, symbol: str) -> float:
        """Fetch the latest ticker price for a symbol."""
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return float(ticker.get("last", 0.0))
        except ccxt.BaseError as exc:
            log.error("fetch_ticker error: %s", exc)
            return 0.0

    def fetch_balance_usdt(self) -> float:
        """Fetch available USDT balance."""
        try:
            balance = self._exchange.fetch_balance()
            usdt    = balance.get("USDT", {}).get("free", 0.0)
            log.debug("Balance: %.4f USDT (free)", usdt)
            return float(usdt)
        except ccxt.BaseError as exc:
            log.error("fetch_balance error: %s", exc)
            return 0.0

    # ─────────────────────────────────────────────────────────────────────
    # ACCOUNT / POSITION CONFIG
    # ─────────────────────────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """
        Set leverage for a symbol. Also attempts to set cross-margin mode.
        Some exchanges may not support margin mode — errors are non-fatal.
        """
        try:
            # Ensure cross-margin mode (not isolated) — Bybit / Binance
            try:
                self._exchange.set_margin_mode("cross", symbol)
            except ccxt.BaseError:
                pass  # Silently skip — some exchanges don't expose this

            self._exchange.set_leverage(leverage, symbol)
            log.info("Leverage set: %dx for %s", leverage, symbol)
        except ccxt.BaseError as exc:
            log.warning("set_leverage error (non-fatal): %s", exc)

    # ─────────────────────────────────────────────────────────────────────
    # ORDER PLACEMENT
    # ─────────────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol:      str,
        side:        str,   # "buy" | "sell"  (or "long"/"short" — normalised below)
        qty:         float,
        reduce_only: bool = False,
    ) -> str | None:
        """
        Place a market order.
        Side accepts "buy"/"sell" or "long"/"short" (normalised internally).
        """
        # Normalise side
        ccxt_side = "buy" if side in ("buy", "long") else "sell"

        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True

        try:
            order = self._exchange.create_market_order(
                symbol = symbol,
                side   = ccxt_side,
                amount = qty,
                params = params,
            )
            order_id = order.get("id", "unknown")
            log.info("Order placed  side=%s  qty=%s  id=%s", ccxt_side, qty, order_id)
            return str(order_id)
        except ccxt.InsufficientFunds as exc:
            log.error("Insufficient funds: %s", exc)
        except ccxt.BaseError as exc:
            log.error("place_market_order error: %s", exc)

        return None