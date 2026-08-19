from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu")
for timeframe, directory in (
    ("5min", ROOT / "backtests/structure_mtf_history"),
    ("15min", ROOT / "backtests/volume_profile_history"),
):
    frame = pd.read_pickle(directory / "TQQQ.pkl")
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame.sort_index()
    local = frame.index.tz_convert("America/New_York")
    frame = frame.assign(local_time=local.strftime("%H:%M"), local_date=local.date.astype(str))
    selected = frame.loc[frame["local_time"].between("09:30", "10:30", inclusive="left")]
    print(f"[{timeframe}] rows around open={len(selected)}")
    for day, group in selected.groupby("local_date", sort=True):
        print(day, list(group["local_time"].head(8)), "bars=", len(group))
        if day >= selected["local_date"].iloc[-1]:
            break
    print("last five timestamps local:", list(frame["local_time"].tail(5)))
