"""Ronda 4 — Estrategias a la baja (put spreads).

Contexto: el bot en producción es estructuralmente LONG-ONLY (cuatro puertas
lo impiden: direction=bull fijo en config, la puerta de entrada exige régimen
bull, el gestor rechaza señales SHORT, y put_choch_entry se calcula pero nadie
lo consume). Eso explica que en las rondas 1-3 los dos periodos no alcistas
dieran 0% de configuraciones rentables: sin puts el bot no tiene forma de
ganar dinero cuando el mercado cae.

La pregunta que decide si merece la pena conectarlos NO es "¿ganan los puts?"
sino:

    ¿Añadir puts en régimen bear gana MÁS que quedarse en cash?

Porque quedarse en cash ya es una opción válida y de riesgo cero. De ahí la
comparación cara a cara `regime_aware` (bull->calls, bear->puts) contra
`regime_hold_cash` (bull->calls, bear->cash), sobre las mismas ventanas.

Se aplican las lecciones de las rondas anteriores:
  - motor de backtest ya corregido (universo, bancarrota, 4 contabilidades),
  - ventanas independientes en vez de una sola división,
  - la ronda 3 demostró que la COMISIÓN es lo que mata la ventaja, así que se
    mide con y sin ella y se etiqueta cada ventana por régimen real de SPY
    (los puts solo pueden ayudar donde el mercado cae).
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
from round2_consistency import WINDOWS as _VENTANAS_REGULARES  # noqa: E402

# Las 14 ventanas regulares de la ronda 2 miden retorno PUNTA A PUNTA, lo que
# esconde las caídas internas: solo 2 de 14 salían "baja" pese a que el
# dataset contiene un drawdown del -19% (feb-jun 2025) y otro del -9.1%
# (mar-abr 2026). Los put spreads ganan por el CAMINO, no por los extremos,
# así que juzgarlos solo con esas ventanas sería injusto. Estas se alinean a
# los episodios de caída reales medidos sobre SPY en el propio dataset.
VENTANAS_BAJISTAS = [
    ("2024-07-24", "2024-08-19"),  # dd -8.4%
    ("2024-12-18", "2025-01-21"),  # dd -4.5%
    ("2025-02-25", "2025-04-30"),  # fase de descenso del -19%
    ("2025-02-25", "2025-06-25"),  # episodio completo -19%
    ("2025-11-17", "2025-11-28"),  # dd -5.1%
    ("2026-03-06", "2026-04-14"),  # dd -9.1%
    ("2026-06-10", "2026-07-10"),  # dd -4.5% / -4.0%
]
WINDOWS = list(_VENTANAS_REGULARES) + VENTANAS_BAJISTAS
N_REGULARES = len(_VENTANAS_REGULARES)

# put_choch / put_smc: puts puros. regime_aware: bull->calls, bear->puts.
# regime_hold_cash: bull->calls, bear->CASH — la referencia a batir.
MOTORES = ["put_choch", "put_smc", "regime_aware", "regime_hold_cash"]
TP_SLS = [(1.4, 0.25), (1.5, 0.50), (1.8, 0.50), (2.0, 0.60)]
DTES = [21, 30]
COMISIONES = [0.0, 0.65]

_DATA = None


def _init(cache_path):
    global _DATA
    import pickle
    with open(cache_path, "rb") as f:
        _DATA = pickle.load(f)


def clasificar_ventanas(data) -> dict:
    """Etiqueta cada ventana por SPY, mirando retorno Y caída interna.

    Clasificar solo por retorno punta a punta esconde los drawdowns, que es
    justo de donde vive un put spread. Una ventana que empieza y acaba igual
    pero cae un 12% por medio es una oportunidad para puts, no una lateral.
    Devuelve {i: (etiqueta, retorno, drawdown_maximo)}.
    """
    spy = data.get("SPY")
    out = {}
    for i, (lo, hi) in enumerate(WINDOWS):
        if spy is None:
            out[i] = ("?", float("nan"), float("nan"))
            continue
        sub = spy[(spy.index >= pd.Timestamp(lo, tz="UTC"))
                  & (spy.index <= pd.Timestamp(hi, tz="UTC"))]
        if len(sub) < 5:
            out[i] = ("?", float("nan"), float("nan"))
            continue
        c = sub["close"].astype(float)
        r = (float(c.iloc[-1]) / float(c.iloc[0]) - 1) * 100
        dd = float(((c / c.cummax()) - 1).min() * 100)
        if r < -2 or dd <= -6:
            etiqueta = "baja"
        elif r > 2:
            etiqueta = "sube"
        else:
            etiqueta = "lateral"
        out[i] = (etiqueta, r, dd)
    return out


def build_grid():
    grid = []
    for motor in MOTORES:
        for dte in DTES:
            for tp, sl in TP_SLS:
                grid.append(dict(
                    motor=motor, tickers=UNI_RETO, risk_pct=0.15, max_pos=3,
                    dte=dte, delta_l=0.30, delta_s=0.10, tp=tp, sl=sl,
                    max_rv=None, anti_earnings=True))
    return grid


def _run_one(job):
    idx, cfg, wi, com = job
    lo, hi = WINDOWS[wi]
    sc = dict(cfg)
    sc["name"] = f"p{idx}w{wi}"
    sc["window_dates"] = (lo, hi)
    sc["window_days"] = None
    sc["comision"] = com
    try:
        eq, tdf, _ec, dd, _mx = run_scenario(f"p{idx}w{wi}", sc, _DATA)
        return dict(idx=idx, win=wi, com=com, error="",
                    ret=(eq / CAPITAL_INICIAL - 1) * 100,
                    trades=len(tdf), dd=dd,
                    wr=float(tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0)
    except Exception as e:  # noqa: BLE001
        return dict(idx=idx, win=wi, com=com, ret=np.nan, trades=0, dd=np.nan,
                    wr=0.0, error=f"{type(e).__name__}: {e}"[:110])


def main():
    cache = os.environ.get("BT_CACHE", "data/bt_cache_1d.pkl")
    out_dir = os.environ.get("BT_OUT", "r4_out")
    os.makedirs(out_dir, exist_ok=True)

    import pickle
    with open(cache, "rb") as f:
        data0 = pickle.load(f)
    regimenes = clasificar_ventanas(data0)
    print("Régimen real de cada ventana (SPY: retorno y caída interna):")
    for i, (lo, hi) in enumerate(WINDOWS):
        et, r, dd = regimenes[i]
        marca = "  <- bajista añadida" if i >= N_REGULARES else ""
        print(f"  w{i:<2} {lo} -> {hi}  SPY ret {r:+6.1f}%  dd {dd:+6.1f}%  "
              f"{et}{marca}")
    n_baja = sum(1 for i in regimenes if regimenes[i][0] == "baja")
    print(f"\nVentanas a la baja: {n_baja}/{len(WINDOWS)} "
          f"(donde los puts pueden aportar)")

    grid = build_grid()
    jobs = [(i, c, w, com) for i, c in enumerate(grid)
            for w in range(len(WINDOWS)) for com in COMISIONES]
    print(f"\nRonda 4: {len(grid)} configs x {len(WINDOWS)} ventanas x "
          f"{len(COMISIONES)} comisiones = {len(jobs)} corridas")

    ckpt = os.path.join(out_dir, "r4_ckpt.jsonl")
    results, done = [], set()
    if os.path.exists(ckpt):
        with open(ckpt) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                results.append(r)
                done.add((r["idx"], r["win"], r["com"]))
        print(f"Checkpoint: {len(done)} hechas, se reanuda")
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
    gdf = pd.DataFrame(grid).drop(columns=["tickers"])
    gdf["idx"] = range(len(gdf))
    rdf = rdf.merge(gdf, on="idx")
    rdf["regimen"] = rdf["win"].map(lambda w: regimenes[w][0])
    rdf["dd_spy"] = rdf["win"].map(lambda w: regimenes[w][2])
    rdf.to_csv(f"{out_dir}/r4_raw.csv", index=False)

    for com in COMISIONES:
        etiqueta = "SIN comisión" if com == 0 else f"comisión ${com}"
        print("\n" + "=" * 94)
        print(f"PUTS POR MOTOR — {etiqueta}")
        print("=" * 94)
        sub = rdf[rdf["com"] == com]
        t = sub.groupby("motor").agg(
            n=("idx", "count"),
            trades=("trades", "sum"),
            pct_vent_pos=("ret", lambda s: (s > 0).mean() * 100),
            ret_med=("ret", "median"),
            ret_peor=("ret", "min"),
            wr_med=("wr", "median"),
        ).round(1).sort_values("ret_med", ascending=False)
        print(t.to_string())

        print(f"\n  Solo ventanas A LA BAJA ({etiqueta}) — donde los puts "
              f"deberían aportar:")
        baja = sub[sub["regimen"] == "baja"]
        if baja.empty:
            print("    (sin ventanas clasificadas a la baja)")
        else:
            tb = baja.groupby("motor").agg(
                n=("idx", "count"), trades=("trades", "sum"),
                pct_pos=("ret", lambda s: (s > 0).mean() * 100),
                ret_med=("ret", "median"), ret_mejor=("ret", "max"),
            ).round(1).sort_values("ret_med", ascending=False)
            print(tb.to_string())

    # --- La comparación que decide: puts en bear vs cash en bear -----------
    print("\n" + "=" * 94)
    print("¿AÑADIR PUTS GANA MÁS QUE QUEDARSE EN CASH?")
    print("  regime_aware (bear->puts)  vs  regime_hold_cash (bear->cash)")
    print("=" * 94)
    for com in COMISIONES:
        sub = rdf[(rdf["com"] == com)
                  & rdf["motor"].isin(["regime_aware", "regime_hold_cash"])]
        if sub.empty:
            continue
        piv = sub.pivot_table(index=["win", "regimen"], columns="motor",
                              values="ret", aggfunc="median")
        if not {"regime_aware", "regime_hold_cash"} <= set(piv.columns):
            continue
        piv["ventaja_puts"] = piv["regime_aware"] - piv["regime_hold_cash"]
        etiqueta = "SIN comisión" if com == 0 else f"comisión ${com}"
        print(f"\n--- {etiqueta} ---")
        print(piv.round(1).to_string())
        gana = (piv["ventaja_puts"] > 0).sum()
        print(f"  Ventanas donde los puts baten al cash: {gana}/{len(piv)}")
        print(f"  Ventaja mediana de los puts: "
              f"{piv['ventaja_puts'].median():+.1f} puntos")
        b = piv[piv.index.get_level_values("regimen") == "baja"]
        if len(b):
            print(f"  Solo en ventanas a la baja: "
                  f"{(b['ventaja_puts'] > 0).sum()}/{len(b)} favorables, "
                  f"ventaja mediana {b['ventaja_puts'].median():+.1f} puntos")

    print(f"\nGuardado {out_dir}/r4_raw.csv")


if __name__ == "__main__":
    main()
