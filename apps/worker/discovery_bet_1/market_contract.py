from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class MarketContract:
    tradingview_symbol: str
    human_label: str
    instrument_label: str
    timeframe: str
    review_window: str


LOCKED_MARKET_CONTRACT = MarketContract(
    tradingview_symbol="BITGET:BTCUSDT.P",
    human_label="BTCUSDT.P on Bitget",
    instrument_label="BTCUSDTPERP PERPETUAL MIX CONTRACT",
    timeframe="1H",
    review_window="last 12 months",
)


def validate_market_contract(contract: MarketContract) -> MarketContract:
    if contract != LOCKED_MARKET_CONTRACT:
        raise ValueError(
            "Discovery Bet 1 requires the locked market contract for BITGET:BTCUSDT.P."
        )
    return contract


def market_contract_as_dict(contract: MarketContract) -> dict[str, str]:
    validate_market_contract(contract)
    return asdict(contract)
