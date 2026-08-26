import sys
import unittest
from datetime import date
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import _option_order_specs
from execution.alpaca_executor import AlpacaExecutor, ExecutionError
from options.chains import Leg, OptionContract, OptionStructure, OptionType


class _NotFound(Exception):
    status_code = 404


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


class _MlegTrading:
    def __init__(self, existing=None):
        self.requests = []
        self.existing = existing

    def get_order_by_client_id(self, client_id):
        if self.existing is None:
            raise _NotFound(client_id)
        return self.existing

    def submit_order(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            id="mleg-parent-1",
            client_order_id=request.client_order_id,
            symbol="",
            side="",
            qty=request.qty,
            filled_qty=0,
            status=SimpleNamespace(value="accepted"),
            order_class=SimpleNamespace(value="mleg"),
            type=SimpleNamespace(value="limit"),
            limit_price=request.limit_price,
            legs=[
                SimpleNamespace(
                    id="mleg-leg-1", symbol=request.legs[0].symbol,
                    side=SimpleNamespace(value="buy"), qty=request.qty,
                    filled_qty=0, ratio_qty=request.legs[0].ratio_qty,
                    status=SimpleNamespace(value="accepted"),
                    position_intent=SimpleNamespace(value="buy_to_open"),
                ),
                SimpleNamespace(
                    id="mleg-leg-2", symbol=request.legs[1].symbol,
                    side=SimpleNamespace(value="sell"), qty=request.qty,
                    filled_qty=0, ratio_qty=request.legs[1].ratio_qty,
                    status=SimpleNamespace(value="accepted"),
                    position_intent=SimpleNamespace(value="sell_to_open"),
                ),
            ],
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

    def test_unexpected_open_orders_payload_fails_closed(self):
        class _BadTrading(_FakeTrading):
            def get_orders(self, filter=None):
                return {"orders": "unparseable"}

        executor = AlpacaExecutor()
        executor.trading = _BadTrading()
        with self.assertRaises(ExecutionError):
            executor.open_orders()

    def test_missing_quote_is_rejected_before_any_order(self):
        with self.assertRaises(ExecutionError):
            _option_order_specs(self._structure(missing=True), {
                "execution": {"order_type": "limit"}
            })

    def test_spread_uses_one_native_mleg_request(self):
        executor = AlpacaExecutor()
        executor.trading = _MlegTrading()
        specs = [
            {"symbol": "TESTC1", "side": "buy", "qty": 2,
             "order_type": "limit", "limit_price": 1.2},
            {"symbol": "TESTC2", "side": "sell", "qty": 2,
             "order_type": "limit", "limit_price": 0.4},
        ]

        result = executor.submit_spread(specs)

        self.assertEqual(len(executor.trading.requests), 1)
        request = executor.trading.requests[0]
        self.assertEqual(request.order_class.value, "mleg")
        self.assertEqual(request.qty, 2)
        self.assertEqual(float(request.limit_price), 0.8)
        self.assertEqual([leg.ratio_qty for leg in request.legs], [1, 1])
        self.assertEqual(
            [leg.position_intent.value for leg in request.legs],
            ["buy_to_open", "sell_to_open"],
        )
        self.assertEqual(result["order_class"], "mleg")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["symbols"], ["TESTC1", "TESTC2"])
        payload = request.to_request_fields()
        self.assertEqual(payload["order_class"], "mleg")
        self.assertEqual(payload["qty"], 2)
        self.assertEqual(payload["limit_price"], 0.8)
        self.assertEqual(payload["legs"][0]["ratio_qty"], 1)
        self.assertEqual(payload["legs"][1]["position_intent"], "sell_to_open")

    def test_spread_reuses_existing_client_order_id_without_resubmit(self):
        existing = SimpleNamespace(
            id="already-submitted", client_order_id="client-mleg-1", symbol="",
            side="", qty=1, filled_qty=0,
            status=SimpleNamespace(value="accepted"),
            order_class=SimpleNamespace(value="mleg"),
            type=SimpleNamespace(value="limit"), limit_price=0.8,
            legs=[],
        )
        executor = AlpacaExecutor()
        executor.trading = _MlegTrading(existing=existing)
        specs = [
            {"symbol": "TESTC1", "side": "buy", "qty": 1,
             "order_type": "limit", "limit_price": 1.2},
            {"symbol": "TESTC2", "side": "sell", "qty": 1,
             "order_type": "limit", "limit_price": 0.4},
        ]

        result = executor.submit_spread(
            specs, client_order_id="client-mleg-1")

        self.assertTrue(result["reused"])
        self.assertEqual(result["id"], "already-submitted")
        self.assertEqual(executor.trading.requests, [])

    def test_spread_close_uses_close_position_intents(self):
        executor = AlpacaExecutor()
        executor.trading = _MlegTrading()
        executor.submit_spread([
            {"symbol": "TESTC1", "side": "sell", "qty": 1,
             "order_type": "limit", "limit_price": 1.0},
            {"symbol": "TESTC2", "side": "buy", "qty": 1,
             "order_type": "limit", "limit_price": 0.4},
        ], closing=True, client_order_id="client-close-1")

        request = executor.trading.requests[0]
        self.assertEqual(
            [leg.position_intent.value for leg in request.legs],
            ["sell_to_close", "buy_to_close"],
        )

    def test_bot_has_no_sequential_spread_submission_path(self):
        source = (Path(__file__).resolve().parents[1] / "bot.py").read_text()
        self.assertNotIn("executor.submit_option_order", source)
        self.assertEqual(source.count("executor.submit_spread"), 3)

    def test_spread_rejects_non_day_time_in_force(self):
        executor = AlpacaExecutor()
        executor.trading = _MlegTrading()
        with self.assertRaises(ExecutionError):
            executor.submit_spread([
                {"symbol": "TESTC1", "side": "buy", "qty": 1,
                 "limit_price": 1.2},
                {"symbol": "TESTC2", "side": "sell", "qty": 1,
                 "limit_price": 0.4},
            ], time_in_force="gtc")


if __name__ == "__main__":
    unittest.main()
