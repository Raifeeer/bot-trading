"""Detector puro de rupturas Donchian 20/55 con volumen."""
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


def _empty(symbol: str, reason: str, timeframe: str, lookback: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback": lookback,
        "direction": "neutral",
        "signal": "no_setup",
        "status": reason,
        "channel_high": None,
        "close": None,
        "relative_volume": None,
        "confirmation_timestamp": None,
        "entry_timestamp": None,
        "atr": None,
        "stop_price": None,
        "target_price": None,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
    }


def scan_breakouts(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "15min",
    lookback: int = 20,
    volume_lookback: int = 20,
    volume_min: float = 1.0,
    atr_period: int = 14,
    break_buffer_atr: float = 0.0,
    stop_buffer_atr: float = 0.10,
    reward_risk: float = 1.5,
    hold_max_bars: int = 20,
    session_start: str = "09:30",
    session_end: str = "15:30",
    one_signal_per_session: bool = True,
    allow_shorts: bool = False,
) -> list[dict[str, Any]]:
    """Detectar rupturas alcistas confirmadas con barras cerradas."""
    if min(lookback, volume_lookback, atr_period, hold_max_bars) < 1:
        raise ValueError("Los periodos deben ser positivos")
    if volume_min < 0 or break_buffer_atr < 0 or stop_buffer_atr < 0 or reward_risk <= 0:
        raise ValueError("Parámetros de ruptura/riesgo inválidos")
    if allow_shorts:
        raise ValueError("Las cortas están bloqueadas en Breakout20/55")
    data = _validate(frame)
    if data.empty:
        return []
    data = data.copy()
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
    data["channel_high"] = data["high"].shift(1).rolling(lookback, min_periods=lookback).max()
    data["prior_low"] = data["low"].shift(1).rolling(lookback, min_periods=lookback).min()
    data["volume_baseline"] = data["volume"].shift(1).rolling(volume_lookback, min_periods=volume_lookback).mean()
    data["relative_volume"] = data["volume"] / data["volume_baseline"].replace(0.0, np.nan)
    local = data.index.tz_convert("America/New_York")
    data["session_date"] = local.strftime("%Y-%m-%d")
    data["minutes"] = local.hour * 60 + local.minute
    start_minutes = int(session_start[:2]) * 60 + int(session_start[3:])
    end_minutes = int(session_end[:2]) * 60 + int(session_end[3:])
    active = (data["minutes"] >= start_minutes) & (data["minutes"] < end_minutes)
    finite = data[["atr", "channel_high", "prior_low", "relative_volume"]].notna().all(axis=1)
    confirmed = active & finite & (data["close"] > data["channel_high"] + break_buffer_atr * data["atr"]) & (data["relative_volume"] >= volume_min)
    warmup = max(lookback, volume_lookback, atr_period)
    signals: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    for idx in np.flatnonzero(confirmed.to_numpy()):
        if idx < warmup or idx >= len(data) - 1:
            continue
        session_day = str(data.iloc[idx]["session_date"])
        if one_signal_per_session and session_day in seen_sessions:
            continue
        row = data.iloc[idx]
        stop = min(float(row["prior_low"]), float(row["channel_high"])) - stop_buffer_atr * float(row["atr"])
        target = float(row["close"]) + reward_risk * (float(row["close"]) - stop)
        signals.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "lookback": lookback,
                "direction": "bull",
                "signal": "breakout_20_55",
                "status": "confirmed",
                "channel_high": round(float(row["channel_high"]), 8),
                "close": round(float(row["close"]), 8),
                "relative_volume": round(float(row["relative_volume"]), 8),
                "confirmation_timestamp": data.index[idx].isoformat(),
                "entry_timestamp": data.index[idx + 1].isoformat(),
                "atr": round(float(row["atr"]), 8),
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


def evaluate_breakout(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    signals = scan_breakouts(frame, **kwargs)
    return signals[-1] if signals else _empty(kwargs.get("symbol", ""), "no_setup", kwargs.get("timeframe", "15min"), int(kwargs.get("lookback", 20)))
