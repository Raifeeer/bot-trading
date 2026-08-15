#!/usr/bin/env python3
"""Two-fold rolling walk-forward for research-only robustness checks."""
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


def candidate(name, motor, *, risk=0.10, dte=21, max_pos=2,
              commission=0.65, slippage_pct=0.03, equity_cost_pct=0.002):
    return dict(
        name=name, motor=motor, tickers=UNI_RETO, risk_pct=risk,
        max_pos=max_pos, dte=dte, delta_l=0.25, delta_s=0.10,
        tp=1.3, sl=0.5, max_rv=None, anti_earnings=False,
        comision=commission if commission is not None else 0.0,
        slippage_pct=slippage_pct, equity_cost_pct=equity_cost_pct,
    )


CANDIDATES = [
    candidate("regime_hold_cash", "regime_hold_cash", max_pos=8, commission=None),
    candidate("hold_weekly", "hold_weekly", max_pos=8, commission=None),
    candidate("breakout20_r10", "breakout20", risk=0.10),
    candidate("breakout20_r15", "breakout20", risk=0.15),
    candidate("breakout55_r10", "breakout55", risk=0.10),
    candidate("breakout55_r15", "breakout55", risk=0.15),
    candidate("smc_r10", "smc_daily", risk=0.10),
]


def run_one(candidate_name, base, window_dates, data, label):
    sc = dict(base, window_dates=window_dates)
    equity, trades, curve, dd, _ = run_scenario(label, sc, data)
    tdf = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    gp = float(tdf.loc[tdf.pnl > 0, "pnl"].sum()) if len(tdf) else 0.0
    gl = float(-tdf.loc[tdf.pnl < 0, "pnl"].sum()) if len(tdf) else 0.0
    return {
        "candidate": candidate_name,
        "equity_final": round(float(equity), 4),
        "return_pct": round((float(equity) / CAPITAL_INICIAL - 1) * 100, 4),
        "trades": int(len(tdf)),
        "win_rate_pct": round(float((tdf.pnl > 0).mean() * 100), 2) if len(tdf) else 0.0,
        "profit_factor": round(gp / gl, 4) if gl > 0 else None,
        "max_drawdown_pct": round(float(dd), 4),
    }


def score(train, validation):
    if train["trades"] < 10 or validation["trades"] < 10:
        return -999.0
    a = train["return_pct"] / (1 + abs(train["max_drawdown_pct"]))
    b = validation["return_pct"] / (1 + abs(validation["max_drawdown_pct"]))
    return 0.4 * a + 0.6 * b


def main():
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    data = feed.history(UNI_RETO, "1d", days=520)
    rows = []
    selections = []
    for fold, windows in FOLDS.items():
        per_fold = {}
        for c in CANDIDATES:
            name = c["name"]
            train = run_one(name, c, windows["train"], data, f"{name}_{fold}_train")
            val = run_one(name, c, windows["validation"], data, f"{name}_{fold}_val")
            train.update(fold=fold, window="train")
            val.update(fold=fold, window="validation")
            rows.extend([train, val])
            per_fold[name] = (train, val)
        selected_score, selected_name = max(
            (score(train, val), name) for name, (train, val) in per_fold.items()
        )
        selected_cfg = next(c for c in CANDIDATES if c["name"] == selected_name)
        test = run_one(selected_name, selected_cfg, windows["test"], data, f"{selected_name}_{fold}_test")
        test.update(fold=fold, window="test", selection_score=round(selected_score, 6))
        rows.append(test)
        selections.append({"fold": fold, "selected": selected_name,
                           "selection_score": round(selected_score, 6),
                           "test": test, "windows": windows})
    out = OUT / "rolling_walk_forward_2026-08-15.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    meta = OUT / "rolling_walk_forward_2026-08-15.json"
    meta.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "0.4 train + 0.6 validation score; score=return/(1+abs(drawdown)); >=10 trades per split",
        "folds": FOLDS,
        "selections": selections,
        "data_source": "yfinance via MarketDataFeed, 520 days",
    }, indent=2) + "\n")
    print(pd.DataFrame(rows).to_string(index=False))
    print("SELECTIONS", json.dumps(selections, indent=2))
    print(out)
    print(meta)


if __name__ == "__main__":
    main()
