"""Estrategia de SWING TRADING.

SwingTrend: cruce de medias SMA 20/50 sobre velas diarias, con filtro de
tendencia macro (precio sobre SMA 200), stop dinámico por ATR y take profit
dinámico a 6x ATR. Solo operaciones largas, posiciones de 2 a 20 días.
"""
import pandas as pd
import ta

from strategies.base import Strategy, Signal, SignalType


class SwingTrend(Strategy):
    name = "swing_trend"
    timeframe = "1d"

    def __init__(self, params: dict):
        self.p = {
            "fast_sma": 20, "slow_sma": 50, "trend_filter_sma": 200,
            "atr_period": 14, "atr_multiplier_stop": 3.0,
            "atr_multiplier_target": 6.0,
            "min_hold_days": 2, "max_hold_days": 20,
        }
        self.p.update(params or {})

    def parameters(self):
        return self.p

    def scan(self, df, **state) -> Signal:
        p = self.p
        df = df.copy()
        df["sma_fast"] = ta.trend.SMAIndicator(df["close"], p["fast_sma"]).sma_indicator()
        df["sma_slow"] = ta.trend.SMAIndicator(df["close"], p["slow_sma"]).sma_indicator()
        df["sma_trend"] = ta.trend.SMAIndicator(df["close"], p["trend_filter_sma"]).sma_indicator()
        df["atr"] = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], p["atr_period"]
        ).average_true_range()

        if len(df) < p["trend_filter_sma"] + 5:
            return Signal("swing_trend", SignalType.NONE, strategy=self.name)

        last, prev = df.iloc[-1], df.iloc[-2]
        symbol = state.get("symbol", "")
        sig = Signal(symbol, SignalType.NONE, strategy=self.name)

        cross_up = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        trend_ok = pd.notna(last["sma_trend"]) and last["close"] > last["sma_trend"]

        if cross_up and trend_ok:
            stop = last["close"] - p["atr_multiplier_stop"] * last["atr"]
            target = last["close"] + p["atr_multiplier_target"] * last["atr"]
            sig.signal_type = SignalType.LONG
            sig.score = 0.7
            sig.stop_price = float(max(stop, 0.01))
            sig.target_price = float(target)
            sig.reason = (f"cruce SMA{p['fast_sma']}/{p['slow_sma']} alcista, "
                          f"precio sobre SMA{p['trend_filter_sma']}, "
                          f"stop {stop:.2f} target {target:.2f}")

        # --- Salida ---
        cross_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]
        stop_hit = state.get("entry_price") is not None and last["low"] <= state["stop_price"]
        target_hit = state.get("entry_price") is not None and last["high"] >= state["target_price"]
        min_hold_ok = state.get("bars_held", 0) >= p["min_hold_days"]
        max_hold = state.get("bars_held", 0) >= p["max_hold_days"]

        if stop_hit or target_hit or max_hold or (cross_down and min_hold_ok):
            sig.signal_type = SignalType.EXIT
            sig.reason = "stop" if stop_hit else ("target" if target_hit else
                          ("máximo de días" if max_hold else "cruce bajista"))
        return sig
