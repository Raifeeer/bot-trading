"""Ronda 3 — ¿Sobrevive la ventaja a los costes reales de ejecución?

Las rondas 1 y 2 miden la señal. Esta mide si queda algo después del roce
de operar. En opciones de capital pequeño el roce es brutal: un spread
vertical son 2 patas, y cada entrada+salida paga 4 comisiones. Con primas
netas de $5-$12 (las reales medidas en la cadena de Alpaca el 17 ago 2026:
SOFI $5.50, NOK $7.00, TQQQ $10.00, TSLA $6.00), $0.65 por pata significa
$2.60 por operación completa — entre el 20% y el 50% de la prima arriesgada.

Se barre:
  - comision:      $/pata/lado (0 = ideal, 0.65 = típico retail, 1.30 = caro)
  - slippage_pct:  fracción perdida al entrar y al salir (0% a 10%)

sobre las candidatas mejor clasificadas por CONSISTENCIA en la ronda 2
(no por retorno máximo: eso volvería a premiar el azar), más la de
producción como referencia.

La pregunta concreta: ¿a partir de qué nivel de coste la expectativa se
vuelve negativa? Si muere con costes realistas, la estrategia no es
operable por mucho que el backtest sin costes luzca bien.
"""
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop_backtests import CAPITAL_INICIAL, UNI_RETO, run_scenario  # noqa: E402
from round2_consistency import WINDOWS  # noqa: E402

COMISIONES = [0.0, 0.65, 1.30]
SLIPPAGES = [0.0, 0.02, 0.05, 0.10]

_DATA = None


def _init(cache_path):
    global _DATA
    import pickle
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def pick_candidates(out_dir):
    """Top-2 por consistencia de la ronda 2 + producción como referencia.
    Si la ronda 2 no ha corrido, cae a un conjunto por defecto."""
    base = dict(uni="reto", tickers=UNI_RETO, risk_pct=0.15, max_pos=3,
                dte=21, delta_l=0.30, delta_s=0.10, max_rv=None,
                anti_earnings=True)
    prod = dict(base, motor="smc_daily", tp=1.4, sl=0.25, etiqueta="PRODUCCION")

    path = os.path.join(out_dir, "r2_consistencia.csv")
    if not os.path.exists(path):
        print(f"(sin {path}: se usan candidatas por defecto)")
        return [prod,
                dict(base, motor="smc_daily", tp=1.8, sl=0.50, etiqueta="alt1"),
                dict(base, motor="smc_daily", tp=2.0, sl=0.60, etiqueta="alt2")]

    r2 = pd.read_csv(path)
    r2 = r2[~((r2["tp"] == 1.4) & (r2["sl"] == 0.25))]  # excluir producción
    r2 = r2.sort_values(["pct_pos", "ret_med"], ascending=False).head(2)
    cands = [prod]
    for i, r in enumerate(r2.itertuples(), 1):
        cands.append(dict(base, motor=r.motor, tp=r.tp, sl=r.sl,
                          etiqueta=f"top{i}_r2"))
    print("Candidatas (de la ronda 2 por consistencia):")
    for c in cands:
        print(f"  {c['etiqueta']:12} {c['motor']:18} tp{c['tp']}/sl{c['sl']}")
    return cands


def _run_one(job):
    ci, cfg, wi, com, slip = job
    lo, hi = WINDOWS[wi]
    sc = dict(cfg)
    sc.pop("etiqueta", None)
    sc["name"] = f"c{ci}w{wi}"
    sc["window_dates"] = (lo, hi)
    sc["window_days"] = None
    sc["comision"] = com
    sc["slippage_pct"] = slip
    try:
        equity, tdf, _e, dd, _m = run_scenario(f"c{ci}w{wi}", sc, _DATA)
        return dict(ci=ci, win=wi, com=com, slip=slip,
                    ret=(equity / CAPITAL_INICIAL - 1) * 100,
                    trades=len(tdf),
                    pnl_mean=float(tdf["pnl"].mean()) if len(tdf) else np.nan,
                    error="")
    except Exception as e:  # noqa: BLE001
        return dict(ci=ci, win=wi, com=com, slip=slip, ret=np.nan, trades=0,
                    pnl_mean=np.nan, error=f"{type(e).__name__}: {e}"[:100])


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "r3_out")
    os.makedirs(out_dir, exist_ok=True)

    cands = pick_candidates(out_dir)
    jobs = [(ci, c, wi, com, slip)
            for ci, c in enumerate(cands)
            for wi in range(len(WINDOWS))
            for com in COMISIONES
            for slip in SLIPPAGES]
    print(f"\nRonda 3: {len(cands)} candidatas x {len(WINDOWS)} ventanas x "
          f"{len(COMISIONES)} comisiones x {len(SLIPPAGES)} slippages "
          f"= {len(jobs)} corridas")

    ckpt = os.path.join(out_dir, "r3_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["ci"], r["win"], r["com"], r["slip"]))
        print(f"Checkpoint: {len(done)} hechas, se reanuda")
    pending = [j for j in jobs if (j[0], j[2], j[3], j[4]) not in done]
    print(f"Pendientes: {len(pending)}", flush=True)

    t0 = time.time()
    if pending:
        with open(ckpt, "a") as cf:
            with ProcessPoolExecutor(max_workers=4, initializer=_init,
                                     initargs=(cache,)) as ex:
                for k, r in enumerate(ex.map(_run_one, pending, chunksize=4), 1):
                    results.append(r)
                    cf.write(json.dumps(r, default=float) + "\n")
                    cf.flush()
                    if k % 50 == 0:
                        el = time.time() - t0
                        print(f"  {k}/{len(pending)} en {el:.0f}s "
                              f"(ETA {el/k*(len(pending)-k):.0f}s)", flush=True)

    rdf = pd.DataFrame(results).dropna(subset=["ret"])
    rdf.to_csv(f"{out_dir}/r3_raw.csv", index=False)

    etiquetas = {i: c["etiqueta"] for i, c in enumerate(cands)}
    cfgtxt = {i: f"{c['motor']} tp{c['tp']}/sl{c['sl']}"
              for i, c in enumerate(cands)}

    print("\n" + "=" * 92)
    print("SUPERVIVENCIA A COSTES — % de ventanas positivas y retorno mediano")
    print("=" * 92)
    for ci in sorted(etiquetas):
        print(f"\n### {etiquetas[ci]}: {cfgtxt[ci]}")
        sub = rdf[rdf["ci"] == ci]
        if sub.empty:
            print("  (sin datos)")
            continue
        print(f"  {'comis':>6} " + "".join(
            f"{'slip ' + format(s * 100, '.0f') + '%':>16}" for s in SLIPPAGES))
        for com in COMISIONES:
            cells = []
            for slip in SLIPPAGES:
                cell = sub[(sub["com"] == com) & (sub["slip"] == slip)]
                if cell.empty:
                    cells.append(f"{'-':>16}")
                    continue
                pct = (cell["ret"] > 0).mean() * 100
                med = cell["ret"].median()
                cells.append(f"{pct:>5.0f}% {med:>+8.1f}%")
            print(f"  ${com:>5.2f} " + "".join(cells))

    print("\n" + "=" * 92)
    print("PUNTO DE MUERTE DE LA VENTAJA (primer coste con mediana <= 0)")
    print("=" * 92)
    for ci in sorted(etiquetas):
        sub = rdf[rdf["ci"] == ci]
        muerto = None
        for com in COMISIONES:
            for slip in SLIPPAGES:
                cell = sub[(sub["com"] == com) & (sub["slip"] == slip)]
                if not cell.empty and cell["ret"].median() <= 0 and muerto is None:
                    muerto = (com, slip)
        realista = sub[(sub["com"] == 0.65) & (sub["slip"] == 0.05)]
        txt_real = (f"mediana {realista['ret'].median():+.1f}%, "
                    f"{(realista['ret'] > 0).mean() * 100:.0f}% ventanas +"
                    if not realista.empty else "n/d")
        print(f"  {etiquetas[ci]:12} {cfgtxt[ci]:28} "
              f"muere en {str(muerto):>18} | realista(0.65/5%): {txt_real}")

    with open(f"{out_dir}/r3_summary.json", "w") as f:
        json.dump(dict(candidatas=cfgtxt, etiquetas=etiquetas,
                       comisiones=COMISIONES, slippages=SLIPPAGES,
                       n_ventanas=len(WINDOWS)), f, indent=2)
    print(f"\nGuardado {out_dir}/r3_raw.csv y r3_summary.json")


if __name__ == "__main__":
    main()
