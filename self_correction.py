"""
self_correction.py — ML Brain (Logistic Regression)

1-layer Neural Network built purely in Numpy.
Uses Gradient Descent to weigh the importance of features like
RSI, Volatility, hour of day, and EMA spread.

All features are normalized via np.tanh() to prevent gradient
domination by large-scale features (e.g. EMA spread in USD).
"""

from __future__ import annotations

import json
import os
import numpy as np
from typing import Any

from config import BotConfig
from indicators import IndicatorSnapshot
from logger import get_logger

log = get_logger("self_correction")


class SelfCorrectionEngine:
    """
    Logistic Regression brain for trade quality prediction.
    Learns from every closed trade via Stochastic Gradient Descent.
    """

    # Number of features: [RSI, MACD_hist, EMA_spread, volatility, hour, bias]
    _NUM_FEATURES = 6

    def __init__(self, cfg: BotConfig) -> None:
        self.cfg = cfg
        self.learning_rate = cfg.ml_learning_rate

        # Small random initialization to avoid symmetry breaking
        rng = np.random.default_rng(42)
        self._weights = rng.normal(0, 0.01, self._NUM_FEATURES)

        # Warmup & persist tracking
        self._trade_count: int = 0
        self._trades_since_save: int = 0

        self._load()

    # ─────────────────────────────────────────────────────────────────────
    # FEATURE EXTRACTION (all normalized to ~[-1, 1])
    # ─────────────────────────────────────────────────────────────────────

    def _extract_features(self, s: IndicatorSnapshot) -> np.ndarray:
        """
        Normalize all features to similar ranges using np.tanh().
        Prevents gradient domination by large-scale features.
        """
        price = max(s.close_price, 1.0)
        return np.array([
            (s.rsi - 50.0) / 50.0,                     # RSI: [-1, 1]
            np.tanh(s.macd_histogram / (price * 0.001)),   # MACD hist: price-relative
            np.tanh(s.ema_spread / (price * 0.01)),     # EMA spread: relative to 1% of price
            np.tanh(s.candle_volatility / 2.0),         # Volatility %: ~[-1, 1]
            s.hour_of_day / 24.0,                       # Hour: [0, 1]
            1.0                                         # Bias term
        ], dtype=float)

    # ─────────────────────────────────────────────────────────────────────
    # PREDICTION
    # ─────────────────────────────────────────────────────────────────────

    def predict_success(self, snapshot: IndicatorSnapshot) -> float:
        """
        Returns confidence score [0, 1].
        During warmup period, always returns 1.0 to allow learning.
        """
        # Warmup: allow all trades for the first N trades
        if self._trade_count < self.cfg.ml_warmup_trades:
            log.debug(
                "[SC-Brain] Warmup mode (%d/%d trades) — allowing all signals.",
                self._trade_count, self.cfg.ml_warmup_trades,
            )
            return 1.0

        features = self._extract_features(snapshot)
        z = np.dot(self._weights, features)
        z = np.clip(z, -20.0, 20.0)
        prob = 1.0 / (1.0 + np.exp(-z))

        log.debug("[SC-Brain] Confidence: %.2f%% (z=%.4f)", prob * 100, z)
        return float(prob)

    # ─────────────────────────────────────────────────────────────────────
    # LEARNING (SGD)
    # ─────────────────────────────────────────────────────────────────────

    def learn_from_trade(self, snapshot: IndicatorSnapshot | None, pnl: float) -> None:
        """
        Update weights using Binary Cross-Entropy gradient.
        Called after every closed trade (TP, SL, or SIGNAL EXIT).
        """
        if snapshot is None:
            return

        self._trade_count += 1
        features = self._extract_features(snapshot)

        # Target: 1.0 (Win) or 0.0 (Loss)
        target = 1.0 if pnl > 0.0 else 0.0

        # Forward pass
        z = np.clip(np.dot(self._weights, features), -20.0, 20.0)
        prediction = 1.0 / (1.0 + np.exp(-z))

        # Gradient Descent (Stochastic)
        error = prediction - target
        self._weights -= self.learning_rate * error * features

        log.info(
            "[SC-Brain] Learned from trade #%d  pnl=%+.4f  target=%.0f  "
            "pred=%.3f  error=%+.3f",
            self._trade_count, pnl, target, prediction, error,
        )

        # Throttled persistence (every N trades)
        self._trades_since_save += 1
        if self._trades_since_save >= self.cfg.ml_persist_every_n:
            self.persist()
            self._trades_since_save = 0

    # ─────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────

    def persist(self) -> None:
        """Save weights and trade count to disk."""
        os.makedirs(os.path.dirname(self.cfg.sc_persist_path), exist_ok=True)
        payload: dict[str, Any] = {
            "weights": self._weights.tolist(),
            "trade_count": self._trade_count,
        }
        with open(self.cfg.sc_persist_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.info("[SC-Brain] State persisted → %s", self.cfg.sc_persist_path)

    def _load(self) -> None:
        """Load weights from disk if available."""
        path = self.cfg.sc_persist_path
        if not os.path.exists(path):
            log.info("[SC-Brain] No memory found. Starting with random weights.")
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)

            w_list = payload.get("weights", [])
            if len(w_list) == self._NUM_FEATURES:
                self._weights = np.array(w_list, dtype=float)
                self._trade_count = int(payload.get("trade_count", 0))
                log.info(
                    "[SC-Brain] Memory loaded! trades=%d  weights=%s",
                    self._trade_count, self._weights,
                )
            else:
                log.warning("[SC-Brain] Weight dimension mismatch! Resetting brain.")
                self._trade_count = 0
                self._trades_since_save = 0

        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.error("[SC-Brain] Failed to load memory: %s", exc)