"""Expectativa matemática de la configuración de salida (TP/SL de prima).

Para un spread de débito, `evaluate_exit` cierra en:
  - TP  cuando la prima llega a  entry * tp_mult   -> ganancia (tp_mult-1)*entry
  - SL  cuando la prima cae a    entry * sl_mult   -> pérdida  (1-sl_mult)*entry

De ahí sale el win rate mínimo para no perder dinero:
    p*(tp_mult-1) = (1-p)*(1-sl_mult)
    p_breakeven = (1-sl_mult) / (tp_mult - 1 + 1 - sl_mult)

Este script imprime esa tabla y la compara con los win rates realmente
observados en los backtests, para saber si la configuración de producción es
alcanzable o si pide un acierto que el motor nunca ha demostrado.
"""
import glob
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def breakeven_wr(tp_mult: float, sl_mult: float) -> float:
    gain = tp_mult - 1.0
    loss = 1.0 - sl_mult
    if gain + loss <= 0:
        return float("nan")
    return loss / (gain + loss) * 100.0


def main():
    print("=" * 74)
    print("WIN RATE MÍNIMO PARA NO PERDER DINERO, SEGÚN TP/SL DE PRIMA")
    print("=" * 74)
    print(f"{'TP':>6} {'SL':>6} {'gana':>8} {'pierde':>8} {'R:R':>7} {'WR breakeven':>14}")
    combos = [
        (1.4, 0.25),   # PRODUCCIÓN ACTUAL (config/config.yaml)
        (1.5, 0.25),
        (1.4, 0.50),
        (1.5, 0.50),   # el usado en casi todos los backtests
        (1.8, 0.50),
        (2.0, 0.50),
        (1.5, 0.60),
        (1.4, 0.60),
        (2.0, 0.60),
        (2.0, 0.70),
        (2.5, 0.60),
    ]
    for tp, sl in combos:
        be = breakeven_wr(tp, sl)
        tag = "   <-- PRODUCCIÓN" if (tp, sl) == (1.4, 0.25) else ""
        rr = (tp - 1.0) / (1.0 - sl)
        print(f"{tp:>6.2f} {sl:>6.2f} {(tp-1)*100:>7.0f}% {(1-sl)*100:>7.0f}% "
              f"{rr:>7.2f} {be:>13.1f}%{tag}")

    out_dir = os.environ.get("BT_OUT", "/tmp/bt")
    resumen = os.path.join(out_dir, "bt_resumen.csv")
    if not os.path.exists(resumen):
        print(f"\n(sin {resumen}; se omite la comparación con backtests)")
        return

    df = pd.read_csv(resumen)
    print("\n" + "=" * 74)
    print("WIN RATES REALMENTE OBSERVADOS EN LOS BACKTESTS")
    print("=" * 74)
    sig = df[df["trades"] >= 10].copy()
    print(f"Escenarios con >=10 trades: {len(sig)}/{len(df)}")
    if len(sig):
        print(f"  win_rate  mediana {sig['win_rate'].median():.0f}%   "
              f"media {sig['win_rate'].mean():.0f}%   "
              f"máx {sig['win_rate'].max():.0f}%   "
              f"p90 {sig['win_rate'].quantile(.9):.0f}%")
        be_prod = breakeven_wr(1.4, 0.25)
        n_ok = (sig["win_rate"] >= be_prod).sum()
        print(f"\n  Escenarios que alcanzan el {be_prod:.1f}% que exige la "
              f"config de PRODUCCIÓN: {n_ok}/{len(sig)} "
              f"({n_ok/len(sig)*100:.0f}%)")
        be_bt = breakeven_wr(1.5, 0.5)
        n_ok2 = (sig["win_rate"] >= be_bt).sum()
        print(f"  Escenarios que alcanzan el {be_bt:.1f}% que exige TP1.5/SL0.5: "
              f"{n_ok2}/{len(sig)} ({n_ok2/len(sig)*100:.0f}%)")

        print("\n  Top 10 por win rate:")
        cols = ["scenario", "name", "motor", "trades", "win_rate",
                "retorno_pct", "max_drawdown_pct"]
        print(sig.nlargest(10, "win_rate")[cols].to_string(index=False))

        print("\n  Distribución de retorno (>=10 trades):")
        print(f"    mediana {sig['retorno_pct'].median():+.1f}%   "
              f"media {sig['retorno_pct'].mean():+.1f}%   "
              f"%>0 {(sig['retorno_pct']>0).mean()*100:.0f}%")

    # Expectativa por trade real, leída de los CSV de trades
    print("\n" + "=" * 74)
    print("EXPECTATIVA POR TRADE (de los CSV de trades reales del backtest)")
    print("=" * 74)
    rows = []
    for path in sorted(glob.glob(os.path.join(out_dir, "bt_*_trades.csv"))):
        key = os.path.basename(path).split("_")[1]
        try:
            t = pd.read_csv(path)
        except Exception:  # noqa: BLE001
            continue
        if len(t) < 10 or "pnl" not in t.columns:
            continue
        wins, losses = t[t["pnl"] > 0]["pnl"], t[t["pnl"] <= 0]["pnl"]
        rows.append(dict(
            scenario=key, trades=len(t),
            wr=round(len(wins) / len(t) * 100, 0),
            avg_win=round(wins.mean(), 2) if len(wins) else 0.0,
            avg_loss=round(losses.mean(), 2) if len(losses) else 0.0,
            expectancy=round(t["pnl"].mean(), 3),
            total=round(t["pnl"].sum(), 2)))
    if rows:
        edf = pd.DataFrame(rows).sort_values("expectancy", ascending=False)
        print(edf.head(15).to_string(index=False))
        print(f"\n  Escenarios con expectativa POSITIVA por trade: "
              f"{(edf['expectancy']>0).sum()}/{len(edf)} "
              f"({(edf['expectancy']>0).mean()*100:.0f}%)")
        print(f"  Expectativa mediana por trade: "
              f"${edf['expectancy'].median():+.3f}")


if __name__ == "__main__":
    main()
