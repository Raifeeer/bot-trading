import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import reconcile_positions_with_broker, _call_with_timeout


class _FakeExecutor:
    def __init__(self, legs):
        self._legs = legs

    def positions(self):
        return self._legs


class _HangingExecutor:
    def positions(self):
        import time
        time.sleep(1.0)
        return []


TQQQ_LONG = dict(symbol="TQQQ260918C00085000", qty=10.0, avg_entry=2.32,
                 market_value=2010.0, unrealized_pl=-310.0,
                 unrealized_pl_pct=-0.1336, asset_class="us_option")
TQQQ_SHORT = dict(symbol="TQQQ260918C00100000", qty=-10.0, avg_entry=0.35,
                  market_value=-350.0, unrealized_pl=0.0,
                  unrealized_pl_pct=0.0, asset_class="us_option")
TQQQ_PUT_LONG = dict(symbol="TQQQ260918P00085000", qty=10.0, avg_entry=2.32,
                     market_value=2010.0, unrealized_pl=-310.0,
                     unrealized_pl_pct=-0.1336, asset_class="us_option")
TQQQ_PUT_SHORT = dict(symbol="TQQQ260918P00100000", qty=-10.0, avg_entry=0.35,
                      market_value=-350.0, unrealized_pl=0.0,
                      unrealized_pl_pct=0.0, asset_class="us_option")


class TestPositionReconciliation(unittest.TestCase):
    def test_external_position_call_has_timeout(self):
        with self.assertRaises(TimeoutError):
            _call_with_timeout(_HangingExecutor().positions, 0.01,
                               "test positions")

    def test_reconstructs_vertical_spread_missing_from_local_state(self):
        state = {"positions": [], "decisions": [], "orders": []}
        executor = _FakeExecutor([TQQQ_LONG, TQQQ_SHORT])

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 1)
        self.assertEqual(len(state["positions"]), 1)
        pos = state["positions"][0]
        self.assertEqual(pos["symbol"], "TQQQ")
        self.assertEqual(pos["structure"], "call_spread_TQQQ_85.0_100.0")
        self.assertAlmostEqual(pos["net_premium"], 2.32 - 0.35)
        self.assertTrue(pos["reconciled"])
        legs_by_side = {leg["side"]: leg for leg in pos["legs"]}
        self.assertEqual(legs_by_side["buy"]["symbol"], "TQQQ260918C00085000")
        self.assertEqual(legs_by_side["sell"]["symbol"], "TQQQ260918C00100000")

    def test_reconstructed_put_is_tagged_for_bear_position_limit(self):
        state = {"positions": [], "decisions": [], "orders": []}
        executor = _FakeExecutor([TQQQ_PUT_LONG, TQQQ_PUT_SHORT])

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 1)
        self.assertEqual(state["positions"][0]["kind"], "put")
        self.assertIn("put_spread", state["positions"][0]["structure"])

    def test_already_known_position_is_not_duplicated(self):
        state = {
            "positions": [{
                "symbol": "TQQQ", "strategy": "opt_swing_trend",
                "structure": "call_spread_TQQQ_85.0_100.0",
                "net_premium": 1.97, "max_risk": 197.0,
                "legs": [
                    {"symbol": "TQQQ260918C00085000", "side": "buy", "qty": 10},
                    {"symbol": "TQQQ260918C00100000", "side": "sell", "qty": 10},
                ],
                "entry_orders": [], "entry_ts": "2026-08-01T00:00:00",
            }],
            "decisions": [], "orders": [],
        }
        executor = _FakeExecutor([TQQQ_LONG, TQQQ_SHORT])

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 0)
        self.assertEqual(len(state["positions"]), 1)

    def test_unpaired_leg_is_not_guessed(self):
        state = {"positions": [], "decisions": [], "orders": []}
        executor = _FakeExecutor([TQQQ_LONG])  # solo una pata, sin su short

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 0)
        self.assertEqual(state["positions"], [])

    def test_mixed_group_is_marked_unmanaged_and_halts_entries(self):
        state = {"positions": [], "decisions": [], "orders": []}
        legs = [
            dict(symbol="AMD260911P00420000", qty=2.0, avg_entry=8.0,
                 asset_class="us_option"),
            dict(symbol="AMD260911P00425000", qty=1.0, avg_entry=9.5,
                 asset_class="us_option"),
            dict(symbol="AMD260911P00430000", qty=-1.0, avg_entry=11.0,
                 asset_class="us_option"),
        ]
        n = reconcile_positions_with_broker(_FakeExecutor(legs), state)

        self.assertEqual(n, 0)
        self.assertTrue(state["_broker_reconciliation_halt"])
        self.assertEqual(len(state["unmanaged_broker_legs"]), 3)

    def test_unequal_vertical_quantities_are_unmanaged(self):
        state = {"positions": [], "decisions": [], "orders": []}
        legs = [
            {
                "symbol": "BB260918P00008500", "qty": -8.0,
                "avg_entry": 0.95, "asset_class": "us_option",
            },
            {
                "symbol": "BB260918P00009000", "qty": 7.0,
                "avg_entry": 1.49, "asset_class": "us_option",
            },
        ]
        n = reconcile_positions_with_broker(_FakeExecutor(legs), state)

        self.assertEqual(n, 0)
        self.assertTrue(state["_broker_reconciliation_halt"])
        self.assertEqual(len(state["unmanaged_broker_legs"]), 2)
        self.assertEqual(state["positions"], [])

    def test_no_option_positions_is_a_noop(self):
        state = {"positions": [], "decisions": [], "orders": []}
        executor = _FakeExecutor([])

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
