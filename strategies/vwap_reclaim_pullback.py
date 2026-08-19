"""Detector determinista de VWAP reclaim/pullback intradía."""
from __future__ import annotations

from datetime import time
from typing import Any

import numpy as np
import pandas as pd

MODES = {"reclaim", "pullback"}
DIRECTIONS = {"long", "short", "both"}


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    out = frame.rename(columns=str.lower).copy()
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def _session_date(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.tz_convert("America/New_York").strftime("%Y-%m-%d"), index=index)


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


def _parse_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour=hour, minute=minute)


def _in_rth(index: pd.DatetimeIndex, start: time, end: time) -> pd.Series:
    local = index.tz_convert("America/New_York")
    times = pd.Series(local.time, index=index)
    return (times >= start) & (times < end)


def _empty(timeframe: str, status: str = "no_setup") -> dict[str, Any]:
    return {
        "signal": "none",
        "status": status,
        "direction": "neutral",
        "timeframe": timeframe,
        "mode": "shadow",
        "orders_allowed": False,
    }


def scan_vwap(
    frame: pd.DataFrame,
    *,
    timeframe: str = "5min",
    mode: str = "reclaim",
    direction: str = "both",
    session_start: str = "09:30",
    session_end: str = "15:30",
    atr_period: int = 14,
    min_impulse_bars: int = 2,
    displacement_atr: float = 0.50,
    vwap_tolerance_atr: float = 0.25,
    max_penetration_atr: float = 0.75,
    break_buffer_atr: float = 0.05,
    volume_lookback: int = 20,
    volume_min: float = 1.20,
    require_volume: bool = True,
    pullback_lookback: int = 3,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 2.0,
    one_signal_per_session: bool = True,
) -> list[dict[str, Any]]:
    """Detectar reclaims/pullbacks usando únicamente barras cerradas hasta cada evento."""
    if mode not in MODES:
        raise ValueError(f"Modo no soportado: {mode}")
    if direction not in DIRECTIONS:
        raise ValueError(f"Dirección no soportada: {direction}")
    if min_impulse_bars < 1 or pullback_lookback < 1:
        raise ValueError("min_impulse_bars y pullback_lookback deben ser positivos")
    data = _normalize(frame)
    if data.empty:
        return []
    start = _parse_time(session_start)
    end = _parse_time(session_end)
    data["session_date"] = _session_date(data.index).to_numpy()
    rth = _in_rth(data.index, start, end)
    typical = (data["high"] + data["low"] + data["close"]) / 3.0
    pv = (typical * data["volume"]).where(rth, 0.0)
    vol = data["volume"].where(rth, 0.0)
    session_key = data["session_date"]
    data["session_vwap"] = pv.groupby(session_key).cumsum() / vol.groupby(session_key).cumsum().replace(0.0, np.nan)
    tr = _true_range(data)
    data["atr"] = tr.rolling(atr_period, min_periods=atr_period).mean()
    data["volume_ref"] = data["volume"].where(rth).shift(1).rolling(
        volume_lookback, min_periods=volume_lookback
    ).mean()
    observations: list[dict[str, Any]] = []
    for session_date, session in data.loc[rth].groupby("session_date", sort=True):
        session_positions = list(session.index)
        emitted = False
        for pos, timestamp in enumerate(session_positions):
            if emitted and one_signal_per_session:
                break
            row = data.loc[timestamp]
            if pd.isna(row["session_vwap"]) or pd.isna(row["atr"]) or float(row["atr"]) <= 0:
                continue
            if pos < min_impulse_bars + 1:
                continue
            prior = session.iloc[:pos]
            prior = prior.dropna(subset=["session_vwap", "atr"])
            if len(prior) < min_impulse_bars:
                continue
            prior_distance = (prior["close"] - prior["session_vwap"]) / prior["atr"].replace(0.0, np.nan)
            recent = prior.tail(max(min_impulse_bars, pullback_lookback + 1))
            previous = prior.iloc[-1]
            current_atr = float(row["atr"])
            current_vwap = float(row["session_vwap"])
            previous_vwap = float(previous["session_vwap"])
            distance_atr = (float(row["close"]) - current_vwap) / current_atr
            vwap_slope = (current_vwap - previous_vwap) / current_atr
            volume_ref = row["volume_ref"]
            volume_ratio = (
                float(row["volume"] / volume_ref)
                if pd.notna(volume_ref) and float(volume_ref) > 0
                else np.nan
            )
            volume_ok = not require_volume or (
                np.isfinite(volume_ratio) and volume_ratio >= volume_min
            )
            long_allowed = direction in {"long", "both"}
            short_allowed = direction in {"short", "both"}
            long_displacement = bool((prior_distance >= displacement_atr).any())
            short_displacement = bool((prior_distance <= -displacement_atr).any())
            tolerance = vwap_tolerance_atr * current_atr
            penetration = max_penetration_atr * current_atr
            prior_micro_high = float(recent["high"].tail(pullback_lookback).max())
            prior_micro_low = float(recent["low"].tail(pullback_lookback).min())
            long_retrace = (
                float(row["low"]) <= current_vwap + tolerance
                and float(row["low"]) >= current_vwap - penetration
            )
            short_retrace = (
                float(row["high"]) >= current_vwap - tolerance
                and float(row["high"]) <= current_vwap + penetration
            )
            long_reclaim = (
                float(previous["close"]) <= previous_vwap
                and float(row["close"]) > current_vwap + break_buffer_atr * current_atr
            )
            short_reclaim = (
                float(previous["close"]) >= previous_vwap
                and float(row["close"]) < current_vwap - break_buffer_atr * current_atr
            )
            long_pullback = (
                long_displacement
                and long_retrace
                and float(row["close"]) > prior_micro_high
                and vwap_slope > 0
            )
            short_pullback = (
                short_displacement
                and short_retrace
                and float(row["close"]) < prior_micro_low
                and vwap_slope < 0
            )
            long_signal = long_allowed and volume_ok and (
                (mode == "reclaim" and long_displacement and long_retrace and long_reclaim)
                or (mode == "pullback" and long_pullback)
            )
            short_signal = short_allowed and volume_ok and (
                (mode == "reclaim" and short_displacement and short_retrace and short_reclaim)
                or (mode == "pullback" and short_pullback)
            )
            if not long_signal and not short_signal:
                continue
            is_long = bool(long_signal)
            side = "bull" if is_long else "bear"
            swing = float(recent["low"].min()) if is_long else float(recent["high"].max())
            stop = swing - current_atr * stop_buffer_atr if is_long else swing + current_atr * stop_buffer_atr
            risk = max(abs(float(row["close"]) - stop), current_atr * 0.05)
            target = float(row["close"]) + reward_risk * risk if is_long else float(row["close"]) - reward_risk * risk
            observations.append(
                {
                    "signal": "vwap_reclaim" if mode == "reclaim" else "vwap_pullback",
                    "status": "confirmed",
                    "direction": side,
                    "timeframe": timeframe,
                    "mode_name": mode,
                    "session_date": str(session_date),
                    "session_vwap": current_vwap,
                    "vwap_slope": float(vwap_slope),
                    "distance_atr": float(distance_atr),
                    "displacement": bool(long_displacement if is_long else short_displacement),
                    "retracement": bool(long_retrace if is_long else short_retrace),
                    "resumption": bool(long_reclaim if is_long else short_pullback),
                    "confirmation_timestamp": timestamp,
                    "volume_ratio": float(volume_ratio) if np.isfinite(volume_ratio) else None,
                    "stop_price": float(stop),
                    "target_price": float(target),
                    "invalidation": "close_through_vwap_or_pullback_swing",
                    "mode": "shadow",
                    "orders_allowed": False,
                }
            )
            emitted = True
    return observations


def evaluate_vwap(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    """Devolver la última observación o un estado neutral fail-closed."""
    observations = scan_vwap(frame, **kwargs)
    if observations:
        return observations[-1]
    return _empty(kwargs.get("timeframe", "5min"), "no_setup")
