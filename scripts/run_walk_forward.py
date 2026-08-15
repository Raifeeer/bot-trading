#!/usr/bin/env python3
"""Strict walk-forward experiment for Polaris research only.

Selection is made on train/validation windows; the test window is evaluated
only after selection. No live service or order path is touched.
"""
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
    "train": ("2025-09-01", "2026-03-31"),
    "validation": ("2026-04-01", "2026-06-30"),
    "test": ("2026-07-01", "2026-08-14"),
}


def candidate(name, motor, *, risk=0.15, dte=21, delta_l=0.25,
              delta_s=0.10, tp=1.3, sl=0.5, max_pos=2,
              commission=0.65, slippage_pct=0.03, equity_cost_pct=0.002):
    return dict(
        name=name,
        motor=motor,
        tickers=UNI_RETO,
        risk_pct=risk,
        max_pos=max_pos,
        dte=dte,
        delta_l=delta_l,
        delta_s=delta_s,
        tp=tp,
        sl=sl,
        max_rv=None,
        anti_earnings=False,
        comision=commission if commission is not None else 0.0,
        slippage_pct=slippage_pct,
        equity_cost_pct=equity_cost_pct,
    )


CANDIDATES = [
    candidate("regime_hold_cash", "regime_hold_cash", max_pos=8, commission=None, slippage_pct=0.0, equity_cost_pct=0.002),
    candidate("hold_weekly", "hold_weekly", max_pos=8, commission=None, slippage_pct=0.0, equity_cost_pct=0.002),
    candidate("smc_r10", "smc_daily", risk=0.10),
    candidate("smc_r15", "smc_daily", risk=0.15),
    candidate("smc_dte30", "smc_daily", risk=0.15, dte=30),
    candidate("breakout20_r10", "breakout20", risk=0.10),
    candidate("breakout55_r10", "breakout55", risk=0.10),
    candidate("breakout55_r15", "breakout55", risk=0.15),
    candidate("put_choch_r10", "put_choch", risk=0.10),
]


def run_one(name, base, window, data):
    sc = dict(base, window_dates=WINDOWS[window])
    equity, trades, curve, dd, _max_eq = run_scenario(name + "_" + window, sc, data)
    tdf = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    gross_profit = float(tdf.loc[tdf.pnl > 0, "pnl"].sum()) if len(tdf) else 0.0
    gross_loss = float(-tdf.loc[tdf.pnl < 0, "pnl"].sum()) if len(tdf) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else None
    return {
        "candidate": name,
        "window": window,
        "motor": base["motor"],
        "equity_final": round(float(equity), 4),
        "return_pct": round((float(equity) / CAPITAL_INICIAL - 1) * 100, 4),
        "trades": int(len(tdf)),
        "win_rate_pct": round(float((tdf.pnl > 0).mean() * 100), 2) if len(tdf) else 0.0,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown_pct": round(float(dd), 4),
        "slippage_pct": base.get("slippage_pct", 0.0),
    }


def selection_score(train_row, validation_row):
    """Score conservador: requiere muestra mínima y combina train/validation."""
    if train_row["trades"] < 10 or validation_row["trades"] < 10:
        return -999.0
    train_score = train_row["return_pct"] / (1.0 + abs(train_row["max_drawdown_pct"]))
    val_score = validation_row["return_pct"] / (1.0 + abs(validation_row["max_drawdown_pct"]))
    return 0.4 * train_score + 0.6 * val_score


def main():
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    data = feed.history(UNI_RETO, "1d", days=520)
    rows = []
    for c in CANDIDATES:
        for w in ("train", "validation"):
            rows.append(run_one(c["name"], c, w, data))
    train_by_name = {r["candidate"]: r for r in rows if r["window"] == "train"}
    val_by_name = {r["candidate"]: r for r in rows if r["window"] == "validation"}
    scored = [(selection_score(train_by_name[name], val_by_name[name]), name)
              for name in train_by_name]
    selected_score, selected_name = max(scored)
    selected = dict(val_by_name[selected_name], selection_score=round(selected_score, 6),
                    train_return_pct=train_by_name[selected_name]["return_pct"],
                    train_trades=train_by_name[selected_name]["trades"])
    selected_cfg = next(c for c in CANDIDATES if c["name"] == selected_name)
    test = run_one(selected_name, selected_cfg, "test", data)
    rows.append(test)
    out = OUT / "walk_forward_2026-08-15.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    meta = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "max 0.4*train_score + 0.6*validation_score, each requiring >=10 trades; score=return/(1+abs(drawdown))",
        "train": WINDOWS["train"],
        "validation": WINDOWS["validation"],
        "test": WINDOWS["test"],
        "selected_candidate": selected_name,
        "selected_validation": selected,
        "test_result": test,
        "anti_earnings": False,
        "data_source": "yfinance via MarketDataFeed, 520 days",
    }
    (OUT / "walk_forward_2026-08-15.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print("SELECTED", selected_name)
    print("TEST", test)
    print(out)


if __name__ == "__main__":
    main()
