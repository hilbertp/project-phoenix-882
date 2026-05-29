"""Hyperliquid client.

M1 ships only the public/read pieces required by the market-data feed and the
detector loop:
  * REST `candleSnapshot` (historical candles, no auth)
  * WS subscriptions: `candle` (live bars per asset/interval)
  * REST `meta` (universe sanity-check)

The signed trading client (order placement, cancels, fills, balances) is
deferred to M3. It will live alongside this module as `signed_client.py` and
share the REST base URL from BotConfig.hyperliquid.

References:
  Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
  REST POST {rest_url}/info  with body {"type": "candleSnapshot", "req": {...}}
  WS    {ws_url}             with {"method": "subscribe", "subscription": {...}}
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

import requests
import websocket

from apps.bot.logging_setup import get_logger
from apps.bot.observability import metrics as _m

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HLCandle:
    """Mirror of Hyperliquid's candle payload, normalized to floats / int ms."""

    coin: str
    interval: str
    open_ms: int   # bar open time, ms since epoch
    close_ms: int  # bar close time (exclusive end), ms since epoch
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int

    @classmethod
    def from_payload(cls, p: dict) -> "HLCandle":
        return cls(
            coin=p["s"],
            interval=p["i"],
            open_ms=int(p["t"]),
            close_ms=int(p["T"]),
            open=float(p["o"]),
            high=float(p["h"]),
            low=float(p["l"]),
            close=float(p["c"]),
            volume=float(p["v"]),
            trade_count=int(p.get("n", 0)),
        )


class HyperliquidPublicClient:
    """Read-only HL client.

    Thread-safety: `candle_snapshot` and `meta` are safe to call from any
    thread (each call gets its own requests session call). The WS lifecycle
    methods (`subscribe_candle`, `start`, `stop`) must be driven from one
    coordinator thread.
    """

    def __init__(
        self,
        *,
        rest_url: str,
        ws_url: str,
        request_timeout_s: float = 10.0,
        error_counter=None,
    ):
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url
        self.request_timeout_s = request_timeout_s
        self.error_counter = error_counter
        self._session = requests.Session()
        self._ws_app: websocket.WebSocketApp | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_lock = threading.Lock()
        self._pending_subs: list[dict] = []
        self._open_evt = threading.Event()
        self._stop = False
        self._on_candle_cb: Callable[[HLCandle], None] | None = None
        # Per-coin last-seen open_ms; used to detect bar rollovers in the
        # WS callback so we only observe latency on TRUE new-bar messages
        # (not on in-progress refresh messages, which would otherwise log
        # the bar's age as "latency" -- meaningless and misleading).
        self._latency_last_open_ms: dict[str, int] = {}

    # --- REST -------------------------------------------------------------

    def meta(self) -> dict:
        return self._post_info({"type": "meta"})

    def candle_snapshot(
        self,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[HLCandle]:
        """Return closed candles in [start_ms, end_ms], oldest first.

        HL returns up to 5000 candles per call. Callers needing more should
        page by adjusting start_ms.
        """
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        raw = self._post_info(payload)
        return [HLCandle.from_payload(c) for c in raw]

    def _post_info(self, body: dict) -> dict | list:
        url = f"{self.rest_url}/info"
        with _m.TimeRest():
            try:
                resp = self._session.post(
                    url,
                    json=body,
                    timeout=self.request_timeout_s,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
            except Exception:
                if self.error_counter is not None:
                    self.error_counter.record("rest")
                raise

    # --- WS ---------------------------------------------------------------

    def subscribe_candle(self, coin: str, interval: str) -> None:
        """Queue a candle subscription. If the WS is already up, send it now.

        Idempotent: subscribing twice for the same (coin, interval) is a no-op
        re-send; Hyperliquid tolerates duplicate subscribe messages.
        """
        sub = {
            "method": "subscribe",
            "subscription": {"type": "candle", "coin": coin, "interval": interval},
        }
        with self._ws_lock:
            if sub not in self._pending_subs:
                self._pending_subs.append(sub)
            ws = self._ws_app
        if ws is not None and self._open_evt.is_set():
            try:
                ws.send(json.dumps(sub))
            except Exception:
                log.warning("ws send subscribe failed; will resend on reconnect",
                            extra={"coin": coin, "interval": interval})

    def start(self, on_candle: Callable[[HLCandle], None]) -> None:
        """Open the WS and start dispatching candle messages to `on_candle`."""
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return
        self._stop = False
        self._on_candle_cb = on_candle
        self._ws_thread = threading.Thread(
            target=self._run_ws_loop, name="hl-ws", daemon=True
        )
        self._ws_thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop = True
        with self._ws_lock:
            ws = self._ws_app
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=timeout_s)
        self._ws_thread = None
        self._open_evt.clear()

    def wait_open(self, timeout_s: float = 10.0) -> bool:
        return self._open_evt.wait(timeout_s)

    def _run_ws_loop(self) -> None:
        backoff = 1.0
        # If a connection stayed open for at least this long we treat the next
        # disconnect as transient and reset the backoff. Without this the
        # backoff doubles on every disconnect for the lifetime of the process,
        # so a long-lived connection that briefly drops waits ~30s before
        # retrying instead of the intended ~1s.
        STABLE_THRESHOLD_S = 60.0
        while not self._stop:
            connected_at = time.monotonic()
            try:
                self._open_one_connection()
            except Exception as exc:
                log.warning("ws loop crashed; reconnecting",
                            extra={"err": str(exc)})
            connection_duration = time.monotonic() - connected_at
            if self._stop:
                break
            if connection_duration >= STABLE_THRESHOLD_S:
                backoff = 1.0
            time.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2.0, 30.0)

    def _open_one_connection(self) -> None:
        def on_open(ws: websocket.WebSocketApp) -> None:
            log.info("hl ws open")
            self._open_evt.set()
            with self._ws_lock:
                subs = list(self._pending_subs)
            for sub in subs:
                ws.send(json.dumps(sub))

        def on_message(ws: websocket.WebSocketApp, message: str) -> None:
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                return
            ch = msg.get("channel")
            if ch == "candle":
                data = msg.get("data") or {}
                try:
                    candle = HLCandle.from_payload(data)
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("candle parse failed", extra={"err": str(exc)})
                    return
                # Observe latency ONLY on bar rollover. In-progress
                # candle updates would otherwise record the bar's age
                # (potentially many minutes) as "latency", polluting the
                # histogram with non-events. Rollover = open_ms strictly
                # greater than the last-seen open_ms for this coin.
                last_open = self._latency_last_open_ms.get(candle.coin)
                if last_open is None or candle.open_ms > last_open:
                    self._latency_last_open_ms[candle.coin] = candle.open_ms
                    if last_open is not None and _m.M_WS_LATENCY is not None:
                        latency_ms = (time.time() * 1000.0) - candle.open_ms
                        if 0 <= latency_ms < 60_000:
                            # Only observe sane values; an extreme reading
                            # (>60s) is more likely a clock skew or stale
                            # message than a true latency event.
                            _m.M_WS_LATENCY.observe(latency_ms)
                if self._on_candle_cb is not None:
                    try:
                        self._on_candle_cb(candle)
                    except Exception:
                        log.exception("on_candle callback raised")
            elif ch == "subscriptionResponse":
                log.debug("subscription ack", extra={"resp": msg.get("data")})
            elif ch == "error":
                log.warning("ws error from server", extra={"data": msg.get("data")})

        def on_close(ws, status_code, msg) -> None:
            log.info("hl ws closed",
                     extra={"status": status_code, "msg": msg})
            self._open_evt.clear()

        def on_error(ws, error) -> None:
            log.warning("hl ws error", extra={"err": str(error)})
            if self.error_counter is not None:
                self.error_counter.record("ws")

        ws_app = websocket.WebSocketApp(
            self.ws_url,
            on_open=on_open,
            on_message=on_message,
            on_close=on_close,
            on_error=on_error,
        )
        with self._ws_lock:
            self._ws_app = ws_app
        try:
            # ping every 30s; HL closes idle connections.
            ws_app.run_forever(ping_interval=30, ping_timeout=10)
        finally:
            with self._ws_lock:
                self._ws_app = None
            self._open_evt.clear()
