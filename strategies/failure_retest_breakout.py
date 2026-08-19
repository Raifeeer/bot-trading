"""Detector puro de aceptación, retest y fallo después de un breakout."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
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


def _event(
    symbol: str,
    timeframe: str,
    lookback: int,
    status: str,
    level: float | None = None,
    break_idx: int | None = None,
    retest_idx: int | None = None,
    decision_idx: int | None = None,
    data: pd.DataFrame | None = None,
    retest_tolerance_atr: float = 0.25,
    reward_risk: float = 1.5,
    stop_buffer_atr: float = 0.10,
    hold_max_bars: int = 20,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback": lookback,
        "direction": "bull",
        "status": status,
        "signal": status,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
        "observational_only": True,
    }
    if data is None or level is None or break_idx is None:
        return result
    break_row = data.iloc[break_idx]
    result.update(
        {
            "break_level": round(float(level), 8),
            "break_close": round(float(break_row["close"]), 8),
            "break_timestamp": data.index[break_idx].isoformat(),
            "session_date": str(break_row["session_date"]),
            "break_relative_volume": round(float(break_row["relative_volume"]), 8),
            "break_atr": round(float(break_row["atr"]), 8),
            "retest_timestamp": data.index[retest_idx].isoformat() if retest_idx is not None else None,
            "decision_timestamp": data.index[decision_idx].isoformat() if decision_idx is not None else None,
            "entry_timestamp": data.index[decision_idx + 1].isoformat() if status == "accepted" and decision_idx is not None and decision_idx + 1 < len(data) else None,
            "retest_tolerance_atr": retest_tolerance_atr,
            "hold_max_bars": hold_max_bars,
        }
    )
    if retest_idx is not None:
        retest_row = data.iloc[retest_idx]
        result["retest_low"] = round(float(retest_row["low"]), 8)
        result["retest_high"] = round(float(retest_row["high"]), 8)
        result["retest_atr"] = round(float(retest_row["atr"]), 8)
    if decision_idx is not None:
        decision_row = data.iloc[decision_idx]
        if status == "accepted":
            atr = float(decision_row["atr"])
            stop = float(level) - stop_buffer_atr * atr
            entry = float(data.iloc[decision_idx + 1]["open"]) if decision_idx + 1 < len(data) else float(decision_row["close"])
            result["stop_price"] = round(stop, 8)
            result["target_price"] = round(entry + reward_risk * (entry - stop), 8)
    return result


def scan_failure_retests(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "15min",
    lookback: int = 10,
    retest_max_bars: int = 3,
    retest_tolerance_atr: float = 0.25,
    volume_lookback: int = 20,
    volume_min: float = 0.0,
    atr_period: int = 14,
    reward_risk: float = 1.5,
    stop_buffer_atr: float = 0.10,
    hold_max_bars: int = 20,
    session_start: str = "09:30",
    session_end: str = "15:30",
    one_sequence_per_session: bool = True,
    allow_shorts: bool = False,
) -> list[dict[str, Any]]:
    """Clasificar secuencias de breakout/retest usando únicamente datos cerrados."""
    if min(lookback, retest_max_bars, volume_lookback, atr_period, hold_max_bars) < 1:
        raise ValueError("Los periodos deben ser positivos")
    if retest_tolerance_atr < 0 or volume_min < 0 or reward_risk <= 0 or stop_buffer_atr < 0:
        raise ValueError("Parámetros inválidos")
    if allow_shorts:
        raise ValueError("Las cortas están bloqueadas en failure/retest")
    data = _prepare(frame)
    if data.empty:
        return []
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
    data["break_level"] = data["high"].shift(1).rolling(lookback, min_periods=lookback).max()
    data["volume_baseline"] = data["volume"].shift(1).rolling(volume_lookback, min_periods=volume_lookback).mean()
    data["relative_volume"] = data["volume"] / data["volume_baseline"].replace(0.0, np.nan)
    local = data.index.tz_convert("America/New_York")
    data["session_date"] = local.strftime("%Y-%m-%d")
    data["minutes"] = local.hour * 60 + local.minute
    start_minute = int(session_start[:2]) * 60 + int(session_start[3:])
    end_minute = int(session_end[:2]) * 60 + int(session_end[3:])
    active = (data["minutes"] >= start_minute) & (data["minutes"] < end_minute)
    finite = data[["atr", "break_level", "relative_volume"]].notna().all(axis=1)
    confirmed = active & finite & (data["close"] > data["break_level"]) & (data["relative_volume"] >= volume_min)
    warmup = max(lookback, volume_lookback, atr_period)
    events: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    idx = warmup
    while idx < len(data) - 1:
        if not bool(confirmed.iloc[idx]):
            idx += 1
            continue
        session = str(data.iloc[idx]["session_date"])
        if one_sequence_per_session and session in seen_sessions:
            idx += 1
            continue
        level = float(data.iloc[idx]["break_level"])
        tolerance = retest_tolerance_atr
        touched_idx: int | None = None
        decision_idx: int | None = None
        status = "expired"
        end_idx = min(len(data) - 1, idx + retest_max_bars)
        for probe in range(idx + 1, end_idx + 1):
            row = data.iloc[probe]
            atr = float(row["atr"]) if pd.notna(row["atr"]) else np.nan
            if not np.isfinite(atr):
                continue
            if touched_idx is None:
                if float(row["close"]) < level - tolerance * atr:
                    status = "failed"
                    decision_idx = probe
                    break
                if float(row["low"]) <= level + tolerance * atr:
                    touched_idx = probe
                    continue
            else:
                if float(row["close"]) < level - tolerance * atr:
                    status = "failed"
                    decision_idx = probe
                    break
                retest_high = float(data.iloc[touched_idx]["high"])
                if float(row["close"]) > level and float(row["high"]) > retest_high:
                    status = "accepted"
                    decision_idx = probe
                    break
        events.append(
            _event(
                symbol,
                timeframe,
                lookback,
                status,
                level,
                idx,
                touched_idx,
                decision_idx,
                data,
                retest_tolerance_atr,
                reward_risk,
                stop_buffer_atr,
                hold_max_bars,
            )
        )
        seen_sessions.add(session)
        idx = max(idx + 1, (decision_idx or end_idx) + 1)
    return events


def evaluate_failure_retest(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    events = scan_failure_retests(frame, **kwargs)
    return events[-1] if events else {"symbol": kwargs.get("symbol", ""), "status": "no_setup", "signal": "no_setup", "mode": "shadow", "influence_entries": False, "orders_allowed": False}
