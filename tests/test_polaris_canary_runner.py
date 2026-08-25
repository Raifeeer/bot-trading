import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_polaris_canary_once.py"


with patch("subprocess.check_output", return_value="test-secret\n"):
    spec = importlib.util.spec_from_file_location("polaris_canary_runner", SCRIPT)
    canary = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = canary
    spec.loader.exec_module(canary)


class TestPolarisCanaryRunner(unittest.TestCase):
    def test_entry_quote_requires_positive_ask_within_limit(self):
        self.assertTrue(canary.entry_quote_allowed(0.02))
        self.assertFalse(canary.entry_quote_allowed(0.0201))
        self.assertFalse(canary.entry_quote_allowed(0))
        self.assertFalse(canary.entry_quote_allowed("bad"))

    def test_exit_quote_requires_positive_bid_not_above_ask(self):
        self.assertTrue(canary.exit_quote_allowed(0.01, 0.02))
        self.assertFalse(canary.exit_quote_allowed(0, 0.02))
        self.assertFalse(canary.exit_quote_allowed(0.03, 0.02))
        self.assertFalse(canary.exit_quote_allowed("bad", 0.02))

    def test_cloud_run_guard_requires_contained_revision_at_100_percent(self):
        with patch.object(
            canary.subprocess,
            "check_output",
            return_value="{'percent': 100, 'revisionName': 'polaris-bot-cbdc186'}\n",
        ):
            self.assertIn("polaris-bot-cbdc186", canary.verify_cloud_run_contained())
        with patch.object(
            canary.subprocess,
            "check_output",
            return_value="{'percent': 100, 'revisionName': 'other'}\n",
        ):
            with self.assertRaisesRegex(RuntimeError, "not_contained"):
                canary.verify_cloud_run_contained()

    def test_empty_account_guard_rejects_existing_position_or_open_order(self):
        account = (200, {"status": "ACTIVE", "equity": "96915.63"})
        with patch.object(canary, "api", side_effect=[account, (200, [{"symbol": "F"}])]):
            with self.assertRaisesRegex(RuntimeError, "positions_not_empty"):
                canary.verify_empty_account()
        with patch.object(canary, "api", side_effect=[account, (200, []), (200, [{"id": "o1"}])]):
            with self.assertRaisesRegex(RuntimeError, "open_orders_not_empty"):
                canary.verify_empty_account()

    def test_market_closed_aborts_without_order_submission(self):
        with patch.object(canary, "fs_create", return_value=(200, {"updateTime": "t1"})), patch.object(
            canary, "verify_cloud_run_contained", return_value="contained"
        ), patch.object(
            canary, "api", return_value=(200, {"is_open": False, "next_open": "later"})
        ), patch.object(canary, "persist_run", return_value="t2") as persist, patch.object(
            canary, "write_run"
        ) as write_run:
            out = io.StringIO()
            with redirect_stdout(out):
                result = canary.main()
        self.assertEqual(result, 0)
        self.assertEqual(persist.call_count, 1)
        write_run.assert_not_called()
        self.assertIn("aborted_market_closed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
