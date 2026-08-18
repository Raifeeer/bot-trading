"""Observability-only VIX evaluator for Polaris.

This module computes what a VIX gate *would* do. It never approves, blocks,
resizes, closes, or submits an order.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from strategies.vix_filter import blocked_by_vix, daily_features, prior_close_for_date

DEFAULT_VARIANTS = ("shock_10", "percentile_70", "level_25")


def _exchange_date(as_of: date | str | None) -> date:
    if as_of is not None:
        return pd.Timestamp(as_of).date()
    return datetime.now(timezone.utc).astimezone(
        ZoneInfo("America/New_York")).date()


def _clean_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "close" not in frame.columns:
        return pd.Series(dtype=float)
    values = frame["close"].astype(float).dropna()
    values.index = pd.to_datetime(values.index, utc=True)
    return values.sort_index()


def _variant_reason(row: pd.Series | None, variant: str, would_block: bool) -> str:
    if row is None or pd.isna(row.get("vix")):
        return "vix_prior_close_missing"
    if variant.startswith("shock_"):
        if pd.isna(row.get("vix_change")):
            return "vix_change_missing"
        return "prior_close_shock" if would_block else "no_prior_close_shock"
    if variant.startswith("percentile_"):
        field = f"vix_pct{variant.split('_')[1]}"
        if pd.isna(row.get(field)):
            return "rolling_percentile_warmup"
        return "vix_above_rolling_percentile" if would_block else "vix_below_rolling_percentile"
    if variant.startswith("level_"):
        return "vix_at_or_above_level" if would_block else "vix_below_level"
    if variant == "zscore_2":
        return "vix_zscore_shock" if would_block else "vix_zscore_normal"
    return "variant_evaluated"


def evaluate_vix_shadow(feed, tickers: list[str], cfg: dict,
                        as_of: date | str | None = None) -> dict:
    """Return a serializable VIX snapshot without an execution side effect.

    ``as_of`` is the exchange date whose entries would be evaluated. The
    evaluator uses only the last VIX close strictly before that date.
    """
    config = cfg.get("vix_shadow", cfg) if isinstance(cfg, dict) else {}
    variants = tuple(config.get("variants", DEFAULT_VARIANTS))
    if not config.get("enabled", False):
        return {
            "enabled": False,
            "mode": "disabled",
            "influence_entries": False,
            "orders_allowed": False,
            "symbols": {},
        }

    exchange_date = _exchange_date(as_of)
    history_days = max(30, int(config.get("history_days", 400)))
    source_symbol = str(config.get("source_symbol", "^VIX"))
    try:
        raw = feed.history([source_symbol], "1d", days=history_days)
        frame = raw.get(source_symbol) if isinstance(raw, dict) else None
    except Exception as exc:  # noqa: BLE001
        frame = None
        fetch_error = f"{type(exc).__name__}:{exc}"
    else:
        fetch_error = None

    values = _clean_series(frame) if isinstance(frame, pd.DataFrame) else pd.Series(dtype=float)
    features = daily_features(values) if not values.empty else pd.DataFrame()
    row = prior_close_for_date(features, exchange_date) if not features.empty else None
    variant_rows: dict[str, dict[str, object]] = {}
    for variant in variants:
        would_block = bool(blocked_by_vix(row, str(variant)))
        variant_rows[str(variant)] = {
            "would_block": would_block,
            "reason": _variant_reason(row, str(variant), would_block),
        }

    available = row is not None and pd.notna(row.get("vix"))
    observation = {
        "enabled": True,
        "mode": str(config.get("mode", "shadow")),
        "influence_entries": False,
        "orders_allowed": False,
        "source_version": "vix-shadow-v1",
        "source_symbol": source_symbol,
        "source_provider": str(getattr(feed, "provider", "unknown")),
        "alignment": "last_close_strictly_before_exchange_date",
        "exchange_date": str(exchange_date),
        "available": bool(available),
        "prior_observation_date": str(row["decision_date"]) if available else None,
        "vix": float(row["vix"]) if available else None,
        "vix_change": float(row["vix_change"]) if available and pd.notna(row.get("vix_change")) else None,
        "vix_z20": float(row["vix_z20"]) if available and pd.notna(row.get("vix_z20")) else None,
        "vix_pct70": float(row["vix_pct70"]) if available and pd.notna(row.get("vix_pct70")) else None,
        "variants": variant_rows,
        "symbols": {
            symbol: {
                "observational_only": True,
                "would_block": {
                    variant: values["would_block"]
                    for variant, values in variant_rows.items()
                },
            }
            for symbol in tickers
        },
        "counts": {
            "symbols_observed": len(tickers),
            "variants": len(variant_rows),
            "available": int(available),
            "would_block": {
                variant: int(values["would_block"])
                for variant, values in variant_rows.items()
            },
        },
        "risk_authority": "RiskManager_and_live_strategies_unchanged",
    }
    if fetch_error:
        observation["fetch_error"] = fetch_error
    return observation
