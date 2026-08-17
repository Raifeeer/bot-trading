"""Ronda 2 — Consistencia temporal de las configuraciones candidatas.

La ronda 1 (walkforward.py) responde "¿qué configuración sobrevive fuera de
muestra?" usando UNA división TRAIN/VALID/TEST. Eso deja una duda: el
resultado en TEST pudo ser suerte de esa ventana concreta.

Esta ronda responde la pregunta que de verdad importa para operar dinero:
¿la configuración gana de forma CONSISTENTE, o solo en ventanas concretas?

Método: cada candidata se corre en N ventanas consecutivas e independientes
(bloques de ~2 meses que cubren todo el histórico disponible). Se reporta la
distribución de resultados por ventana, no un único número agregado:
  - % de ventanas positivas   <- la métrica de consistencia
  - mediana / peor ventana    <- lo que hay que estar dispuesto a aguantar
  - nº de ventanas sin trades <- cuánto del "no pierde" es simplemente no operar

Un retorno alto con 20% de ventanas positivas NO es una estrategia: es una
lotería que acertó una vez.
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop_backtests import (CAPITAL_INICIAL, UNI_RETO, run_scenario)  # noqa: E402

UNIVERSOS = {
    "reto": UNI_RETO,
    "baratos": ["SOFI", "F", "NOK", "BB"],
}

# Bloques consecutivos de ~2 meses sobre el histórico cacheado
# (2024-03-05 -> 2026-08-13). Disjuntos: cada uno es una prueba independiente.
WINDOWS = [
    ("2024-03-05", "2024-05-05"), ("2024-05-06", "2024-07-06"),
    ("2024-07-07", "2024-09-07"), ("2024-09-08", "2024-11-08"),
    ("2024-11-09", "2025-01-09"), ("2025-01-10", "2025-03-10"),
    ("2025-03-11", "2025-05-11"), ("2025-05-12", "2025-07-12"),
    ("2025-07-13", "2025-09-13"), ("2025-09-14", "2025-11-14"),
    ("2025-11-15", "2026-01-15"), ("2026-01-16", "2026-03-16"),
    ("2026-03-17", "2026-05-17"), ("2026-05-18", "2026-08-13"),
]

_DATA = None


def _init(cache_path):
    global _DATA
    import pickle
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def build_candidates():
    """Candidatas: la de PRODUCCIÓN y las alternativas con mejor relación
    ganancia/pérdida. Se mantiene deliberadamente pequeño: el objetivo es
    medir consistencia de pocas opciones, no barrer una rejilla enorme
    (eso invita a elegir la que mejor quedó por azar)."""
    cands = []
    for motor in ("smc_daily", "swing", "regime_hold_cash", "hold_weekly"):
        for uni in ("reto",):
            for tp, sl in ((1.4, 0.25),   # PRODUCCIÓN
                           (1.5, 0.50),
                           (1.8, 0.50),
                           (2.0, 0.60)):
                cands.append(dict(
                    motor=motor, uni=uni, tickers=UNIVERSOS[uni],
                    risk_pct=0.15, max_pos=3, dte=21,
                    delta_l=0.30, delta_s=0.10, tp=tp, sl=sl,
                    max_rv=None, anti_earnings=True, comision=0.65))
    return cands


def _run_one(job):
    idx, cfg, wi = job
    lo, hi = WINDOWS[wi]
    sc = dict(cfg)
    sc["name"] = f"c{idx}w{wi}"
    sc["window_dates"] = (lo, hi)
    sc["window_days"] = None
    try:
        equity, tdf, _e, dd, _m = run_scenario(f"c{idx}w{wi}", sc, _DATA)
        return dict(idx=idx, win=wi, ret=(equity / CAPITAL_INICIAL - 1) * 100,
                    trades=len(tdf), dd=dd,
                    wr=float(tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0,
                    error="")
    except Exception as e:  # noqa: BLE001
        return dict(idx=idx, win=wi, ret=np.nan, trades=0, dd=np.nan,
                    wr=0.0, error=f"{type(e).__name__}: {e}"[:100])


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "r2_out")
    os.makedirs(out_dir, exist_ok=True)

    cands = build_candidates()
    jobs = [(i, c, w) for i, c in enumerate(cands) for w in range(len(WINDOWS))]
    print(f"Ronda 2: {len(cands)} candidatas x {len(WINDOWS)} ventanas "
          f"= {len(jobs)} corridas")

    ckpt = os.path.join(out_dir, "r2_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["idx"], r["win"]))
        print(f"Checkpoint: {len(done)} hechas, se reanuda")
    pending = [j for j in jobs if (j[0], j[2]) not in done]
    print(f"Pendientes: {len(pending)}", flush=True)

    t0 = time.time()
    if pending:
        with open(ckpt, "a") as cf:
            with ProcessPoolExecutor(max_workers=4, initializer=_init,
                                     initargs=(cache,)) as ex:
                for k, r in enumerate(ex.map(_run_one, pending, chunksize=2), 1):
                    results.append(r)
                    cf.write(json.dumps(r, default=float) + "\n")
                    cf.flush()
                    if k % 25 == 0:
                        el = time.time() - t0
                        print(f"  {k}/{len(pending)} en {el:.0f}s "
                              f"(ETA {el/k*(len(pending)-k):.0f}s)", flush=True)

    rdf = pd.DataFrame(results)
    cdf = pd.DataFrame(cands)
    cdf["idx"] = range(len(cdf))
    cdf = cdf.drop(columns=["tickers"])
    rdf.to_csv(f"{out_dir}/r2_raw.csv", index=False)

    print("\n" + "=" * 96)
    print("CONSISTENCIA POR CANDIDATA — cada fila resume 14 ventanas "
          "independientes de ~2 meses")
    print("=" * 96)
    rows = []
    for _i, c in cdf.iterrows():
        sub = rdf[rdf["idx"] == c["idx"]].dropna(subset=["ret"])
        if sub.empty:
            continue
        traded = sub[sub["trades"] > 0]
        rows.append(dict(
            motor=c["motor"], tp=c["tp"], sl=c["sl"],
            vent=len(sub),
            vent_con_trades=len(traded),
            pct_pos=round((sub["ret"] > 0).mean() * 100),
            ret_med=round(sub["ret"].median(), 1),
            ret_peor=round(sub["ret"].min(), 1),
            ret_mejor=round(sub["ret"].max(), 1),
            trades_tot=int(sub["trades"].sum()),
            wr_med=round(traded["wr"].median(), 0) if len(traded) else 0,
            prod="<<<" if (c["tp"] == 1.4 and c["sl"] == 0.25) else "",
        ))
    sdf = pd.DataFrame(rows).sort_values(["pct_pos", "ret_med"],
                                         ascending=False)
    print(sdf.to_string(index=False))

    sdf.to_csv(f"{out_dir}/r2_consistencia.csv", index=False)
    print(f"\nGuardado {out_dir}/r2_consistencia.csv")

    print("\n--- Lectura honesta ---")
    prod = sdf[sdf["prod"] == "<<<"]
    if len(prod):
        print(f"PRODUCCIÓN (tp1.4/sl0.25): "
              f"% ventanas positivas mediana {prod['pct_pos'].median():.0f}%, "
              f"retorno mediano {prod['ret_med'].median():+.1f}%")
    best = sdf.head(3)
    print("Mejores por consistencia:")
    for _, r in best.iterrows():
        print(f"  {r['motor']:18} tp{r['tp']}/sl{r['sl']}: "
              f"{r['pct_pos']:.0f}% ventanas positivas, "
              f"mediana {r['ret_med']:+.1f}%, peor {r['ret_peor']:+.1f}%, "
              f"{r['trades_tot']} trades")


if __name__ == "__main__":
    main()
