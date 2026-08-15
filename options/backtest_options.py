"""Backtest de OPCIONES sobre historia del subyacente.

Como Alpaca solo entrega ~7 días de snapshot histórico de opciones, este
simulador valora cada estructura con Black-Scholes a lo largo de la historia
del subyacente (IV modelada: constante, surface simple o realized vol).

Metodología por operación:
  1. Señal del subyacente (estrategia base) → construir spread (mismo builder)
  2. Valorar las patas con BS usando IV del día (default: realized vol 20d)
  3. Avanzar día a día re-valuando la estructura
  4. Salidas: TP/SL por prima, 21 DTE, vencimiento (valor intrínseco)
  5. Registrar trades y equity

Uso:
  DATA_PROVIDER=yfinance python options/backtest_options.py [AAPL MSFT NVDA]
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config
from data.feed import MarketDataFeed
from strategies.swing_trading import SwingTrend
from options.chains import (OptionType, OptionContract, Leg, OptionStructure,
                            black_scholes_price, greeks)
from options.strategy import OptionsStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("options.bt")

MULT = 100


def realized_vol(df: pd.DataFrame, window: int = 20) -> float:
    ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    return float(ret.rolling(window).std().iloc[-1] * np.sqrt(252)) if len(ret) >= window else 0.3


def build_synthetic_chain(spot, sigma, dte_list=(21, 30, 45), r=0.045):
    """Cadena sintética de contratos valorados con BS (para simulación)."""
    today = date.today()
    chain = []
    for dte in dte_list:
        T = dte / 365.0
        for i, k in enumerate(np.arange(spot * 0.85, spot * 1.15, spot * 0.0125)):
            for ot in (OptionType.CALL, OptionType.PUT):
                px = black_scholes_price(spot, k, T, r, sigma, ot)
                d, g, th, v = greeks(spot, k, T, r, sigma, ot)
                spread = max(px * 0.03, 0.05)  # spread simulado 3%
                chain.append(OptionContract(
                    f"SYN{dte:03d}{'C' if ot == OptionType.CALL else 'P'}{int(k*1000):08d}",
                    "SYN", ot, float(k), today + timedelta(days=dte),
                    bid=px - spread / 2, ask=px + spread / 2,
                    volume=200 - i * 5, open_interest=1000 - i * 10,
                    iv=sigma, delta=d, gamma=g, theta=th, vega=v))
    return chain


def run_option_backtest(data: dict, strat, capital: float = 100_000.0,
                        sigma_default: float = 0.30):
    """`strat` debe ser una OptionsStrategy (o exponer last_structure/reset)."""
    """Backtest por símbolo: procesa historia diaria, construye spreads y los
    gestiona día a día."""
    trades, equity_points = [], []
    equity = capital
    open_pos = {}  # sym -> dict con estructura y estado

    for sym, df in data.items():
        sigma = realized_vol(df) or sigma_default
        # eventos solo dentro de horas de mercado aproximadas no aplica a diario
        for i, (ts, row) in enumerate(df.iterrows()):
            hist = df.iloc[:i + 1]
            spot = row["close"]
            # --- gestionar posición abierta ---
            if sym in open_pos:
                op = open_pos[sym]
                # re-valuar estructura a precio de hoy
                new_legs = []
                for leg in op["structure"].legs:
                    c = leg.contract
                    T = max((c.expiration - date.today()).days, 0) / 365.0
                    if T <= 0:
                        px = max(spot - c.strike, 0) if c.option_type == OptionType.CALL else max(c.strike - spot, 0)
                    else:
                        px = black_scholes_price(spot, c.strike, T, 0.045, sigma, c.option_type)
                    new_legs.append(Leg(c, leg.quantity, premium=px))
                cur = OptionStructure(op["structure"].name, new_legs, sym)
                dte = (op["structure"].legs[0].contract.expiration - date.today()).days
                exit_reason = ""
                if dte <= 0:
                    exit_reason = "vencimiento"
                elif dte <= 21:
                    exit_reason = "gestion_21dte"
                elif cur.net_premium <= op["entry_premium"] * 0.15:
                    exit_reason = "sl_debito_total"
                elif cur.net_premium >= op["entry_premium"] * 1.5:
                    exit_reason = "tp_premio_50"
                if exit_reason:
                    pnl = cur.net_premium - op["entry_premium"]
                    equity += pnl
                    trades.append(dict(symbol=sym, strategy=op["strategy"],
                                       structure=op["structure"].name,
                                       entry_ts=op["entry_ts"], exit_ts=str(ts),
                                       entry_premium=op["entry_premium"],
                                       exit_premium=cur.net_premium, pnl=pnl,
                                       exit_reason=exit_reason,
                                       spot_entry=op["spot_entry"], spot_exit=spot))
                    del open_pos[sym]

            # --- escanear entrada ---
            if sym not in open_pos and len(hist) >= 60:
                sig = strat.scan(hist, symbol=sym)
                if sig.tradable and strat.last_structure:
                    st = strat.last_structure
                    # re-valorar con spot real e IV del día
                    repriced = []
                    for leg in st.legs:
                        c = leg.contract
                        T = (c.expiration - date.today()).days / 365.0
                        px = black_scholes_price(spot, c.strike, T, 0.045, sigma, c.option_type)
                        repriced.append(Leg(c, leg.quantity, premium=px))
                    st = OptionStructure(st.name, repriced, sym,
                                         max_risk=sum(abs(l.net_premium) for l in repriced))
                    risk = st.max_risk
                    if risk > 0 and risk <= equity * 0.02 and st.net_premium > 0:  # 2% capital por spread
                        equity -= st.max_risk  # débito reservado
                        open_pos[sym] = dict(structure=st, entry_premium=st.net_premium,
                                             strategy=strat.name, entry_ts=str(ts),
                                             spot_entry=spot)
                        strat.reset()

        # cerrar posición restante al final
        if sym in open_pos:
            op = open_pos[sym]
            pnl = -op["entry_premium"]  # expira worthless (peor caso conservador)
            equity += pnl
            trades.append(dict(symbol=sym, strategy=op["strategy"],
                               structure=op["structure"].name,
                               entry_ts=op["entry_ts"], exit_ts=str(df.index[-1]),
                               entry_premium=op["entry_premium"], exit_premium=0.0,
                               pnl=pnl, exit_reason="fin_backtest",
                               spot_entry=op["spot_entry"], spot_exit=df["close"].iloc[-1]))

    eq = pd.DataFrame(equity_points) if equity_points else pd.DataFrame(
        {"equity": [equity]}, index=[pd.Timestamp.utcnow()])
    return pd.DataFrame(trades), eq, equity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", default=None)
    args = parser.parse_args()
    cfg = get_config()
    tickers = args.tickers or cfg["universo"]["tickers"][:6]

    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    data = feed.history(tickers, "1d", days=cfg["data"]["history_days"])

    base = SwingTrend(cfg["strategies"]["swing_trend"]["params"])
    mock_builder = _MockBuilder()
    strat = OptionsStrategy(base, mock_builder, {"direction": "bull"})
    trades, eq, final_eq = run_option_backtest(data, strat)
    print(f"\nTrades: {len(trades)} | Equity final: {final_eq:,.0f}")
    if len(trades):
        tdf = pd.DataFrame(trades)
        print(tdf[["symbol", "structure", "entry_premium", "exit_premium", "pnl", "exit_reason"]].to_string(index=False))
        wins = tdf[tdf["pnl"] > 0]
        print(f"\nWin rate: {len(wins)/len(tdf)*100:.1f}% | P&L total: {tdf['pnl'].sum():,.0f}")
    os.makedirs("output", exist_ok=True)
    if len(trades):
        pd.DataFrame(trades).to_csv("output/options_trades.csv", index=False)


class _MockBuilder:
    """SpreadBuilder sintético para backtest (sin API de Alpaca)."""

    def vertical_spread(self, sym, spot, direction, delta_long=0.4, delta_short=0.2):
        import scipy.stats as st
        sigma, T, r = 0.30, 30 / 365.0, 0.045

        def strike_for_delta(d_target):
            lo, hi = spot * 0.8, spot * 1.3
            for _ in range(40):
                mid = (lo + hi) / 2
                d1 = (np.log(spot / mid) + (r + sigma ** 2 / 2) * T) / (sigma * np.sqrt(T))
                d = st.norm.cdf(d1)
                if d > d_target:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2

        k_long = strike_for_delta(delta_long)
        k_short = strike_for_delta(delta_short)
        px_long = black_scholes_price(spot, k_long, T, r, sigma, OptionType.CALL)
        px_short = black_scholes_price(spot, k_short, T, r, sigma, OptionType.CALL)
        today = date.today()
        cl = OptionContract(f"{sym.upper()[:3]}L{int(k_long * 1000):06d}", sym, OptionType.CALL,
                            k_long, today + timedelta(days=30), bid=px_long * 0.98,
                            ask=px_long * 1.02, volume=500, open_interest=2000, iv=sigma)
        cs = OptionContract(f"{sym.upper()[:3]}S{int(k_short * 1000):06d}", sym, OptionType.CALL,
                            k_short, today + timedelta(days=30), bid=px_short * 0.98,
                            ask=px_short * 1.02, volume=500, open_interest=2000, iv=sigma)
        legs = [Leg(cl, +1), Leg(cs, -1)]
        return OptionStructure(
            f"call_spread_{sym}_{k_long:.0f}_{k_short:.0f}", legs, sym,
            max_risk=sum(abs(l.net_premium) for l in legs),
            rationale=f"spread delta {delta_long}/{delta_short}, IV {sigma:.0%}")


if __name__ == "__main__":
    main()
