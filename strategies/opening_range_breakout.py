"""Detector determinista de Opening Range Breakout intradía."""
from __future__ import annotations

from datetime import time
from typing import Any

import numpy as np
import pandas as pd

SUPPORTED_DIRECTIONS = {"long", "short", "both"}
SUPPORTED_RANGE_MINUTES = {5, 15, 30}


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    out = frame.rename(columns=str.lower).copy()
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    if out.index.tz is None:
        out.index = pd.to_datetime(out.index, utc=True)
    else:
        out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def _session_time(value: pd.Timestamp) -> time:
    return value.tz_convert("America/New_York").time()


def _session_date(value: pd.Timestamp) -> str:
    return value.tz_convert("America/New_York").date().isoformat()


def _parse_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour=hour, minute=minute)


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def scan_orb(
    frame: pd.DataFrame,
    *,
    timeframe: str = "5min",
    opening_range_minutes: int = 30,
    direction: str = "both",
    session_start: str = "09:30",
    session_end: str = "15:30",
    atr_period: int = 14,
    break_buffer_atr: float = 0.05,
    volume_lookback: int = 20,
    volume_min: float = 1.0,
    require_volume: bool = True,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 2.0,
    one_signal_per_session: bool = True,
) -> list[dict[str, Any]]:
    """Devuelve rupturas confirmadas usando solo barras cerradas hasta cada evento."""
    if direction not in SUPPORTED_DIRECTIONS:
        raise ValueError(f"Dirección no soportada: {direction}")
    if opening_range_minutes not in SUPPORTED_RANGE_MINUTES:
        raise ValueError(f"Rango no soportado: {opening_range_minutes}")
    if atr_period < 1 or volume_lookback < 1:
        raise ValueError("atr_period y volume_lookback deben ser positivos")

    data = _normalize(frame)
    if data.empty:
        return []
    start = _parse_time(session_start)
    end = _parse_time(session_end)
    range_end_minutes = start.hour * 60 + start.minute + opening_range_minutes
    range_end = time(range_end_minutes // 60, range_end_minutes % 60)
    atr = _true_range(data).rolling(atr_period, min_periods=atr_period).mean()
    volume_reference = data["volume"].shift(1).rolling(
        volume_lookback, min_periods=volume_lookback
    ).mean()
    observations: list[dict[str, Any]] = []
    current_date: str | None = None
    range_high: float | None = None
    range_low: float | None = None
    emitted = False

    for index, row in data.iterrows():
        local_time = _session_time(index)
        date_key = _session_date(index)
        if date_key != current_date:
            current_date = date_key
            range_high = None
            range_low = None
            emitted = False
        if local_time < start or local_time >= end:
            continue
        if local_time < range_end:
            high = float(row["high"])
            low = float(row["low"])
            range_high = high if range_high is None else max(range_high, high)
            range_low = low if range_low is None else min(range_low, low)
            continue
        if range_high is None or range_low is None or (emitted and one_signal_per_session):
            continue

        current_atr = float(atr.loc[index]) if pd.notna(atr.loc[index]) else np.nan
        if not np.isfinite(current_atr) or current_atr <= 0:
            continue
        volume_ratio = (
            float(row["volume"] / volume_reference.loc[index])
            if pd.notna(volume_reference.loc[index]) and volume_reference.loc[index] > 0
            else np.nan
        )
        volume_ok = not require_volume or (
            np.isfinite(volume_ratio) and volume_ratio >= volume_min
        )
        if not volume_ok:
            continue

        close = float(row["close"])
        threshold = break_buffer_atr * current_atr
        long_break = direction in {"long", "both"} and close > range_high + threshold
        short_break = direction in {"short", "both"} and close < range_low - threshold
        if not long_break and not short_break:
            continue

        side = "bull" if long_break else "bear"
        stop = (
            range_low - current_atr * stop_buffer_atr
            if side == "bull"
            else range_high + current_atr * stop_buffer_atr
        )
        risk = max(abs(close - stop), current_atr * 0.05)
        target = close + reward_risk * risk if side == "bull" else close - reward_risk * risk
        observations.append(
            {
                "signal": "orb_breakout",
                "status": "confirmed",
                "direction": side,
                "timeframe": timeframe,
                "session_date": date_key,
                "opening_range_minutes": opening_range_minutes,
                "opening_range_high": float(range_high),
                "opening_range_low": float(range_low),
                "break_timestamp": index,
                "confirmation_timestamp": index,
                "break_close": close,
                "atr": current_atr,
                "volume_ratio": float(volume_ratio) if np.isfinite(volume_ratio) else None,
                "stop_price": float(stop),
                "target_price": float(target),
                "invalidation": "close_back_inside_opening_range",
                "mode": "shadow",
                "orders_allowed": False,
            }
        )
        emitted = True

    return observations


def evaluate_orb(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    """Devuelve la última observación ORB o un estado neutral serializable."""
    observations = scan_orb(frame, **kwargs)
    if observations:
        return observations[-1]
    timeframe = kwargs.get("timeframe", "5min")
    return {
        "signal": "none",
        "status": "no_setup",
        "direction": "mixed",
        "timeframe": timeframe,
        "mode": "shadow",
        "orders_allowed": False,
    }
