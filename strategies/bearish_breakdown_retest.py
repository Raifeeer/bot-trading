"""Detector determinista de breakdown bearish y retest fallido."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

SUPPORTED_MODES = {"rolling_support", "opening_range_low", "swing_support"}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    out = df.rename(columns=str.lower).copy()
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    return out.sort_index()


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"],
         (df["high"] - prev_close).abs(),
         (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def _in_session(ts: Any, start: str | None, end: str | None) -> bool:
    if not start or not end:
        return True
    value = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
    return start <= value < end


def scan_breakdown_retests(
    df: pd.DataFrame,
    *,
    timeframe: str = "15min",
    support_mode: str = "rolling_support",
    lookback: int = 20,
    atr_period: int = 14,
    break_atr: float = 0.10,
    volume_min: float = 1.20,
    retest_max_bars: int = 3,
    retest_tolerance_atr: float = 0.25,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 2.0,
    session_start: str | None = None,
    session_end: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve todas las confirmaciones, usando únicamente barras cerradas."""
    if support_mode not in SUPPORTED_MODES:
        raise ValueError(f"support_mode no soportado: {support_mode}")
    frame = _normalize(df)
    if len(frame) < max(lookback + atr_period + 5, 40):
        return []

    tr = _true_range(frame)
    atr = tr.rolling(atr_period, min_periods=atr_period).mean()
    support = frame["low"].shift(1).rolling(lookback, min_periods=lookback).min()
    volume_ref = frame["volume"].shift(1).rolling(20, min_periods=20).mean()
    candidate: dict[str, Any] | None = None
    confirmations: list[dict[str, Any]] = []

    previous_session_day = None
    for i in range(len(frame)):
        ts = frame.index[i]
        session_day = ts.tz_convert("America/New_York").date() if getattr(ts, "tzinfo", None) else ts.date()
        if previous_session_day is not None and session_day != previous_session_day:
            candidate = None
        previous_session_day = session_day
        if not _in_session(ts, session_start, session_end):
            continue
        current_atr = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else np.nan
        level = float(support.iloc[i]) if pd.notna(support.iloc[i]) else np.nan
        if not np.isfinite(current_atr) or current_atr <= 0 or not np.isfinite(level):
            continue

        row = frame.iloc[i]
        close = float(row["close"])
        high = float(row["high"])
        volume_ratio = (
            float(row["volume"] / volume_ref.iloc[i])
            if pd.notna(volume_ref.iloc[i]) and volume_ref.iloc[i] > 0
            else np.nan
        )

        if candidate is not None:
            bars_since_break = i - candidate["break_index"]
            tolerance = candidate["atr"] * retest_tolerance_atr
            if bars_since_break > retest_max_bars or close > candidate["support"] + tolerance:
                candidate = None
            elif high >= candidate["support"] - tolerance and float(row["low"]) <= candidate["support"] + tolerance:
                bearish_rejection = close < float(row["open"]) and close < candidate["support"]
                if bearish_rejection:
                    stop = max(high, candidate["support"] + tolerance) + current_atr * stop_buffer_atr
                    risk = max(stop - close, current_atr * 0.05)
                    confirmations.append({
                        "signal": "bearish_breakdown_retest",
                        "status": "confirmed",
                        "direction": "bear",
                        "timeframe": timeframe,
                        "support_mode": support_mode,
                        "support_level": candidate["support"],
                        "break_timestamp": candidate["break_timestamp"],
                        "retest_timestamp": ts,
                        "confirmation_timestamp": ts,
                        "break_close": candidate["break_close"],
                        "break_volume_ratio": candidate["volume_ratio"],
                        "retest_distance_atr": abs(high - candidate["support"]) / candidate["atr"],
                        "bars_to_retest": bars_since_break,
                        "stop_price": float(stop),
                        "target_price": float(close - reward_risk * risk),
                        "invalidation": "close_above_broken_support",
                        "mode": "shadow",
                        "orders_allowed": False,
                    })
                    candidate = None
                    continue

        volume_ok = np.isfinite(volume_ratio) and volume_ratio >= volume_min
        break_ok = close < level - break_atr * current_atr
        if break_ok and volume_ok:
            candidate = {
                "break_index": i,
                "break_timestamp": ts,
                "support": level,
                "break_close": close,
                "volume_ratio": volume_ratio,
                "atr": current_atr,
                "session_day": session_day,
            }

    return confirmations


def evaluate_breakdown_retest(
    df: pd.DataFrame,
    *,
    timeframe: str = "15min",
    support_mode: str = "rolling_support",
    lookback: int = 20,
    atr_period: int = 14,
    break_atr: float = 0.10,
    volume_min: float = 1.20,
    retest_max_bars: int = 3,
    retest_tolerance_atr: float = 0.25,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 2.0,
    session_start: str | None = None,
    session_end: str | None = None,
) -> dict[str, Any]:
    """Devuelve la última señal confirmada o un estado neutral de observación."""
    frame = _normalize(df)
    if len(frame) < max(lookback + atr_period + 5, 40):
        return {"signal": "none", "status": "insufficient_data", "timeframe": timeframe}
    confirmations = scan_breakdown_retests(
        frame,
        timeframe=timeframe,
        support_mode=support_mode,
        lookback=lookback,
        atr_period=atr_period,
        break_atr=break_atr,
        volume_min=volume_min,
        retest_max_bars=retest_max_bars,
        retest_tolerance_atr=retest_tolerance_atr,
        stop_buffer_atr=stop_buffer_atr,
        reward_risk=reward_risk,
        session_start=session_start,
        session_end=session_end,
    )
    if confirmations:
        return confirmations[-1]
    return {
        "signal": "none",
        "status": "no_setup",
        "direction": "bear",
        "timeframe": timeframe,
        "mode": "shadow",
        "orders_allowed": False,
    }
