"""Gamma-wall calculations with explicit data-quality gates."""
from __future__ import annotations

import pandas as pd

REQUIRED = {"timestamp", "strike", "option_type", "open_interest", "gamma", "spot", "multiplier"}


def coverage_status(frame: pd.DataFrame) -> str:
    """Return OK only if the frame can support a point-in-time GEX proxy."""
    if not REQUIRED.issubset(frame.columns):
        return "REJECT_DATA"
    if frame.empty or frame[list(REQUIRED)].isna().any().any():
        return "REJECT_DATA"
    return "OK"


def gex_snapshot(frame: pd.DataFrame, call_sign: float = 1.0,
                 put_sign: float = -1.0) -> dict[str, object]:
    """Compute a documented OI*gamma proxy and walls for one snapshot."""
    if coverage_status(frame) != "OK":
        return {"status": "REJECT_DATA", "reason": "missing_point_in_time_oi_gamma_fields"}
    data = frame.copy()
    signs = data["option_type"].str.lower().map({"call": call_sign, "put": put_sign})
    if signs.isna().any():
        return {"status": "REJECT_DATA", "reason": "unknown_option_type"}
    data["gex_proxy"] = (data["open_interest"].astype(float)
                          * data["gamma"].astype(float)
                          * data["multiplier"].astype(float)
                          * data["spot"].astype(float)
                          * signs)
    grouped = data.groupby(["option_type", "strike"], as_index=False)["gex_proxy"].sum()
    calls = grouped[grouped["option_type"].str.lower() == "call"]
    puts = grouped[grouped["option_type"].str.lower() == "put"]
    return {"status": "OK",
            "call_wall": float(calls.loc[calls["gex_proxy"].abs().idxmax(), "strike"]) if not calls.empty else None,
            "put_wall": float(puts.loc[puts["gex_proxy"].abs().idxmax(), "strike"]) if not puts.empty else None,
            "net_gex_proxy": float(data["gex_proxy"].sum()),
            "strikes": int(grouped["strike"].nunique())}
