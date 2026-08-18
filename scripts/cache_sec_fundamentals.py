"""Cache SEC Company Facts and submissions without using future filing data."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

OUT = Path("/home/ubuntu/backtests/fundamental_history")
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB"]
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "Polaris research contact research@example.com"}


def get_json(url: str) -> dict:
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    return response.json()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = get_json(SEC_TICKERS_URL)
    by_symbol = {row["ticker"].upper(): str(row["cik_str"]).zfill(10)
                 for row in tickers.values()}
    manifest = {"source": "SEC EDGAR APIs", "symbols": {}, "user_agent": HEADERS["User-Agent"]}
    for symbol in SYMBOLS:
        cik = by_symbol.get(symbol)
        if not cik:
            manifest["symbols"][symbol] = {"status": "missing_cik"}
            continue
        companyfacts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            facts = get_json(companyfacts_url)
            time.sleep(0.2)
            submissions = get_json(submissions_url)
            (OUT / f"{symbol}_companyfacts.json").write_text(
                json.dumps(facts), encoding="utf-8")
            (OUT / f"{symbol}_submissions.json").write_text(
                json.dumps(submissions), encoding="utf-8")
            manifest["symbols"][symbol] = {
                "status": "ok", "cik": cik,
                "facts": len(facts.get("facts", {}).get("us-gaap", {})),
                "filings": len(submissions.get("filings", {}).get("recent", {}).get("form", [])),
            }
        except requests.RequestException as exc:
            manifest["symbols"][symbol] = {"status": "error", "error": str(exc)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"symbols": manifest["symbols"], "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
