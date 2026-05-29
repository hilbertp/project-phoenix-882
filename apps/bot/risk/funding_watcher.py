"""Periodic funding-rate watcher.

PRD §7.2: "Adverse funding rate (per-asset, annualized) > 100% → skip new
entries on that asset."

The watcher polls HL's `meta_and_asset_ctxs` on a cadence (default once an
hour), converts per-hour funding to APY, and asks the RiskEngine to pause /
resume each asset accordingly. The pause is a `runtime_flags` row so it
survives restarts and is visible to `risk-status`.

Direction matters: funding payments flow from longs to shorts when funding
is POSITIVE (longs pay), and shorts to longs when NEGATIVE. The DB1
strategy takes BOTH longs and shorts, so we pause an asset whenever the
ABSOLUTE annualized rate is over the threshold — either direction is
adverse for half of our potential trades, and the strategy doesn't filter
by direction.

Threading: `start()` spawns a daemon thread that loops poll_once() every
`poll_interval_s` (default 3600). `stop()` signals the loop to exit.
"""
from __future__ import annotations

import threading

from apps.bot.config import RiskConfig
from apps.bot.exchange.signed_client import SignedHyperliquidClient
from apps.bot.logging_setup import get_logger
from apps.bot.observability import metrics as _m
from apps.bot.risk.engine import FUNDING_SKIP_PREFIX, RiskEngine
from apps.bot.state import StateStore

log = get_logger(__name__)

FUNDING_OBS_PREFIX = "funding_apy:"
DEFAULT_POLL_INTERVAL_S = 3600.0  # 1 hour


class FundingWatcher:
    def __init__(
        self,
        client: SignedHyperliquidClient,
        risk_engine: RiskEngine,
        store: StateStore,
        risk_cfg: RiskConfig,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        error_counter=None,
    ):
        self.client = client
        self.risk = risk_engine
        self.store = store
        self.cfg = risk_cfg
        self.poll_interval_s = poll_interval_s
        # Optional: if the operator wires this in, persistent funding-poll
        # failures contribute to the §7.3 error-rate kill threshold.
        self.error_counter = error_counter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> dict[str, float]:
        """Single observation pass: refresh skip flags, return the APY map."""
        try:
            apy_map = self.client.fetch_funding_rates_apy()
        except Exception:
            log.exception("funding-rate poll failed")
            if self.error_counter is not None:
                self.error_counter.record("rest")
            return {}
        threshold = self.cfg.adverse_funding_apy_skip
        already_paused = set(
            k[len(FUNDING_SKIP_PREFIX):]
            for k in self.store.list_flags_prefix(FUNDING_SKIP_PREFIX)
        )
        for asset, apy in apy_map.items():
            # Record the observation for visibility regardless of action.
            self.store.set_flag(
                f"{FUNDING_OBS_PREFIX}{asset}", f"{apy:.4f}",
            )
            if _m.M_FUNDING_APY is not None:
                _m.M_FUNDING_APY.set(apy, asset=asset)
            adverse = abs(apy) > threshold
            if adverse and asset not in already_paused:
                self.risk.pause_asset_funding(asset, apy)
            elif not adverse and asset in already_paused:
                self.risk.resume_asset_funding(asset)
        return apy_map

    def start(self) -> None:
        """Spawn the daemon poll loop. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="funding-watcher", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._thread = None

    def _run(self) -> None:
        log.info("funding watcher started",
                 extra={"interval_s": self.poll_interval_s})
        # `poll_once` was already called by the caller (cmd_live seeds it
        # synchronously before going live). The loop here re-polls.
        while not self._stop.is_set():
            # Wait first so we don't double-poll at startup.
            if self._stop.wait(self.poll_interval_s):
                break
            try:
                self.poll_once()
            except Exception:
                log.exception("funding watcher loop iteration failed")
        log.info("funding watcher stopped")
