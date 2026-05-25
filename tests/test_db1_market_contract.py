from __future__ import annotations

import unittest

from apps.worker.discovery_bet_1.market_contract import LOCKED_MARKET_CONTRACT, MarketContract, validate_market_contract


class DB1MarketContractTests(unittest.TestCase):
    def test_locked_market_contract_matches_approved_identity(self) -> None:
        self.assertEqual(LOCKED_MARKET_CONTRACT.tradingview_symbol, "BITGET:BTCUSDT.P")
        self.assertEqual(LOCKED_MARKET_CONTRACT.human_label, "BTCUSDT.P on Bitget")
        self.assertEqual(
            LOCKED_MARKET_CONTRACT.instrument_label,
            "BTCUSDTPERP PERPETUAL MIX CONTRACT",
        )
        self.assertEqual(LOCKED_MARKET_CONTRACT.timeframe, "1H")
        self.assertEqual(LOCKED_MARKET_CONTRACT.review_window, "last 12 months")

    def test_validate_market_contract_rejects_alternate_identity(self) -> None:
        with self.assertRaises(ValueError):
            validate_market_contract(
                MarketContract(
                    tradingview_symbol="BINANCE:BTCUSDT.P",
                    human_label="BTCUSDT.P on Binance",
                    instrument_label="BTCUSDT perpetual",
                    timeframe="1H",
                    review_window="last 3 months",
                )
            )


if __name__ == "__main__":
    unittest.main()