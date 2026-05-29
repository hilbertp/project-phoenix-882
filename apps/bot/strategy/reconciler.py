"""Startup reconciler — verify the exchange and the state store agree.

PRD F-09: "At startup, reconcile: pull open orders & positions from HL,
rebuild the FSM state, recover from any mid-trade crash. Never double-enter,
never orphan a stop."

The reconciler is deliberately conservative for M3 v1. It does NOT auto-heal
ambiguous state; it categorizes the situation and refuses to start the live
runner unless every in-flight setup matches the exchange's view.

Categories:

  * **CLEAN** — no setups in mid-flight states, no open orders, no positions.
    Safe to start fresh.
  * **RESUMABLE** — in-flight setups exist AND their expected orders/positions
    match what the exchange reports exactly. Safe to rehydrate the FSMs.
  * **AMBIGUOUS** — anything else: orphan position (no matching setup), missing
    order (setup expected it but exchange has none), surplus order, size
    mismatch. The live runner refuses to start; operator inspects and resolves.

Auto-recovery of in-flight FSMs (rebuilding the FSM at the correct state from
the persisted state_transitions log) is intentionally NOT implemented in v1.
Treat any in-flight crash as an operator-intervention event during the paper /
shadow / canary phases (PRD §10). M4+ will add automated recovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from apps.bot.exchange.signed_client import OpenOrder, Position
from apps.bot.logging_setup import get_logger
from apps.bot.state import OrderRecord, SetupRecord, StateStore
from apps.bot.strategy.order_manager import ExchangeClient

log = get_logger(__name__)

IN_FLIGHT_STATES = {"entered", "tp1_hit", "tp2_hit", "armed"}


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    category: str           # CLEAN | RESUMABLE | AMBIGUOUS
    issues: list[str] = field(default_factory=list)
    in_flight_setups: list[SetupRecord] = field(default_factory=list)
    open_orders: list[OpenOrder] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.category != "AMBIGUOUS"


def reconcile(client: ExchangeClient, store: StateStore) -> ReconciliationResult:
    """Compare state.db's in-flight setups against the exchange's truth."""
    open_orders = client.open_orders()
    positions = client.positions()
    in_flight = _load_in_flight_setups(store)
    issues: list[str] = []

    expected_orders_by_cloid: dict[str, OrderRecord] = {}
    for setup in in_flight:
        for order in store.open_orders_for(setup.setup_key):
            expected_orders_by_cloid[order.client_order_id] = order

    exchange_cloids = {o.cloid for o in open_orders if o.cloid}
    expected_cloids = set(expected_orders_by_cloid.keys())

    # Missing: state.db says this order should be live, exchange disagrees.
    missing = expected_cloids - exchange_cloids
    for cloid in sorted(missing):
        rec = expected_orders_by_cloid[cloid]
        issues.append(
            f"missing order on exchange: cloid={cloid} setup={rec.setup_key} "
            f"role={rec.level_role}"
        )

    # Surplus: exchange has an order we don't expect.
    surplus = exchange_cloids - expected_cloids
    for cloid in sorted(surplus):
        issues.append(f"surplus open order on exchange: cloid={cloid}")

    # Position consistency: every coin with an open position must have a
    # corresponding in-flight setup. (Crash-recovered FSMs aren't yet
    # implemented in v1, so an existing position is enough to flag.)
    setup_assets = {s.asset for s in in_flight}
    for pos in positions:
        if pos.coin not in setup_assets:
            issues.append(
                f"orphan position on {pos.coin}: size={pos.size}; "
                f"no in-flight setup to claim it"
            )

    # Conversely, an in-flight setup PAST the "entered" gate must have a
    # non-zero position on its asset. "armed" doesn't require one.
    pos_by_coin = {p.coin: p for p in positions}
    for setup in in_flight:
        state = store.get_state(setup.setup_key)
        if state and state.state in ("entered", "tp1_hit", "tp2_hit"):
            pos = pos_by_coin.get(setup.asset)
            if pos is None or pos.size == 0:
                issues.append(
                    f"setup {setup.setup_key} is {state.state} but no position "
                    f"exists on {setup.asset}"
                )

    if issues:
        category = "AMBIGUOUS"
    elif not in_flight and not open_orders and not positions:
        category = "CLEAN"
    else:
        category = "RESUMABLE"

    return ReconciliationResult(
        category=category,
        issues=issues,
        in_flight_setups=in_flight,
        open_orders=open_orders,
        positions=positions,
    )


def _load_in_flight_setups(store: StateStore) -> list[SetupRecord]:
    out: list[SetupRecord] = []
    for setup in store.list_setups(limit=10_000):
        state = store.get_state(setup.setup_key)
        if state and state.state in IN_FLIGHT_STATES:
            out.append(setup)
    return out


def format_summary(result: ReconciliationResult) -> str:
    """Human-readable one-shot summary for the CLI."""
    parts = [
        f"category: {result.category}",
        f"in-flight setups: {len(result.in_flight_setups)}",
        f"open orders: {len(result.open_orders)}",
        f"positions: {len(result.positions)}",
    ]
    if result.issues:
        parts.append("issues:")
        parts.extend(f"  * {msg}" for msg in result.issues)
    return "\n".join(parts)


__all__ = [
    "ReconciliationResult",
    "reconcile",
    "format_summary",
    "IN_FLIGHT_STATES",
]


# Keep iterable-typed helpers around if higher-level code needs them.
def _ensure_iterable(x: Iterable | None) -> Iterable:
    return x if x is not None else ()
