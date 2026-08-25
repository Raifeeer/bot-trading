import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import (
    _call_with_timeout,
    _exit_statuses_need_review,
    _restore_persistent_exit_ledger,
    reconcile_positions_with_broker,
)


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


class _FailingExecutor:
    def positions(self):
        raise RuntimeError("alpaca unavailable")


TQQQ_LONG = dict(symbol="TQQQ260918C00085000", qty=10.0, avg_entry=2.32,
                 market_value=2010.0, unrealized_pl=-310.0,
                 unrealized_pl_pct=-0.1336, asset_class="us_option")
TQQQ_SHORT = dict(symbol="TQQQ260918C00100000", qty=-10.0, avg_entry=0.35,
                  market_value=-350.0, unrealized_pl=0.0,
                  unrealized_pl_pct=0.0, asset_class="us_option")
TQQQ_PUT_LONG = dict(symbol="TQQQ260918P00100000", qty=10.0, avg_entry=2.32,
                     market_value=2010.0, unrealized_pl=-310.0,
                     unrealized_pl_pct=-0.1336, asset_class="us_option")
TQQQ_PUT_SHORT = dict(symbol="TQQQ260918P00085000", qty=-10.0, avg_entry=0.35,
                      market_value=-350.0, unrealized_pl=0.0,
                      unrealized_pl_pct=0.0, asset_class="us_option")


class TestPositionReconciliation(unittest.TestCase):
    def test_external_position_call_has_timeout(self):
        with self.assertRaises(TimeoutError):
            _call_with_timeout(_HangingExecutor().positions, 0.01,
                               "test positions")

    def test_position_read_failure_halts_entries_fail_closed(self):
        state = {"positions": [], "decisions": [], "orders": []}
        n = reconcile_positions_with_broker(_FailingExecutor(), state)
        self.assertEqual(n, 0)
        self.assertTrue(state["_broker_reconciliation_halt"])
        self.assertIn("alpaca unavailable", state["broker_reconciliation_error"])

    def test_position_timeout_halts_entries_fail_closed(self):
        state = {"positions": [], "decisions": [], "orders": []}
        with patch("bot._positions_with_timeout", side_effect=TimeoutError("stale")):
            n = reconcile_positions_with_broker(_FakeExecutor([]), state)
        self.assertEqual(n, 0)
        self.assertTrue(state["_broker_reconciliation_halt"])
        self.assertIn("stale", state["broker_reconciliation_error"])

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

    def test_reconstructs_valid_spread_and_keeps_orphans_unmanaged(self):
        state = {"positions": [], "decisions": [], "orders": []}
        legs = [
            {
                "symbol": "AMD260911P00420000", "qty": 6.0,
                "avg_entry": 8.025, "asset_class": "us_option",
            },
            {
                "symbol": "AMD260911P00425000", "qty": 3.0,
                "avg_entry": 9.5, "asset_class": "us_option",
            },
            {
                "symbol": "AMD260911P00452500", "qty": -2.0,
                "avg_entry": 19.15, "asset_class": "us_option",
            },
            {
                "symbol": "AMD260911P00455000", "qty": 2.0,
                "avg_entry": 22.2, "asset_class": "us_option",
            },
        ]
        n = reconcile_positions_with_broker(_FakeExecutor(legs), state)

        self.assertEqual(n, 1)
        self.assertEqual(len(state["positions"]), 1)
        self.assertIn("put_spread_AMD_455.0_452.5",
                      state["positions"][0]["structure"])
        self.assertTrue(state["_broker_reconciliation_halt"])
        self.assertEqual(
            {leg["symbol"] for leg in state["unmanaged_broker_legs"]},
            {"AMD260911P00420000", "AMD260911P00425000"},
        )

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

    def test_exit_intent_allows_confirmed_position_removal(self):
        position = {
            "symbol": "TQQQ", "strategy": "reconciled_broker",
            "structure": "call_spread_TQQQ_85.0_100.0",
            "net_premium": 1.97, "max_risk": 197.0,
            "legs": [
                {"symbol": "TQQQ260918C00085000", "side": "buy", "qty": 1},
                {"symbol": "TQQQ260918C00100000", "side": "sell", "qty": 1},
            ],
        }
        state = {
            "positions": [position], "decisions": [], "orders": [],
            "exit_intents": {
                "TQQQ|reconciled_broker|call_spread_TQQQ_85.0_100.0|"
                "TQQQ260918C00085000,TQQQ260918C00100000": {
                    "reason": "stop", "order_ids": ["close-1"],
                "ledger_id": "exit-test-1",
                }
            },
        }
        with patch("bot.complete_exit_intent", return_value=True):
            n = reconcile_positions_with_broker(_FakeExecutor([]), state)

        self.assertEqual(n, 0)
        self.assertEqual(state["positions"], [])
        self.assertEqual(state["exit_history"][0]["status"], "completed")
        self.assertEqual(state["decisions"][0]["action"],
                         "POSITION_CLOSED_RECONCILED")

    def test_restores_exit_intent_from_firestore_before_reconciliation(self):
        position = {
            "symbol": "TQQQ", "strategy": "reconciled_broker",
            "structure": "call_spread_TQQQ_85.0_100.0",
            "legs": [
                {"symbol": "TQQQ260918C00085000", "side": "buy", "qty": 1},
                {"symbol": "TQQQ260918C00100000", "side": "sell", "qty": 1},
            ],
        }
        position_key = (
            "TQQQ|reconciled_broker|call_spread_TQQQ_85.0_100.0|"
            "TQQQ260918C00085000,TQQQ260918C00100000"
        )
        state = {"positions": [position], "decisions": [], "orders": []}
        ledger = {
            "source_day": "2026-08-24",
            "exit_intents": {
                position_key: {
                    "status": "submitted", "reason": "stop",
                    "order_ids": ["close-1", "close-2"],
                    "ledger_id": "exit-restored-1",
                }
            },
            "exit_history": [],
        }
        with patch("bot.FIRESTORE_ENABLED", True), patch(
            "bot.read_exit_ledger", return_value=ledger
        ):
            self.assertTrue(_restore_persistent_exit_ledger(state))

        self.assertEqual(state["exit_intents"][position_key]["status"], "submitted")
        self.assertTrue(state["_broker_reconciliation_halt"])
        with patch("bot.complete_exit_intent", return_value=True):
            self.assertEqual(
                reconcile_positions_with_broker(_FakeExecutor([]), state), 0
            )
        self.assertEqual(state["positions"], [])
        self.assertFalse(state["_broker_reconciliation_halt"])
        self.assertEqual(state["exit_history"][0]["status"], "completed")

    def test_completion_failure_keeps_position_and_halts(self):
        position = {
            "symbol": "TQQQ", "strategy": "reconciled_broker",
            "structure": "call_spread_TQQQ_85.0_100.0",
            "legs": [
                {"symbol": "TQQQ260918C00085000", "side": "buy", "qty": 1},
                {"symbol": "TQQQ260918C00100000", "side": "sell", "qty": 1},
            ],
        }
        key = "TQQQ|reconciled_broker|call_spread_TQQQ_85.0_100.0|"
        key += "TQQQ260918C00085000,TQQQ260918C00100000"
        state = {
            "positions": [position], "decisions": [], "orders": [],
            "exit_intents": {key: {
                "status": "submitted", "ledger_id": "exit-failed-complete",
                "reason": "stop", "order_ids": ["close-1"],
            }},
        }
        with patch("bot.complete_exit_intent", return_value=False):
            reconcile_positions_with_broker(_FakeExecutor([]), state)
        self.assertEqual(len(state["positions"]), 1)
        self.assertEqual(state["exit_intents"][key]["status"], "needs_review")
        self.assertTrue(state["_broker_reconciliation_halt"])

    def test_ledger_read_failure_halts_boot_fail_closed(self):
        state = {"positions": [], "decisions": [], "orders": []}
        with patch("bot.FIRESTORE_ENABLED", True), patch(
            "bot.read_exit_ledger", return_value=None
        ):
            self.assertFalse(_restore_persistent_exit_ledger(state))
        self.assertTrue(state["_broker_reconciliation_halt"])

    def test_order_status_api_failure_is_review_and_fail_closed(self):
        self.assertTrue(_exit_statuses_need_review([]))
        self.assertTrue(_exit_statuses_need_review([
            {"status": "filled"}, {"status": "rejected"}
        ]))
        self.assertTrue(_exit_statuses_need_review([
            {"status": "canceled"}, {"status": "rejected"}
        ]))
        self.assertFalse(_exit_statuses_need_review([
            {"status": "filled"}, {"status": "filled"}
        ]))

    def test_no_option_positions_is_a_noop(self):
        state = {"positions": [], "decisions": [], "orders": []}
        executor = _FakeExecutor([])

        n = reconcile_positions_with_broker(executor, state)

        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
