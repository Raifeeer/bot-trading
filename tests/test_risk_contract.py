import sys
import unittest
from datetime import date
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from risk.manager import RiskManager
from risk.regime import classify_regime
from state import telegram_bot


class TestRiskContract(unittest.TestCase):
    def test_daily_breaker_resets_on_new_day_but_total_state_remains(self):
        rm = RiskManager({
            "max_drawdown_daily_pct": 5.0,
            "max_drawdown_total_pct": 15.0,
        })
        rm.capital = 100.0
        rm.reset_day(100.0, date(2026, 8, 14))
        rm.check_circuit_breakers(94.0, day=date(2026, 8, 14))
        self.assertTrue(rm.halted_today)
        rm.check_circuit_breakers(100.0, day=date(2026, 8, 14))
        self.assertTrue(rm.halted_today)  # permanece bloqueado hasta rollover
        rm.check_circuit_breakers(100.0, day=date(2026, 8, 15))
        self.assertFalse(rm.halted_today)
        self.assertEqual(rm._risk_day, date(2026, 8, 15))

    def test_option_structure_approval_uses_risk_budget_and_position_limit(self):
        rm = RiskManager({"mode": "aggressive", "max_risk_per_trade_pct": 5.0, "max_open_positions": 2})
        rm.capital = 100_000.0
        rm.reset_day(100_000.0, date(2026, 8, 21))
        structure = SimpleNamespace(net_premium=10.0, max_risk=2_000.0)
        approved = rm.approve_option_structure("TQQQ", structure, 100_000.0, [], "promoted_breakout")
        self.assertEqual(approved.decision, "APPROVED")

        too_risky = SimpleNamespace(net_premium=10.0, max_risk=6_000.0)
        rejected = rm.approve_option_structure("AMD", too_risky, 100_000.0, [], "promoted_breakout")
        self.assertEqual(rejected.decision, "REJECTED")
        self.assertIn("presupuesto", rejected.reason)

    def test_no_data_is_cash_not_bear(self):
        result = classify_regime({}, ["SOFI", "PLTR"])
        self.assertEqual(result["regime"], "cash")
        self.assertEqual(result["n"], 0)
        self.assertFalse(result["crash_event"])

    def test_telegram_risk_supports_canonical_percentage_and_legacy_fraction(self):
        with patch.object(telegram_bot, "_state", {
            "payload": {"equity": 100.0, "risk": {
                "max_risk_per_trade_pct": 5.0,
                "max_open_positions": 2,
            }}
        }):
            msg = telegram_bot._cmd_riesgo()
        self.assertIn("Riesgo por trade: 5.0%", msg)
        self.assertIn("Máx. posiciones: 2", msg)

        with patch.object(telegram_bot, "_state", {
            "payload": {"equity": 100.0, "risk": {
                "risk_per_trade_pct": 0.01,
                "max_positions": 5,
            }}
        }):
            msg = telegram_bot._cmd_riesgo()
        self.assertIn("Riesgo por trade: 1.0%", msg)


if __name__ == "__main__":
    unittest.main()
