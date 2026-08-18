import unittest
from datetime import date, timedelta

import pandas as pd

from options.chains import OptionContract, OptionType
from options.defined_risk_shadow import evaluate_defined_risk_shadow


class FakeFeed:
    def __init__(self, chains):
        self.chains = chains

    def contracts(self, underlying, otype=None, **_kwargs):
        return [c for c in self.chains[underlying] if c.option_type == otype]

    def snapshots(self, contracts, **_kwargs):
        return contracts


def _contract(symbol, kind, strike, expiration):
    option_type = OptionType.CALL if kind == "call" else OptionType.PUT
    return OptionContract(
        symbol=symbol,
        underlying="TEST",
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        bid=1.00,
        ask=1.02,
        last=1.01,
        volume=100,
        open_interest=1000,
    )


class DefinedRiskShadowTests(unittest.TestCase):
    def setUp(self):
        exp = date.today() + timedelta(days=30)
        self.feed = FakeFeed({"TEST": [
            _contract("TESTC105", "call", 105.0, exp),
            _contract("TESTC110", "call", 110.0, exp),
            _contract("TESTP95", "put", 95.0, exp),
            _contract("TESTP90", "put", 90.0, exp),
        ]})
        self.frames = {"TEST": {"1d": pd.DataFrame({"close": [100.0]})}}
        self.cfg = {"defined_risk_shadow": {"enabled": True, "mode": "shadow"}}

    def test_shadow_never_allows_orders(self):
        out = evaluate_defined_risk_shadow(
            self.feed, self.frames, "bear", False, self.cfg)
        self.assertFalse(out["orders_allowed"])
        self.assertFalse(out["influence_entries"])
        candidates = out["symbols"]["TEST"]["candidates"]
        self.assertEqual(len(candidates), 3)
        bear_call = next(c for c in candidates if c["strategy"] == "bear_call_credit")
        self.assertEqual(bear_call["status"], "available")
        self.assertFalse(bear_call["orders_allowed"])

    def test_cash_regime_can_observe_condor_but_not_directional_candidates(self):
        out = evaluate_defined_risk_shadow(
            self.feed, self.frames, "cash", False, self.cfg)
        candidates = out["symbols"]["TEST"]["candidates"]
        condor = next(c for c in candidates if c["strategy"] == "iron_condor")
        bull_put = next(c for c in candidates if c["strategy"] == "bull_put_credit")
        self.assertEqual(condor["status"], "available")
        self.assertEqual(bull_put["status"], "regime_or_floor_blocked")

    def test_floor_blocks_available_structure_without_authorizing_order(self):
        out = evaluate_defined_risk_shadow(
            self.feed, self.frames, "bear", True, self.cfg)
        bear_call = next(c for c in out["symbols"]["TEST"]["candidates"] if c["strategy"] == "bear_call_credit")
        self.assertEqual(bear_call["status"], "regime_or_floor_blocked")
        self.assertFalse(bear_call["floor_allowed"])
        self.assertFalse(bear_call["orders_allowed"])


if __name__ == "__main__":
    unittest.main()
