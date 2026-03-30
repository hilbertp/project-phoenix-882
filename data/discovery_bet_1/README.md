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

Place the matching provenance sidecar at:

```text
data/discovery_bet_1/bitget_btcusdt_p_1h_last_3_months.provenance.json
```

## Required CSV Columns

```text
source_timestamp,open,high,low,close,volume
```

## Validation Rules

1. `source_timestamp` values must be preserved exactly as delivered by the TradingView-based source.
2. Rows must be in ascending chronological order.
3. Source timestamp irregularities such as DST gaps are preserved and must not be normalized away.
4. The file must contain last-3-month data only.
5. The provenance sidecar must include acquisition timestamp, acquisition operator or process, acquisition method, and a matching SHA-256 hash of the CSV file.

The generator does not infer market identity from filename alone.
It validates the run against the locked market contract in code, validates the provenance sidecar hash, and stamps market contract, source provenance, and artifact schema version into the generation manifest.
