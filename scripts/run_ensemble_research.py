#!/usr/bin/env python3
"""Fixed-weight portfolio ensembles for research-only robustness checks."""
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
WINDOWS = {
    "lateral_2025": ("2025-09-01", "2025-12-31"),
    "selloff_2026": ("2026-01-01", "2026-04-30"),
    "recent_2026": ("2026-04-01", "2026-08-14"),
    "latest_30d": ("2026-07-01", "2026-08-14"),
}
WEIGHTS = (0.3, 0.5, 0.7, 1.0)


def sc(motor, window):
    return dict(
        name=f"{motor}_{window}", motor=motor,
        window_dates=WINDOWS[window], tickers=UNI_RETO,
        risk_pct=0.10, max_pos=8 if motor == "regime_hold_cash" else 2,
        dte=21, delta_l=0.25, delta_s=0.10, tp=1.3, sl=0.5,
        max_rv=None, anti_earnings=False,
        comision=0.0 if motor == "regime_hold_cash" else 0.65,
        slippage_pct=0.03 if motor != "regime_hold_cash" else 0.0,
        equity_cost_pct=0.002,
    )


def result_for(motor, window, data):
    cfg = sc(motor, window)
    equity, trades, curve, dd, _ = run_scenario(cfg["name"], cfg, data)
    curve = curve[["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"], utc=True).dt.normalize()
    return cfg, float(equity), curve, trades, float(dd)


def combine(curve_a, curve_b, weight_b):
    a = curve_a.rename(columns={"equity": "a"}).set_index("date")
    b = curve_b.rename(columns={"equity": "b"}).set_index("date")
    idx = a.index.union(b.index).sort_values()
    joined = pd.concat([a, b], axis=1).reindex(idx).ffill().fillna(CAPITAL_INICIAL)
    joined["ensemble"] = ((1.0 - weight_b) * joined["a"]
                           + weight_b * joined["b"])
    return joined.reset_index()


def main():
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    data = feed.history(UNI_RETO, "1d", days=520)
    rows = []
    for window in WINDOWS:
        base_cfg, base_final, base_curve, _, base_dd = result_for("regime_hold_cash", window, data)
        for motor in ("breakout20", "breakout55"):
            _, breakout_final, breakout_curve, _, breakout_dd = result_for(motor, window, data)
            for weight in WEIGHTS:
                ensemble = combine(base_curve, breakout_curve, weight)
                eq = ensemble["ensemble"].astype(float)
                dd = ((eq / eq.cummax()) - 1.0).min() * 100
                rows.append({
                    "window": window,
                    "breakout_motor": motor,
                    "weight_regime_hold_cash": 1.0 - weight,
                    "weight_breakout": weight,
                    "equity_final": round(float(eq.iloc[-1]), 5),
                    "return_pct": round((float(eq.iloc[-1]) / CAPITAL_INICIAL - 1) * 100, 5),
                    "max_drawdown_pct": round(float(dd), 5),
                    "regime_final": round(base_final, 5),
                    "regime_dd": round(base_dd, 5),
                    "breakout_final": round(breakout_final, 5),
                    "breakout_dd": round(breakout_dd, 5),
                })
    df = pd.DataFrame(rows)
    out = OUT / "ensemble_research_2026-08-15.csv"
    df.to_csv(out, index=False)
    summary = (df.groupby(["breakout_motor", "weight_regime_hold_cash", "weight_breakout"])
                 .agg(median_return_pct=("return_pct", "median"),
                      min_return_pct=("return_pct", "min"),
                      median_dd_pct=("max_drawdown_pct", "median"),
                      positive_windows=("return_pct", lambda s: int((s > 0).sum())),
                      total_windows=("return_pct", "count"))
                 .reset_index())
    summary["positive_share"] = summary["positive_windows"] / summary["total_windows"]
    summary_path = OUT / "ensemble_summary_2026-08-15.csv"
    summary.to_csv(summary_path, index=False)
    meta = OUT / "ensemble_research_2026-08-15.json"
    meta.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "windows": WINDOWS,
        "weights_breakout": WEIGHTS,
        "data_source": "yfinance via MarketDataFeed, 520 days",
        "note": "Fixed-weight ensemble only; no live deployment or order path changed.",
        "csv": str(out), "summary_csv": str(summary_path),
    }, indent=2) + "\n")
    print(summary.sort_values("median_return_pct", ascending=False).to_string(index=False))
    print(out)
    print(summary_path)


if __name__ == "__main__":
    main()
