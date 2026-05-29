"""Risk engine: per-trade pre-flight enforcing PRD §7.2 account-level limits.

`RiskEngine.can_arm(setup)` is a pure decision function: it reads the state
store, applies every active limit, and returns a `RiskDecision`. The
OrderManager calls it before any work in `arm_setup`. A denied decision
becomes a `setup_states.state = "risk_blocked"` entry with the reason in
the payload — so historical investigations can see exactly why a setup
never armed.

Limits enforced (defaults from `RiskConfig`, all configurable):

  * `halt`                        — kill switch fired; refuse everything
  * `max_concurrent_positions`    — count in-flight setups across all assets
  * `max_trades_per_asset_per_day`— UTC day, count of setups detected today
  * `daily_loss_r_limit`          — sum of realized_r over today's terminals
  * `weekly_loss_r_limit`         — rolling 7-day window
  * `consecutive_loss_limit`      — count of consecutive wipeouts at the head
  * funding-skip per asset        — flag set by the funding-rate watcher

All time windows use UTC. The "today" boundary is `YYYY-MM-DDT00:00:00`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apps.bot.config import RiskConfig
from apps.bot.logging_setup import get_logger
from apps.bot.observability import metrics as _m
from apps.bot.state import StateStore
from apps.bot.strategy.fsm import Setup

log = get_logger(__name__)

# Reason strings — stable identifiers Codex tests can assert against.
REASON_HALTED = "halted"
REASON_MAX_CONCURRENT = "max_concurrent_positions"
REASON_MAX_PER_ASSET_DAY = "max_trades_per_asset_per_day"
REASON_DAILY_LOSS = "daily_loss_r_limit"
REASON_WEEKLY_LOSS = "weekly_loss_r_limit"
REASON_CONSEC_LOSS = "consecutive_loss_limit"
REASON_FUNDING_SKIP = "adverse_funding"

# Setup states that mean a position is in-flight (counted for max_concurrent).
IN_FLIGHT_STATES = ("armed", "entered", "tp1_hit", "tp2_hit")

# Setup terminal states (used for R-accounting + consecutive-loss).
TERMINAL_STATES = (
    "wipeout", "tp1_then_scratch", "tp2_then_scratch", "tp3_full",
)

FUNDING_SKIP_PREFIX = "pause_asset:"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str        # one of the REASON_* constants, or "ok"
    payload: dict      # observation that triggered the decision


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_day_start_iso(now: datetime | None = None) -> str:
    n = now or _utc_now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0
                     ).strftime("%Y-%m-%dT%H:%M:%S")


def _rolling_window_start_iso(days: int, now: datetime | None = None) -> str:
    n = now or _utc_now()
    return (n - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


class RiskEngine:
    """Stateless decision function over the state store."""

    def __init__(self, store: StateStore, risk_cfg: RiskConfig):
        self.store = store
        self.cfg = risk_cfg

    # --- public API ------------------------------------------------------

    def can_arm(self, setup: Setup) -> RiskDecision:
        """Return whether `setup` is allowed to arm now."""
        decision = self._can_arm_inner(setup)
        if not decision.allowed and _m.M_RISK_DENIALS is not None:
            _m.M_RISK_DENIALS.inc(reason=decision.reason)
        return decision

    def _can_arm_inner(self, setup: Setup) -> RiskDecision:
        # 1. Kill switch.
        if self.store.get_flag("halt") is not None:
            return RiskDecision(
                allowed=False, reason=REASON_HALTED, payload={},
            )

        # 2. Per-asset funding-skip flag.
        if self.store.get_flag(f"{FUNDING_SKIP_PREFIX}{setup.asset}") is not None:
            return RiskDecision(
                allowed=False, reason=REASON_FUNDING_SKIP,
                payload={"asset": setup.asset},
            )

        # 3. Max concurrent positions (counted across all assets).
        concurrent = self.store.count_setups_in_state(IN_FLIGHT_STATES)
        if concurrent >= self.cfg.max_concurrent_positions:
            return RiskDecision(
                allowed=False, reason=REASON_MAX_CONCURRENT,
                payload={"current": concurrent,
                         "limit": self.cfg.max_concurrent_positions},
            )

        # 4. Max trades per asset per UTC day.
        day_start = _utc_day_start_iso()
        per_asset_today = self.store.count_setups_per_asset_since(
            setup.asset, day_start,
        )
        if per_asset_today >= self.cfg.max_trades_per_asset_per_day:
            return RiskDecision(
                allowed=False, reason=REASON_MAX_PER_ASSET_DAY,
                payload={"asset": setup.asset,
                         "today": per_asset_today,
                         "limit": self.cfg.max_trades_per_asset_per_day,
                         "day_start_utc": day_start},
            )

        # 5. Daily realized loss.
        day_r = self.store.sum_realized_r_since(day_start)
        if day_r <= self.cfg.daily_loss_r_limit:
            return RiskDecision(
                allowed=False, reason=REASON_DAILY_LOSS,
                payload={"daily_r": day_r,
                         "limit": self.cfg.daily_loss_r_limit,
                         "day_start_utc": day_start},
            )

        # 6. Weekly (rolling 7-day) realized loss.
        week_start = _rolling_window_start_iso(7)
        week_r = self.store.sum_realized_r_since(week_start)
        if week_r <= self.cfg.weekly_loss_r_limit:
            return RiskDecision(
                allowed=False, reason=REASON_WEEKLY_LOSS,
                payload={"week_r": week_r,
                         "limit": self.cfg.weekly_loss_r_limit,
                         "week_start_utc": week_start},
            )

        # 7. Consecutive losses at the head of recent terminal outcomes.
        recent = self.store.recent_terminal_outcomes(
            limit=self.cfg.consecutive_loss_limit,
        )
        consec_losses = 0
        for state, _r in recent:
            if state == "wipeout":
                consec_losses += 1
            else:
                break
        if consec_losses >= self.cfg.consecutive_loss_limit:
            return RiskDecision(
                allowed=False, reason=REASON_CONSEC_LOSS,
                payload={"consecutive_losses": consec_losses,
                         "limit": self.cfg.consecutive_loss_limit},
            )

        return RiskDecision(allowed=True, reason="ok", payload={})

    # --- mutators (called by the funding watcher / kill switch) ----------

    def pause_asset_funding(self, asset: str, apy: float) -> None:
        self.store.set_flag(f"{FUNDING_SKIP_PREFIX}{asset}",
                            f"funding_apy={apy:.2f}")
        log.warning("asset paused for adverse funding",
                    extra={"asset": asset, "funding_apy": apy})

    def resume_asset_funding(self, asset: str) -> None:
        if self.store.get_flag(f"{FUNDING_SKIP_PREFIX}{asset}") is not None:
            self.store.clear_flag(f"{FUNDING_SKIP_PREFIX}{asset}")
            log.info("asset resumed (funding back in range)",
                     extra={"asset": asset})

    # --- observability helpers ------------------------------------------

    def status_snapshot(self) -> dict:
        """One-shot view of every limit currently in effect."""
        day_start = _utc_day_start_iso()
        week_start = _rolling_window_start_iso(7)
        recent = self.store.recent_terminal_outcomes(
            limit=self.cfg.consecutive_loss_limit,
        )
        consec = 0
        for state, _ in recent:
            if state == "wipeout":
                consec += 1
            else:
                break
        return {
            "halted": self.store.get_flag("halt") is not None,
            "halt_reason": self.store.get_flag("halt"),
            "concurrent_positions": self.store.count_setups_in_state(
                IN_FLIGHT_STATES,
            ),
            "max_concurrent_positions": self.cfg.max_concurrent_positions,
            "daily_realized_r": self.store.sum_realized_r_since(day_start),
            "daily_loss_r_limit": self.cfg.daily_loss_r_limit,
            "weekly_realized_r": self.store.sum_realized_r_since(week_start),
            "weekly_loss_r_limit": self.cfg.weekly_loss_r_limit,
            "consecutive_losses": consec,
            "consecutive_loss_limit": self.cfg.consecutive_loss_limit,
            "paused_assets": sorted(
                k[len(FUNDING_SKIP_PREFIX):]
                for k in self.store.list_flags_prefix(FUNDING_SKIP_PREFIX)
            ),
        }
