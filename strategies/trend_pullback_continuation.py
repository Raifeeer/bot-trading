"""Detector puro de pullback de continuación de tendencia."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.columns = [str(column).lower() for column in out.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(out.columns):
        raise ValueError(f"Faltan columnas OHLCV: {sorted(required - set(out.columns))}")
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    elif out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out.sort_index().dropna(subset=list(required))


def _session_vwap(frame: pd.DataFrame) -> pd.Series:
    session = frame.index.tz_convert("America/New_York").strftime("%Y-%m-%d")
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    weighted = typical * frame["volume"]
    denominator = frame["volume"].groupby(session).cumsum().replace(0, np.nan)
    return weighted.groupby(session).cumsum() / denominator


def _empty(symbol: str, reason: str, timestamp: pd.Timestamp | None = None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": "neutral",
        "signal": "no_setup",
        "status": reason,
        "trend_state": "unknown",
        "impulse_timestamp": None,
        "pullback_timestamp": None,
        "confirmation_timestamp": timestamp.isoformat() if timestamp is not None else None,
        "entry_timestamp": None,
        "ema_fast": None,
        "ema_slow": None,
        "vwap": None,
        "atr": None,
        "volume_ratio": None,
        "stop_price": None,
        "target_price": None,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
    }


def scan_trend_pullbacks(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "5min",
    direction: str = "long",
    ema_fast: int = 9,
    ema_slow: int = 21,
    atr_period: int = 14,
    trend_slope_bars: int = 3,
    impulse_lookback: int = 5,
    pullback_lookback: int = 3,
    impulse_atr: float = 0.75,
    vwap_tolerance_atr: float = 0.50,
    break_buffer_atr: float = 0.05,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 2.0,
    volume_lookback: int = 20,
    volume_min: float = 1.0,
    require_volume: bool = False,
    require_vwap_alignment: bool = True,
    allow_shorts: bool = False,
    session_start: str = "09:30",
    session_end: str = "15:30",
    one_signal_per_session: bool = True,
) -> list[dict[str, Any]]:
    """Detectar continuaciones usando solo barras cerradas hasta la confirmación."""
    if direction not in {"long", "short", "both"}:
        raise ValueError("direction debe ser long, short o both")
    periods = (ema_fast, ema_slow, atr_period, trend_slope_bars, impulse_lookback, pullback_lookback, volume_lookback)
    if any(value < 1 for value in periods):
        raise ValueError("Los periodos deben ser positivos")
    if ema_fast >= ema_slow:
        raise ValueError("ema_fast debe ser menor que ema_slow")
    if reward_risk <= 0 or impulse_atr < 0 or volume_min <= 0:
        raise ValueError("Parámetros de riesgo/volumen inválidos")
    data = _validate(frame)
    if data.empty:
        return []
    data = data.copy()
    data["ema_fast"] = data["close"].ewm(span=ema_fast, adjust=False, min_periods=ema_fast).mean()
    data["ema_slow"] = data["close"].ewm(span=ema_slow, adjust=False, min_periods=ema_slow).mean()
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = true_range.rolling(atr_period, min_periods=atr_period).mean()
    data["vwap"] = _session_vwap(data)
    data["volume_ratio"] = data["volume"] / data["volume"].shift(1).rolling(
        volume_lookback, min_periods=max(3, min(volume_lookback, 3))
    ).mean()
    local = data.index.tz_convert("America/New_York")
    data["session_date"] = local.strftime("%Y-%m-%d")
    minutes = local.hour * 60 + local.minute
    start_minutes = int(session_start[:2]) * 60 + int(session_start[3:])
    end_minutes = int(session_end[:2]) * 60 + int(session_end[3:])

    closes = data["close"].to_numpy(dtype=float)
    fast = data["ema_fast"].to_numpy(dtype=float)
    slow = data["ema_slow"].to_numpy(dtype=float)
    atr = data["atr"].to_numpy(dtype=float)
    vwap = data["vwap"].to_numpy(dtype=float)
    volume_ratio = data["volume_ratio"].to_numpy(dtype=float)
    pb_low = data["low"].rolling(pullback_lookback).min().shift(1).to_numpy(dtype=float)
    pb_high = data["high"].rolling(pullback_lookback).max().shift(1).to_numpy(dtype=float)
    pb_first_close = data["close"].shift(pullback_lookback).to_numpy(dtype=float)
    pb_last_close = data["close"].shift(1).to_numpy(dtype=float)
    prior_end_close = data["close"].shift(pullback_lookback + 1).to_numpy(dtype=float)
    prior_start_close = data["close"].shift(pullback_lookback + impulse_lookback).to_numpy(dtype=float)
    slope = fast - np.roll(fast, trend_slope_bars)
    valid_slope = np.arange(len(data)) >= trend_slope_bars
    warmup = max(ema_slow, atr_period, impulse_lookback + pullback_lookback + 1, volume_lookback + 1, trend_slope_bars + 1)
    active = (minutes >= start_minutes) & (minutes < end_minutes)
    finite = np.isfinite(fast) & np.isfinite(slow) & np.isfinite(atr) & (atr > 0)
    volume_ok = np.ones(len(data), dtype=bool) if not require_volume else (np.isfinite(volume_ratio) & (volume_ratio >= volume_min))
    vwap_ok = np.ones(len(data), dtype=bool) if not require_vwap_alignment else (np.isfinite(vwap) & (vwap > 0))
    bull_trend = (fast > slow) & (slope > 0) & (closes > slow) & valid_slope
    bear_trend = (fast < slow) & (slope < 0) & (closes < slow) & valid_slope
    bull_impulse = (prior_end_close - prior_start_close) >= impulse_atr * atr
    bear_impulse = (prior_start_close - prior_end_close) >= impulse_atr * atr
    bull_pullback = (pb_low <= fast + vwap_tolerance_atr * atr) & (pb_low >= slow - 1.5 * atr) & (pb_last_close <= pb_first_close)
    bear_pullback = (pb_high >= fast - vwap_tolerance_atr * atr) & (pb_high <= slow + 1.5 * atr) & (pb_last_close >= pb_first_close)
    bull_alignment = np.ones(len(data), dtype=bool) if not require_vwap_alignment else (closes >= vwap)
    bear_alignment = np.ones(len(data), dtype=bool) if not require_vwap_alignment else (closes <= vwap)
    bull_break = closes > pb_high + break_buffer_atr * atr
    bear_break = closes < pb_low - break_buffer_atr * atr
    confirmed_bull = np.full(len(data), direction in {"long", "both"}, dtype=bool) & (active & finite & vwap_ok & volume_ok & bull_trend & bull_impulse & bull_pullback & bull_alignment & bull_break)
    confirmed_bear = np.full(len(data), direction in {"short", "both"} and allow_shorts, dtype=bool) & (active & finite & vwap_ok & volume_ok & bear_trend & bear_impulse & bear_pullback & bear_alignment & bear_break)

    sessions = data["session_date"].to_numpy()
    indices = np.flatnonzero(confirmed_bull | confirmed_bear)
    signals: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    for idx in indices:
        if idx < warmup or idx >= len(data) - 1:
            continue
        session_day = str(sessions[idx])
        if one_signal_per_session and session_day in seen_sessions:
            continue
        is_bull = bool(confirmed_bull[idx]) and not bool(confirmed_bear[idx])
        side = "bull" if is_bull else "bear"
        confirmation_timestamp = data.index[idx]
        entry_timestamp = data.index[idx + 1]
        if side == "bull":
            stop = min(float(pb_low[idx]), float(slow[idx])) - stop_buffer_atr * float(atr[idx])
            target = float(closes[idx]) + reward_risk * (float(closes[idx]) - stop)
        else:
            stop = max(float(pb_high[idx]), float(slow[idx])) + stop_buffer_atr * float(atr[idx])
            target = float(closes[idx]) - reward_risk * (stop - float(closes[idx]))
        signals.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "direction": side,
                "signal": "trend_pullback_continuation",
                "status": "confirmed",
                "trend_state": "bull" if is_bull else "bear",
                "impulse_timestamp": data.index[idx - pullback_lookback - 1].isoformat(),
                "pullback_timestamp": data.index[idx - 1].isoformat(),
                "confirmation_timestamp": confirmation_timestamp.isoformat(),
                "entry_timestamp": entry_timestamp.isoformat(),
                "ema_fast": round(float(fast[idx]), 8),
                "ema_slow": round(float(slow[idx]), 8),
                "vwap": round(float(vwap[idx]), 8),
                "atr": round(float(atr[idx]), 8),
                "volume_ratio": round(float(volume_ratio[idx]), 8) if np.isfinite(volume_ratio[idx]) else None,
                "stop_price": round(stop, 8),
                "target_price": round(target, 8),
                "mode": "shadow",
                "influence_entries": False,
                "orders_allowed": False,
            }
        )
        seen_sessions.add(session_day)
    return signals


def evaluate_trend_pullback(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    signals = scan_trend_pullbacks(frame, **kwargs)
    if signals:
        return signals[-1]
    return _empty(kwargs.get("symbol", ""), "no_setup")
