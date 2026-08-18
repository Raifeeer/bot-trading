"""Cache VIX/VIX3M daily history from Yahoo Chart API for research only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path("/home/ubuntu/backtests/vix_history")
START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 8, 19, tzinfo=timezone.utc).timestamp())
TICKERS = {"VIX": "%5EVIX", "VIX3M": "%5EVIX3M"}


def _download(ticker: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": START, "period2": END, "interval": "1d", "events": "history"}
    response = requests.get(url, params=params, timeout=45)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame(quote, index=pd.to_datetime(timestamps, unit="s", utc=True))
    frame.index.name = "timestamp"
    frame = frame.rename(columns={"adjclose": "adj_close"})
    return frame.sort_index()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"source": "Yahoo Finance Chart API", "tickers": {},
                                   "requested_start": "2024-01-01", "requested_end": "2026-08-19"}
    for name, ticker in TICKERS.items():
        frame = _download(ticker)
        frame.to_pickle(OUT / f"{name.lower()}.pkl")
        frame.to_csv(OUT / f"{name.lower()}.csv")
        manifest["tickers"][name] = {"ticker": ticker, "rows": len(frame),
                                      "start": str(frame.index.min()), "end": str(frame.index.max()),
                                      "missing_close": int(frame["close"].isna().sum())}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
