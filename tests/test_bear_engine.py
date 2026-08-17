"""Motor bajista: put spreads sobre CHoCH bear (AGENTS.md §40).

Hasta el 17 ago 2026 el bot era long-only por cuatro puertas y en régimen bear
no abría nada. `put_choch` es lo único del corpus con ventaja positiva,
consistente y fuera de muestra: 75% de ventanas bajistas en positivo, mediana
+6.8%, batiendo al cash (-1.3%).

Estos tests fijan las tres condiciones que vienen de la MEDICIÓN, no de una
preferencia, y cuya pérdida silenciosa anularía el motor:

1. Solo actúa cuando el régimen NO es bull (es el hueco que cubría).
2. Prima total >= min_premium_net ($100): por debajo, las 4 comisiones del
   spread ($2.60) se comen la ventaja — a prima $15 el resultado cae a -5.2%.
3. Salida propia tp1.5/sl0.5: con el tp1.4/sl0.25 de los calls, `put_choch`
   NUNCA cruza el umbral de ventaja.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot as B  # noqa: E402

CFG = {
    "universo": {
        "options_bear": {
            "enabled": True, "delta_long": 0.30, "delta_short": 0.10,
            "dte_min": 14, "dte_max": 35, "min_premium_net": 100.0,
            "tp_premium_mult": 1.5, "sl_premium_mult": 0.50,
            "close_dte": 7, "max_positions": 2,
        },
        "options_reto": {
            "max_premium_net": 12.0, "tp_premium_mult": 1.4,
            "sl_premium_mult": 0.25, "close_dte": 7,
        },
    },
    "risk": {},
    "execution": {"order_type": "limit", "limit_offset_pct": 0.1},
}


def _regime(reg, **bear_flags):
    return {"regime": reg,
            "ticker_status": {s: {"bear_choch": v}
                              for s, v in bear_flags.items()}}


class TestBearCandidates(unittest.TestCase):
    def test_no_candidates_in_bull_regime(self):
        """En bull manda el motor de calls; el bajista no debe interferir."""
        r = _regime("bull", TSLA=True, AMD=True)
        self.assertEqual(B.bear_entry_candidates(r, {"positions": []}, CFG), [])

    def test_candidates_in_bear_regime(self):
        r = _regime("bear", TSLA=True, AMD=False, NOK=True)
        got = B.bear_entry_candidates(r, {"positions": []}, CFG)
        self.assertEqual(sorted(got), ["NOK", "TSLA"])

    def test_also_acts_in_cash_regime(self):
        """`cash` tambien es un regimen donde el bot no hacia nada."""
        r = _regime("cash", TSLA=True)
        self.assertEqual(B.bear_entry_candidates(r, {"positions": []}, CFG),
                         ["TSLA"])

    def test_only_tickers_with_choch(self):
        r = _regime("bear", TSLA=False, AMD=False)
        self.assertEqual(B.bear_entry_candidates(r, {"positions": []}, CFG), [])

    def test_skips_symbols_already_open(self):
        r = _regime("bear", TSLA=True, NOK=True)
        state = {"positions": [{"symbol": "TSLA", "kind": "put"}]}
        self.assertEqual(B.bear_entry_candidates(r, state, CFG), ["NOK"])

    def test_respects_max_positions(self):
        r = _regime("bear", TSLA=True, NOK=True, AMD=True)
        state = {"positions": [{"symbol": "F", "kind": "put"},
                               {"symbol": "BB", "kind": "put"}]}
        self.assertEqual(B.bear_entry_candidates(r, state, CFG), [])

    def test_call_positions_do_not_consume_bear_quota(self):
        r = _regime("bear", TSLA=True, NOK=True)
        state = {"positions": [{"symbol": "F"}, {"symbol": "BB"}]}  # calls
        self.assertEqual(len(B.bear_entry_candidates(r, state, CFG)), 2)

    def test_disabled_by_config(self):
        cfg = {**CFG, "universo": {**CFG["universo"],
                                   "options_bear": {"enabled": False}}}
        r = _regime("bear", TSLA=True)
        self.assertEqual(B.bear_entry_candidates(r, {"positions": []}, cfg), [])


class TestExitConfigPerPositionType(unittest.TestCase):
    def test_puts_get_their_own_exit(self):
        pec = B.exit_cfg_for_position({"kind": "put",
                                       "structure": "put_spread_TSLA_400_390"},
                                      CFG)
        self.assertEqual((pec["tp_mult"], pec["sl_mult"]), (1.5, 0.50))

    def test_calls_keep_the_challenge_exit(self):
        pec = B.exit_cfg_for_position({"structure": "call_spread_TQQQ_85_100"},
                                      CFG)
        self.assertEqual((pec["tp_mult"], pec["sl_mult"]), (1.4, 0.25))

    def test_detects_put_by_structure_name_without_kind(self):
        """Las posiciones reconciliadas del broker no traen `kind`."""
        pec = B.exit_cfg_for_position({"structure": "put_spread_F_15_14"}, CFG)
        self.assertEqual(pec["tp_mult"], 1.5)

    def test_call_and_put_exits_are_actually_different(self):
        c = B.exit_cfg_for_position({"structure": "call_spread_X_1_2"}, CFG)
        p = B.exit_cfg_for_position({"structure": "put_spread_X_2_1"}, CFG)
        self.assertNotEqual((c["tp_mult"], c["sl_mult"]),
                            (p["tp_mult"], p["sl_mult"]),
                            "aplicar la salida de los calls a los puts anula "
                            "el motor bajista (ronda 5)")


class TestMinPremiumThresholdIsMeaningful(unittest.TestCase):
    def test_threshold_matches_the_measured_value(self):
        b = B.options_bear_cfg(CFG)
        self.assertGreaterEqual(
            b["min_premium_net"], 100.0,
            "por debajo de $100 la comisión se come la ventaja (ronda 5)")

    def test_commission_drag_at_threshold_is_small(self):
        """Comprobación numérica de por qué el umbral es $100."""
        comision_operacion = 4 * 0.65
        self.assertLess(comision_operacion / 100.0, 0.03)   # < 3%
        self.assertGreater(comision_operacion / 15.0, 0.15)  # > 15% a prima $15


if __name__ == "__main__":
    unittest.main()
