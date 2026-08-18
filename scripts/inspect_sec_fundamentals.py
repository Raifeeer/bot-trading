"""Inspect coverage of SEC fundamentals without printing full filings."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/home/ubuntu/backtests/fundamental_history")
TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
    "ProfitLoss",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",
    "StockholdersEquity",
    "Liabilities",
    "Assets",
]


def main() -> None:
    rows = []
    for path in sorted(ROOT.glob("*_companyfacts.json")):
        symbol = path.name.split("_", 1)[0]
        data = json.loads(path.read_text(encoding="utf-8"))
        facts = data.get("facts", {})
        us_gaap = facts.get("us-gaap", {})
        row = {"symbol": symbol, "us_gaap_tags": len(us_gaap)}
        for tag in TAGS:
            if tag in us_gaap:
                units = us_gaap[tag].get("units", {})
                row[tag] = sum(len(values) for values in units.values())
            else:
                row[tag] = 0
        rows.append(row)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
