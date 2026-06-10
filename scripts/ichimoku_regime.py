#!/usr/bin/env python
"""Ichimoku regime detector v1 -- the "26-bar two-sides rule".

THE RULE, exactly as a human can check it on a TradingView chart with a
standard Ichimoku (9/26/52, displacement 26) on the 1H:

    At any bar, look back 26 bars (~one day of 1H candles):
      * if price CLOSED above the cloud at least once AND below the cloud
        at least once inside that window, the market is REPRICING
        ("transition")  ->  NO fib trades. Stand down.
      * otherwise the market is SETTLED -> fib trades are allowed.

    Settled sub-classes (informational, not part of the veto):
      bull  -- close above the cloud and the cloud is bullish (senkouA>senkouB)
      bear  -- close below the cloud and the cloud is bearish
      range -- everything else (price inside the cloud / mixed signals)

WHY THIS RULE: measured on BTC 1H Mar-May 2026 with the human-validated
executor (5m sub-bar resolution, 0.941 regime):

    6c/2x: transition fills = 31/72 trades, 25 losses, -21.8R of the
           -23.1R total bleed. Settled fills ~ breakeven.
    6c/4x: transition fills = 26/41, -14.7R. Settled fills = +7.5R/15.

The veto is evaluated AT THE FILL BAR (when 0.941 is tagged), not at leg
detection -- that is how the numbers above were measured.

v1 deliberately has ONE feature (the two-sides veto). Candidate v2 features
to test before adopting: counter-trend veto (skip deep longs in bear /
shorts in bull), flat-cloud range bonus, lookback sensitivity (13/26/52).
"""
from __future__ import annotations

TENKAN, KIJUN, SENKOU_B, DISPLACEMENT = 9, 26, 52, 26
TWO_SIDES_LOOKBACK = 26

TRANSITION = "transition"
BULL = "bull"
BEAR = "bear"
RANGE = "range"
NA = "n/a"

SETTLED = {BULL, BEAR, RANGE}


class IchimokuRegime:
    """Precomputes Ichimoku lines over a candle list; classify(i) per bar."""

    def __init__(self, candles):
        n = len(candles)
        H = [c.high for c in candles]
        L = [c.low for c in candles]
        self.close = [c.close for c in candles]

        def mid(span, i):
            if i + 1 < span:
                return None
            return (max(H[i - span + 1:i + 1]) + min(L[i - span + 1:i + 1])) / 2

        self.tenkan = [mid(TENKAN, i) for i in range(n)]
        self.kijun = [mid(KIJUN, i) for i in range(n)]
        self.mid_b = [mid(SENKOU_B, i) for i in range(n)]
        self.n = n

    def cloud(self, i):
        """(top, bottom, bullish) of the cloud ABOVE bar i -- projected
        DISPLACEMENT bars ago -- or (None, None, None) before warmup."""
        j = i - DISPLACEMENT
        if j < 0 or self.tenkan[j] is None or self.kijun[j] is None \
                or self.mid_b[j] is None:
            return None, None, None
        a = (self.tenkan[j] + self.kijun[j]) / 2
        b = self.mid_b[j]
        return max(a, b), min(a, b), a > b

    def classify(self, i) -> str:
        top, bot, bullish = self.cloud(i)
        if top is None:
            return NA
        above = below = False
        for j in range(max(0, i - TWO_SIDES_LOOKBACK), i + 1):
            t, b, _ = self.cloud(j)
            if t is None:
                continue
            if self.close[j] > t:
                above = True
            if self.close[j] < b:
                below = True
            if above and below:
                return TRANSITION
        if self.close[i] > top and bullish:
            return BULL
        if self.close[i] < bot and not bullish:
            return BEAR
        return RANGE

    def tradeable(self, i) -> bool:
        """The v1 veto: trade only when the market is settled."""
        return self.classify(i) in SETTLED
