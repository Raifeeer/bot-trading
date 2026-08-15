"""Métricas de rendimiento de backtest / performance."""
import pandas as pd
import numpy as np


def portfolio_metrics(equity: pd.DataFrame, risk_free_rate: float = 0.04,
                      trades: pd.DataFrame = None) -> dict:
    """Calcula métricas institucionales a partir de la equity curve diaria.

    equity: DataFrame con index datetime y columna 'equity' (valor de portafolio).
    """
    eq = equity["equity"] if isinstance(equity, pd.DataFrame) else equity
    eq = eq.resample("1D").last().dropna()
    if len(eq) < 2:
        return {"error": "datos insuficientes"}

    ret = eq.pct_change().dropna()
    days = (eq.index[-1] - eq.index[0]).days or 1
    years = days / 365.25
    total_ret = eq.iloc[-1] / eq.iloc[0] - 1

    cumeq = eq.cummax()
    dd = (eq - cumeq) / cumeq
    mdd = dd.min()
    mdd_dur = 0
    start = None
    for i, v in enumerate(dd):
        if v < 0:
            if start is None:
                start = i
            mdd_dur = max(mdd_dur, i - start + 1)
        else:
            start = None

    std_r = ret.std()
    ann_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0.0
    ann_vol = std_r * np.sqrt(252)
    sharpe = (ann_ret - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
    downside = ret[ret < 0].std() * np.sqrt(252)
    sortino = (ann_ret - risk_free_rate) / downside if downside > 0 else 0.0

    out = {
        "periodo_dias": days,
        "retorno_total_pct": round(total_ret * 100, 2),
        "retorno_anualizado_pct": round(ann_ret * 100, 2),
        "volatilidad_anual_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "drawdown_max_pct": round(mdd * 100, 2),
        "drawdown_max_duracion_dias": int(mdd_dur),
        "ratio_calmar": round(ann_ret / abs(mdd), 2) if mdd < 0 else float("inf"),
    }
    if trades is not None and len(trades):
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        out.update({
            "operaciones": len(trades),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
            "pnl_promedio_ganador": round(wins["pnl"].mean(), 2) if len(wins) else 0.0,
            "pnl_promedio_perdedor": round(losses["pnl"].mean(), 2) if len(losses) else 0.0,
            "profit_factor": round(abs(wins["pnl"].sum() / losses["pnl"].sum()), 2)
            if len(losses) and losses["pnl"].sum() != 0 else float("inf"),
        })
    return out
