"""Stops intradiarios contra el escenario catastrófico E3 (-50% en 72h).

Hallazgo18. El motor `regime_hold_cash` gana el parámetro `intraday_stop`
(p.ej. 0.04 = quiebre del 4% bajo el close previo del día): si el low del día
rompe ese umbral en el subyacente, las posiciones del hold se valoran al
precio de quiebre (ejecución intradiaria, best case) en el rebalance o en el
cierre bear de ese mismo día. Complementa al detector `crash_event` (que actúa
sobre cierres) y protege en el día 1 del shock, antes de que el CHoCH pueda
formarse.

Escenarios: E1 Flash, E2 Severo, E3 Catastrófico, E3+gap de apertura,
            E5 peor-timing, y la ventana real abr-ago 2026 (comisiones on).
Salida: /home/ubuntu/backtests/bt_intraday_resumen.csv
"""
import os
import sys
import time

import numpy as np
import pandas as pd

TOP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOP)

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import (run_scenario, UNI_RETO, CAPITAL_INICIAL,
                             SCENARIOS, realized_vol)  # noqa: E402
from stress_test import inject_crash, run_stress  # noqa: E402


def main():
    print("Descargando datos reales (universo reto)...")
    t0 = time.time()
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    base = feed.history(UNI_RETO, "1d", days=365)
    print(f"Datos en {time.time()-t0:.0f}s")

    base_date = pd.Timestamp("2026-05-15", tz="UTC")
    sc = dict(SCENARIOS["S78"])

    rows = []
    configs = [
        ("E1 Flash -20% 1d", dict(crash_days=1, crash_mag=0.20), None, False),
        ("E2 Severo -35% 5d +rebote", dict(crash_days=5, crash_mag=0.35),
         dict(opct=0.5, n_days=70), False),
        ("E3 Catastrófico -50% 3d", dict(crash_days=3, crash_mag=0.50),
         None, False),
        ("E3a gap -20% apertura", dict(crash_days=3, crash_mag=0.50,
         gap_day1=0.20), None, False),
        ("E3b sin rebote 7d", dict(crash_days=3, crash_mag=0.50),
         None, True),
        ("E3c rebal mismo día + shock gradual",
         dict(crash_days=3, crash_mag=0.50, rebal_same_day=True,
              shock_gradual=True), None, False),
    ]
    variants = [
        ("base", None),
        ("stop 4%", 0.04),
        ("stop 6%", 0.06),
        ("stop 8%", 0.08),
        ("stop 10%", 0.10),
    ]
    for name, crash, rec, keep_base in configs:
        crash = dict(crash)
        gap = crash.pop("gap_day1", 0.0)
        rebal_same_day = crash.pop("rebal_same_day", False)
        shock_gradual = crash.pop("shock_gradual", False)
        SAME_DAY = rebal_same_day  # conservar para ajustar el rebalance
        data = inject_crash(base, **crash, base_date=base_date, recovery=rec)
        # las barras sintéticas ya vienen ordenadas por inject_crash (sort_index
        # dentro), garantizando cronología correcta para el bucle del motor
        # fuerza de bull: en algunos escenarios (E3) la historia previa de
        # yfinance ya es bear (CHoCH), así el motor entra a cash antes del
        # shock y nunca sufre la caída. Para medir la defensa intradiaria
        # necesitamos que SOSTENGA el hold hasta el shock: sellamos la
        # evaluación de régimen hasta 1 día antes del shock.
        if keep_base:
            continue  # sin fuerza de bull: escenario "ya bear" (control)
        if gap > 0:
            d1 = data[UNI_RETO[0]][
                data[UNI_RETO[0]].index.normalize() == base_date].index[0]
            for sym, df in data.items():
                if d1 not in df.index:
                    continue
                idx = list(df.index).index(d1)
                df.iloc[idx, df.columns.get_loc("open")] *= (1 - gap)
                df.iloc[idx, df.columns.get_loc("high")] = max(
                    df.iloc[idx, df.columns.get_loc("high")],
                    df.iloc[idx, df.columns.get_loc("open")])
                df.iloc[idx, df.columns.get_loc("low")] = min(
                    df.iloc[idx, df.columns.get_loc("low")],
                    df.iloc[idx, df.columns.get_loc("open")])
                df.iloc[idx, df.columns.get_loc("close")] = min(
                    df.iloc[idx, df.columns.get_loc("close")],
                    df.iloc[idx, df.columns.get_loc("open")])
        end = data[UNI_RETO[0]].index[-1].normalize()
        s78 = dict(sc, window_dates=(str(base_date.date()), str(end.date())))
        # ventana de fuerza de bull: el régimen se fuerza a bull hasta el
        # día antes del primer día de shock (el detector crash_event sí
        # permanece activo dentro de esa ventana).
        same_day = False  # rebal_same_day ya se extrajo antes como SAME_DAY
        # El shock dura crash_days días hábiles; forzar bull hasta el último
        # día del shock para que el motor entre al crash SOSTENIENDO la
        # posición (el detector crash_event sí sigue activo y corta).
        shock_end = base_date
        n_crash_days = crash.get("crash_days", 3)
        for _ in range(n_crash_days + 1):
            shock_end += pd.Timedelta(days=1)
            while shock_end.weekday() >= 5:
                shock_end += pd.Timedelta(days=1)
        s78["force_bull_until"] = str(shock_end.date())
        # E3c (peor caso): el rebalance semanal coincide con el día 1 del
        # shock. El bucle del motor compra el rebalance al open del día 1
        # del shock (precio pre-caída); el intraday_stop/crash_event del
        # MISMO día corta al precio de quiebre. Para forzar ese alineamiento
        # sin fuerza de régimen, basta con que el día 1 del shock sea día
        # de rebalance: el shock empieza el 18-may (lunes), que SÍ cae en
        # un día de rebalance semanal desde el 15-may (viernes) → 18 = 15+3
        # no es múltiplo de 7. Ajustar: mover el inicio del shock al día
        # hábil siguiente al rebalance (base +7).
        if SAME_DAY:
            first_rebal = base_date  # el primer día de ventana es rebalance
            shock_start2 = first_rebal
            for _ in range(7):
                shock_start2 += pd.Timedelta(days=1)
                while shock_start2.weekday() >= 5:
                    shock_start2 += pd.Timedelta(days=1)
            # reconstruir data con el shock empezando en el rebalance+7
            data = inject_crash(base, base_date=shock_start2, **crash,
                                recovery=rec)
            s78["window_dates"] = (str(base_date.date()), str(end.date()))
            shock_end2 = shock_start2
            for _ in range(n_crash_days + 1):
                shock_end2 += pd.Timedelta(days=1)
                while shock_end2.weekday() >= 5:
                    shock_end2 += pd.Timedelta(days=1)
            s78["force_bull_until"] = str(shock_end2.date())
            if shock_gradual:
                sd2 = shock_start2 + pd.Timedelta(days=1)
                while sd2.weekday() >= 5:
                    sd2 += pd.Timedelta(days=1)
                for sym, df in data.items():
                    sd_loc = sd2.replace(hour=df.index[-1].hour,
                                         minute=0, second=0,
                                         microsecond=0)
                    prev = df.index.get_loc(sd_loc) - 1
                    open_prev = float(df["close"].iloc[prev])
                    open_new = open_prev * 1.02
                    close_new = open_new * (1 - 0.17)
                    mask = df.index.normalize() == sd_loc.normalize()
                    df.loc[mask, "open"] = open_new
                    df.loc[mask, "high"] = open_new
                    df.loc[mask, "low"] = close_new
                    df.loc[mask, "close"] = close_new
                    df.loc[mask, "volume"] = (
                        df.loc[mask, "volume"] * 3)
                s78["force_bull_until"] = str(sd2.date())
        if shock_gradual:
            # día 1 del shock: abre +2% (rally falso) y cae -17% intradiario.
            # Con el fix de inject_crash, las fechas del shock reemplazan las
            # barras reales; identificarlas por fecha directamente (base_date
            # +1..+3 días hábiles).
            shock_days = []
            nxt = base_date
            for _ in range(3):
                nxt += pd.Timedelta(days=1)
                while nxt.weekday() >= 5:
                    nxt += pd.Timedelta(days=1)
                shock_days.append(nxt)
            sd = shock_days[0]
            for sym, df in data.items():
                # alinear la hora de sd a la del índice del DF (04:00 UTC en
                # datos US; el get_loc falla si las horas difieren)
                sd_loc = sd.replace(
                    hour=df.index[-1].hour, minute=0, second=0, microsecond=0)
                prev = df.index.get_loc(sd_loc) - 1
                open_prev = float(df["close"].iloc[prev])
                open_new = open_prev * 1.02
                close_new = open_new * (1 - 0.17)
                mask = df.index.normalize() == sd_loc.normalize()
                df.loc[mask, "open"] = open_new
                df.loc[mask, "high"] = open_new
                df.loc[mask, "low"] = close_new
                df.loc[mask, "close"] = close_new
                df.loc[mask, "volume"] = (
                    df.loc[mask, "volume"] * 3)
            s78["force_bull_until"] = str(sd.date())
        for vname, ith in variants:
            cfg = dict(s78, crash_event=0.03)
            if ith is not None:
                cfg["intraday_stop"] = ith
            row, tdf, _ = run_stress(f"INT_{name}_{ith}", cfg, data,
                                     f"{name} / {vname}")
            row["escenario"] = name
            rows.append(row)
            print(f"[{name} / {vname}] ${row['equity']} "
                  f"({row['retorno_pct']:+.1f}%) dd={row['max_drawdown_pct']}%")

    # ventana real abr-ago 2026 (con comisiones) — costo de falsos positivos
    print("\nVentana real abr-ago 2026 (sin churn por comisiones):")
    data_real = base
    sc_real = dict(sc, window_dates=("2026-04-01", "2026-08-14"))
    for vname, ith in variants:
        cfg = dict(sc_real, crash_event=0.03)
        if ith is not None:
            cfg["intraday_stop"] = ith
        row, tdf, _ = run_stress(f"INT_real_{ith}", cfg, data_real,
                                 f"Real abr-ago / {vname}")
        row["escenario"] = "Real abr-ago 2026"
        rows.append(row)
        print(f"[Real / {vname}] ${row['equity']} ({row['retorno_pct']:+.1f}%) "
              f"dd={row['max_drawdown_pct']}% trades={row['trades']}")

    out_dir = "/home/ubuntu/backtests"
    os.makedirs(out_dir, exist_ok=True)
    pd.DataFrame(rows).to_csv(f"{out_dir}/bt_intraday_resumen.csv", index=False)
    print(f"\nResumen guardado en {out_dir}/bt_intraday_resumen.csv")


if __name__ == "__main__":
    main()
