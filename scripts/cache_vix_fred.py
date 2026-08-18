"""Cache the FRED VIXCLS daily series for VIX regime research."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

OUT = Path("/home/ubuntu/backtests/vix_history")
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    response = requests.get(URL, timeout=45)
    response.raise_for_status()
    path = OUT / "vix_fred_raw.csv"
    path.write_bytes(response.content)
    frame = pd.read_csv(path, parse_dates=["observation_date"])
    frame = frame.rename(columns={"observation_date": "timestamp", "VIXCLS": "close"})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).set_index("timestamp").sort_index()
    frame.to_pickle(OUT / "vix.pkl")
    frame.to_csv(OUT / "vix.csv")
    manifest = {"source": "FRED VIXCLS", "url": URL, "rows": len(frame),
                "start": str(frame.index.min()), "end": str(frame.index.max()),
                "missing_close_after_drop": int(frame["close"].isna().sum())}
    (OUT / "manifest_fred.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
