"""El saneador de barras no debe tirar el ticker entero por una barra mala.

Bug en producción el 17 ago 2026: `_clean()` corregía las barras incoherentes
(high < low, high < open, etc.) con un doble corchete,

    df.loc[bad, [["open", "close"]]].max(axis=1)   # <- dos corchetes

lo que hacía que pandas buscase UNA columna llamada ('open','close') y lanzase
KeyError("None of [Index([('open','close')])] are in the [columns]"). El
except del llamador se comía el error y el ticker desaparecía del universo
COMPLETO; bastaba una única barra malformada.

Efecto observado: NOK, BB, SOFI y F se caían, el régimen se calculaba sobre 5
de 8 tickers (`bull 4/5` en los logs) y se perdían justo los tickers baratos
donde el motor dispara sus señales. Cada fallo iba precedido en el log por
"Corrigiendo N barras incoherentes", que fue la pista.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from data.feed import _clean  # noqa: E402


def _frame(rows):
    idx = pd.date_range("2026-08-10", periods=len(rows), freq="D", tz="UTC")
    return pd.DataFrame(rows, index=idx)


class TestSanitizeIncoherentBars(unittest.TestCase):
    def test_does_not_raise_on_incoherent_bar(self):
        """El caso exacto que rompía: high por debajo de open/close."""
        df = _frame([
            {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6},
            {"open": 12.0, "high": 9.0, "low": 8.0, "close": 11.0, "volume": 2e6},
        ])
        out = _clean(df)   # antes: KeyError
        self.assertEqual(len(out), 2)

    def test_repairs_high_and_low_from_open_close(self):
        df = _frame([
            {"open": 12.0, "high": 9.0, "low": 13.0, "close": 11.0, "volume": 1e6},
        ])
        out = _clean(df)
        self.assertEqual(float(out["high"].iloc[0]), 12.0)  # max(open, close)
        self.assertEqual(float(out["low"].iloc[0]), 11.0)   # min(open, close)

    def test_coherent_bars_are_left_untouched(self):
        df = _frame([
            {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1e6},
        ])
        out = _clean(df)
        self.assertEqual(float(out["high"].iloc[0]), 11.0)
        self.assertEqual(float(out["low"].iloc[0]), 9.0)

    def test_result_stays_coherent_after_repair(self):
        """Invariante de negocio: tras sanear, high >= low y encierran a
        open/close en TODAS las filas."""
        df = _frame([
            {"open": 12.0, "high": 9.0, "low": 8.0, "close": 11.0, "volume": 1e6},
            {"open": 5.0, "high": 4.0, "low": 6.0, "close": 5.5, "volume": 2e6},
            {"open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "volume": 3e6},
        ])
        out = _clean(df)
        self.assertTrue((out["high"] >= out["low"]).all())
        self.assertTrue((out["high"] >= out[["open", "close"]].max(axis=1)).all())
        self.assertTrue((out["low"] <= out[["open", "close"]].min(axis=1)).all())

    def test_many_bad_bars_do_not_break_it(self):
        rows = [{"open": 10.0 + i, "high": 1.0, "low": 99.0,
                 "close": 10.5 + i, "volume": 1e6} for i in range(30)]
        out = _clean(_frame(rows))
        self.assertEqual(len(out), 30)
        self.assertTrue((out["high"] >= out["low"]).all())


if __name__ == "__main__":
    unittest.main()
