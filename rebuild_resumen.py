"""Reconstruye bt_resumen.csv consolidado a partir de los CSVs individuales
bt_S{N}_trades.csv (equity final, trades, wins, win_rate, dd) generados por
loop_backtests.py."""
import csv
import glob
import os

OUT = "/home/ubuntu/backtests/bt_resumen.csv"
rows = []
for path in sorted(glob.glob("/home/ubuntu/backtests/bt_S*_equity.csv")):
    key = os.path.basename(path).replace("bt_", "").replace("_equity.csv", "")
    trades_path = f"/home/ubuntu/backtests/bt_{key}_trades.csv"
    equity = 100.0
    dd = 0.0
    mx = 100.0
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            r = list(csv.DictReader(f))
        if r:
            eqs = [float(x["equity"]) for x in r if x.get("equity")]
            if eqs:
                equity = eqs[-1]
                mx = max(max(eqs), 100.0)
                dd = (min(eqs) / mx - 1) * 100 if mx else 0
    wins = tr = 0
    pnl = 0.0
    if os.path.exists(trades_path):
        with open(trades_path, newline="", encoding="utf-8") as f:
            t = list(csv.DictReader(f))
        tr = len(t)
        wins = sum(1 for x in t if float(x.get("pnl", 0)) >= 0)
        pnl = sum(float(x.get("pnl", 0)) for x in t)
    rows.append(dict(
        scenario=key, equity_final=round(equity, 2),
        retorno_pct=round((equity - 100) / 100 * 100, 1),
        trades=tr, wins=wins,
        win_rate=round(wins / tr * 100, 1) if tr else 0,
        pnl_total=round(pnl, 2),
        max_drawdown_pct=round(dd, 1),
        max_equity=round(mx, 2),
    ))
rows.sort(key=lambda x: x["scenario"])
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} escenarios consolidados -> {OUT}")
for r in rows[-8:]:
    print(r["scenario"], r["equity_final"], r["retorno_pct"], "trades", r["trades"])
