"""Detector puro de rebote RSI sobre SMA200."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data.columns = [str(column).lower() for column in data.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(data.columns):
        raise ValueError(f"Faltan columnas OHLCV: {sorted(required - set(data.columns))}")
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index, utc=True)
    elif data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")
    return data.sort_index().dropna(subset=list(required))


def _empty(symbol: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": "neutral",
        "signal": "no_setup",
        "status": reason,
        "rsi": None,
        "rsi_threshold": None,
        "sma200": None,
        "sma50": None,
        "oversold_timestamp": None,
        "confirmation_timestamp": None,
        "entry_timestamp": None,
        "atr": None,
        "stop_price": None,
        "target_price": None,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
    }


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def scan_rsi_bounces(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "15min",
    rsi_period: int = 5,
    oversold_threshold: float = 25.0,
    oversold_lookback: int = 5,
    sma_fast_period: int = 50,
    sma_trend_period: int = 200,
    atr_period: int = 14,
    require_sma_fast_above_trend: bool = False,
    break_buffer_atr: float = 0.05,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 1.5,
    hold_max_bars: int = 20,
    session_start: str = "09:30",
    session_end: str = "15:30",
    one_signal_per_session: bool = True,
) -> list[dict[str, Any]]:
    """Detectar rebotes confirmados usando únicamente barras cerradas."""
    if rsi_period < 1 or oversold_lookback < 1 or sma_fast_period < 1 or sma_trend_period < 1 or atr_period < 1 or hold_max_bars < 1:
        raise ValueError("Los periodos deben ser positivos")
    if oversold_threshold <= 0 or oversold_threshold >= 50:
        raise ValueError("oversold_threshold debe estar entre 0 y 50")
    if reward_risk <= 0 or break_buffer_atr < 0 or stop_buffer_atr < 0:
        raise ValueError("Parámetros de riesgo inválidos")
    data = _validate(frame)
    if data.empty:
        return []
    data = data.copy()
    data["rsi"] = _rsi(data["close"], rsi_period)
    data["sma_fast"] = data["close"].rolling(sma_fast_period, min_periods=sma_fast_period).mean()
    data["sma_trend"] = data["close"].rolling(sma_trend_period, min_periods=sma_trend_period).mean()
    prev_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = true_range.rolling(atr_period, min_periods=atr_period).mean()
    local = data.index.tz_convert("America/New_York")
    data["session_date"] = local.strftime("%Y-%m-%d")
    data["minutes"] = local.hour * 60 + local.minute
    start_minutes = int(session_start[:2]) * 60 + int(session_start[3:])
    end_minutes = int(session_end[:2]) * 60 + int(session_end[3:])
    data["oversold_min_prior"] = data["rsi"].shift(1).rolling(oversold_lookback, min_periods=oversold_lookback).min()
    data["prior_high"] = data["high"].shift(1).rolling(oversold_lookback, min_periods=oversold_lookback).max()
    data["prior_low"] = data["low"].shift(1).rolling(oversold_lookback, min_periods=oversold_lookback).min()
    closes = data["close"].to_numpy(dtype=float)
    rsi = data["rsi"].to_numpy(dtype=float)
    sma_fast = data["sma_fast"].to_numpy(dtype=float)
    sma_trend = data["sma_trend"].to_numpy(dtype=float)
    atr = data["atr"].to_numpy(dtype=float)
    oversold_min = data["oversold_min_prior"].to_numpy(dtype=float)
    prior_high = data["prior_high"].to_numpy(dtype=float)
    prior_low = data["prior_low"].to_numpy(dtype=float)
    minutes = data["minutes"].to_numpy(dtype=int)
    sessions = data["session_date"].to_numpy()
    warmup = max(rsi_period, sma_trend_period, atr_period, oversold_lookback + 1)
    active = (minutes >= start_minutes) & (minutes < end_minutes)
    finite = np.isfinite(rsi) & np.isfinite(sma_trend) & np.isfinite(atr) & (atr > 0) & np.isfinite(oversold_min) & np.isfinite(prior_high) & np.isfinite(prior_low)
    trend_ok = closes > sma_trend
    if require_sma_fast_above_trend:
        trend_ok &= np.isfinite(sma_fast) & (sma_fast > sma_trend)
    confirmed = active & finite & trend_ok & (oversold_min < oversold_threshold) & (rsi >= oversold_threshold) & (closes > prior_high + break_buffer_atr * atr)
    signals: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    for idx in np.flatnonzero(confirmed):
        if idx < warmup or idx >= len(data) - 1:
            continue
        session_day = str(sessions[idx])
        if one_signal_per_session and session_day in seen_sessions:
            continue
        oversold_index = max(0, idx - int(oversold_lookback))
        stop = min(float(prior_low[idx]), float(sma_trend[idx])) - stop_buffer_atr * float(atr[idx])
        target = float(closes[idx]) + reward_risk * (float(closes[idx]) - stop)
        signals.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "direction": "bull",
                "signal": "rsi_bounce_sma200",
                "status": "confirmed",
                "rsi": round(float(rsi[idx]), 8),
                "rsi_threshold": float(oversold_threshold),
                "sma200": round(float(sma_trend[idx]), 8),
                "sma50": round(float(sma_fast[idx]), 8) if np.isfinite(sma_fast[idx]) else None,
                "oversold_timestamp": data.index[oversold_index].isoformat(),
                "confirmation_timestamp": data.index[idx].isoformat(),
                "entry_timestamp": data.index[idx + 1].isoformat(),
                "atr": round(float(atr[idx]), 8),
                "stop_price": round(stop, 8),
                "target_price": round(target, 8),
                "hold_max_bars": int(hold_max_bars),
                "mode": "shadow",
                "influence_entries": False,
                "orders_allowed": False,
            }
        )
        seen_sessions.add(session_day)
    return signals


def evaluate_rsi_bounce(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    signals = scan_rsi_bounces(frame, **kwargs)
    return signals[-1] if signals else _empty(kwargs.get("symbol", ""), "no_setup")
