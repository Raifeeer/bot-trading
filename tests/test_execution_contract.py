import sys
import unittest
from datetime import date
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import _option_order_specs
from execution.alpaca_executor import AlpacaExecutor, ExecutionError
from options.chains import Leg, OptionContract, OptionStructure, OptionType


class _FakeTrading:
    def __init__(self):
        self.requests = []
        self.orders = [SimpleNamespace(
            id="order-open-1",
            symbol="TESTC1",
            side=SimpleNamespace(value="buy"),
            qty=1,
            filled_qty=0,
            status=SimpleNamespace(value="new"),
            position_intent=SimpleNamespace(value="buy_to_close"),
            client_order_id="client-open-1",
        )]

    def submit_order(self, request):
        self.requests.append(request)
        return SimpleNamespace(status="accepted")

    def get_orders(self, filter=None):
        return self.orders

    def get_order_by_id(self, order_id):
        return SimpleNamespace(
            id=order_id,
            symbol="TESTC1",
            side=SimpleNamespace(value="buy"),
            qty=1,
            filled_qty=1,
            status=SimpleNamespace(value="filled"),
            position_intent=SimpleNamespace(value="buy_to_close"),
        )


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

    def test_option_request_uses_supported_request_schema(self):
        executor = AlpacaExecutor()
        executor.trading = _FakeTrading()
        result = executor.submit_option_order(
            "TESTC1", "buy", 1, order_type="limit", limit_price=1.2)

        request = executor.trading.requests[0]
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(request.symbol, "TESTC1")
        self.assertEqual(float(request.limit_price), 1.2)
        self.assertNotIn("asset_class", type(request).model_fields)

    def test_open_orders_are_normalized_for_idempotency(self):
        executor = AlpacaExecutor()
        executor.trading = _FakeTrading()
        orders = executor.open_orders(symbols=["TESTC1"])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["id"], "order-open-1")
        self.assertEqual(orders[0]["status"], "new")
        self.assertEqual(orders[0]["position_intent"], "buy_to_close")

    def test_order_statuses_are_normalized_for_fill_reconciliation(self):
        executor = AlpacaExecutor()
        executor.trading = _FakeTrading()
        statuses = executor.order_statuses(["order-open-1"])
        self.assertEqual(statuses[0]["status"], "filled")
        self.assertEqual(statuses[0]["filled_qty"], 1.0)

    def test_missing_quote_is_rejected_before_any_order(self):
        with self.assertRaises(ExecutionError):
            _option_order_specs(self._structure(missing=True), {
                "execution": {"order_type": "limit"}
            })


if __name__ == "__main__":
    unittest.main()
