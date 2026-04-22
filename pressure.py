"""
pressure.py — Adaptive risk management system.

Escalates through NORMAL → REDUCED → HIGH PRESSURE states
based on consecutive losses and loss rate. Reduces leverage
and risk percentage, and pauses trading during cooldown.
"""

from __future__ import annotations

import time
from enum import Enum, auto

from config import BotConfig
from logger import get_logger
from performance import PerformanceTracker

log = get_logger("pressure")


# ─────────────────────────────────────────────────────────────────────────────
# STATE ENUM
# ─────────────────────────────────────────────────────────────────────────────

class PressureState(Enum):
    NORMAL  = auto()
    REDUCED = auto()
    HIGH    = auto()


# ─────────────────────────────────────────────────────────────────────────────
# MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class PressureManager:
    """
    Manages trading pressure state based on performance.
    Reduces leverage and risk on losses, pauses trading in HIGH state.
    """

    # Number of wins needed to stop panicking
    _RECOVERY_WINS_NEEDED: int = 2

    def __init__(self, cfg: BotConfig, perf: PerformanceTracker) -> None:
        self.cfg   = cfg
        self.perf  = perf
        self.state = PressureState.NORMAL

        # Timestamp when a HIGH cooldown started (0 = not in cooldown)
        self._cooldown_start: float = 0.0

        # Track consecutive wins so we can go back to NORMAL
        self._consecutive_wins_since_reduced: int = 0

    # ─────────────────────────────────────────────────────────────────────
    # EVALUATE — called after every closed trade
    # ─────────────────────────────────────────────────────────────────────

    def evaluate(self, perf: PerformanceTracker) -> None:
        """
        Update pressure state based on performance metrics.
        """
        loss_exceeds_win = perf.loss_exceeds_win
        consec_losses    = perf.consecutive_losses
        consec_threshold = self.cfg.pressure_consecutive_loss_threshold

        is_deteriorating = (
            loss_exceeds_win or
            consec_losses >= consec_threshold
        )

        prev_state = self.state

        # ── State transitions ─────────────────────────────────────────────
        if self.state == PressureState.HIGH:
            # Check if cooldown has expired
            if self._cooldown_expired():
                self.state = PressureState.REDUCED
                self._consecutive_wins_since_reduced = 0
                log.info("[PRESSURE] Cooldown expired → entering REDUCED state.")

        elif self.state == PressureState.REDUCED:
            if is_deteriorating:
                # Conditions have worsened even in REDUCED — escalate to HIGH
                self._enter_high_pressure()
            else:
                # Count consecutive wins toward recovery
                if perf.consecutive_losses == 0 and perf.total_trades > 0:
                    self._consecutive_wins_since_reduced += 1
                else:
                    self._consecutive_wins_since_reduced = 0

                if self._consecutive_wins_since_reduced >= self._RECOVERY_WINS_NEEDED:
                    self.state = PressureState.NORMAL
                    self._consecutive_wins_since_reduced = 0
                    log.info("[PRESSURE] Recovered → returning to NORMAL state.")

        else:  # NORMAL
            if is_deteriorating:
                self.state = PressureState.REDUCED
                log.warning(
                    "[PRESSURE] Performance deteriorating → REDUCED  "
                    "(loss_rate=%.1f%%  consec_losses=%d)",
                    perf.loss_rate * 100, consec_losses,
                )

        if self.state != prev_state:
            log.warning(
                "[PRESSURE] State: %s → %s",
                prev_state.name, self.state.name,
            )

    # ─────────────────────────────────────────────────────────────────────
    # QUERY METHODS — used by TradingBot before every order
    # ─────────────────────────────────────────────────────────────────────

    def allow_trading(self) -> bool:
        """
        Returns False if trading is paused (HIGH state with active cooldown).
        """
        if self.state == PressureState.HIGH:
            if self._cooldown_expired():
                # Auto-transition so we don't need to wait for a closed trade
                self.state = PressureState.REDUCED
                log.info("[PRESSURE] Cooldown expired in allow_trading() → REDUCED.")
                return True
            return False
        return True

    def effective_leverage(self) -> int:
        """Returns effective leverage (reduced during REDUCED/HIGH state)."""
        if self.state == PressureState.NORMAL:
            return self.cfg.leverage

        reduced = max(1, int(self.cfg.leverage * self.cfg.pressure_leverage_multiplier))
        log.debug("[PRESSURE] Effective leverage: %dx (state=%s)", reduced, self.state.name)
        return reduced

    def effective_risk_pct(self) -> float:
        """Returns effective risk percentage (reduced during REDUCED/HIGH state)."""
        if self.state == PressureState.NORMAL:
            return self.cfg.risk_pct

        reduced = self.cfg.risk_pct * self.cfg.pressure_risk_multiplier
        log.debug("[PRESSURE] Effective risk_pct: %.3f (state=%s)", reduced, self.state.name)
        return reduced

    def cooldown_remaining(self) -> int:
        """Returns remaining cooldown time in seconds."""
        if self.state != PressureState.HIGH or self._cooldown_start == 0:
            return 0
        elapsed = time.monotonic() - self._cooldown_start
        remaining = self.cfg.pressure_cooldown_seconds - elapsed
        return max(0, int(remaining))

    def state_label(self) -> str:
        """Returns a human-readable label for the current pressure state."""
        labels = {
            PressureState.NORMAL:  "NORMAL",
            PressureState.REDUCED: "REDUCED ⚠",
            PressureState.HIGH:    f"HIGH PRESSURE 🔴 (cd: {self.cooldown_remaining()}s)",
        }
        return labels[self.state]

    # ─────────────────────────────────────────────────────────────────────
    # INTERNALS
    # ─────────────────────────────────────────────────────────────────────

    def _enter_high_pressure(self) -> None:
        """Enter HIGH pressure state and start cooldown timer."""
        self.state            = PressureState.HIGH
        self._cooldown_start  = time.monotonic()
        log.error(
            "[PRESSURE] ⛔ HIGH PRESSURE — trading PAUSED for %ds.  "
            "Leverage and risk will be halved on resume.",
            self.cfg.pressure_cooldown_seconds,
        )

    def _cooldown_expired(self) -> bool:
        """Returns True if cooldown period has elapsed."""
        if self._cooldown_start == 0:
            return False
        elapsed = time.monotonic() - self._cooldown_start
        return elapsed >= self.cfg.pressure_cooldown_seconds