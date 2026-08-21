"""Adaptadores PAPER para promover detectores shadow al contrato live.

Los adaptadores no construyen órdenes ni hablan con Alpaca. Solo convierten una
confirmación fresca de la última barra cerrada en ``Signal``; la construcción de
la estructura, el RiskManager y el executor siguen siendo responsabilidad del
flujo normal de ``bot.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from strategies.base import Signal, SignalType, Strategy
from strategies.breakout_20_55_volume import evaluate_breakout
from strategies.trend_pullback_continuation import evaluate_trend_pullback


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_fresh_confirmation(observation: dict[str, Any], frame: pd.DataFrame) -> bool:
    """Solo acepta una confirmación exactamente en la última barra cerrada."""
    if frame is None or frame.empty:
        return False
    observed = _as_utc(observation.get("confirmation_timestamp"))
    latest = _as_utc(frame.index[-1])
    return observed is not None and latest is not None and observed == latest


def _none_signal(symbol: str, strategy: str, reason: str) -> Signal:
    return Signal(symbol, SignalType.NONE, reason=reason, strategy=strategy)


class _PromotedDetectorStrategy(Strategy):
    detector: Callable[..., dict[str, Any]]
    signal_name = "promoted_shadow"

    def __init__(self, cfg: dict[str, Any], *, symbol_label: str):
        self.cfg = dict(cfg)
        self.symbol_label = symbol_label
        self.last_observation: dict[str, Any] | None = None
        self.last_structure = None
        self.timeframe = str(self.cfg.get("timeframe", "15min"))
        self.name = symbol_label

    def parameters(self):
        return dict(self.cfg)

    def _evaluate(self, df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    def scan(self, df: pd.DataFrame, **state: Any) -> Signal:
        symbol = str(state.get("symbol", ""))
        try:
            observation = dict(self._evaluate(df, symbol))
        except (KeyError, TypeError, ValueError):
            self.last_observation = None
            return _none_signal(symbol, self.name, "detector_error")
        self.last_observation = observation
        if observation.get("status") != "confirmed":
            return _none_signal(symbol, self.name, observation.get("status", "no_setup"))
        if not _is_fresh_confirmation(observation, df):
            return _none_signal(symbol, self.name, "stale_confirmation")
        direction = observation.get("direction", "bull")
        signal_type = SignalType.LONG if direction == "bull" else SignalType.SHORT
        return Signal(
            symbol,
            signal_type,
            score=float(observation.get("score", 0.75)),
            stop_price=observation.get("stop_price"),
            target_price=observation.get("target_price"),
            reason=f"{self.signal_name}: {observation.get('signal', 'confirmed')}",
            strategy=self.name,
        )

    def reset(self):
        self.last_observation = None
        self.last_structure = None


class PromotedTrendPullback(_PromotedDetectorStrategy):
    signal_name = "trend_pullback_continuation"

    def __init__(self, cfg: dict[str, Any]):
        super().__init__(cfg, symbol_label="promoted_trend_pullback")

    def _evaluate(self, df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        keys = (
            "timeframe", "direction", "ema_fast", "ema_slow", "atr_period",
            "trend_slope_bars", "impulse_lookback", "pullback_lookback",
            "impulse_atr", "vwap_tolerance_atr", "break_buffer_atr",
            "stop_buffer_atr", "reward_risk", "volume_lookback", "volume_min",
            "require_volume", "require_vwap_alignment", "allow_shorts",
            "session_start", "session_end",
        )
        params = {key: self.cfg[key] for key in keys if key in self.cfg}
        return evaluate_trend_pullback(df, symbol=symbol, **params)


class PromotedBreakout20_55(_PromotedDetectorStrategy):
    signal_name = "breakout_20_55"

    def __init__(self, cfg: dict[str, Any]):
        super().__init__(cfg, symbol_label="promoted_breakout_20_55")

    def _evaluate(self, df: pd.DataFrame, symbol: str) -> dict[str, Any]:
        keys = (
            "timeframe", "lookback", "volume_lookback", "volume_min", "atr_period",
            "break_buffer_atr", "stop_buffer_atr", "reward_risk", "hold_max_bars",
            "session_start", "session_end", "one_signal_per_session", "allow_shorts",
        )
        params = {key: self.cfg[key] for key in keys if key in self.cfg}
        return evaluate_breakout(df, symbol=symbol, **params)
