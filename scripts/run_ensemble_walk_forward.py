#!/usr/bin/env python3
"""Walk-forward selection of a fixed-weight regime/breakout ensemble."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import CAPITAL_INICIAL, UNI_RETO, run_scenario  # noqa: E402

OUT = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
OUT.mkdir(parents=True, exist_ok=True)
FOLDS = {
    "fold_a": {
        "train": ("2025-09-01", "2025-12-31"),
        "validation": ("2026-01-01", "2026-03-31"),
        "test": ("2026-04-01", "2026-06-30"),
    },
    "fold_b": {
        "train": ("2025-12-01", "2026-03-31"),
        "validation": ("2026-04-01", "2026-06-30"),
        "test": ("2026-07-01", "2026-08-14"),
    },
}
WEIGHTS = (0.3, 0.5, 0.7)


def cfg(motor, window):
    return dict(
        name=f"{motor}_{window}", motor=motor, window_dates=window,
        tickers=UNI_RETO, risk_pct=0.10,
        max_pos=8 if motor == "regime_hold_cash" else 2,
        dte=21, delta_l=0.25, delta_s=0.10, tp=1.3, sl=0.5,
        max_rv=None, anti_earnings=False,
        comision=0.0 if motor == "regime_hold_cash" else 0.65,
        slippage_pct=0.0 if motor == "regime_hold_cash" else 0.03,
        equity_cost_pct=0.002,
    )


def run_motor(motor, window, data, label):
    sc = cfg(motor, window)
    eq, trades, curve, dd, _ = run_scenario(label, sc, data)
    curve = curve[["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"], utc=True).dt.normalize()
    return {"equity": float(eq), "curve": curve, "trades": int(len(trades)), "dd": float(dd)}


def ensemble_metrics(a, b, weight):
    x = a["curve"].rename(columns={"equity": "a"}).set_index("date")
    y = b["curve"].rename(columns={"equity": "b"}).set_index("date")
    idx = x.index.union(y.index).sort_values()
    z = pd.concat([x, y], axis=1).reindex(idx).ffill().fillna(CAPITAL_INICIAL)
    eq = (1.0 - weight) * z["a"] + weight * z["b"]
    dd = ((eq / eq.cummax()) - 1.0).min() * 100
    return {"equity_final": float(eq.iloc[-1]),
            "return_pct": (float(eq.iloc[-1]) / CAPITAL_INICIAL - 1) * 100,
            "max_drawdown_pct": float(dd),
            "trades": a["trades"] + b["trades"]}


def score(x):
    if x["trades"] < 10:
        return -999.0
    return x["return_pct"] / (1 + abs(x["max_drawdown_pct"]))


def main():
    data = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance")).history(UNI_RETO, "1d", days=520)
    rows, choices = [], []
    for fold, windows in FOLDS.items():
        per_window = {}
        for part in ("train", "validation", "test"):
            a = run_motor("regime_hold_cash", windows[part], data, f"regime_{fold}_{part}")
            b = run_motor("breakout55", windows[part], data, f"breakout55_{fold}_{part}")
            for weight in WEIGHTS:
                m = ensemble_metrics(a, b, weight)
                m.update(fold=fold, window=part,
                         weight_regime=1-weight, weight_breakout=weight)
                rows.append(m)
                per_window[(part, weight)] = m
        scored = [(score(per_window[("train", w)]) * 0.4 +
                   score(per_window[("validation", w)]) * 0.6, w)
                  for w in WEIGHTS]
        selected_score, selected_weight = max(scored)
        test = per_window[("test", selected_weight)]
        choices.append({"fold": fold, "selected_weight_breakout": selected_weight,
                        "selected_weight_regime": 1-selected_weight,
                        "selection_score": round(selected_score, 6),
                        "test": test, "windows": windows})
    out = OUT / "ensemble_walk_forward_2026-08-15.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    meta = OUT / "ensemble_walk_forward_2026-08-15.json"
    meta.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "weights": WEIGHTS, "folds": FOLDS, "choices": choices,
        "selection_rule": "0.4 train + 0.6 validation, score return/(1+abs(drawdown)), >=10 aggregate trades",
        "data_source": "yfinance via MarketDataFeed, 520 days",
    }, indent=2) + "\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print("CHOICES", json.dumps(choices, indent=2))
    print(out)
    print(meta)


if __name__ == "__main__":
    main()
