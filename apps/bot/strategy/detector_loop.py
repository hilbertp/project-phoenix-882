"""Detector loop: runs the ATR-zigzag swing detector on each closed bar.

Subscribed to MarketDataFeed.BarCloseEvent. On each event, computes ATR over
the rolling Candle buffer, runs `swing_detector.clean_legs`, and persists any
newly-discovered legs to the state store.

A leg is considered NEW if its setup_key (asset|direction|parent_ts|term_ts)
has not been seen before. This makes the loop idempotent: re-running over the
same candle stream re-derives the same legs and does not duplicate them.

The loop does NOT place orders -- that arrives in M2 (FSM executor). For now
it logs every new setup and writes it to `setups` with `setup_states.state =
'detected'`. The FSM transitions to 'armed' once the executor takes ownership.
"""
from __future__ import annotations

from typing import Callable

from apps.bot.config import DetectorConfig
from apps.bot.logging_setup import get_logger
from apps.bot.marketdata import BarCloseEvent
from apps.bot.state import (
    SetupRecord,
    StateStore,
    now_iso,
    setup_key_for,
)
from apps.bot.strategy.fsm import Setup
from apps.worker.discovery_bet_1.atr import calculate_atr14
from apps.worker.discovery_bet_1.swing_detector import clean_legs
from apps.worker.discovery_bet_1.types import Candle

log = get_logger(__name__)

NewSetupCallback = Callable[[Setup, tuple[Candle, ...]], None]


class DetectorLoop:
    """Stateful subscriber to BarCloseEvent. Persists new setups, logs them.

    Optionally calls `on_new_setup(Setup, history)` for each leg the detector
    finds for the first time. `history` is the slice of candles from the leg's
    terminal-bar + 1 through the just-closed bar — the OrderManager dry-walks
    these to determine whether the live entry / abort already happened during
    the detector's lag. See OrderManager.arm_setup for details.
    """

    def __init__(
        self,
        store: StateStore,
        detector_cfg: DetectorConfig,
        on_new_setup: NewSetupCallback | None = None,
    ):
        self.store = store
        self.detector_cfg = detector_cfg
        self._on_new_setup = on_new_setup

    def on_bar_close(self, event: BarCloseEvent) -> None:
        """Run the detector on the closed candle window and persist new legs."""
        candles = list(event.candles)
        if len(candles) < self.detector_cfg.min_bars + 14:
            return  # need at least an ATR warmup + min_bars span
        atr = calculate_atr14(candles)
        legs = clean_legs(
            candles,
            atr,
            None,
            min_bars=self.detector_cfg.min_bars,
            mult=self.detector_cfg.mult,
        )
        if not legs:
            return

        detected_at = now_iso()
        new_count = 0
        for leg in legs:
            key = setup_key_for(
                event.asset, leg["direction"], leg["parent_ts"], leg["term_ts"]
            )
            rec = SetupRecord(
                setup_key=key,
                asset=event.asset,
                direction=leg["direction"],
                parent_ts=leg["parent_ts"],
                parent_price=float(leg["parent_price"]),
                term_ts=leg["term_ts"],
                term_price=float(leg["term_price"]),
                detector_min_bars=self.detector_cfg.min_bars,
                detector_mult=self.detector_cfg.mult,
                detected_at=detected_at,
            )
            is_new = self.store.upsert_setup(rec)
            if not is_new:
                continue
            self.store.set_state(key, "detected", {"source": "detector_loop"})
            new_count += 1
            log.info(
                "setup detected",
                extra={
                    "asset": event.asset,
                    "setup_key": key,
                    "direction": leg["direction"],
                    "parent_ts": leg["parent_ts"],
                    "term_ts": leg["term_ts"],
                    "parent_price": leg["parent_price"],
                    "term_price": leg["term_price"],
                },
            )
            if self._on_new_setup is not None:
                # Candles from the bar AFTER the leg's terminal through the
                # current bar. The OrderManager dry-walks these to detect
                # entries / aborts that already happened in the gap between
                # the leg's terminal and the bar where the detector finalized
                # the leg.
                term_idx = leg.get("term_idx", 0)
                history = tuple(candles[term_idx + 1:])
                try:
                    self._on_new_setup(
                        Setup(
                            asset=event.asset,
                            direction=leg["direction"],
                            parent_ts=leg["parent_ts"],
                            parent_price=float(leg["parent_price"]),
                            term_ts=leg["term_ts"],
                            term_price=float(leg["term_price"]),
                        ),
                        history,
                    )
                except Exception:
                    log.exception(
                        "on_new_setup hook raised",
                        extra={"setup_key": key},
                    )
        if new_count:
            log.info(
                "detector cycle done",
                extra={
                    "asset": event.asset,
                    "bars": len(candles),
                    "new_setups": new_count,
                    "total_legs_seen": len(legs),
                },
            )
