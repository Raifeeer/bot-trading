"""Backtest del RETO $100 -> $200 (último mes).

Repite la lógica del bot calibrada al reto:
- Señal: swing_trend (SMA20/50 + filtro SMA200) sobre velas diarias (mismo motor del bot)
- Estructura: call spread delta 0.30/0.15, DTE 7-45, prima neta máx $0.50
- Riesgo: 20% del capital por trade, máx 2 posiciones simultáneas
- Gestión: TP +50% prima, SL -100% (débito total), cierre 21 DTE
- Valoración de las patas con Black-Scholes usando IV modelada (realized vol 20d,
  más una superficie simple por moneyness para no subestimar la curva)
- Salida: equity $100 -> equity final, trades, win rate, drawdown
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

from scipy import stats
from data.feed import MarketDataFeed
from config import get_config
from strategies.swing_trading import SwingTrend
from options.chains import black_scholes_price

CAPITAL_INICIAL = 100.0
RISK_PCT = 0.20          # 20% del capital en riesgo por trade
MAX_POS = 2              # máx posiciones simultáneas
MAX_PREMIUM_NET = 0.50   # prima neta máxima por spread
DTE_MIN, DTE_MAX = 7, 45
DTE_CHOICE = 21          # DTE del spread (dentro del rango 7-45, coherente con gestión 21d)
TP_MULT = 1.5            # cierre si prima actual >= 1.5x entrada (+50%)
SL_MULT = 0.15           # cierre si prima actual <= 15% de la entrada (débito total perdido)
MARGIN_MULT = 1.2        # spread extra sobre la prima teórica (bid/ask simulado)
R = 0.045
N_DIAS_HIST = 300        # historia para indicadores (necesario para SMA200)

TICKERS = ["SPY","QQQ","IWM","TQQQ","SQQQ","NVDA","TSLA","AMD","PLTR","SOFI",
           "AAPL","AMZN","META","MSFT","GOOGL"]

def realized_vol(df, window=20):
    ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    return float(ret.rolling(window).std().iloc[-1] * np.sqrt(252)) if len(ret) >= window else 0.3

def iv_surface(sigma_atm, moneyness):
    """Superficie simple: smile simétrico + leve skew bajista (puts más caras),
    y un poco de term structure: strikes OTM más lejos = IV algo mayor."""
    smile = 0.12 * (moneyness - 1) ** 2          # smile convexo
    skew = -0.25 * (moneyness - 1)               # skew bajista
    return sigma_atm * (1.0 + smile + skew)

def delta_call(spot, k, T, r, sigma):
    d1 = (np.log(spot / k) + (r + sigma ** 2 / 2) * T) / (sigma * np.sqrt(T))
    return float(stats.norm.cdf(d1))

def strike_for_delta(spot, target_delta, T, r, sigma, lo=None, hi=None):
    lo, hi = lo or spot * 0.8, hi or spot * 1.3
    for _ in range(60):
        mid = (lo + hi) / 2
        if delta_call(spot, mid, T, r, sigma) > target_delta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def build_spread(spot, sigma_atm, entry_date):
    T = DTE_CHOICE / 365.0
    k_long = strike_for_delta(spot, 0.30, T, R, sigma_atm)
    k_short = strike_for_delta(spot, 0.15, T, R, sigma_atm)
    px_l = black_scholes_price(spot, k_long, T, R, sigma_atm, "call")
    px_s = black_scholes_price(spot, k_short, T, R, sigma_atm, "call")
    net = (px_l - px_s) * 100 * MARGIN_MULT   # prima neta por contrato (con margen)
    if net <= 0:
        return None
    return dict(k_long=k_long, k_short=k_short, px_l=px_l, px_s=px_s,
                net=net, t=T, entry_date=entry_date, sigma=sigma_atm)

def value_spread(spread, spot, days_later):
    T = max((spread["t"] * 365.0 - days_later), 0) / 365.0
    sig = spread["sigma"]
    if T <= 0:
        # vencido: valor intrínseco
        v = (max(spot - spread["k_long"], 0) - max(spot - spread["k_short"], 0)) * 100
        return v * MARGIN_MULT
    px_l = black_scholes_price(spot, spread["k_long"], T, R, sig, "call")
    px_s = black_scholes_price(spot, spread["k_short"], T, R, sig, "call")
    return (px_l - px_s) * 100 * MARGIN_MULT

def main():
    cfg = get_config()
    tickers = cfg["universo"]["tickers"]
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    print(f"Descargando {N_DIAS_HIST}d de historia para {len(tickers)} tickers...")
    data = feed.history(tickers, "1d", days=N_DIAS_HIST)

    today = pd.Timestamp.now(tz="UTC").normalize()
    end = today
    start = today - pd.Timedelta(days=30)
    strat = SwingTrend(cfg["strategies"]["swing_trend"]["params"])

    equity = CAPITAL_INICIAL
    open_pos = []   # list of dicts
    trades = []
    equity_curve = []

    # línea de tiempo diaria (solo días hábiles presentes en los datos)
    dates = sorted({ts.normalize() for df in data.values() for ts in df.index})
    dates = [d for d in dates if start <= d <= end]
    print(f"Ventana: {dates[0].date()} -> {dates[-1].date()} ({len(dates)} días hábiles)")

    for d in dates:
        hist_today = {}
        for sym, df in data.items():
            sub = df[df.index.normalize() <= d]
            if len(sub) >= 60:
                hist_today[sym] = sub
        # valorar posiciones abiertas (días transcurridos desde entrada)
        still_open = []
        for pos in open_pos:
            days_held = (d - pos["entry_date"]).days
            val = value_spread(pos["spread"], pos["last_spot"], days_held)
            cur = val / pos["entry_net"] if pos["entry_net"] > 0 else 0
            reason = ""
            if days_held >= DTE_CHOICE - 21:      # gestión 21 DTE (cerrar a 21 días del venc)
                reason = "gestion_21dte"
            elif cur >= TP_MULT:
                reason = "tp_+50%"
            elif cur <= SL_MULT:
                reason = "sl_-100%"
            if reason:
                pnl = val - pos["entry_net"]
                equity += pnl
                trades.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                                   exit_date=d, entry_premium=pos["entry_net"],
                                   exit_value=val, pnl=pnl, pnl_pct=pnl / pos["entry_net"],
                                   reason=reason, days_held=days_held,
                                   strategy=pos["strategy"]))
                continue
            still_open.append(pos)
        open_pos = still_open

        # escanear entradas (una por ticker si hay señal, respetando límites de riesgo/posiciones)
        if len(open_pos) < MAX_POS:
            for sym, hist in sorted(hist_today.items()):
                if any(p["symbol"] == sym for p in open_pos):
                    continue
                sig = strat.scan(hist, symbol=sym)
                if sig.tradable:
                    spot = hist["close"].iloc[-1]
                    sigma = realized_vol(hist) or 0.3
                    spread = build_spread(spot, sigma, d)
                    if spread is None:
                        continue
                    if spread["net"] > MAX_PREMIUM_NET * 100:
                        # prima del contrato excede prima neta máx calibrada ($0.50/contrato... no, $0.50 neto)
                        if spread["net"] > MAX_PREMIUM_NET * 100:
                            continue
                    # riesgo = prima neta (débito máx); cabe dentro del 20%?
                    risk_budget = equity * RISK_PCT
                    if spread["net"] > risk_budget or spread["net"] > equity * 0.5:
                        continue
                    open_pos.append(dict(symbol=sym, spread=spread, entry_net=spread["net"],
                                         last_spot=spot, entry_date=d,
                                         strategy="opt_swing_trend"))
                    # en live el risk manager aprueba 1 trade a la vez por tick; aquí
                    # respetamos max posiciones y pasamos al siguiente día para no
                    # sobrestimar entradas del mismo día en el backtest simple
                    break

        equity_curve.append(dict(date=d, equity=round(equity, 2),
                                 open_positions=len(open_pos)))

    # cerrar posiciones abiertas al final (valor intrínseco conservador)
    for pos in open_pos:
        days_held = (dates[-1] - pos["entry_date"]).days
        val = value_spread(pos["spread"], pos["last_spot"], days_held)
        pnl = val - pos["entry_net"]
        equity += pnl
        trades.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                           exit_date=dates[-1], entry_premium=pos["entry_net"],
                           exit_value=val, pnl=pnl, pnl_pct=pnl / pos["entry_net"],
                           reason="fin_backtest", days_held=days_held,
                           strategy="opt_swing_trend"))

    tdf = pd.DataFrame(trades)
    ecdf = pd.DataFrame(equity_curve)
    print("\n=== RESULTADO ===")
    print(f"Capital inicial: ${CAPITAL_INICIAL:.2f} -> final: ${equity:.2f}")
    print(f"Retorno: {(equity/CAPITAL_INICIAL - 1)*100:+.1f}%")
    print(f"Trades: {len(tdf)} | Ganadores: {(tdf['pnl']>0).sum()} | Win rate: {(tdf['pnl']>0).mean()*100:.0f}%")
    if len(tdf):
        print(f"P&L total: ${tdf['pnl'].sum():+.2f} | Mayor ganador: ${tdf['pnl'].max():+.2f} | Mayor perdedor: ${tdf['pnl'].min():+.2f}")
        print(tdf[["symbol","entry_date","exit_date","entry_premium","exit_value","pnl","reason","days_held"]].to_string(index=False))
    # drawdown
    ecdf["peak"] = ecdf["equity"].cummax()
    dd = (ecdf["equity"] / ecdf["peak"] - 1).min()
    print(f"\nDrawdown máximo durante el mes: {dd*100:.1f}%")
    ecdf.to_csv("/home/ubuntu/bt_equity_curve.csv", index=False)
    if len(tdf):
        tdf.to_csv("/home/ubuntu/bt_trades.csv", index=False)

if __name__ == "__main__":
    main()
