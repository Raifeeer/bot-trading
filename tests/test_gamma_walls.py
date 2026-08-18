import unittest

import pandas as pd

from strategies.gamma_walls import coverage_status, gex_snapshot


class GammaWallsTests(unittest.TestCase):
    def test_missing_historical_fields_is_rejected(self):
        frame = pd.DataFrame({"strike": [100.0], "option_type": ["call"]})
        self.assertEqual(coverage_status(frame), "REJECT_DATA")
        self.assertEqual(gex_snapshot(frame)["status"], "REJECT_DATA")

    def test_gex_proxy_has_separate_call_and_put_walls(self):
        frame = pd.DataFrame({
            "timestamp": ["2026-08-14", "2026-08-14", "2026-08-14"],
            "strike": [95.0, 100.0, 105.0],
            "option_type": ["put", "call", "call"],
            "open_interest": [100.0, 200.0, 50.0],
            "gamma": [0.2, 0.4, 0.1],
            "spot": [100.0, 100.0, 100.0],
            "multiplier": [100.0, 100.0, 100.0],
        })
        self.assertEqual(coverage_status(frame), "OK")
        result = gex_snapshot(frame)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["call_wall"], 100.0)
        self.assertEqual(result["put_wall"], 95.0)
        self.assertAlmostEqual(result["net_gex_proxy"], 650_000.0)


if __name__ == "__main__":
    unittest.main()
