"""
exchange.py — literally just wrapping ccxt so my TA doesn't know I used it.

it handles Bybit and Binance without me doing anything so, stonks right?
shoutout to whoever wrote ccxt, carrying my whole degree.

testnet:
set cfg.testnet = True. if u set False ur gambling ur tuition money.

errors:
i just stuck try-except everywhere so it never crashes.
a crash = F on assignment. we return 0.0 or None and pretend nothing happened.
"""

from __future__ import annotations

from typing import Any

from config import BotConfig
from logger import get_logger

log = get_logger("exchange")

# ── try to import ccxt gracefully basically in case i run this on my laptop
# without installing requirements first and spending 3 hrs debugging it. ──────────
try:
    import ccxt  # type: ignore
    _CCXT_AVAILABLE = True
except ImportError:
    _CCXT_AVAILABLE = False
    log.warning("ccxt not installed — ExchangeClient will raise if used.")


class ExchangeClient:
    """
    wrapper thing so i don't have to look at awful JSON responses directly.
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
        """builds the ccxt thing."""
        exchange_class = getattr(ccxt, cfg.exchange_id)

        params: dict[str, Any] = {
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",  # Always futures
            },
        }

        # Bybit v5 gave me an error once, so i put this here and it fixed it idk

        exchange = exchange_class(params)

        if cfg.testnet:
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
        fetches the candlesticks.

        also it sends the active unclosed candle at the end which ruined my
        backtest yesterday. i am dropping the last one.
        """
        try:
            candles = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit + 1)
            # Drop the current (unclosed) candle
            return candles[:-1] if len(candles) > 1 else candles
        except ccxt.BaseError as exc:
            log.error("fetch_ohlcv error: %s", exc)
            return []

    def fetch_ticker_price(self, symbol: str) -> float:
        """spits out the current price."""
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return float(ticker.get("last", 0.0))
        except ccxt.BaseError as exc:
            log.error("fetch_ticker error: %s", exc)
            return 0.0

    def fetch_balance_usdt(self) -> float:
        """check how broke i am."""
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
        yolo leverage button.

        some exchanges let us set margin mode cross here, some throw error.
        i'm just gonna try both and close my eyes.
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
        places the order and takes my money.

        "side" can be buy/sell or long/short bc i kept forgetting which one ccxt wants.
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