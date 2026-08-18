"""Inspect option-history columns and coverage for gamma-wall eligibility."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu/backtests")
PATHS = [
    ROOT / "defined_risk_option_history_2026-08-18/option_bars.pkl",
    ROOT / "wheel_option_history_2026-08-18/option_bars.pkl",
]


def main() -> None:
    output = []
    for path in PATHS:
        if not path.exists():
            output.append({"path": str(path), "exists": False})
            continue
        frame = pd.read_pickle(path)
        output.append({"path": str(path), "exists": True, "rows": len(frame),
                       "columns": list(frame.columns),
                       "min_timestamp": str(frame.index.min()) if len(frame) else None,
                       "max_timestamp": str(frame.index.max()) if len(frame) else None,
                       "has_open_interest": "open_interest" in frame.columns or "oi" in frame.columns,
                       "has_gamma": "gamma" in frame.columns,
                       "has_iv": "implied_volatility" in frame.columns or "iv" in frame.columns,
                       "unique_symbols": int(frame["underlying_symbol"].nunique()) if "underlying_symbol" in frame else None})
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
