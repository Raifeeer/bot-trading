"""Walk-forward out-of-sample sobre la rejilla de configuraciones.

Objetivo: separar "lo que funciona" de "lo que se ve bien en la muestra".
La trampa clásica de este repo (documentada en docs/skills/backtest_skill.md
§8) es elegir el escenario ganador mirando la misma ventana en la que se
midió; eso produce números altos que no sobreviven fuera de muestra.

Método:
  1. Se parte el histórico en TRAIN / VALID / TEST disjuntos y cronológicos.
  2. Cada configuración de la rejilla se corre en las tres ventanas.
  3. La selección SOLO puede mirar TRAIN (+VALID). TEST se reserva.
  4. Se reporta:
       - rendimiento en TEST de las mejores por TRAIN,
       - distribución en TEST de TODAS las configs (línea base de azar),
       - correlación de rangos TRAIN vs TEST (si ~0, no hay generalización).

Uso: BT_CACHE=data/bt_cache_1d.pkl python3 walkforward.py
"""
import json
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop_backtests import (CAPITAL_INICIAL, UNI_RETO, UNI_TECH, UNI_ETF,  # noqa: E402
                            run_scenario)

# Ventanas disjuntas y cronológicas. TEST no se mira hasta el final.
SPLITS = {
    "TRAIN": ("2024-03-05", "2025-06-30"),
    "VALID": ("2025-07-01", "2026-01-31"),
    "TEST": ("2026-02-01", "2026-08-13"),
}

UNIVERSOS = {
    "reto": UNI_RETO,
    "tech": UNI_TECH,
    "etf": UNI_ETF,
    "baratos": ["SOFI", "F", "NOK", "BB"],
}

_DATA = None


def _init(cache_path):
    global _DATA
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def build_grid():
    """Rejilla de configuraciones. Amplia a propósito: la idea no es que
    todas sean buenas, sino medir cuánta dispersión hay y si el ranking en
    TRAIN predice algo en TEST."""
    grid = []
    motores = ["smc_daily", "swing", "regime_hold_cash", "hold_weekly",
               "rebote_rsi40"]
    # La pregunta central: la config de PRODUCCIÓN (tp 1.4 / sl 0.25) exige un
    # 65.2% de acierto para no perder, y ningún escenario del corpus histórico
    # (máx 64%, mediana 47%) lo alcanza. Se barren alternativas con mejor
    # relación ganancia/pérdida para ver cuáles sobreviven fuera de muestra.
    tp_sls = [
        (1.4, 0.25),   # producción actual
        (1.3, 0.50),
        (1.5, 0.50),
        (1.5, 0.35),
        (1.8, 0.50),
        (1.5, 0.60),
        (2.0, 0.60),
    ]
    for motor in motores:
        for uni_name in ("reto", "baratos"):
            for dte in (21, 30):
                for tp, sl in tp_sls:
                    grid.append(dict(
                        motor=motor, uni=uni_name,
                        tickers=UNIVERSOS[uni_name],
                        risk_pct=0.15, max_pos=3, dte=dte,
                        delta_l=0.30, delta_s=0.10,
                        tp=tp, sl=sl, max_rv=None,
                        anti_earnings=True, comision=0.65))
    return grid


def _run_one(job):
    idx, cfg, split_name = job
    lo, hi = SPLITS[split_name]
    sc = dict(cfg)
    sc["name"] = f"cfg{idx}"
    sc["window_dates"] = (lo, hi)
    sc["window_days"] = None
    try:
        equity, tdf, _ecdf, dd_pct, _max_eq = run_scenario(f"cfg{idx}", sc, _DATA)
        ret = (equity / CAPITAL_INICIAL - 1) * 100
        n = len(tdf)
        wr = float(tdf["pnl"].gt(0).mean() * 100) if n else 0.0
        pnl_std = float(tdf["pnl"].std()) if n > 1 else 0.0
        pnl_mean = float(tdf["pnl"].mean()) if n else 0.0
    except Exception as e:  # noqa: BLE001
        return dict(idx=idx, split=split_name, error=f"{type(e).__name__}: {e}"[:120],
                    ret=np.nan, trades=0, wr=0.0, dd=np.nan,
                    pnl_mean=np.nan, pnl_std=np.nan)
    return dict(idx=idx, split=split_name, error="", ret=ret, trades=n,
                wr=wr, dd=dd_pct, pnl_mean=pnl_mean, pnl_std=pnl_std)


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "wf_out")
    os.makedirs(out_dir, exist_ok=True)

    grid = build_grid()
    print(f"Rejilla: {len(grid)} configuraciones x {len(SPLITS)} ventanas "
          f"= {len(grid)*len(SPLITS)} corridas")

    jobs = [(i, cfg, sp) for i, cfg in enumerate(grid) for sp in SPLITS]

    # Checkpoint incremental: cada corrida se apunta a un JSONL en cuanto
    # termina, y al arrancar se saltan las ya hechas. Un reinicio del
    # contenedor (o del proceso) no cuesta volver a empezar de cero.
    ckpt = os.path.join(out_dir, "walkforward_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["idx"], r["split"]))
        print(f"Checkpoint: {len(done)} corridas ya hechas, se reanuda")
    pending = [j for j in jobs if (j[0], j[2]) not in done]
    print(f"Pendientes: {len(pending)}")

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
    gdf = pd.DataFrame(grid)
    gdf["idx"] = range(len(gdf))
    gdf = gdf.drop(columns=["tickers"])

    wide = rdf.pivot(index="idx", columns="split",
                     values=["ret", "trades", "wr", "dd"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    full = gdf.merge(wide.reset_index(), on="idx")
    full.to_csv(f"{out_dir}/walkforward_grid.csv", index=False)
    print(f"\nGuardado {out_dir}/walkforward_grid.csv")

    # --- Análisis honesto -------------------------------------------------
    MIN_TRADES = 10
    valid = full[(full["trades_TRAIN"] >= MIN_TRADES)
                 & (full["trades_TEST"] >= MIN_TRADES)].copy()
    print(f"\nConfigs con >={MIN_TRADES} trades en TRAIN y TEST: "
          f"{len(valid)}/{len(full)}")
    if valid.empty:
        print("Sin configs suficientes para concluir.")
        return

    from scipy import stats as _st
    rho, pval = _st.spearmanr(valid["ret_TRAIN"], valid["ret_TEST"])
    rho_v, pval_v = _st.spearmanr(valid["ret_VALID"], valid["ret_TEST"])
    print(f"\nCorrelación de rangos TRAIN vs TEST: rho={rho:+.3f} (p={pval:.3f})")
    print(f"Correlación de rangos VALID vs TEST: rho={rho_v:+.3f} (p={pval_v:.3f})")
    print("  (rho ~ 0 => el ranking en la ventana de ajuste no predice "
          "nada fuera de muestra)")

    print(f"\nTEST — todas las configs válidas: "
          f"mediana {valid['ret_TEST'].median():+.1f}%  "
          f"media {valid['ret_TEST'].mean():+.1f}%  "
          f"p25 {valid['ret_TEST'].quantile(.25):+.1f}%  "
          f"p75 {valid['ret_TEST'].quantile(.75):+.1f}%  "
          f"%>0 {(valid['ret_TEST']>0).mean()*100:.0f}%")

    top_train = valid.nlargest(10, "ret_TRAIN")
    print("\n=== Top 10 elegidas SOLO por TRAIN, y su resultado en TEST ===")
    cols = ["idx", "motor", "uni", "risk_pct", "dte", "delta_l", "delta_s",
            "tp", "sl", "ret_TRAIN", "ret_VALID", "ret_TEST",
            "trades_TEST", "wr_TEST", "dd_TEST"]
    print(top_train[cols].to_string(index=False))
    print(f"\nMediana en TEST de esas top-10: "
          f"{top_train['ret_TEST'].median():+.1f}%  "
          f"vs mediana global {valid['ret_TEST'].median():+.1f}%")

    # Selección honesta: mejor por TRAIN+VALID combinados
    valid["score_sel"] = valid[["ret_TRAIN", "ret_VALID"]].min(axis=1)
    top_sel = valid.nlargest(10, "score_sel")
    print("\n=== Top 10 por min(TRAIN, VALID) — selección robusta ===")
    print(top_sel[cols].to_string(index=False))
    print(f"\nMediana en TEST de esa selección: "
          f"{top_sel['ret_TEST'].median():+.1f}%")

    # Por motor
    print("\n=== TEST por motor (mediana) ===")
    bym = valid.groupby("motor").agg(
        n=("idx", "count"),
        ret_TRAIN_med=("ret_TRAIN", "median"),
        ret_TEST_med=("ret_TEST", "median"),
        ret_TEST_p75=("ret_TEST", lambda s: s.quantile(.75)),
        pct_pos_TEST=("ret_TEST", lambda s: (s > 0).mean() * 100),
        trades_TEST_med=("trades_TEST", "median"),
    ).round(1).sort_values("ret_TEST_med", ascending=False)
    print(bym.to_string())

    summary = dict(
        n_configs=len(full), n_valid=len(valid),
        rho_train_test=float(rho), p_train_test=float(pval),
        rho_valid_test=float(rho_v),
        test_median_all=float(valid["ret_TEST"].median()),
        test_median_top10_train=float(top_train["ret_TEST"].median()),
        test_median_top10_sel=float(top_sel["ret_TEST"].median()),
        splits=SPLITS,
    )
    with open(f"{out_dir}/walkforward_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResumen en {out_dir}/walkforward_summary.json")


if __name__ == "__main__":
    main()
