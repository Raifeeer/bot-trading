"""Estrategias de DAY TRADING.

1. DayMomentum: cruce EMA 9/21 sobre velas de 5 minutos con filtros de
   volumen relativo, RSI y stop dinámico por ATR. Solo largas (sesgo del
   mercado), ideal para empezar; el framework soporta cortas.

2. DayBreakout: ruptura del canal Donchian de 10 velas de 15 minutos,
   operativo solo entre 10:00 y 15:30 ET (evita la primera hora ruidosa
   y el cierre).
"""
import logging

import pandas as pd
import numpy as np
import ta

from strategies.base import Strategy, Signal, SignalType

logger = logging.getLogger("strategies.day")


def _add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = ta.trend.EMAIndicator(df["close"], p["fast_ema"]).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(df["close"], p["slow_ema"]).ema_indicator()
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], p["atr_period"]
    ).average_true_range()
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], p.get("rsi_period", 14)).rsi()
    df["vol_sma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_sma"].replace(0, np.nan)
    return df


class DayMomentum(Strategy):
    name = "day_momentum"
    timeframe = "5min"

    def __init__(self, params: dict):
        self.p = {
            "fast_ema": 9, "slow_ema": 21, "atr_period": 14,
            "atr_multiplier_stop": 2.0, "volume_min_multiple": 1.5,
            "rsi_period": 14, "rsi_max": 70, "rsi_min": 30,
            "hold_max_bars": 48, "cooldown_minutes": 30,
        }
        self.p.update(params or {})

    def parameters(self):
        return self.p

    def scan(self, df, **state) -> Signal:
        p = self.p
        df = _add_indicators(df, p)
        if len(df) < max(p["slow_ema"], p["atr_period"]) + 5:
            return Signal(self.name, SignalType.NONE, strategy=self.name)

        last, prev = df.iloc[-1], df.iloc[-2]
        symbol = state.get("symbol", "")
        sig = Signal(symbol, SignalType.NONE, strategy=self.name,
                     ts=last.name.to_pydatetime() if hasattr(last.name, "to_pydatetime") else None)

        # --- Reglas de ENTRADA larga ---
        cross_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
        volume_ok = pd.notna(last["vol_ratio"]) and last["vol_ratio"] >= p["volume_min_multiple"]
        rsi_ok = p["rsi_min"] <= last["rsi"] <= p["rsi_max"]
        trend_up = last["close"] > last["ema_slow"]

        if cross_up and volume_ok and rsi_ok and trend_up:
            stop = last["close"] - p["atr_multiplier_stop"] * last["atr"]
            sig.signal_type = SignalType.LONG
            sig.score = float(min(1.0, (last["vol_ratio"] / 3.0 + (last["rsi"] - 50) / 60.0) / 2.0))
            sig.stop_price = float(max(stop, 0.01))
            sig.reason = (f"cruce EMA{p['fast_ema']}/{p['slow_ema']} alcista, "
                          f"vol {last['vol_ratio']:.1f}x, RSI {last['rsi']:.0f}")

        # --- Regla de SALIDA ---
        cross_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]
        stop_hit = state.get("entry_price") is not None and last["low"] <= state["stop_price"]
        max_hold = state.get("bars_held", 0) >= p["hold_max_bars"]
        if cross_down or stop_hit or max_hold:
            sig.signal_type = SignalType.EXIT
            sig.reason = ("cruce bajista" if cross_down else
                          ("stop" if stop_hit else "máximo de barras"))
        return sig


class DayBreakout(Strategy):
    name = "day_breakout"
    timeframe = "15min"

    def __init__(self, params: dict):
        self.p = {
            "donchian_period": 10, "atr_period": 14, "atr_multiplier_stop": 2.5,
            "breakout_conf_bars": 1, "hold_max_bars": 20,
            "session_start": "10:00", "session_end": "15:30",
        }
        self.p.update(params or {})

    def parameters(self):
        return self.p

    @staticmethod
    def _in_session(ts, start, end):
        t = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        return start <= t < end

    def scan(self, df, **state) -> Signal:
        p = self.p
        df = df.copy()
        df["donch_hi"] = df["high"].shift(1).rolling(p["donchian_period"]).max()
        df["donch_lo"] = df["low"].shift(1).rolling(p["donchian_period"]).min()
        df["atr"] = ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], p["atr_period"]
        ).average_true_range()

        if len(df) < p["donchian_period"] + 5:
            return Signal("day_breakout", SignalType.NONE, strategy=self.name)

        last = df.iloc[-1]
        symbol = state.get("symbol", "")
        sig = Signal(symbol, SignalType.NONE, strategy=self.name)

        in_sess = self._in_session(last.name, p["session_start"], p["session_end"])

        # --- Entrada: cierre por encima del canal con volumen > mediano ---
        if in_sess and last["close"] > last["donch_hi"]:
            conf = df.iloc[-(p["breakout_conf_bars"] + 1): -1]
            if len(conf) and conf["close"].iloc[-1] <= conf["donch_hi"].iloc[-1]:
                stop = last["close"] - p["atr_multiplier_stop"] * last["atr"]
                sig.signal_type = SignalType.LONG
                sig.score = 0.6
                sig.stop_price = float(max(stop, 0.01))
                sig.reason = (f"breakout Donchian{p['donchian_period']} "
                              f"cierre {last['close']:.2f} > canal {last['donch_hi']:.2f}")

        # --- Salida ---
        stop_hit = state.get("entry_price") is not None and last["low"] <= state["stop_price"]
        fall_back = last["close"] < last["donch_lo"]  # rompe el soporte del canal
        max_hold = state.get("bars_held", 0) >= p["hold_max_bars"]
        if stop_hit or fall_back or max_hold:
            sig.signal_type = SignalType.EXIT
            sig.reason = "stop" if stop_hit else ("reversión al canal" if fall_back else "máximo de barras")
        return sig
