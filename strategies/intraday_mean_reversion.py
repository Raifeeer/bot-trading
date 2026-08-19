"""Detector puro de extensiones intradía y reversión hacia VWAP."""
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
    data = data.sort_index().dropna(subset=list(required))
    if data.empty:
        return data
    local = data.index.tz_convert("America/New_York")
    data["session_date"] = local.strftime("%Y-%m-%d")
    data["minutes"] = local.hour * 60 + local.minute
    typical = (data["high"] + data["low"] + data["close"]) / 3.0
    data["pv"] = typical * data["volume"]
    data["cum_volume"] = data.groupby("session_date")["volume"].cumsum()
    data["vwap"] = data.groupby("session_date")["pv"].cumsum() / data["cum_volume"].replace(0.0, np.nan)
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["atr"] = true_range.rolling(14, min_periods=14).mean()
    data["z_vwap"] = (data["close"] - data["vwap"]) / data["atr"].replace(0.0, np.nan)
    return data


def _empty(symbol: str, reason: str, timeframe: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": "bull",
        "status": reason,
        "signal": reason,
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
        "observational_only": True,
        "risk_authority": "risk_manager_only",
    }


def scan_intraday_mean_reversion(
    frame: pd.DataFrame,
    *,
    symbol: str = "",
    timeframe: str = "5min",
    extension_atr: float = 1.5,
    reclaim_atr: float = 0.5,
    gate: str = "bull",
    regime_by_session: dict[str, str] | None = None,
    session_start: str = "09:45",
    session_end: str = "15:15",
    max_hold_bars: int = 12,
    one_signal_per_session: bool = True,
    allow_shorts: bool = False,
) -> list[dict[str, Any]]:
    """Detectar extensiones bajo VWAP y reclaim posterior usando barras cerradas."""
    if extension_atr <= reclaim_atr or reclaim_atr < 0 or max_hold_bars < 1:
        raise ValueError("Los umbrales o max_hold_bars son inválidos")
    if gate not in {"none", "bull", "no_crash"}:
        raise ValueError("gate no soportado")
    if allow_shorts:
        raise ValueError("Las cortas están bloqueadas")
    data = _prepare(frame)
    if data.empty:
        return []
    start_minute = int(session_start[:2]) * 60 + int(session_start[3:])
    end_minute = int(session_end[:2]) * 60 + int(session_end[3:])
    active = (data["minutes"] >= start_minute) & (data["minutes"] < end_minute)
    finite = data[["vwap", "atr", "z_vwap"]].notna().all(axis=1)
    regime_by_session = regime_by_session or {}
    signals: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    index = 0
    while index < len(data) - 1:
        row = data.iloc[index]
        session = str(row["session_date"])
        regime = regime_by_session.get(session, "unknown")
        gate_allowed = gate == "none" or (gate == "bull" and regime == "bull") or (gate == "no_crash" and regime not in {"crash", "unknown"})
        if one_signal_per_session and session in seen_sessions:
            index += 1
            continue
        if not (bool(active.iloc[index]) and bool(finite.iloc[index]) and gate_allowed and float(row["z_vwap"]) <= -extension_atr):
            index += 1
            continue
        extension_index = index
        confirm_index: int | None = None
        end_index = min(len(data) - 1, index + max_hold_bars)
        for probe in range(index + 1, end_index + 1):
            probe_row = data.iloc[probe]
            if str(probe_row["session_date"]) != session:
                break
            if not bool(finite.iloc[probe]):
                continue
            if float(probe_row["close"]) >= float(probe_row["vwap"]):
                confirm_index = probe
                break
            if float(probe_row["z_vwap"]) >= -reclaim_atr:
                confirm_index = probe
                break
        if confirm_index is None:
            signals.append(
                {
                    **_empty(symbol, "extension_no_reclaim", timeframe),
                    "session_date": session,
                    "extension_timestamp": data.index[extension_index].isoformat(),
                    "vwap": round(float(row["vwap"]), 8),
                    "z_vwap": round(float(row["z_vwap"]), 8),
                    "gate_allowed": gate_allowed,
                }
            )
            seen_sessions.add(session)
            index = end_index + 1
            continue
        confirm_row = data.iloc[confirm_index]
        entry_index = confirm_index + 1
        if entry_index >= len(data) or str(data.iloc[entry_index]["session_date"]) != session:
            seen_sessions.add(session)
            index = end_index + 1
            continue
        entry = float(data.iloc[entry_index]["open"])
        atr = float(row["atr"])
        stop = max(0.01, float(row["low"]) - 0.10 * atr)
        target = float(row["vwap"])
        if target <= entry:
            signals.append(
                {
                    **_empty(symbol, "confirmation_no_edge", timeframe),
                    "session_date": session,
                    "extension_timestamp": data.index[extension_index].isoformat(),
                    "confirmation_timestamp": data.index[confirm_index].isoformat(),
                    "entry_timestamp": data.index[entry_index].isoformat(),
                    "vwap": round(target, 8),
                    "z_vwap": round(float(row["z_vwap"]), 8),
                    "gate_allowed": gate_allowed,
                }
            )
            seen_sessions.add(session)
            index = end_index + 1
            continue
        signals.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "direction": "bull",
                "status": "confirmed",
                "signal": "vwap_reversion_confirmed",
                "mode": "shadow",
                "influence_entries": False,
                "orders_allowed": False,
                "observational_only": True,
                "risk_authority": "risk_manager_only",
                "session_date": session,
                "extension_timestamp": data.index[extension_index].isoformat(),
                "confirmation_timestamp": data.index[confirm_index].isoformat(),
                "entry_timestamp": data.index[entry_index].isoformat(),
                "vwap": round(float(confirm_row["vwap"]), 8),
                "extension_vwap": round(float(row["vwap"]), 8),
                "z_vwap": round(float(row["z_vwap"]), 8),
                "atr": round(atr, 8),
                "entry": round(entry, 8),
                "stop_price": round(stop, 8),
                "target_price": round(target, 8),
                "gate": gate,
                "regime": regime,
                "gate_allowed": gate_allowed,
                "max_hold_bars": max_hold_bars,
            }
        )
        seen_sessions.add(session)
        index = end_index + 1
    return signals


def evaluate_intraday_mean_reversion(frame: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    signals = scan_intraday_mean_reversion(frame, **kwargs)
    return signals[-1] if signals else _empty(kwargs.get("symbol", ""), "no_setup", kwargs.get("timeframe", "5min"))
