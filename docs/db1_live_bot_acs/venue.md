# ACs — `apps/bot/exchange/venue.py`

Hyperliquid-specific normalization (qty + price rounding, min-notional
check). All `OrderManager` placements MUST pass through these helpers; the
signed client stays a thin transport.

## AC-VENUE-01: `round_qty_down` truncates toward zero

Given `qty = 0.123456789, sz_decimals = 3`
Then `round_qty_down(qty, sz_decimals) == 0.123` (NOT 0.124).

Negative or zero `qty` returns `0.0`.

## AC-VENUE-02: `round_price` honors max sig figs

Given `price = 76717.59` and BTC's szDecimals=5 (perp)
Then `round_price(price, 5) == 76718` (5 sig figs leaves 0 decimal places).

Given `price = 0.123456` and an asset with szDecimals=2 (e.g. SOL)
Then `round_price(price, 2)` keeps up to `min(5 - integer_digits,
6 - sz_decimals)` decimals.

## AC-VENUE-03: `round_price` honors max decimals per szDecimals

Given `price = 3000.12345` and ETH's szDecimals=4 (perp)
Then `round_price(price, 4) == 3000.12`  (max decimals = 6 - 4 = 2).

## AC-VENUE-04: `round_price` does not amplify zero / negative prices

Given any non-positive input
Then the function returns the input unchanged. (Defensive — strategy code
should never pass zero, but normalization must never invent a price.)

## AC-VENUE-05: `meets_min_notional` strict comparison

Given `qty = 0.001, price = 9999.9, min_notional_usd = 10.0`
Then `meets_min_notional(qty, price, min_notional)` is `False` (9.9999 < 10).

At exactly `qty * price == min_notional_usd`, the function returns `True`
(`>=` semantics).
