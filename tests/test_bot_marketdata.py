"""MarketDataFeed regression tests.

DEV-ONLY iteration aid — NOT part of the Codex-owned regression suite.
The authoritative contract lives in docs/db1_live_bot_acs/marketdata.md
(in particular AC-MD-02..05 which cover the two bugs documented below).

Targets two real bugs:

  1. After backfill, the first live WS message used to emit a spurious
     BarCloseEvent for the already-closed bar. The detector + OrderManager
     would re-process a stale bar as if it just closed.

  2. The buffer used to append the OPEN bar's first snapshot and then
     overwrite it on each refresh, so when the bar transitioned the buffer
     held the NEW bar's data labelled as the just-closed one. Subscribers
     received the wrong OHLC for the just-closed bar.

Both are fixed by tracking the in-progress snapshot separately from the
closed-bars buffer; this file verifies the new behavior.
"""
from __future__ import annotations

import unittest

from apps.bot.exchange.hyperliquid import HLCandle
from apps.bot.marketdata import BarCloseEvent, MarketDataFeed


class _StubClient:
    """A market-data client that exposes only candle_snapshot for tests."""

    def __init__(self, backfill_response: list[HLCandle]):
        self._backfill = backfill_response

    def candle_snapshot(self, coin, interval, start_ms, end_ms):
        return list(self._backfill)

    def start(self, on_candle):  # pragma: no cover - WS path not exercised
        pass

    def stop(self):  # pragma: no cover
        pass

    def subscribe_candle(self, coin, interval):  # pragma: no cover
        pass


def _hl(coin: str, open_ms: int, *, o=100.0, h=101.0, low=99.0, c=100.5) -> HLCandle:
    return HLCandle(
        coin=coin, interval="1h",
        open_ms=open_ms, close_ms=open_ms + 3_600_000 - 1,
        open=o, high=h, low=low, close=c, volume=1.0, trade_count=1,
    )


class MarketDataFeedFirstMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        # Three closed bars backfilled, then a WS message for the in-progress
        # bar that opens an hour after the last closed one.
        self.closed_bars = [
            _hl("BTC", 0 * 3_600_000),
            _hl("BTC", 1 * 3_600_000),
            _hl("BTC", 2 * 3_600_000),
        ]
        self.client = _StubClient(self.closed_bars)
        self.feed = MarketDataFeed(
            self.client, assets=("BTC",), interval="1h", buffer_size=100,
        )
        self.events: list[BarCloseEvent] = []
        self.feed.subscribe(self.events.append)
        self.feed.backfill()

    def test_first_live_ws_message_emits_no_close(self) -> None:
        """The bar at index 3 starts streaming after backfill. No close event."""
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000, o=200.0, h=201.0,
                                  low=199.0, c=200.5))
        self.assertEqual(self.events, [])

    def test_refresh_of_in_progress_emits_no_close(self) -> None:
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000))
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000, h=205.0))
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000, h=210.0))
        self.assertEqual(self.events, [])

    def test_real_rollover_emits_close_with_in_progress_data(self) -> None:
        # In-progress bar 3, watched while it accumulates the high.
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000,
                                  o=200.0, h=201.0, low=199.0, c=200.5))
        self.feed._on_candle(_hl("BTC", 3 * 3_600_000,
                                  o=200.0, h=215.0, low=199.0, c=212.0))
        self.assertEqual(self.events, [])

        # Bar 4 opens. Bar 3 is now closed with its FINAL snapshot (high=215).
        self.feed._on_candle(_hl("BTC", 4 * 3_600_000,
                                  o=212.5, h=213.0, low=212.0, c=212.5))
        self.assertEqual(len(self.events), 1)
        evt = self.events[0]
        self.assertEqual(evt.closed_open_ms, 3 * 3_600_000)
        just_closed = evt.candles[-1]
        # The buffer's last entry must be the freshest in-progress snapshot of
        # the just-closed bar, NOT the new bar's first snapshot.
        self.assertEqual(just_closed.high, 215.0)
        self.assertEqual(just_closed.close, 212.0)
        # Buffer must include all backfilled closed bars plus the just-closed
        # one (3 backfilled + 1 just-closed = 4).
        self.assertEqual(len(evt.candles), 4)


if __name__ == "__main__":
    unittest.main()
