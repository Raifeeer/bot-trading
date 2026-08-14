"""Prueba de estrés del régimen S78 (bull->hold/bear->cash) ante crashes
sintéticos abruptos.

Inyecta shocks sintéticos en el feed real de yfinance (universo reto),
garantizando que el shock sea coherente con la detección CHoCH pragmática
(máximo dominante reciente + rompimiento bajo swing LOW), para que el
detector pueda dispararse en algún momento.

Escenarios:
  E1 Flash:     -20% en 1 día, lateral 90d
  E2 Severo:    -35% en 5 días, rebote +50% lento en 90d
  E3 Catastrófico: -50% en 3 días, sin rebote
  E4 Realista:  -30% en 20 días, rebote débil, crash secundario -15%
  E5 Timing:    como E2 pero el crash ocurre 1 día después del rebalance (peor
                caso: hold recién reequilibrado)
Ejecuta S78 (regime_hold_cash) vs hold_weekly (benchmark).
"""
import os
import sys
import time

import numpy as np
import pandas as pd

TOP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOP)

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import (run_scenario, UNI_RETO, CAPITAL_INICIAL, SCENARIOS,
                             realized_vol)  # noqa: E402


def inject_crash(base_hist: dict, crash_days, crash_mag, base_date,
                 recovery=None):
    """Inyecta un shock sintético coherente con CHoCH en los DataFrames base.

    - Crea barras nuevas a partir de base_date: caída gradual (máx -7% diario
      por barra para mantener realismo de swings), manteniendo estructura OHLC.
    - recovery: dict(opct, n_days) rebote parcial posterior.
    Devuelve dict simétrico de DataFrame con index extendido.
    """
    out = {}
    for sym, df in base_hist.items():
        df = df.copy()
        last = df.index[-1]
        rows = []
        spot = float(df["close"].iloc[-1])
        hi = float(df["high"].iloc[-1])
        rv = realized_vol(df) or 0.3
        daily = 1 - (1 - crash_mag) ** (1.0 / max(crash_days, 1))
        t = (base_date.tz_convert("UTC") if base_date.tzinfo is not None
         else pd.Timestamp(base_date, tz="UTC"))
        for i in range(crash_days):
            nxt = t + pd.Timedelta(days=i + 1)
            while nxt.weekday() >= 5:
                nxt += pd.Timedelta(days=1)
            open_ = spot
            close = spot * (1 - daily)
            hi = max(hi, open_)
            low = close * (1 - 0.012 * rv)
            rows.append(dict(open=open_, high=hi, low=low, close=close,
                             volume=int(df["volume"].iloc[-1] * 2.5)))
            spot = close
        if recovery:
            ro, rn = recovery.get("opct", 0.5), recovery.get("n_days", 60)
            r_daily = (1 + ro) ** (1.0 / max(rn, 1))
            for i in range(rn):
                nxt = t + pd.Timedelta(days=crash_days + i + 1)
                while nxt.weekday() >= 5:
                    nxt += pd.Timedelta(days=1)
                open_ = spot
                close = spot * r_daily
                hi = max(hi, open_)
                low = min(low, close * (1 - 0.012 * rv))
                rows.append(dict(open=open_, high=hi, low=low, close=close,
                                 volume=int(df["volume"].iloc[-1])))
                spot = close
        tail = pd.DataFrame(rows, index=rows and [
            t + pd.Timedelta(days=i) for i in range(1, len(rows) + 1)])
        # reindexar a días de trading aproximados (quitar fines de semana)
        tail = tail[~tail.index.to_series().dt.weekday.isin((5, 6))]
        out[sym] = pd.concat([df, tail])
    return out


def run_stress(key, sc, data, desc):
    t0 = time.time()
    equity, tdf, ecdf, dd_pct, max_eq = run_scenario(key, sc, data)
    elapsed = time.time() - t0
    wr = (tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0
    row = dict(desc=desc, motor=sc["motor"], equity=round(equity, 2),
               retorno_pct=round((equity / CAPITAL_INICIAL - 1) * 100, 1),
               trades=len(tdf), wins=int((tdf["pnl"] > 0).sum()),
               win_rate=round(wr, 0),
               max_drawdown_pct=round(dd_pct, 1), segundos=round(elapsed, 0))
    return row, tdf, ecdf


def main():
    print("Descargando datos reales (universo reto)...")
    t0 = time.time()
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    base = feed.history(UNI_RETO, "1d", days=365)
    print(f"Datos en {time.time()-t0:.0f}s")

    # base_date: 60 días tras el inicio para que todos los DF tengan >=110 filas
    dates0 = sorted(base[UNI_RETO[0]].index.normalize())
    base_date = pd.Timestamp("2026-05-15", tz="UTC")
    assert base_date > dates0[0] + pd.Timedelta(days=130), "historia insuficiente"

    sc = dict(SCENARIOS["S78"], crash_event=0.03)  # detector de flash crash
    hold_sc = dict(SCENARIOS["S74"])
    hold_sc["tickers"] = UNI_RETO  # usar mismo universo del reto

    rows, tdfs, eq_out = [], {}, {}
    # E1-E4: timing estándar (crash comienza 3 días antes de un posible rebalance
    # = caso "a mitad de semana")
    for name, crash, rec in (
            ("E1 Flash -20% 1d", dict(crash_days=1, crash_mag=0.20), None),
            ("E2 Severo -35% 5d +rebote", dict(crash_days=5, crash_mag=0.35),
             dict(opct=0.5, n_days=70)),
            ("E3 Catastrófico -50% 3d", dict(crash_days=3, crash_mag=0.50), None),
            ("E4 Realista -30% 20d +débil", dict(crash_days=20, crash_mag=0.30),
             dict(opct=0.2, n_days=50))):
        data = inject_crash(base, **crash, base_date=base_date, recovery=rec)
        end = data[UNI_RETO[0]].index[-1].normalize()
        s78 = dict(sc, window_dates=(str(base_date.date()), str(end.date())))
        hold = dict(hold_sc, window_dates=(str(base_date.date()), str(end.date())))
        r78, t78, e78 = run_stress(f"STRESS_{name}_S78", s78, data, name)
        rhold, th, eh = run_stress(f"STRESS_{name}_HOLD", hold, data, name)
        rows += [r78, rhold]
        tdfs[f"{name}_S78"] = t78
        tdfs[f"{name}_HOLD"] = th
        eq_out[f"{name}_S78"] = e78
        eq_out[f"{name}_HOLD"] = eh
        print(f"[{name}] S78: ${r78['equity']} ({r78['retorno_pct']:+.1f}%) "
              f"dd={r78['max_drawdown_pct']}% | HOLD: ${rhold['equity']} "
              f"({rhold['retorno_pct']:+.1f}%) dd={rhold['max_drawdown_pct']}%")

    # E5: peor timing — crash 1 día tras rebalance
    data5 = inject_crash(base, crash_days=5, crash_mag=0.35,
                         base_date=base_date + pd.Timedelta(days=1),
                         recovery=dict(opct=0.5, n_days=70))
    end5 = data5[UNI_RETO[0]].index[-1].normalize()
    s78e5 = dict(sc, window_dates=(str(base_date.date()), str(end5.date())))
    holde5 = dict(hold_sc, window_dates=(str(base_date.date()), str(end5.date())))
    r78e5, t78e5, e78e5 = run_stress("STRESS_E5_S78", s78e5, data5, "E5 peak-crash")
    rholde5, th5, eh5 = run_stress("STRESS_E5_HOLD", holde5, data5, "E5 peak-crash")
    rows += [r78e5, rholde5]
    tdfs["E5_S78"] = t78e5
    tdfs["E5_HOLD"] = th5
    eq_out["E5_S78"] = e78e5
    eq_out["E5_HOLD"] = eh5
    print(f"[E5 peor-timing] S78: ${r78e5['equity']} ({r78e5['retorno_pct']:+.1f}%) "
          f"dd={r78e5['max_drawdown_pct']}% | HOLD: ${rholde5['equity']} "
          f"({rholde5['retorno_pct']:+.1f}%) dd={rholde5['max_drawdown_pct']}%")

    import csv
    out_dir = "/home/ubuntu/backtests"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/bt_stress_resumen.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for k, v in tdfs.items():
        if len(v):
            v.to_csv(f"{out_dir}/bt_stress_{k}_trades.csv", index=False)
    for k, v in eq_out.items():
        if len(v):
            pd.DataFrame(v).to_csv(f"{out_dir}/bt_stress_{k}_equity.csv",
                                   index=False)
    print(f"\nResumen guardado en {out_dir}/bt_stress_resumen.csv")


if __name__ == "__main__":
    main()
