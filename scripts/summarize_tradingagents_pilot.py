"""Summarize completed JSON rows from a TradingAgents pilot log."""

from __future__ import annotations

import json
from pathlib import Path


LOG = Path("/home/ubuntu/backtests/tradingagents_pilot_2026-08-24/run.log")
OUT = Path("/home/ubuntu/backtests/tradingagents_pilot_2026-08-24/partial_summary.json")


def main() -> None:
    rows = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        outcome = row.get("forward_outcome", {})
        rows.append(
            {
                "ticker": row.get("ticker"),
                "trade_date": row.get("trade_date"),
                "status": row.get("status"),
                "rating": row.get("rating"),
                "elapsed_seconds": row.get("elapsed_seconds"),
                "forward_return_5d": outcome.get("return_5d"),
                "forward_status": outcome.get("status"),
            }
        )
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"rows={len(rows)}")
    for row in rows:
        print(
            row["ticker"],
            row["trade_date"],
            row["status"],
            row["rating"],
            row["forward_return_5d"],
            row["elapsed_seconds"],
        )


if __name__ == "__main__":
    main()
