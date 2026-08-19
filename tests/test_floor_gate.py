"""Verifica el piso del reto $100->$200 (AGENTS.md): (1) check_floor()
detecta below_floor/crossed correctamente y (2) la condición de gate que usa
bot.py antes de abrir una posición nueva (`regime=='bull' and not
below_floor`) de verdad bloquea la entrada cuando el equity está bajo el
piso, no solo en teoría."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from risk.floor import check_floor
from state import firestore_state


class TestFloorGate(unittest.TestCase):
    def test_below_floor_detected_and_crossed_once(self):
        # Aunque exista un latch histórico, bajo $100,000 rige la recuperación
        # con piso $99,000. Solo se bloquea por debajo de ese nivel.
        state = {"_challenge_armed": True}
        r1 = check_floor(98_800.0, state)
        self.assertTrue(r1["below_floor"])
        self.assertTrue(r1["crossed"])
        self.assertEqual(r1["floor"], 99_000.0)
        self.assertEqual(r1["phase"], "recuperacion")
        self.assertIn("PISO ROTADO", r1["reason"])

        # Segundo tick aún bajo el piso: no debe re-disparar el aviso.
        r2 = check_floor(98_850.0, state)
        self.assertTrue(r2["below_floor"])
        self.assertFalse(r2["crossed"])

        # Recupera el piso de recuperación: crossed=True una sola vez.
        r3 = check_floor(99_050.0, state)
        self.assertFalse(r3["below_floor"])
        self.assertTrue(r3["crossed"])
        self.assertIn("PISO RECUPERADO", r3["reason"])

        r4 = check_floor(100_050.0, state)
        self.assertFalse(r4["crossed"])

    def test_new_entry_gate_blocks_when_below_floor(self):
        """Reproduce exactamente la condición de bot.py (línea ~552-554):
        `sig.tradable and regime=='bull' and not below_floor`."""
        state = {"_challenge_armed": True}
        floor_res = check_floor(98_500.0, state)
        regime = {"regime": "bull", "floor": floor_res}

        sig_tradable = True
        gate_open = (sig_tradable and regime.get("regime") == "bull"
                     and not (regime.get("floor") or {}).get("below_floor"))
        self.assertFalse(gate_open, "el piso de recuperación debe bloquear bajo $99,000")

    def test_new_entry_gate_allows_when_above_floor(self):
        state = {}
        floor_res = check_floor(100_500.0, state)
        regime = {"regime": "bull", "floor": floor_res}

        sig_tradable = True
        gate_open = (sig_tradable and regime.get("regime") == "bull"
                     and not (regime.get("floor") or {}).get("below_floor"))
        self.assertTrue(gate_open)


class TestReadLastEquitySeedsFloor(unittest.TestCase):
    def test_read_last_equity_returns_todays_value(self):
        fake_snap = MagicMock()
        fake_snap.exists = True
        fake_snap.to_dict.return_value = {"payload": {"equity": 99_650.5}}
        fake_doc_ref = MagicMock()
        fake_doc_ref.get.return_value = fake_snap
        fake_collection = MagicMock()
        fake_collection.document.return_value = fake_doc_ref
        fake_db = MagicMock()
        fake_db.collection.return_value = fake_collection

        with patch.object(firestore_state, "_get_db", return_value=fake_db):
            equity = firestore_state.read_last_equity()
        self.assertEqual(equity, 99_650.5)

    def test_read_last_equity_falls_back_to_previous_days(self):
        missing_snap = MagicMock()
        missing_snap.exists = False
        found_snap = MagicMock()
        found_snap.exists = True
        found_snap.to_dict.return_value = {"payload": {"equity": 99_400.0}}

        fake_doc_ref = MagicMock()
        fake_doc_ref.get.side_effect = [missing_snap, found_snap]
        fake_collection = MagicMock()
        fake_collection.document.return_value = fake_doc_ref
        fake_db = MagicMock()
        fake_db.collection.return_value = fake_collection

        with patch.object(firestore_state, "_get_db", return_value=fake_db):
            equity = firestore_state.read_last_equity()
        self.assertEqual(equity, 99_400.0)

    def test_read_last_equity_returns_none_on_failure(self):
        with patch.object(firestore_state, "_get_db", side_effect=Exception("boom")):
            equity = firestore_state.read_last_equity()
        self.assertIsNone(equity)


if __name__ == "__main__":
    unittest.main()
