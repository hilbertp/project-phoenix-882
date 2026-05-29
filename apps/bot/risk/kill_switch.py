"""Kill switch — flatten everything, halt, refuse further entries.

PRD §7.3 contract:

  Triggered by:
    * operator command
    * account-level limit breach (handled by the live runner, which calls
      fire() with a structured reason)
    * repeated WS/REST errors (> 10 consecutive in 60s; tracked elsewhere)

  Action on fire:
    * cancel ALL open orders on the exchange
    * market-flat ALL open positions
    * persist a halt flag in `runtime_flags` so the RiskEngine refuses
      every subsequent `can_arm` until the operator clears it
    * log + return a structured summary

  Recovery:
    * operator runs `python -m apps.bot re-arm` to clear the halt flag
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from apps.bot.exchange.signed_client import (
    SignedHyperliquidClient,
)
from apps.bot.logging_setup import get_logger
from apps.bot.state import StateStore, now_iso
from apps.bot.strategy.cloid import make_cloid

log = get_logger(__name__)

HALT_FLAG_KEY = "halt"


@dataclass(slots=True)
class KillSwitchSummary:
    halted_at: str
    reason: str
    cancelled_orders: list[str] = field(default_factory=list)
    cancel_failures: list[str] = field(default_factory=list)
    closed_positions: list[str] = field(default_factory=list)
    close_failures: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.cancel_failures and not self.close_failures


class KillSwitch:
    """Centralized halt + flatten routine."""

    def __init__(self, client: SignedHyperliquidClient, store: StateStore):
        self.client = client
        self.store = store

    # --- halt-flag plumbing ----------------------------------------------

    def is_halted(self) -> bool:
        return self.store.get_flag(HALT_FLAG_KEY) is not None

    def halt_reason(self) -> str | None:
        return self.store.get_flag(HALT_FLAG_KEY)

    def re_arm(self) -> None:
        """Clear the halt flag. Operator-only command."""
        if not self.is_halted():
            return
        self.store.clear_flag(HALT_FLAG_KEY)
        log.warning("kill switch re-armed; bot will accept new entries again")

    # --- fire ------------------------------------------------------------

    def fire(self, reason: str) -> KillSwitchSummary:
        """Cancel all open orders, market-close all positions, set halt flag.

        Idempotent: calling fire() when already halted re-runs the flatten
        pass and keeps the original `halt_reason` (the first reason wins
        for traceability; subsequent reasons append to the log).
        """
        log.error("KILL SWITCH FIRED", extra={"reason": reason})
        existing_reason = self.halt_reason()
        if existing_reason is None:
            self.store.set_flag(HALT_FLAG_KEY, reason)
        else:
            log.warning("kill switch already halted; re-running flatten",
                        extra={"original_reason": existing_reason,
                               "new_reason": reason})

        summary = KillSwitchSummary(
            halted_at=now_iso(),
            reason=existing_reason or reason,
        )

        # 1. Cancel every open order on the exchange.
        try:
            open_orders = self.client.open_orders()
        except Exception:
            log.exception("kill switch could not list open orders")
            open_orders = []
        for order in open_orders:
            cloid = order.cloid
            if cloid is None:
                # Without a cloid we can't use our cancel API. Log and skip
                # -- but this means we left a resting order on the exchange.
                summary.cancel_failures.append(f"unknown-cloid:{order.oid}")
                log.error(
                    "open order has no cloid; cannot cancel via our API",
                    extra={"oid": order.oid, "coin": order.coin},
                )
                continue
            try:
                self.client.cancel(coin=order.coin, cloid=cloid)
                summary.cancelled_orders.append(cloid)
            except Exception as exc:
                summary.cancel_failures.append(cloid)
                log.exception("cancel failed during kill switch",
                              extra={"cloid": cloid, "coin": order.coin,
                                     "err": str(exc)})

        # 2. Market-close every open position.
        try:
            positions = self.client.positions()
        except Exception:
            log.exception("kill switch could not list positions")
            positions = []
        for pos in positions:
            qty = abs(pos.size)
            if qty <= 0:
                continue
            # Synthesize a per-kill cloid so retries are idempotent.
            cloid = make_cloid(
                f"kill|{pos.coin}|{summary.halted_at}",
                "flatten",
                int(time.time() * 1000),
            )
            try:
                self.client.market_close(coin=pos.coin, qty=qty, cloid=cloid)
                summary.closed_positions.append(pos.coin)
            except Exception as exc:
                summary.close_failures.append(pos.coin)
                log.exception("market_close failed during kill switch",
                              extra={"coin": pos.coin, "err": str(exc)})

        log.error("KILL SWITCH COMPLETE",
                  extra={"summary": _summary_extras(summary)})

        # Durable audit trail. Best-effort: never let a logging failure
        # bubble up out of the kill switch.
        try:
            self.store.record_kill_event(
                halted_at=summary.halted_at,
                reason=summary.reason,
                summary_json=json.dumps(asdict(summary)),
            )
        except Exception:
            log.exception("failed to persist kill_event row")
        return summary


def _summary_extras(s: KillSwitchSummary) -> dict:
    return {
        "halted_at": s.halted_at,
        "reason": s.reason,
        "cancelled": len(s.cancelled_orders),
        "cancel_failures": len(s.cancel_failures),
        "closed_positions": len(s.closed_positions),
        "close_failures": len(s.close_failures),
        "ok": s.ok(),
    }
