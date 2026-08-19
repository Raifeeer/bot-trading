"""Detector puro de relative strength/cross-sectional momentum."""
from __future__ import annotations

from math import sqrt
from typing import Any

import pandas as pd


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.rename(columns=str.lower).copy()
    if "close" not in out.columns:
        return pd.DataFrame()
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index().dropna(subset=["close"])


def _asof_frame(frame: pd.DataFrame, asof: pd.Timestamp | None) -> pd.DataFrame:
    out = _normalise(frame)
    if out.empty:
        return out
    if asof is not None:
        asof = pd.Timestamp(asof)
        if asof.tzinfo is None:
            asof = asof.tz_localize("UTC")
        else:
            asof = asof.tz_convert("UTC")
        out = out.loc[out.index <= asof]
    return out


def _empty(symbol: str, reason: str, *, asof_timestamp: str | None = None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": "neutral",
        "status": "missing_data" if reason == "missing_data" else "insufficient_data",
        "reason": reason,
        "rank": None,
        "percentile": None,
        "return_formation": None,
        "benchmark_return": None,
        "excess_return": None,
        "universe_size": 0,
        "asof_timestamp": asof_timestamp,
        "horizon_bars": None,
        "volatility": None,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
    }


def evaluate_relative_strength(
    frames: dict[str, pd.DataFrame],
    *,
    horizon_bars: int = 20,
    top_percentile: float = 0.75,
    bottom_percentile: float = 0.25,
    only_positive: bool = True,
    allow_shorts: bool = False,
    benchmark: str = "equal_weight_universe",
    asof_timestamp: str | None = None,
) -> dict[str, Any]:
    """Rankear símbolos con información disponible hasta `asof_timestamp`."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars debe ser positivo")
    if not 0.5 < top_percentile <= 1.0:
        raise ValueError("top_percentile debe estar entre 0.5 y 1.0")
    if not 0.0 <= bottom_percentile < 0.5:
        raise ValueError("bottom_percentile debe estar entre 0.0 y 0.5")
    asof = pd.Timestamp(asof_timestamp) if asof_timestamp else None
    if asof is not None:
        if asof.tzinfo is None:
            asof = asof.tz_localize("UTC")
        else:
            asof = asof.tz_convert("UTC")
    valid: dict[str, tuple[float, float, pd.Timestamp, float]] = {}
    missing: list[str] = []
    for symbol, frame in frames.items():
        data = _asof_frame(frame, asof)
        if data.empty:
            missing.append(symbol)
            continue
        if len(data) <= horizon_bars:
            continue
        current = float(data["close"].iloc[-1])
        previous = float(data["close"].iloc[-1 - horizon_bars])
        if current <= 0 or previous <= 0:
            continue
        formation_return = current / previous - 1.0
        returns = data["close"].pct_change().dropna().tail(horizon_bars)
        volatility = float(returns.std(ddof=1) * sqrt(horizon_bars)) if len(returns) > 1 else 0.0
        valid[symbol] = (formation_return, volatility, data.index[-1], current)
    if not valid:
        return {
            "asof_timestamp": asof.isoformat() if asof is not None else None,
            "benchmark": benchmark,
            "universe_size": 0,
            "missing_symbols": missing,
            "observations": [
                _empty(symbol, "missing_data" if symbol in missing else "insufficient_data", asof_timestamp=asof.isoformat() if asof is not None else None)
                for symbol in frames
            ],
            "mode": "shadow",
            "influence_entries": False,
            "orders_allowed": False,
        }
    formation = pd.Series({symbol: values[0] for symbol, values in valid.items()}, dtype=float)
    benchmark_return = float(formation.mean()) if benchmark == "equal_weight_universe" else None
    if benchmark_return is None:
        raise ValueError(f"Benchmark no soportado: {benchmark}")
    ranked = formation.rank(method="average", ascending=True)
    percentile = formation.rank(method="average", pct=True, ascending=True)
    shared_asof = max(values[2] for values in valid.values())
    observations: list[dict[str, Any]] = []
    for symbol in frames:
        if symbol not in valid:
            observations.append(
                _empty(
                    symbol,
                    "missing_data" if symbol in missing else "insufficient_data",
                    asof_timestamp=shared_asof.isoformat(),
                )
            )
            continue
        values = valid[symbol]
        ret = float(values[0])
        excess = ret - benchmark_return
        pct = float(percentile[symbol])
        if pct >= top_percentile and (not only_positive or ret > 0):
            direction = "bull"
            status = "leader"
        elif allow_shorts and pct <= bottom_percentile and (not only_positive or ret < 0):
            direction = "bear"
            status = "laggard"
        else:
            direction = "neutral"
            status = "ranked"
        observations.append(
            {
                "symbol": symbol,
                "direction": direction,
                "status": status,
                "rank": int(ranked[symbol]),
                "percentile": round(pct, 6),
                "return_formation": round(ret, 8),
                "benchmark_return": round(benchmark_return, 8),
                "excess_return": round(excess, 8),
                "universe_size": len(valid),
                "asof_timestamp": values[2].isoformat(),
                "horizon_bars": horizon_bars,
                "volatility": round(float(values[1]), 8),
                "mode": "shadow",
                "influence_entries": False,
                "orders_allowed": False,
            }
        )
    return {
        "asof_timestamp": shared_asof.isoformat(),
        "benchmark": benchmark,
        "benchmark_return": round(benchmark_return, 8),
        "universe_size": len(valid),
        "missing_symbols": missing,
        "observations": observations,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
        "source_version": "relative-strength-v1",
    }
