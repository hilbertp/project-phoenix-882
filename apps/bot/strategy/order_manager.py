"""OrderManager: translates FSM events into signed exchange calls.

Owns the running FSMs in memory (keyed by setup_key) and is the only component
that writes OrderRecord rows. On each FsmEvent it:

  1. Computes the action (cloid, side, qty, price).
  2. Calls the ExchangeClient (signed-live or paper-mock — same Protocol).
  3. Persists/updates OrderRecord in the StateStore.

PRD F-10 write-ahead semantics: persist the order intent BEFORE calling the
exchange, then update with the exchange response. Reconciler at startup uses
the intent rows + open_orders() to resolve any crash mid-call.

Sizing: 1R = equity * account_risk_pct/100. Position qty = 1R / risk_per_unit.
Equity is snapshotted at OrderManager construction; restart the bot to
re-snapshot. (PRD §12: a dedicated subaccount with fixed allocation keeps
sizing stable across trades.)

This module is exchange-agnostic — it talks to `ExchangeClient` (a Protocol).
The signed HL implementation lives in apps/bot/exchange/signed_client.py; the
unit tests use a fake.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol, Sequence

from apps.bot.config import RiskConfig, StrategyConfig
from apps.bot.exchange.signed_client import OpenOrder, PlacedOrder
from apps.bot.exchange.venue import (
    meets_min_notional,
    round_price,
    round_qty_down,
)
from apps.bot.logging_setup import get_logger
from apps.bot.marketdata import BarCloseEvent
from apps.bot.observability import metrics as _m
from apps.bot.risk.engine import RiskEngine
from apps.bot.state import OrderRecord, SetupRecord, StateStore, now_iso
from apps.bot.strategy.cloid import make_cloid
from apps.bot.strategy.fsm import FibFSM, FsmEvent, FsmState, Setup
from apps.bot.strategy.levels import Levels
from apps.worker.discovery_bet_1.types import Candle

log = get_logger(__name__)


class ExchangeClient(Protocol):
    """The subset of the signed client the OrderManager uses.

    SignedHyperliquidClient implements this implicitly. Tests pass a fake.
    """

    def place_limit_post_only(
        self, coin: str, is_buy: bool, qty: float, price: float, cloid: str,
    ) -> PlacedOrder: ...

    def place_reduce_only_limit(
        self, coin: str, is_buy: bool, qty: float, price: float, cloid: str,
    ) -> PlacedOrder: ...

    def place_stop_market(
        self, coin: str, is_buy: bool, qty: float, trigger_px: float, cloid: str,
    ) -> PlacedOrder: ...

    def market_close(
        self, coin: str, qty: float, cloid: str, slippage: float = 0.05,
    ) -> PlacedOrder: ...

    def cancel(self, coin: str, cloid: str) -> dict: ...

    def open_orders(self) -> list[OpenOrder]: ...


@dataclass(slots=True)
class _ManagedSetup:
    """OrderManager's per-setup bookkeeping alongside the FSM."""

    setup: Setup
    fsm: FibFSM
    entry_qty: float          # the position size at fill (1R-sized)
    entry_cloid: str
    init_sl_cloid: str | None = None
    tp1_cloid: str | None = None
    tp2_cloid: str | None = None
    tp3_cloid: str | None = None
    be_cloid_seq: int = 0     # bumped each time we fire a software BE close
    # The asset is the FSM's setup.asset; kept here for fast routing.
    asset: str = ""


@dataclass(slots=True)
class OrderManager:
    """Bridges FsmEvents <-> signed exchange calls.

    `equity` is the trading-subaccount notional in quote currency (USDC). The
    manager assumes this is stable for the run; restart on meaningful equity
    changes.

    `qty_precision` maps asset -> szDecimals (HL's per-asset quantity
    precision). Positions are rounded DOWN to this precision so HL accepts
    the order. Missing keys default to 8 decimals (no-op rounding).
    """

    client: ExchangeClient
    store: StateStore
    strategy_cfg: StrategyConfig
    risk_cfg: RiskConfig
    equity: float
    qty_precision: dict[str, int] = field(default_factory=dict)
    # asset -> HL's per-asset maxLeverage. Empty -> default huge (no cap).
    max_leverage: dict[str, int] = field(default_factory=dict)
    # Optional account-level pre-flight. None -> permissive (legacy / tests).
    risk_engine: RiskEngine | None = None
    _active: dict[str, _ManagedSetup] = field(default_factory=dict)

    # --- public API ------------------------------------------------------

    def arm_setup(
        self, setup: Setup, history: Sequence[Candle] = (),
    ) -> _ManagedSetup | None:
        """Create an FSM for this setup and place the entry order.

        Returns the managed setup, or None if degenerate / risk-limited / the
        setup already concluded during the detection-to-arm gap.

        ATR-zigzag detection lags: when a leg finalizes at bar T, its terminal
        sits at bar T-K (the detector needs K bars of counter-move). The
        `history` argument lets the caller pass candles[term_idx+1:T+1] so we
        can dry-walk the FSM through that gap. If the FSM transitions out of
        ARMED during the walk, we KNOW the live exchange already moved past
        our entry (or invalidated the setup), and arming a fresh limit order
        now would either fill at a stale price or never fill at all — so we
        refuse and log it.
        """
        # Account-level pre-flight (PRD §7.2). Done FIRST so we don't even
        # construct the FSM if the bot is halted / over limit.
        if self.risk_engine is not None:
            decision = self.risk_engine.can_arm(setup)
            if not decision.allowed:
                log.info(
                    "risk engine refused arm",
                    extra={"setup_key": _key(setup),
                           "asset": setup.asset,
                           "reason": decision.reason,
                           "payload": decision.payload},
                )
                self.store.upsert_setup(SetupRecord(
                    setup_key=_key(setup), asset=setup.asset,
                    direction=setup.direction,
                    parent_ts=setup.parent_ts,
                    parent_price=setup.parent_price,
                    term_ts=setup.term_ts, term_price=setup.term_price,
                    detector_min_bars=0, detector_mult=0.0,
                    detected_at=now_iso(),
                ))
                self.store.set_state(_key(setup), "risk_blocked", {
                    "reason": decision.reason,
                    "observation": decision.payload,
                })
                return None

        fsm = FibFSM(setup, self.strategy_cfg)
        if fsm.state == FsmState.DEGENERATE:
            log.warning("degenerate setup ignored",
                        extra={"setup_key": _key(setup)})
            return None
        # Dry-walk: the events emitted here are observational only -- we do
        # NOT dispatch them to the exchange. We just check the resulting
        # state to decide whether arming live is still meaningful.
        for c in history:
            fsm.on_bar(c)
            if fsm.finished or fsm.state != FsmState.ARMED:
                log.info(
                    "setup already moved past ARMED during detection gap; "
                    "refusing to arm live",
                    extra={
                        "setup_key": _key(setup),
                        "history_bars": len(history),
                        "fsm_state": fsm.state.value,
                        "fsm_status": fsm.status,
                    },
                )
                # Persist the outcome so the operator sees it.
                self.store.upsert_setup(SetupRecord(
                    setup_key=_key(setup), asset=setup.asset,
                    direction=setup.direction,
                    parent_ts=setup.parent_ts, parent_price=setup.parent_price,
                    term_ts=setup.term_ts, term_price=setup.term_price,
                    detector_min_bars=0, detector_mult=0.0,
                    detected_at=now_iso(),
                ))
                self.store.set_state(_key(setup), "missed", {
                    "reason": "detection_gap",
                    "fsm_state": fsm.state.value,
                    "fsm_status": fsm.status,
                })
                return None
        qty = self._size_position(fsm.levels, setup.asset)
        if qty <= 0:
            log.warning(
                "zero or below-precision position; refusing to arm",
                extra={"setup_key": _key(setup),
                       "asset": setup.asset,
                       "risk_per_unit": fsm.levels.risk_per_unit,
                       "qty": qty},
            )
            return None
        # Pre-flight: HL rejects orders below its min notional. Refuse to arm
        # rather than ship a doomed order to the exchange.
        entry_price = self._venue_price(setup.asset, fsm.levels.entry)
        if not meets_min_notional(qty, entry_price,
                                  self.risk_cfg.min_notional_usd):
            log.warning(
                "below min notional; refusing to arm",
                extra={"setup_key": _key(setup), "asset": setup.asset,
                       "qty": qty, "entry_price": entry_price,
                       "min_notional_usd": self.risk_cfg.min_notional_usd,
                       "notional": qty * entry_price},
            )
            return None
        # Pre-flight: leverage cap. PRD §7.1 requires the strategy's 1.05
        # stop to sit INSIDE the exchange-imposed liquidation. A small leg
        # (tight risk_per_unit) yields a large qty and may push notional
        # past `equity * maxLeverage[asset]` -- HL would then reject the
        # order or, worse, liquidate before our SL fires.
        notional = qty * entry_price
        cap_lev = self.max_leverage.get(setup.asset)
        if cap_lev is not None:
            notional_cap = self.equity * cap_lev
            if notional > notional_cap:
                log.warning(
                    "notional exceeds leverage cap; refusing to arm",
                    extra={"setup_key": _key(setup), "asset": setup.asset,
                           "qty": qty, "entry_price": entry_price,
                           "notional": notional,
                           "max_leverage": cap_lev,
                           "notional_cap": notional_cap},
                )
                return None
        # FK-required: ensure the setup exists in the store before any orders
        # reference it. Detector-driven flows have already upserted; arming
        # directly (e.g. from a test) hadn't, hence the explicit upsert here.
        self.store.upsert_setup(SetupRecord(
            setup_key=_key(setup), asset=setup.asset, direction=setup.direction,
            parent_ts=setup.parent_ts, parent_price=setup.parent_price,
            term_ts=setup.term_ts, term_price=setup.term_price,
            detector_min_bars=0, detector_mult=0.0,
            detected_at=now_iso(),
        ))
        self.store.set_state(_key(setup), "armed", {"qty": qty})
        managed = _ManagedSetup(
            setup=setup, fsm=fsm, entry_qty=qty,
            entry_cloid=make_cloid(_key(setup), "entry"),
            asset=setup.asset,
        )
        self._active[_key(setup)] = managed
        if _m.M_ARMED_ENTRIES is not None:
            _m.M_ARMED_ENTRIES.inc(asset=setup.asset)
        for ev in fsm.events:
            self._dispatch(managed, ev)
        return managed

    def on_bar_close(self, event: BarCloseEvent) -> None:
        """Drive every FSM whose asset matches with this bar's close."""
        if not event.candles:
            return
        latest = event.candles[-1]
        finished: list[str] = []
        for key, managed in self._active.items():
            if managed.asset != event.asset:
                continue
            if managed.fsm.finished:
                finished.append(key)
                continue
            new_events = managed.fsm.on_bar(latest)
            for ev in new_events:
                self._dispatch(managed, ev)
            if managed.fsm.finished:
                finished.append(key)
        for key in finished:
            self._active.pop(key, None)

    def active(self) -> dict[str, _ManagedSetup]:
        return dict(self._active)

    def refresh_equity(self, new_equity: float) -> None:
        """Re-snapshot the equity used for 1R sizing on subsequent arms.

        Existing in-flight setups keep their original sizing -- changing
        position size mid-trade is out of scope for v1. PRD §12 calls for a
        dedicated subaccount with fixed allocation, so equity should drift
        only with realized PnL; the live runner is responsible for choosing a
        refresh cadence (e.g. once per UTC day) that matches that assumption.
        """
        if new_equity <= 0:
            log.warning("refresh_equity ignored: non-positive value",
                        extra={"requested": new_equity})
            return
        log.info("equity refreshed",
                 extra={"old": self.equity, "new": new_equity})
        self.equity = new_equity

    # --- dispatch table --------------------------------------------------

    def _dispatch(self, managed: _ManagedSetup, ev: FsmEvent) -> None:
        kind = ev.kind
        if kind == "place_entry":
            self._place_entry(managed)
        elif kind == "place_initial_sl":
            self._place_initial_sl(managed)
        elif kind == "place_tp1":
            self._place_tp(managed, "tp1", managed.fsm.levels.tp1,
                           self.strategy_cfg.tp1_size)
        elif kind == "place_tp2":
            self._place_tp(managed, "tp2", managed.fsm.levels.tp2,
                           self.strategy_cfg.tp2_size)
        elif kind == "place_tp3":
            self._place_tp(managed, "tp3", managed.fsm.levels.tp3,
                           self.strategy_cfg.tp3_size)
        elif kind == "cancel_entry":
            self._cancel_if_known(managed, managed.entry_cloid, "entry")
        elif kind == "cancel_initial_sl":
            self._cancel_if_known(managed, managed.init_sl_cloid, "init_sl")
        elif kind == "fill_entry":
            # FSM thinks we're filled. In live mode the exchange will confirm
            # via the order response or a fill WS message. For M3 v1 we trust
            # the FSM's view; richer fill reconciliation lands in M4.
            self.store.set_state(_key(managed.setup), "entered",
                                 {"price": ev.price})
            # Transition the gauges: this setup was armed (limit resting),
            # now it's an open position.
            if _m.M_ARMED_ENTRIES is not None:
                _m.M_ARMED_ENTRIES.dec(asset=managed.asset)
            if _m.M_OPEN_POSITIONS is not None:
                _m.M_OPEN_POSITIONS.inc(asset=managed.asset)
        elif kind == "tp1_hit":
            self.store.set_state(_key(managed.setup), "tp1_hit",
                                 {"realized_r": managed.fsm.realized_r})
        elif kind == "tp2_hit":
            self.store.set_state(_key(managed.setup), "tp2_hit",
                                 {"realized_r": managed.fsm.realized_r})
        elif kind in ("tp3_hit", "initial_sl_hit"):
            # Outcome-bearing events. The "done" event that immediately
            # follows carries the canonical terminal status; we let it write
            # the final state so setup_states.state ends up as the explicit
            # terminal name (e.g. "tp3_full", "wipeout") rather than a
            # generic "done" with the status hidden in the payload.
            pass
        elif kind == "be_stop_close":
            # FSM has decided to scratch the remainder at break-even. Fire a
            # software market close (the exchange-side SL was already cancelled
            # at TP1 to avoid wick-based double-stop). The FSM state has
            # already advanced to DONE by this point, so read the pre-transition
            # phase from the event payload to size the close correctly.
            phase = (ev.payload or {}).get("phase", "tp1_hit")
            self._fire_be_market_close(managed, phase)
        elif kind == "done":
            payload = ev.payload or {}
            # Final state is the FSM's terminal status string (wipeout,
            # tp1_then_scratch, tp2_then_scratch, tp3_full, no_trigger,
            # no_entry, degenerate, open). Querying terminal states no longer
            # requires parsing the payload.
            terminal = payload.get("status") or "done"
            realized_r = payload.get(
                "realized_r", managed.fsm.realized_r,
            )
            self.store.set_state(
                _key(managed.setup), terminal,
                {"realized_r": realized_r},
            )
            # Observability hooks — decrement whichever gauge bucket
            # this setup was in. fill_entry already moved armed -> open
            # for setups that actually triggered, so terminal touches
            # OPEN. Setups that never triggered (no_trigger / no_entry /
            # degenerate) decrement ARMED instead.
            is_trade = terminal in (
                "wipeout", "tp1_then_scratch",
                "tp2_then_scratch", "tp3_full",
            )
            if is_trade:
                if _m.M_OPEN_POSITIONS is not None:
                    _m.M_OPEN_POSITIONS.dec(asset=managed.asset)
            else:
                if _m.M_ARMED_ENTRIES is not None:
                    _m.M_ARMED_ENTRIES.dec(asset=managed.asset)
            if is_trade:
                if _m.M_TRADES_TOTAL is not None:
                    _m.M_TRADES_TOTAL.inc(
                        asset=managed.asset, outcome=terminal,
                    )
                if _m.M_REALIZED_R is not None and realized_r:
                    _m.M_REALIZED_R.inc(realized_r, asset=managed.asset)

    # --- order placement helpers -----------------------------------------

    def _place_entry(self, m: _ManagedSetup) -> None:
        lvl = m.fsm.levels
        is_buy = m.fsm.up
        price = self._venue_price(m.asset, lvl.entry)
        self._record_intent(m, m.entry_cloid, "entry", is_buy,
                            m.entry_qty, price)
        try:
            resp = self.client.place_limit_post_only(
                coin=m.asset, is_buy=is_buy, qty=m.entry_qty,
                price=price, cloid=m.entry_cloid,
            )
        except Exception:
            log.exception("place_entry failed",
                          extra={"setup_key": _key(m.setup)})
            self._mark_order_status(m.entry_cloid, "rejected")
            return
        self._mark_order_status(m.entry_cloid, resp.status,
                                exchange_order_id=str(resp.exchange_order_id)
                                if resp.exchange_order_id else None)

    def _place_initial_sl(self, m: _ManagedSetup) -> None:
        lvl = m.fsm.levels
        # Initial stop closes the position, so it sells if we're long and buys
        # if we're short.
        is_buy = not m.fsm.up
        cloid = make_cloid(_key(m.setup), "init_sl")
        m.init_sl_cloid = cloid
        trigger_px = self._venue_price(m.asset, lvl.init_sl)
        self._record_intent(m, cloid, "init_sl", is_buy,
                            m.entry_qty, trigger_px)
        try:
            resp = self.client.place_stop_market(
                coin=m.asset, is_buy=is_buy, qty=m.entry_qty,
                trigger_px=trigger_px, cloid=cloid,
            )
        except Exception:
            log.exception("place_initial_sl failed",
                          extra={"setup_key": _key(m.setup)})
            self._mark_order_status(cloid, "rejected")
            return
        self._mark_order_status(cloid, resp.status,
                                exchange_order_id=str(resp.exchange_order_id)
                                if resp.exchange_order_id else None)

    def _place_tp(self, m: _ManagedSetup, role: str, price: float,
                  size_fraction: float) -> None:
        # TP qty inherits the asset's szDecimals from the entry_qty already
        # being rounded; multiplying by a fractional size and re-rounding
        # keeps it valid on the HL grid.
        decimals = self.qty_precision.get(m.asset, 8)
        qty = round_qty_down(m.entry_qty * size_fraction, decimals)
        if qty <= 0:
            log.warning(
                "tp partial rounds to zero; skipping",
                extra={"setup_key": _key(m.setup), "role": role,
                       "entry_qty": m.entry_qty, "fraction": size_fraction},
            )
            return
        is_buy = not m.fsm.up
        cloid = make_cloid(_key(m.setup), role)
        setattr(m, f"{role}_cloid", cloid)
        venue_price = self._venue_price(m.asset, price)
        self._record_intent(m, cloid, role, is_buy, qty, venue_price)
        try:
            resp = self.client.place_reduce_only_limit(
                coin=m.asset, is_buy=is_buy, qty=qty,
                price=venue_price, cloid=cloid,
            )
        except Exception:
            log.exception("place_tp failed",
                          extra={"setup_key": _key(m.setup), "role": role})
            self._mark_order_status(cloid, "rejected")
            return
        self._mark_order_status(cloid, resp.status,
                                exchange_order_id=str(resp.exchange_order_id)
                                if resp.exchange_order_id else None)

    # Retry budget for cancellations: HL is reliable but a transient timeout
    # at the wrong moment leaves a wick-based SL alongside our software
    # BE-drag (see _dispatch be_stop_close handling). Three quick attempts is
    # plenty without slowing the bar-close path noticeably.
    _CANCEL_MAX_ATTEMPTS = 3
    _CANCEL_BACKOFF_S = 0.5

    def _cancel_if_known(self, m: _ManagedSetup, cloid: str | None,
                         role: str) -> bool:
        """Cancel an order with bounded retries. Returns True if HL accepted
        the cancel; False if every attempt failed."""
        if cloid is None:
            return True
        import time as _time
        last_exc: BaseException | None = None
        for attempt in range(1, self._CANCEL_MAX_ATTEMPTS + 1):
            try:
                self.client.cancel(coin=m.asset, cloid=cloid)
                self._mark_order_status(cloid, "cancelled")
                return True
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "cancel attempt failed",
                    extra={"setup_key": _key(m.setup), "role": role,
                           "cloid": cloid, "attempt": attempt,
                           "err": str(exc)},
                )
                if attempt < self._CANCEL_MAX_ATTEMPTS:
                    _time.sleep(self._CANCEL_BACKOFF_S * attempt)
        log.error(
            "cancel exhausted retries; downstream actions may be unsafe",
            extra={"setup_key": _key(m.setup), "role": role,
                   "cloid": cloid, "last_err": str(last_exc)},
        )
        # The DB still reflects the order as live (HL believes it lives too).
        # Caller decides whether to abort the downstream action.
        return False

    def _fire_be_market_close(self, m: _ManagedSetup, phase: str) -> None:
        """Software-side BE stop: market-close the remaining position.

        `phase` is the FSM phase BEFORE the be_stop_close transition (the FSM
        has already moved to DONE by the time we get here, so we can't read
        m.fsm.state). The FSM passes it through the event payload.
        """
        m.be_cloid_seq += 1
        cloid = make_cloid(_key(m.setup), "be_close", m.be_cloid_seq)
        remaining_fraction = self._remaining_fraction_for_phase(phase)
        decimals = self.qty_precision.get(m.asset, 8)
        qty = round_qty_down(m.entry_qty * remaining_fraction, decimals)
        if qty <= 0:
            return
        self._record_intent(m, cloid, "be_close", not m.fsm.up, qty, None)
        try:
            self.client.market_close(coin=m.asset, qty=qty, cloid=cloid)
        except Exception:
            log.exception("be_close market_close failed",
                          extra={"setup_key": _key(m.setup)})
            self._mark_order_status(cloid, "rejected")
            return
        self._mark_order_status(cloid, "filled")

    def _remaining_fraction_for_phase(self, phase: str) -> float:
        if phase == "tp1_hit":
            return 1.0 - self.strategy_cfg.tp1_size
        if phase == "tp2_hit":
            return 1.0 - self.strategy_cfg.tp1_size - self.strategy_cfg.tp2_size
        return 0.0

    # --- sizing ----------------------------------------------------------

    def _size_position(self, levels: Levels, asset: str) -> float:
        """Position qty so that the 1.05 SL is exactly 1R of equity.

        Rounded DOWN to the asset's HL szDecimals so:
          1. HL accepts the order (over-precise qty is rejected).
          2. Realized risk never exceeds 1R from over-rounding upward.
        """
        risk_dollars = self.equity * (self.risk_cfg.account_risk_pct / 100.0)
        if levels.risk_per_unit <= 0:
            return 0.0
        raw = risk_dollars / levels.risk_per_unit
        decimals = self.qty_precision.get(asset, 8)
        return round_qty_down(raw, decimals)

    def _venue_price(self, asset: str, price: float) -> float:
        """Round a strategy-computed price to HL's tick grid for this asset."""
        decimals = self.qty_precision.get(asset, 0)
        return round_price(price, decimals, is_perp=True)

    # --- state-store interaction ----------------------------------------

    def _record_intent(self, m: _ManagedSetup, cloid: str, role: str,
                       is_buy: bool, qty: float, price: float | None) -> None:
        now = now_iso()
        rec = OrderRecord(
            client_order_id=cloid,
            setup_key=_key(m.setup),
            asset=m.asset,
            side="buy" if is_buy else "sell",
            level_role=role,
            qty=qty,
            price=price,
            status="pending",
            exchange_order_id=None,
            created_at=now,
            updated_at=now,
        )
        self.store.upsert_order(rec)

    def _mark_order_status(self, cloid: str, status: str,
                            exchange_order_id: str | None = None) -> None:
        # Re-read existing row to preserve immutable fields, then upsert with
        # the new status / exchange id. Map exchange-side "resting" status to
        # our internal "live" so open_orders_for() can find it again.
        if status == "resting":
            status = "live"
        existing = self.store.get_order(cloid)
        if existing is None:
            return
        updated = replace(existing, status=status,
                          exchange_order_id=exchange_order_id
                          or existing.exchange_order_id,
                          updated_at=now_iso())
        self.store.upsert_order(updated)


def _key(setup: Setup) -> str:
    return f"{setup.asset}|{setup.direction}|{setup.parent_ts}|{setup.term_ts}"
