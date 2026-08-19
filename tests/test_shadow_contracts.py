import unittest
from unittest.mock import Mock, patch

from bot import (
    _defined_risk_shadow_snapshot,
    _setup_shadow_snapshot,
    _vix_shadow_snapshot,
)


class ShadowContractTests(unittest.TestCase):
    def test_setup_snapshot_is_always_observational(self):
        snapshot = _setup_shadow_snapshot(
            {},
            ["TQQQ"],
            {"enabled": True, "mode": "real", "influence_entries": True, "orders_allowed": True},
        )
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])

    def test_defined_risk_snapshot_is_always_observational(self):
        builder = Mock()
        builder.feed = Mock()
        snapshot = _defined_risk_shadow_snapshot(
            {},
            [],
            {"regime": "bull", "floor": {"below_floor": False}},
            {},
            builder,
            {"enabled": True, "mode": "real", "influence_entries": True, "orders_allowed": True},
        )
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])

    @patch("bot.evaluate_vix_shadow")
    def test_vix_snapshot_overrides_delegate_output(self, evaluate):
        evaluate.return_value = {"mode": "real", "influence_entries": True, "orders_allowed": True}
        snapshot = _vix_shadow_snapshot(
            Mock(),
            ["TQQQ"],
            {"enabled": True, "mode": "real", "influence_entries": True, "orders_allowed": True},
        )
        self.assertEqual(snapshot["mode"], "shadow")
        self.assertFalse(snapshot["influence_entries"])
        self.assertFalse(snapshot["orders_allowed"])
        evaluate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
