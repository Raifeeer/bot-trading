"""Ronda 5 — ¿A qué tamaño de posición deja de importar la comisión?

Diagnóstico unificado de las rondas 1-4: la señal no es el problema dominante,
la COMISIÓN lo es. Un spread vertical paga 4 comisiones por operación completa
($2.60 con $0.65 por pata-lado), y eso es un coste FIJO:

    prima $15   -> comisión = 17%  del capital arriesgado   (backtest)
    prima $289  -> comisión = 0.9%
    prima $777  -> comisión = 0.3%  (dimensionamiento de recuperación en vivo)

Evidencia acumulada:
  - Ronda 3 (calls): sin comisión la estrategia es break-even (50% de ventanas
    positivas, +0.1%); con $0.65 se hunde a 21% y -18.6%.
  - Ronda 4 (puts): `put_choch` gana en 64% de las ventanas bajistas sin
    comisión (+1.1%), y cae a 10.9% y -6.5% con $0.65.

Ambos lados de la estrategia mueren por lo mismo. Esta ronda mide DÓNDE está
el umbral, porque de eso depende que el dimensionamiento sin tope que ya corre
en producción sea una mejora real o solo más varianza.

Método: el backtest trabaja con $100 de capital, así que la prima está atada a
~$15. En vez de inflar el capital, se escala la comisión a la BAJA en la misma
proporción, que es matemáticamente equivalente: lo que importa es el cociente
comisión/prima. Cada nivel se etiqueta con la prima real a la que corresponde.
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

COMISION_BASE = 0.65
PRIMA_BACKTEST = 15.0  # risk_pct 0.15 sobre $100 de capital

# Primas reales a simular. La comisión equivalente mantiene constante el
# cociente comisión/prima: com_eq = 0.65 * (PRIMA_BACKTEST / prima_real).
PRIMAS = [15.0, 50.0, 100.0, 289.0, 777.0]

MOTORES = ["smc_daily", "swing", "put_choch", "regime_hold_cash"]
TP_SLS = [(1.4, 0.25), (1.5, 0.50)]

_DATA = None


def _init(cache_path):
    global _DATA
    import pickle
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def comision_equivalente(prima_real: float) -> float:
    return COMISION_BASE * (PRIMA_BACKTEST / float(prima_real))


def build_grid():
    return [dict(motor=m, tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                 delta_l=0.30, delta_s=0.10, tp=tp, sl=sl, max_rv=None,
                 anti_earnings=True)
            for m in MOTORES for tp, sl in TP_SLS]


def _run_one(job):
    idx, cfg, wi, prima = job
    lo, hi = WINDOWS[wi]
    sc = dict(cfg)
    sc["name"] = f"s{idx}w{wi}"
    sc["window_dates"] = (lo, hi)
    sc["window_days"] = None
    sc["comision"] = comision_equivalente(prima)
    try:
        eq, tdf, _ec, dd, _mx = run_scenario(f"s{idx}w{wi}", sc, _DATA)
        return dict(idx=idx, win=wi, prima=prima, error="",
                    ret=(eq / CAPITAL_INICIAL - 1) * 100, trades=len(tdf),
                    wr=float(tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0)
    except Exception as e:  # noqa: BLE001
        return dict(idx=idx, win=wi, prima=prima, ret=np.nan, trades=0, wr=0.0,
                    error=f"{type(e).__name__}: {e}"[:110])


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "r5_out")
    os.makedirs(out_dir, exist_ok=True)

    import pickle
    with open(cache, "rb") as f:
        regimenes = clasificar_ventanas(pickle.load(f))

    print("Equivalencia tamaño <-> comisión")
    print("  (el backtest opera primas de ~$%.0f; se baja la comisión para que"
          % PRIMA_BACKTEST)
    print("   el cociente comisión/prima iguale el de la prima real)")
    for p in PRIMAS:
        ce = comision_equivalente(p)
        # El lastre se mide SIEMPRE contra la prima del backtest ($15), que es
        # la que el motor arriesga de verdad. Dividir por la prima real daría
        # un número distinto y sin sentido.
        lastre = 4 * ce / PRIMA_BACKTEST * 100
        real = 4 * COMISION_BASE / p * 100
        print(f"  prima real ${p:>7,.0f}  ->  comisión simulada "
              f"${ce:>6.3f}/pata   lastre {lastre:>5.2f}% "
              f"(= {real:.2f}% que paga esa prima en el mundo real)")

    grid = build_grid()
    jobs = [(i, c, w, p) for i, c in enumerate(grid)
            for w in range(len(WINDOWS)) for p in PRIMAS]
    print(f"\nRonda 5: {len(grid)} configs x {len(WINDOWS)} ventanas x "
          f"{len(PRIMAS)} tamaños = {len(jobs)} corridas", flush=True)

    ckpt = os.path.join(out_dir, "r5_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["idx"], r["win"], r["prima"]))
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
                    if k % 100 == 0:
                        el = time.time() - t0
                        print(f"  {k}/{len(pending)} en {el:.0f}s "
                              f"(ETA {el/k*(len(pending)-k):.0f}s)", flush=True)

    rdf = pd.DataFrame(results).dropna(subset=["ret"])
    gdf = pd.DataFrame(grid).drop(columns=["tickers"])
    gdf["idx"] = range(len(gdf))
    rdf = rdf.merge(gdf, on="idx")
    rdf["regimen"] = rdf["win"].map(lambda w: regimenes[w][0])
    rdf.to_csv(f"{out_dir}/r5_raw.csv", index=False)

    print("\n" + "=" * 90)
    print("EFECTO DEL TAMAÑO — % de ventanas positivas y retorno mediano")
    print("=" * 90)
    print(f"{'motor':18} {'tp/sl':10} " +
          "".join(f"{'$'+format(p,'.0f'):>17}" for p in PRIMAS))
    for motor in MOTORES:
        for tp, sl in TP_SLS:
            sub = rdf[(rdf["motor"] == motor) & (rdf["tp"] == tp)
                      & (rdf["sl"] == sl)]
            if sub.empty:
                continue
            cells = []
            for p in PRIMAS:
                c = sub[sub["prima"] == p]
                if c.empty:
                    cells.append(f"{'-':>17}")
                else:
                    cells.append(f"{(c['ret']>0).mean()*100:>5.0f}% "
                                 f"{c['ret'].median():>+9.1f}%")
            print(f"{motor:18} {f'{tp}/{sl}':10} " + "".join(cells))

    print("\n" + "=" * 90)
    print("SOLO VENTANAS BAJISTAS (donde los puts deben aportar)")
    print("=" * 90)
    baja = rdf[rdf["regimen"] == "baja"]
    print(f"{'motor':18} " + "".join(f"{'$'+format(p,'.0f'):>17}" for p in PRIMAS))
    for motor in MOTORES:
        sub = baja[baja["motor"] == motor]
        if sub.empty:
            continue
        cells = []
        for p in PRIMAS:
            c = sub[sub["prima"] == p]
            cells.append(f"{(c['ret']>0).mean()*100:>5.0f}% "
                         f"{c['ret'].median():>+9.1f}%" if not c.empty
                         else f"{'-':>17}")
        print(f"{motor:18} " + "".join(cells))

    print("\n--- Umbral: primer tamaño con mediana > 0 y >50% de ventanas ---")
    for motor in MOTORES:
        for tp, sl in TP_SLS:
            sub = rdf[(rdf["motor"] == motor) & (rdf["tp"] == tp)
                      & (rdf["sl"] == sl)]
            umbral = None
            for p in PRIMAS:
                c = sub[sub["prima"] == p]
                if not c.empty and c["ret"].median() > 0 \
                        and (c["ret"] > 0).mean() > 0.5:
                    umbral = p
                    break
            print(f"  {motor:18} tp{tp}/sl{sl}: "
                  f"{'prima $'+format(umbral,'.0f') if umbral else 'nunca'}")

    print(f"\nGuardado {out_dir}/r5_raw.csv")


if __name__ == "__main__":
    main()
