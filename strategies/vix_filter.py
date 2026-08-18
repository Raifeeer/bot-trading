"""VIX regime features for research; no order execution."""
from __future__ import annotations

import pandas as pd


def daily_features(vix: pd.Series) -> pd.DataFrame:
    """Build lagged VIX features indexed by exchange date."""
    frame = vix.rename("vix").to_frame().sort_index()
    frame["vix_change"] = frame["vix"].pct_change()
    frame["vix_mean_20"] = frame["vix"].rolling(20, min_periods=20).mean()
    frame["vix_std_20"] = frame["vix"].rolling(20, min_periods=20).std()
    frame["vix_z20"] = (frame["vix"] - frame["vix_mean_20"]) / frame["vix_std_20"]
    rolling = frame["vix"].rolling(252, min_periods=252)
    frame["vix_pct60"] = rolling.quantile(0.6)
    frame["vix_pct70"] = rolling.quantile(0.7)
    frame["vix_pct80"] = rolling.quantile(0.8)
    frame["decision_date"] = frame.index.date
    return frame


def prior_close_for_date(features: pd.DataFrame, trade_date) -> pd.Series | None:
    """Return the last VIX observation strictly before the trade date."""
    eligible = features[features["decision_date"] < trade_date]
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def blocked_by_vix(row: pd.Series | None, variant: str) -> bool:
    """Return whether a new long entry should be blocked by the VIX gate."""
    if variant == "baseline":
        return False
    if row is None or pd.isna(row.get("vix")):
        return True
    vix = float(row["vix"])
    if variant.startswith("level_"):
        threshold = float(variant.split("_")[1])
        return vix >= threshold
    if variant.startswith("percentile_"):
        percentile = variant.split("_")[1]
        field = f"vix_pct{percentile}"
        return pd.isna(row[field]) or vix >= float(row[field])
    if variant.startswith("shock_"):
        threshold = float(variant.split("_")[1]) / 100.0
        return pd.notna(row["vix_change"]) and float(row["vix_change"]) > threshold
    if variant == "zscore_2":
        return pd.notna(row["vix_z20"]) and float(row["vix_z20"]) > 2.0
    if variant == "combined_25_shock":
        shock = pd.notna(row["vix_change"]) and float(row["vix_change"]) > 0.20
        return vix >= 25.0 or shock
    raise ValueError(f"Unknown VIX variant: {variant}")
