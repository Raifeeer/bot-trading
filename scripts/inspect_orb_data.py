from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu")
DIRECTORIES = {
    "5min": ROOT / "backtests/structure_mtf_history",
    "15min": ROOT / "backtests/volume_profile_history",
}
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]

for timeframe, directory in DIRECTORIES.items():
    print(f"[{timeframe}] {directory}")
    for symbol in SYMBOLS:
        path = directory / f"{symbol}.pkl"
        if not path.exists():
            print(symbol, "MISSING_FILE")
            continue
        frame = pd.read_pickle(path)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame = frame.sort_index()
        local = frame.index.tz_convert("America/New_York")
        open_rows = frame.loc[(local.strftime("%H:%M") >= "09:30") & (local.strftime("%H:%M") < "10:30")]
        print(
            symbol,
            "rows=", len(frame),
            "start=", frame.index.min().isoformat(),
            "end=", frame.index.max().isoformat(),
            "columns=", ",".join(str(column).lower() for column in frame.columns),
            "open_rows=", len(open_rows),
            "first_open_day=", open_rows.index[0].tz_convert("America/New_York").date().isoformat() if len(open_rows) else "NONE",
        )
