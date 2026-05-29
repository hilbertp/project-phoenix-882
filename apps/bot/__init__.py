"""DB1-Sniper live trading bot.

Implements the validated DB1 0.941 deep-entry Fib strategy on Hyperliquid perps.
See docs/db1_live_bot_prd.md for the full product requirements and milestone
plan. The current foundation (M1) covers: market-data feed, swing detector
loop, state persistence, and a CLI to run the detect-only loop. Order
placement, risk engine, and the live dashboard tab arrive in M2-M4.
"""

__version__ = "0.1.0-m1"
