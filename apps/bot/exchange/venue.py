"""Hyperliquid venue normalization: round prices/quantities to HL's grid.

HL rejects orders that violate any of:
  * qty has more decimal places than the asset's `szDecimals`
  * price has more than 5 significant figures
  * price has more than (MAX_DECIMALS - szDecimals) decimal places,
    where MAX_DECIMALS = 6 for perps and 8 for spot
  * order notional below the venue's min (currently ~$10 for perps)

We normalize at the OrderManager seam so:
  - Tests for the FSM stay untouched (FSM operates on raw level prices).
  - The signed client stays a thin transport — it does not silently mutate.
  - One source of truth (this module) covers ALL place_* paths.
"""
from __future__ import annotations

import math

# Hyperliquid's MAX_DECIMALS per market class.
PERP_MAX_DECIMALS = 6
SPOT_MAX_DECIMALS = 8
PRICE_MAX_SIG_FIGS = 5


def round_qty_down(qty: float, sz_decimals: int) -> float:
    """Truncate qty to `sz_decimals` places (round toward zero).

    Round-DOWN so realized risk never exceeds the intended 1R from
    over-rounding upward at the precision boundary.
    """
    if qty <= 0:
        return 0.0
    scale = 10 ** sz_decimals
    return int(qty * scale) / scale


def round_price(
    price: float, sz_decimals: int, *, is_perp: bool = True,
) -> float:
    """Round `price` to the strictest of HL's two rules.

    Returns the nearest valid HL price (standard round-half-to-even via
    Python's `round`), since prices represent levels, not risk — slight
    rounding either direction is fine.
    """
    if price <= 0:
        return price
    max_decimals_total = (PERP_MAX_DECIMALS if is_perp else SPOT_MAX_DECIMALS)
    max_decimals_per_sz = max(0, max_decimals_total - sz_decimals)
    # Significant figures restrict trailing decimals: a price >= 10^k uses
    # at least k+1 leading digits, leaving (5 - (k+1)) digits for decimals.
    integer_digits = int(math.floor(math.log10(price))) + 1
    sig_fig_decimals = max(0, PRICE_MAX_SIG_FIGS - integer_digits)
    decimals = min(max_decimals_per_sz, sig_fig_decimals)
    return round(price, decimals)


def meets_min_notional(qty: float, price: float, min_notional_usd: float) -> bool:
    """True if qty * price >= the venue's minimum notional."""
    return qty * price >= min_notional_usd
