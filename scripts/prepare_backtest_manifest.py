#!/usr/bin/env python3
"""Prepare a reproducible OHLCV manifest for Polaris research backtests.

The live strategy's earnings calendar is deliberately not used here because
its yfinance calendar is current-state data, not point-in-time historical data.
This script records the price-data cutoff and the exact research assumptions.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
OUT.mkdir(parents=True, exist_ok=True)

manifest = {
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "repository": "Raifeeer/bot-trading",
    "git_commit": subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
    ).strip(),
    "source": {
        "provider": "yfinance via data.feed.MarketDataFeed",
        "data_type": "daily OHLCV",
        "adjustment": "auto_adjust=False",
        "price_cutoff_rule": "Only bars with timestamp <= scenario end date are used",
        "earnings": "excluded from primary PIT runs; current yfinance calendar is not point-in-time",
    },
    "universe": ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"],
    "windows": [
        {"name": "selloff_2026", "start": "2026-01-01", "end": "2026-04-30"},
        {"name": "recent_2026", "start": "2026-04-01", "end": "2026-08-14"},
        {"name": "lateral_2025", "start": "2025-09-01", "end": "2025-12-31"},
    ],
    "model": {
        "capital_initial_usd": 100.0,
        "commission_usd_per_leg": 0.65,
        "slippage": "optional slippage_pct overlay on option entry/exit; each run must record the value",
        "option_pricing": "Black-Scholes proxy using realized volatility; not point-in-time option chains",
        "anti_lookahead": [
            "signals use rows normalized <= decision date",
            "evaluation windows are explicit and end-dated",
            "no current earnings calendar in primary historical runs",
            "results must be separated in-sample versus out-of-sample",
        ],
    },
}

path = OUT / "manifest_2026-08-15.json"
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(path)
