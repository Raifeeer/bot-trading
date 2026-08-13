"""Motor de backtesting orientado a eventos (bar-by-bar).

Simula el bot completo: para cada barra, cada estrategia escanea, el risk
manager aprueba/rechaza, y las posiciones se gestionan con stops y targets.
Aplica slippage y comisiones configurables.

Salida: tabla de operaciones (trades), equity curve diaria y métricas
(comisión: ver engine/metrics.py).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import numpy as np

from strategies.base import SignalType
from risk.manager import RiskManager, PositionState

logger = logging.getLogger("engine")


@dataclass
class Trade:
    symbol: str
    strategy: str
    side: str
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime = None
    exit_price: float = None
    shares: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    bars_held: int = 0


@dataclass
class BacktestState:
    symbol: str = ""
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = None
    shares: float = 0.0
    strategy: str = ""
    bars_held: int = 0
    entry_ts: datetime = None
    side: str = "long"


class BacktestEngine:
    def __init__(self, strategies, risk_cfg: dict, slippage_bps: float = 5.0,
                 commission_usd: float = 0.0):
        self.strategies = strategies          # dict name -> Strategy instance
        self.rm = RiskManager(risk_cfg)
        self.slippage_bps = slippage_bps
        self.commission_usd = commission_usd

    def _slip(self, price: float, buy: bool) -> float:
        slip = price * self.slippage_bps / 10_000.0
        return price + slip if buy else price - slip

    def run(self, data: dict, capital: float = 100_000.0,
            start: str = None, end: str = None) -> pd.DataFrame:
        """data: {symbol: DataFrame con index datetime UTC}."""
        self.rm.capital = capital
        equity = capital
        states: dict = {}           # symbol -> BacktestState
        trades: list = []
        equity_points = []

        # Unión de timestamps por estrategia/timeframe es compleja; se usa el
        # enfoque por símbolo: avanzar barra a barra por símbolo (cada símbolo
        # usa su propia frecuencia; en producción live el dispatcher ordena).
        # Para simplicidad y corrección, procesamos cada símbolo con cada
        # estrategia asignada, respetando cronología global mediante eventos.
        # Línea de eventos global ordenada por tiempo. En vez de reconstruir
        # `hist` con loc[<=ts] en cada barra (O(n²)), se recorre el DataFrame
        # completo de cada símbolo y se registra el índice por timestamp.
        event_list = []
        for sym, df in data.items():
            sub = df if start is None else df.loc[start:end]
            for i, (ts, bar) in enumerate(sub.iterrows()):
                event_list.append((ts, sym, i, bar))
        event_list.sort(key=lambda e: e[0])

        # Historial acumulativo por símbolo (crece por slicing hasta el índice)
        hist_idx = {sym: 0 for sym in data}

        for ts, sym, idx, row in event_list:
            full = data[sym]
            hist = full.iloc[:idx + 1]

            if sym in states:
                st = states[sym]
                st.bars_held += 1
                # stop / target intrabarra (aproximación: se ejecutan al stop/target)
                exited = False
                if st.stop_price and row["low"] <= st.stop_price:
                    exit_px, reason = st.stop_price, "stop"
                    exited = True
                elif st.target_price and row["high"] >= st.target_price:
                    exit_px, reason = st.target_price, "target"
                    exited = True
                else:
                    # salida por estrategia
                    if len(hist) < 60:
                        continue
                    for sname, strat in self.strategies.items():
                        sig = strat.scan(hist, symbol=sym, entry_price=st.entry_price,
                                         stop_price=st.stop_price,
                                         target_price=st.target_price,
                                         bars_held=st.bars_held)
                        if sig.signal_type == SignalType.EXIT:
                            exit_px, reason = row["close"], sig.reason
                            exited = True
                            break
                if exited:
                    exec_px = self._slip(exit_px, buy=False)
                    pnl = (exec_px - st.entry_price) * st.shares
                    pnl -= self.commission_usd * st.shares
                    equity += pnl + st.shares * st.entry_price  # liberar capital
                    trades.append(Trade(
                        sym, st.strategy, st.side or "long", st.entry_ts,
                        st.entry_price, ts, exec_px, st.shares, pnl,
                        pnl / (st.entry_price * st.shares) * 100 if st.shares else 0.0,
                        reason, st.bars_held,
                    ))
                    del states[sym]
                # registrar equity con posición marcada a mercado
            else:
                # escanear señales de entrada (solo cuando hay historia suficiente
                # para los indicadores; el propio scan también lo valida)
                if len(hist) < 60:   # margen para los indicadores más lentos
                    continue
                open_positions = [BacktestState.__class__.__name__ and PositionState(
                    symbol=s, entry_price=v.entry_price, stop_price=v.stop_price)
                    for s, v in states.items()]
                for sname, strat in self.strategies.items():
                    sig = strat.scan(hist, symbol=sym)
                    if sig.tradable:
                        entry_px = self._slip(row["close"], buy=True)
                        dec = self.rm.approve_position(sym, sig, entry_px, equity, open_positions)
                        if dec.decision == "APPROVED" and dec.suggested_shares > 0:
                            cost = dec.suggested_shares * entry_px
                            equity -= cost
                            states[sym] = BacktestState(
                                sym, entry_px, sig.stop_price, sig.target_price,
                                dec.suggested_shares, strat.name, 0, ts,
                                "long" if sig.signal_type == SignalType.LONG else "short",
                            )
                            logger.debug("Backtest: entrada %s %s @ %.2f x %.0f",
                                         sym, strat.name, entry_px, dec.suggested_shares)
                            break  # una entrada por símbolo por barra
            equity_points.append({"ts": ts, "equity": equity + sum(
                v.shares * row["close"] for k, v in states.items() if k == sym)})

        # cierre forzado de posiciones restantes al final
        for sym, st in list(states.items()):
            hist = data[sym]
            last = hist.iloc[-1]
            exec_px = self._slip(last["close"], buy=False)
            pnl = (exec_px - st.entry_price) * st.shares - self.commission_usd * st.shares
            equity += pnl + st.shares * st.entry_price
            trades.append(Trade(sym, st.strategy, st.side or "long", st.entry_ts,
                                st.entry_price, last.name, exec_px, st.shares, pnl,
                                pnl / (st.entry_price * st.shares) * 100, "fin_backtest",
                                st.bars_held))

        df_trades = pd.DataFrame([vars(t) for t in trades])
        eq = pd.DataFrame(equity_points).set_index("ts")
        return df_trades, eq
