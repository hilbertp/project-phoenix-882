"""Market-data feed and bar-close stream.

Owns a rolling per-asset buffer of CLOSED 1H candles. Backfills on start via
REST, then updates from the WS candle channel. Emits a `BarCloseEvent` to
subscribers whenever a bar rolls over (the previous bar transitions from
in-progress to closed).

State model per asset:
  * `_buffers[asset]`        — deque of CLOSED candles only, oldest to newest.
  * `_last_open_ms[asset]`   — open_ms of the bar we're currently tracking
                                as "in progress" (or, before any WS message,
                                of the last backfilled closed bar).
  * `_in_progress[asset]`    — the freshest snapshot of the in-progress bar
                                we've seen from WS. None until the first WS
                                message for this asset.

A genuine bar rollover (WS message with open_ms > _last_open_ms) appends the
stored `_in_progress` snapshot to the closed-bars buffer and emits a
BarCloseEvent. If `_in_progress` is None (the very first WS message after
backfill), the rollover doesn't emit a spurious close event for the
already-closed backfilled bar.

Threading model: the HL WS callback runs on the WS thread. We hold a small
per-asset lock around the buffer mutation, then dispatch subscriber callbacks
synchronously. With 7 assets and 1H bars rolling once per hour each, this is
trivially safe; if we ever push to lower timeframes we should move dispatch
onto a queue + worker thread.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from apps.bot.exchange.hyperliquid import HLCandle, HyperliquidPublicClient
from apps.bot.logging_setup import get_logger
from apps.worker.discovery_bet_1.types import Candle

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BarCloseEvent:
    asset: str
    interval: str
    closed_open_ms: int     # the bar that just closed
    candles: tuple[Candle, ...]  # rolling buffer snapshot, oldest first


def hl_to_worker_candle(c: HLCandle) -> Candle:
    """Convert an HL candle to the worker package's Candle dataclass.

    Source timestamp is the bar's open in UTC, ISO 8601 without timezone suffix
    (matching the existing CSV format consumed by the backtest scripts).
    """
    ts = datetime.fromtimestamp(c.open_ms / 1000, tz=timezone.utc)
    return Candle(
        source_timestamp=ts.strftime("%Y-%m-%dT%H:%M:%S"),
        open=c.open,
        high=c.high,
        low=c.low,
        close=c.close,
        volume=c.volume,
    )


_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "12h": 43_200_000, "1d": 86_400_000,
}


def interval_to_ms(interval: str) -> int:
    if interval not in _INTERVAL_MS:
        raise ValueError(f"unknown interval {interval!r}")
    return _INTERVAL_MS[interval]


class MarketDataFeed:
    """Per-universe market-data fanout.

    Usage:
        feed = MarketDataFeed(client, assets=["BTC", "ETH"], interval="1h",
                              buffer_size=2000)
        feed.subscribe(my_callback)        # callback(BarCloseEvent)
        feed.backfill()                    # blocks; pulls history via REST
        feed.start_live()                  # opens the WS stream
        ...
        feed.stop()
    """

    def __init__(
        self,
        client: HyperliquidPublicClient,
        *,
        assets: Iterable[str],
        interval: str = "1h",
        buffer_size: int = 2000,
    ):
        self.client = client
        self.assets: tuple[str, ...] = tuple(assets)
        self.interval = interval
        self.buffer_size = buffer_size
        self._buffers: dict[str, deque[Candle]] = {
            a: deque(maxlen=buffer_size) for a in self.assets
        }
        self._last_open_ms: dict[str, int] = {}
        self._in_progress: dict[str, Candle] = {}
        self._locks: dict[str, threading.Lock] = {
            a: threading.Lock() for a in self.assets
        }
        self._subs: list[Callable[[BarCloseEvent], None]] = []
        self._started = False

    # --- subscription API -------------------------------------------------

    def subscribe(self, cb: Callable[[BarCloseEvent], None]) -> None:
        self._subs.append(cb)

    def buffer(self, asset: str) -> tuple[Candle, ...]:
        with self._locks[asset]:
            return tuple(self._buffers[asset])

    # --- lifecycle --------------------------------------------------------

    def backfill(self) -> None:
        """REST-pull the most recent `buffer_size` closed candles per asset."""
        interval_ms = interval_to_ms(self.interval)
        # Time-align to the start of the current bar so we only grab CLOSED bars.
        now_ms = int(time.time() * 1000)
        current_bar_open = (now_ms // interval_ms) * interval_ms
        end_ms = current_bar_open - 1  # last ms of the previous bar
        start_ms = end_ms - self.buffer_size * interval_ms
        for asset in self.assets:
            try:
                candles = self.client.candle_snapshot(
                    asset, self.interval, start_ms, end_ms
                )
            except Exception:
                log.exception("backfill failed", extra={"asset": asset})
                continue
            with self._locks[asset]:
                self._buffers[asset].clear()
                for hlc in candles:
                    self._buffers[asset].append(hl_to_worker_candle(hlc))
                if candles:
                    self._last_open_ms[asset] = candles[-1].open_ms
            log.info("backfill complete",
                     extra={"asset": asset, "bars": len(candles)})

    def start_live(self) -> None:
        """Open the WS and subscribe to candles for every asset."""
        if self._started:
            return
        self._started = True
        self.client.start(on_candle=self._on_candle)
        # Subscribe queues until the WS opens; the public client flushes
        # pending subs on connect.
        for asset in self.assets:
            self.client.subscribe_candle(asset, self.interval)

    def stop(self) -> None:
        self.client.stop()
        self._started = False

    # --- WS callback ------------------------------------------------------

    def _on_candle(self, hlc: HLCandle) -> None:
        if hlc.coin not in self._buffers:
            return  # subscription leaked through for an unknown asset
        if hlc.interval != self.interval:
            return
        asset = hlc.coin
        worker_c = hl_to_worker_candle(hlc)
        interval_ms = interval_to_ms(self.interval)
        events: list[BarCloseEvent] = []

        with self._locks[asset]:
            buf = self._buffers[asset]
            last = self._last_open_ms.get(asset)

            if last is None or hlc.open_ms > last:
                # Gap detection: when the incoming bar is MORE than one
                # interval ahead, we missed one or more closed bars (e.g.
                # WS disconnected through a bar boundary). REST-fetch them
                # and replay synthetic close events in order so subscribers
                # see every bar.
                if (
                    last is not None
                    and hlc.open_ms > last + interval_ms
                ):
                    gap_start = last + interval_ms
                    gap_end = hlc.open_ms - 1
                    log.warning(
                        "ws gap detected; REST-filling missed bars",
                        extra={"asset": asset, "gap_start_ms": gap_start,
                               "gap_end_ms": gap_end},
                    )
                    try:
                        gap_candles = self.client.candle_snapshot(
                            asset, self.interval, gap_start, gap_end,
                        )
                    except Exception:
                        log.exception("ws gap REST-fill failed",
                                      extra={"asset": asset})
                        gap_candles = []
                    # Promote any stored in-progress to the buffer first so
                    # the order is: in-progress-at-disconnect, then each
                    # REST-fetched missed bar.
                    in_prog = self._in_progress.get(asset)
                    if in_prog is not None:
                        buf.append(in_prog)
                        events.append(BarCloseEvent(
                            asset=asset, interval=self.interval,
                            closed_open_ms=last,
                            candles=tuple(buf),
                        ))
                    for gc in gap_candles:
                        if gc.open_ms <= (last or -1):
                            continue
                        c = hl_to_worker_candle(gc)
                        buf.append(c)
                        events.append(BarCloseEvent(
                            asset=asset, interval=self.interval,
                            closed_open_ms=gc.open_ms,
                            candles=tuple(buf),
                        ))
                    # Set up state for the now-current in-progress bar.
                    self._last_open_ms[asset] = hlc.open_ms
                    self._in_progress[asset] = worker_c
                else:
                    # Normal single-bar rollover.
                    in_prog = self._in_progress.get(asset)
                    if in_prog is not None and last is not None:
                        buf.append(in_prog)
                        events.append(BarCloseEvent(
                            asset=asset, interval=self.interval,
                            closed_open_ms=last,
                            candles=tuple(buf),
                        ))
                    self._last_open_ms[asset] = hlc.open_ms
                    self._in_progress[asset] = worker_c
            elif hlc.open_ms == last:
                # Refresh of the in-progress snapshot. No state change.
                self._in_progress[asset] = worker_c
            else:
                # Stale message — older bar arrived after a newer one. Ignore.
                return

        for event in events:
            for cb in self._subs:
                try:
                    cb(event)
                except Exception:
                    log.exception("bar-close subscriber raised",
                                  extra={"asset": asset})
