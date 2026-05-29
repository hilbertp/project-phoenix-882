"""Sliding-window error counter.

PRD §7.3: "repeated WS/REST errors (> 10 consecutive in 60s)" triggers
the kill switch. "Consecutive" here means "within the rolling window";
true wall-clock consecutivity is impractical when errors arrive from
multiple threads on different transports.

The counter tracks timestamps per `kind` (e.g. "rest", "ws", "sign") in
a deque. On each `record()`, expired entries are evicted; if the size
crosses `threshold`, an `on_trip(kind, count)` callback fires AT MOST
ONCE per kind until `reset(kind)` is called (or `reset_all()`).

Thread-safe via a single `threading.Lock`. The bot writes from any
thread (WS callback, REST helpers, signed-client wrapper); the kill-
switch callback is invoked synchronously from the writer's thread.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque

from apps.bot.logging_setup import get_logger
from apps.bot.observability import metrics as _m

log = get_logger(__name__)


class ErrorCounter:
    def __init__(
        self,
        *,
        threshold: int = 10,
        window_s: float = 60.0,
        on_trip: Callable[[str, int], None] | None = None,
    ):
        self.threshold = threshold
        self.window_s = window_s
        self._on_trip = on_trip
        self._lock = threading.Lock()
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._tripped: set[str] = set()

    def record(self, kind: str, *, now: float | None = None) -> None:
        """Record one error of `kind`. May fire `on_trip` if threshold crossed."""
        t = now if now is not None else time.monotonic()
        fired_kind: str | None = None
        fired_count = 0
        with self._lock:
            q = self._events[kind]
            q.append(t)
            cutoff = t - self.window_s
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.threshold and kind not in self._tripped:
                self._tripped.add(kind)
                fired_kind = kind
                fired_count = len(q)
        if _m.M_ERRORS is not None:
            _m.M_ERRORS.inc(kind=kind)
        if fired_kind is not None:
            log.error(
                "error-rate threshold crossed",
                extra={"kind": fired_kind, "count": fired_count,
                       "threshold": self.threshold,
                       "window_s": self.window_s},
            )
            if self._on_trip is not None:
                try:
                    self._on_trip(fired_kind, fired_count)
                except Exception:
                    log.exception("error_counter on_trip handler raised")

    def reset(self, kind: str) -> None:
        with self._lock:
            self._tripped.discard(kind)
            self._events.pop(kind, None)

    def reset_all(self) -> None:
        with self._lock:
            self._tripped.clear()
            self._events.clear()

    def current_count(self, kind: str, *, now: float | None = None) -> int:
        t = now if now is not None else time.monotonic()
        with self._lock:
            q = self._events.get(kind)
            if q is None:
                return 0
            cutoff = t - self.window_s
            while q and q[0] < cutoff:
                q.popleft()
            return len(q)

    def is_tripped(self, kind: str) -> bool:
        with self._lock:
            return kind in self._tripped
