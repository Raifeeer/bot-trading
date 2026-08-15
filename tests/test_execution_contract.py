import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import _option_order_specs
from execution.alpaca_executor import ExecutionError
from options.chains import Leg, OptionContract, OptionStructure, OptionType


class TestExecutionContract(unittest.TestCase):
    def _structure(self, missing=False):
        long = OptionContract(
            "TESTC1", "TEST", OptionType.CALL, 100.0, date(2026, 9, 18),
            bid=None if missing else 1.0,
            ask=None if missing else 1.2,
            last=None if missing else 1.1,
        )
        short = OptionContract(
            "TESTC2", "TEST", OptionType.CALL, 105.0, date(2026, 9, 18),
            bid=0.4, ask=0.6, last=0.5,
        )
        return OptionStructure(
            "call_spread_TEST_100.0_105.0",
            [Leg(long, +1), Leg(short, -1)],
            "TEST",
        )

    def test_limit_specs_use_ask_for_buys_and_bid_for_sells(self):
        specs = _option_order_specs(self._structure(), {
            "execution": {"order_type": "limit", "limit_offset_pct": 0.0}
        })
        self.assertEqual([s["side"] for s in specs], ["buy", "sell"])
        self.assertEqual([s["limit_price"] for s in specs], [1.2, 0.4])
        self.assertTrue(all(s["limit_price"] > 0 for s in specs))

    def test_missing_quote_is_rejected_before_any_order(self):
        with self.assertRaises(ExecutionError):
            _option_order_specs(self._structure(missing=True), {
                "execution": {"order_type": "limit"}
            })


if __name__ == "__main__":
    unittest.main()
