"""Estructura de mercado multi-timeframe para observabilidad shadow.

El módulo solo analiza barras cerradas que recibe el llamador. Cada swing usa
una ventana fractal y, por tanto, solo se considera confirmado cuando las
barras posteriores necesarias ya existen en el DataFrame entregado. No conoce
ni importa el executor, el sizing ni el RiskManager.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.smc import fractal_swing_points

DEFAULT_WEIGHTS = {"1d": 0.50, "15min": 0.30, "5min": 0.20}


def _normalise(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    mapping = {"open": "open", "high": "high", "low": "low",
               "close": "close", "volume": "volume",
               "Open": "open", "High": "high", "Low": "low",
               "Close": "close", "Volume": "volume"}
    rename = {column: mapping[column] for column in df.columns
              if column in mapping}
    out = df.rename(columns=rename).copy()
    required = {"high", "low", "close"}
    if not required.issubset(out.columns):
        return None
    out = out.dropna(subset=["high", "low", "close"])
    if out.empty:
        return None
    return out.sort_index()


def _iso_index(df: pd.DataFrame, idx: int) -> str | None:
    if not hasattr(df.index, "__getitem__") or idx >= len(df.index):
        return None
    value = pd.Timestamp(df.index[idx])
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    return value.isoformat()


def _trend_for_frame(df: pd.DataFrame | None, order: int = 3,
                     tolerance: float = 0.001) -> dict[str, Any]:
    frame = _normalise(df)
    if frame is None or len(frame) < 2 * order + 7:
        return {
            "direction": "neutral", "status": "insufficient_data",
            "confirmed_highs": 0, "confirmed_lows": 0,
            "last_confirmed_pivot": None, "higher_high": False,
            "higher_low": False, "lower_high": False, "lower_low": False,
            "break": "none",
        }

    swings = fractal_swing_points(frame, order=order, conservative=True)
    highs = [s for s in swings if s.is_high]
    lows = [s for s in swings if not s.is_high]
    result: dict[str, Any] = {
        "direction": "neutral", "status": "confirmed",
        "confirmed_highs": len(highs), "confirmed_lows": len(lows),
        "last_confirmed_pivot": None, "higher_high": False,
        "higher_low": False, "lower_high": False, "lower_low": False,
        "break": "none",
    }
    if swings:
        last_swing = swings[-1]
        result["last_confirmed_pivot"] = {
            "kind": "high" if last_swing.is_high else "low",
            "price": round(float(last_swing.price), 6),
            "timestamp": _iso_index(frame, last_swing.idx),
        }
    if len(highs) < 2 or len(lows) < 2:
        result["status"] = "insufficient_swings"
        return result

    prev_high, last_high = highs[-2].price, highs[-1].price
    prev_low, last_low = lows[-2].price, lows[-1].price
    high_tol = max(abs(float(prev_high)) * tolerance, 1e-12)
    low_tol = max(abs(float(prev_low)) * tolerance, 1e-12)
    result["higher_high"] = bool(last_high > prev_high + high_tol)
    result["higher_low"] = bool(last_low > prev_low + low_tol)
    result["lower_high"] = bool(last_high < prev_high - high_tol)
    result["lower_low"] = bool(last_low < prev_low - low_tol)

    close = float(frame["close"].iloc[-1])
    if result["higher_high"] and result["higher_low"]:
        result["direction"] = "bull"
        if close > float(last_high):
            result["break"] = "bull"
    elif result["lower_high"] and result["lower_low"]:
        result["direction"] = "bear"
        if close < float(last_low):
            result["break"] = "bear"
    return result


def evaluate_structure_mtf(frames: dict[str, pd.DataFrame | None],
                           weights: dict[str, float] | None = None,
                           order: int = 3,
                           tolerance: float = 0.001) -> dict[str, Any]:
    """Evalúa 1d/15min/5min sin conceder autoridad operativa.

    `frames` debe contener únicamente barras cerradas al momento de evaluar.
    Para backtests, el llamador debe truncar cada DataFrame a la fecha de
    evaluación antes de invocar esta función.
    """
    frame_weights = dict(DEFAULT_WEIGHTS)
    frame_weights.update(weights or {})
    by_timeframe = {}
    weighted_score = 0.0
    weight_available = 0.0
    for timeframe, weight in frame_weights.items():
        obs = _trend_for_frame(frames.get(timeframe), order, tolerance)
        by_timeframe[timeframe] = obs
        if obs["status"] == "confirmed":
            value = 1.0 if obs["direction"] == "bull" else -1.0 if obs["direction"] == "bear" else 0.0
            weighted_score += float(weight) * value
            weight_available += float(weight)
    score = weighted_score / weight_available if weight_available else 0.0
    if score >= 0.50:
        direction = "bull"
    elif score <= -0.50:
        direction = "bear"
    else:
        direction = "mixed" if abs(score) > 0.0 else "neutral"
    return {
        "mode": "shadow",
        "orders_allowed": False,
        "influence_entries": False,
        "direction": direction,
        "score": round(score, 6),
        "available_weight": round(weight_available, 6),
        "by_timeframe": by_timeframe,
    }


def evaluate_universe_structure(universe_frames: dict[str, dict[str, pd.DataFrame | None]],
                                weights: dict[str, float] | None = None,
                                order: int = 3,
                                tolerance: float = 0.001) -> dict[str, Any]:
    """Evalúa todos los símbolos y devuelve contadores observacionales."""
    symbols = {
        symbol: evaluate_structure_mtf(frames, weights, order, tolerance)
        for symbol, frames in universe_frames.items()
    }
    bull_count = sum(obs["direction"] == "bull" for obs in symbols.values())
    bear_count = sum(obs["direction"] == "bear" for obs in symbols.values())
    return {
        "mode": "shadow",
        "orders_allowed": False,
        "influence_entries": False,
        "symbols": symbols,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "neutral_or_mixed_count": len(symbols) - bull_count - bear_count,
        "universe_size": len(symbols),
    }
