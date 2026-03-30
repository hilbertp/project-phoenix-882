# Discovery Bet 1 Manual Input Contract

Discovery Bet 1 uses a manual CSV import for the exact locked market contract below.

## Locked Market Identity

- TradingView full symbol: `BITGET:BTCUSDT.P`
- human label: `BTCUSDT.P on Bitget`
- instrument label: `BTCUSDTPERP PERPETUAL MIX CONTRACT`
- timeframe: `1H`
- review window: `last 3 months`

## Required Input File

Place the manual export at:

```text
data/discovery_bet_1/bitget_btcusdt_p_1h_last_3_months.csv
```

## Required CSV Columns

```text
timestamp_utc,open,high,low,close,volume
```

## Validation Rules

1. `timestamp_utc` values must be UTC timestamps.
2. Rows must be in ascending chronological order.
3. Candles must use an exact `1H` cadence.
4. The file must contain last-3-month data only.

The generator does not infer market identity from filename alone.
It validates the run against the locked market contract in code and stamps that contract into the generation manifest.