"""Ronda 6 — La tabla de decisión documentada, medida pata por pata.

`docs/skills/wheel_skill.md` §4 define un playbook régimen -> estructura que
nunca se ha medido como conjunto:

| Régimen                          | Estructura documentada                    | Ref |
|----------------------------------|-------------------------------------------|-----|
| Bull                             | call debit 0.25/0.10, DTE 10-45, cierre 7 | S51 |
| CHoCH bear (>=30% del universo)  | put spread 0.30/0.10, DTE 21, TP1.5/SL0.5 | S63 |
| Lateral                          | cash, no operar                           | S55 |
| Rebote en selloff (RSI<25 >SMA100)| call spread 0.30/0.10, DTE 21, budget 15%| S36 |
| Bear suave HTF (sin CHoCH)       | cash + hold solo si bull local            | S78 |

Tres cosas que esta ronda comprueba y que no estaban comprobadas:

1. **La pata de REBOTE no existía.** El skill atribuye a S36 la condición
   "RSI<25 y precio>SMA100" con +53-60% y win 71-75%, pero en el código S36 es
   `motor="smc_daily"`. La condición documentada se implementa ahora como
   motor `rebote_doc` para poder medirla en vez de citarla.

2. **Cada pata se mide en SU régimen, no en promedio.** Un playmaker por
   régimen solo tiene sentido si cada pata gana donde le toca; el agregado
   sobre las 21 ventanas mezcla regímenes y esconde exactamente eso.

3. **A dos tamaños.** La ronda 5 demostró que la comisión (coste fijo, 4 patas
   por operación) decide el signo: a prima ~$15 es el 17% del capital
   arriesgado y hunde cualquier señal; a >=$100 deja de importar. Medir una
   pata solo al tamaño pequeño diría que no sirve cuando el problema es el
   tamaño.
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
from round4_puts import WINDOWS, clasificar_ventanas  # noqa: E402
from round5_size import comision_equivalente  # noqa: E402

# Cada pata del playbook, con los parámetros que dice la documentación.
PATAS = {
    "bull_call_S51":   dict(motor="smc_daily",  delta_l=0.25, delta_s=0.10,
                            dte=30, tp=1.4, sl=0.25),
    "bull_call_v2":    dict(motor="smc_daily",  delta_l=0.30, delta_s=0.10,
                            dte=21, tp=1.5, sl=0.50),
    "swing_call":      dict(motor="swing",      delta_l=0.30, delta_s=0.10,
                            dte=21, tp=1.5, sl=0.50),
    "choch_put_S63":   dict(motor="put_choch",  delta_l=0.30, delta_s=0.10,
                            dte=21, tp=1.5, sl=0.50),
    "rebote_doc_S36":  dict(motor="rebote_doc", delta_l=0.30, delta_s=0.10,
                            dte=21, tp=1.5, sl=0.50),
    "rebote_rsi40":    dict(motor="rebote_rsi40", delta_l=0.30, delta_s=0.10,
                            dte=21, tp=1.5, sl=0.50),
    "cash_ref":        dict(motor="regime_hold_cash", delta_l=0.30,
                            delta_s=0.10, dte=21, tp=1.5, sl=0.50),
}

PRIMAS = [15.0, 289.0]   # tamaño del backtest vs tamaño operativo real

_DATA = None


def _init(cache_path):
    global _DATA
    import pickle
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def _run_one(job):
    nombre, cfg, wi, prima = job
    lo, hi = WINDOWS[wi]
    sc = dict(cfg, name=nombre, tickers=UNI_RETO, risk_pct=0.15, max_pos=3,
              max_rv=None, anti_earnings=True,
              window_dates=(lo, hi), window_days=None,
              comision=comision_equivalente(prima))
    try:
        eq, tdf, _ec, dd, _mx = run_scenario(nombre, sc, _DATA)
        return dict(pata=nombre, win=wi, prima=prima, error="",
                    ret=(eq / CAPITAL_INICIAL - 1) * 100, trades=len(tdf), dd=dd,
                    wr=float(tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0)
    except Exception as e:  # noqa: BLE001
        return dict(pata=nombre, win=wi, prima=prima, ret=np.nan, trades=0,
                    dd=np.nan, wr=0.0, error=f"{type(e).__name__}: {e}"[:110])


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "r6_out")
    os.makedirs(out_dir, exist_ok=True)

    import pickle
    with open(cache, "rb") as f:
        regimenes = clasificar_ventanas(pickle.load(f))

    jobs = [(n, c, w, p) for n, c in PATAS.items()
            for w in range(len(WINDOWS)) for p in PRIMAS]
    print(f"Ronda 6: {len(PATAS)} patas x {len(WINDOWS)} ventanas x "
          f"{len(PRIMAS)} tamaños = {len(jobs)} corridas", flush=True)

    ckpt = os.path.join(out_dir, "r6_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["pata"], r["win"], r["prima"]))
        print(f"Checkpoint: {len(done)} hechas")
    pending = [j for j in jobs if (j[0], j[2], j[3]) not in done]
    print(f"Pendientes: {len(pending)}", flush=True)

    t0 = time.time()
    if pending:
        with open(ckpt, "a") as cf:
            with ProcessPoolExecutor(max_workers=4, initializer=_init,
                                     initargs=(cache,)) as ex:
                for k, r in enumerate(ex.map(_run_one, pending, chunksize=3), 1):
                    results.append(r)
                    cf.write(json.dumps(r, default=float) + "\n")
                    cf.flush()
                    if k % 50 == 0:
                        el = time.time() - t0
                        print(f"  {k}/{len(pending)} en {el:.0f}s "
                              f"(ETA {el/k*(len(pending)-k):.0f}s)", flush=True)

    rdf = pd.DataFrame(results).dropna(subset=["ret"])
    rdf["regimen"] = rdf["win"].map(lambda w: regimenes[w][0])
    rdf.to_csv(f"{out_dir}/r6_raw.csv", index=False)

    for prima in PRIMAS:
        print("\n" + "=" * 98)
        print(f"CADA PATA EN CADA RÉGIMEN — prima ${prima:,.0f} "
              f"(comisión equivalente ${comision_equivalente(prima):.3f}/pata)")
        print("=" * 98)
        sub = rdf[rdf["prima"] == prima]
        regs = ["sube", "lateral", "baja"]
        print(f"{'pata':18}" + "".join(f"{r:>24}" for r in regs) +
              f"{'trades':>9}")
        for nombre in PATAS:
            fila = sub[sub["pata"] == nombre]
            if fila.empty:
                continue
            cells = []
            for reg in regs:
                c = fila[fila["regimen"] == reg]
                if c.empty:
                    cells.append(f"{'-':>24}")
                else:
                    cells.append(f"{(c['ret']>0).mean()*100:>6.0f}% "
                                 f"{c['ret'].median():>+9.1f}%   ")
            print(f"{nombre:18}" + "".join(cells) +
                  f"{int(fila['trades'].sum()):>9}")

    print("\n" + "=" * 98)
    print("MEJOR PATA POR RÉGIMEN (prima $289, criterio: mediana y % positivas)")
    print("=" * 98)
    sub = rdf[rdf["prima"] == 289.0]
    for reg in ["sube", "lateral", "baja"]:
        c = sub[sub["regimen"] == reg]
        if c.empty:
            continue
        t = c.groupby("pata").agg(
            pct=("ret", lambda s: (s > 0).mean() * 100),
            med=("ret", "median"), n=("ret", "count"),
            trades=("trades", "sum")).round(1)
        t = t.sort_values(["med", "pct"], ascending=False)
        print(f"\n--- régimen '{reg}' ---")
        print(t.to_string())
        mejor = t.index[0]
        print(f"  => mejor: {mejor}  (mediana {t.loc[mejor,'med']:+.1f}%, "
              f"{t.loc[mejor,'pct']:.0f}% de ventanas positivas)")
        ref = t.loc["cash_ref"] if "cash_ref" in t.index else None
        if ref is not None:
            print(f"     cash de referencia: mediana {ref['med']:+.1f}%, "
                  f"{ref['pct']:.0f}% positivas -> "
                  f"{'MERECE operar' if t.loc[mejor,'med'] > ref['med'] else 'NO bate al cash'}")

    print(f"\nGuardado {out_dir}/r6_raw.csv")


if __name__ == "__main__":
    main()
