#!/usr/bin/env python3
"""Sensitivity grid for research-only robustness evaluation."""
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


def make_sc(motor, window, risk, slip, eq_cost):
    return dict(
        name=f"{motor}_{window}_r{risk:.2f}_s{slip:.3f}_e{eq_cost:.4f}",
        motor=motor,
        window_dates=WINDOWS[window],
        tickers=UNI_RETO,
        risk_pct=risk,
        max_pos=8 if motor == "regime_hold_cash" else 2,
        dte=21,
        delta_l=0.25,
        delta_s=0.10,
        tp=1.3,
        sl=0.5,
        max_rv=None,
        anti_earnings=False,
        comision=0.0 if motor == "regime_hold_cash" else 0.65,
        slippage_pct=slip,
        equity_cost_pct=eq_cost,
    )


def run_grid(data):
    rows = []
    for motor in ("regime_hold_cash", "breakout20", "breakout55", "smc_daily"):
        risks = (0.10,) if motor == "regime_hold_cash" else (0.05, 0.10, 0.15)
        slips = (0.0, 0.001, 0.002, 0.005) if motor == "regime_hold_cash" else (0.01, 0.03, 0.05)
        eq_costs = (0.001, 0.002, 0.005) if motor == "regime_hold_cash" else (0.0,)
        for window in WINDOWS:
            for risk in risks:
                for slip in slips:
                    for eq_cost in eq_costs:
                        sc = make_sc(motor, window, risk, slip, eq_cost)
                        equity, trades, curve, dd, _ = run_scenario(sc["name"], sc, data)
                        tdf = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
                        gp = float(tdf.loc[tdf.pnl > 0, "pnl"].sum()) if len(tdf) else 0.0
                        gl = float(-tdf.loc[tdf.pnl < 0, "pnl"].sum()) if len(tdf) else 0.0
                        rows.append({
                            "motor": motor, "window": window,
                            "risk_pct": risk, "slippage_pct": slip,
                            "equity_cost_pct": eq_cost,
                            "equity_final": round(float(equity), 5),
                            "return_pct": round((float(equity) / CAPITAL_INICIAL - 1) * 100, 5),
                            "trades": int(len(tdf)),
                            "win_rate_pct": round(float((tdf.pnl > 0).mean() * 100), 3) if len(tdf) else 0.0,
                            "profit_factor": round(gp / gl, 5) if gl > 0 else None,
                            "max_drawdown_pct": round(float(dd), 5),
                        })
    return pd.DataFrame(rows)


def main():
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    data = feed.history(UNI_RETO, "1d", days=520)
    df = run_grid(data)
    out = OUT / "sensitivity_2026-08-15.csv"
    df.to_csv(out, index=False)
    grouped = (df.groupby(["motor", "risk_pct", "slippage_pct", "equity_cost_pct"])
                 .agg(median_return_pct=("return_pct", "median"),
                      min_return_pct=("return_pct", "min"),
                      median_dd_pct=("max_drawdown_pct", "median"),
                      positive_windows=("return_pct", lambda s: int((s > 0).sum())),
                      total_windows=("return_pct", "count"),
                      min_trades=("trades", "min"))
                 .reset_index())
    grouped["positive_share"] = grouped["positive_windows"] / grouped["total_windows"]
    summary = OUT / "sensitivity_summary_2026-08-15.csv"
    grouped.to_csv(summary, index=False)
    meta = OUT / "sensitivity_2026-08-15.json"
    meta.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "windows": WINDOWS,
        "data_source": "yfinance via MarketDataFeed, 520 days",
        "primary_exclusion": "current-state earnings calendar excluded because not point-in-time",
        "grid_rows": int(len(df)),
        "csv": str(out),
        "summary_csv": str(summary),
    }, indent=2) + "\n")
    print(df.head(3).to_string(index=False))
    print("ROWS", len(df))
    print("SUMMARY", summary)
    print("RAW", out)


if __name__ == "__main__":
    main()
