"""Detector de régimen S78 (validado en backtests S1-S89) + defensas.

Implementa en producción las defensas calibradas en el AGENTS.md sección 7.1.1:
  - Régimen global del universo (bull / bear / cash) según los contadores
    validados en S78: bull_count >= 50% n -> "bull" (hold/entrar);
    bear_count >= 30% n -> "bear" (cash); otro -> "cash" (lateral, no operar).
  - crash_event (umbral 3% / cool-down 5 días): si >=30% del universo pierde
    >=3% en la velocidad de 2 días de cierre, cortar todo a cash de inmediato.
  - intraday_stop 4% (hallazgo18): precio intradiario <= (1-0.04) * close del
    día previo -> señal de corte; el bot cierra la posición de ese subyacente.

El régimen y el lock de crash se persisten en bot_state.json (crash_lock:
fecha) para sobrevivir reinicios de Cloud Run.
"""
import logging
from datetime import datetime

import pandas as pd
import ta

logger = logging.getLogger("risk.regime")

DEFAULT_REGIME_CFG = {
    "regime_enabled": True,
    "bull_threshold": 0.5,      # >=50% del universo en bull -> bull
    "bear_threshold": 0.3,      # >=30% con CHoCH bear -> bear
    "crash_event_pct": 0.03,    # umbral de caída crash_event (3%)
    "crash_cooldown_days": 5,   # días de cool-down tras activar crash_event
    "intraday_stop_pct": 0.04,  # umbral stop intradiario (4%) — hallazgo18
    "equity_floor": 99900.0,    # piso absoluto de equity (regla del dueño)
}


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    return ta.momentum.RSIIndicator(series, n).rsi()


def _sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def _fractal_swing_points(df: pd.DataFrame, order: int = 3):
    """Puntos swing fractales (order=3) sobre high/low. Misma lógica que
    strategies.smc.fractal_swing_points para portabilidad (lista de dicts)."""
    df = _norm(df)
    highs = df["High"].to_numpy(); lows = df["Low"].to_numpy()
    if len(df) < 2 * (2 * order + 1):
        order = max(1, min(order, (len(df) // 2 - 1) // 2))
    swings = []
    for i in range(order, len(df) - order):
        if highs[i] == max(highs[i - order:i + order + 1]):
            swings.append({"price": float(highs[i]), "idx": i,
                           "is_high": True})
        elif lows[i] == min(lows[i - order:i + order + 1]):
            swings.append({"price": float(lows[i]), "idx": i,
                           "is_high": False})
    return swings


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {"open": "Open", "high": "High", "low": "Low",
               "close": "Close", "volume": "Volume"}
    return df.rename(columns={c: mapping[c] for c in df.columns if c in mapping})


def put_choch_entry(df: pd.DataFrame) -> bool:
    """CHoCH bajista pragmático (S63/S78): cierre bajo el último swing LOW
    relevante con un HI dominante reciente (<60 días)."""
    df = _norm(df)
    if len(df) < 60:
        return False
    sw = _fractal_swing_points(df, 3)
    if len(sw) < 4:
        return False
    last4 = sw[-4:]
    his = [s["price"] for s in last4 if s["is_high"]]
    los = [s["price"] for s in last4 if not s["is_high"]]
    if not his or not los:
        return False
    last_hi = max(his)
    hi_idx = None
    for s in last4:
        if s["is_high"] and s["price"] == last_hi:
            hi_idx = s["idx"]
            break
    last_lo = los[-1]
    close = float(df["Close"].iloc[-1])
    if hi_idx is None:
        return False
    n_days_since_hi = (len(df) - 1 - hi_idx)  # aprox. en barras diarias
    return bool(close < last_lo and n_days_since_hi < 60)


def classify_regime(data_1d: dict, tickers: list,
                    cfg: dict = None) -> dict:
    """Clasifica el régimen global del universo con los contadores de S78.

    data_1d: {symbol: pd.DataFrame con OHLCV diario (>=110 filas por ticker
    para el SMA200; se degrada suavemente si hay menos historia)}.
    Devuelve {"regime": "bull"|"bear"|"cash",
              "bull_count": int, "bear_count": int, "n": int,
              "crash_event": bool, "crash_active": bool,
              "intraday_cuts": {symbol: precio_quiebre},
              "summary": str}.
    """
    cfg = {**DEFAULT_REGIME_CFG, **(cfg or {})}
    if not cfg.get("regime_enabled"):
        return {"regime": "cash", "bull_count": 0, "bear_count": 0, "n": 0,
                "crash_event": False, "crash_active": False,
                "intraday_cuts": {}, "summary": "régimen deshabilitado"}

    bull_count = bear_count = n = 0
    ticker_status = {}
    # --- crash_event (hallazgo17): caída rápida de cierre (2d) vs umbral
    c_thresh = float(cfg["crash_event_pct"])
    n_eval = n_crash = 0
    intraday_cuts = {}
    for sym in tickers:
        df = data_1d.get(sym)
        if df is None or len(df) < 3:
            continue
        df = _norm(df)
        close_now = float(df["Close"].iloc[-1])
        close_prev = float(df["Close"].iloc[-2])
        close_2d = float(df["Close"].iloc[-3]) if len(df) >= 3 else close_now
        n_eval += 1
        fast = close_2d > 0 and close_now / close_2d - 1 <= -c_thresh
        if fast:
            n_crash += 1
        # --- régimen por ticker: bull = RSI>50 + precio > SMA200
        rsi_s = _rsi(df["Close"])
        s200 = _sma(df["Close"], 200)
        rsi_ok = pd.notna(rsi_s.iloc[-1]) and rsi_s.iloc[-1] > 50
        s200_ok = pd.notna(s200.iloc[-1]) and close_now > s200.iloc[-1]
        is_bull = bool(rsi_ok and s200_ok)
        n += 1
        ticker_status[sym] = {"bull": is_bull,
                              "bear_choch": put_choch_entry(df),
                              "rsi": float(rsi_s.iloc[-1])
                              if pd.notna(rsi_s.iloc[-1]) else None}
        if is_bull:
            bull_count += 1
        # --- stop intradiario 4% (hallazgo18): quiebre del día
        ith = float(cfg["intraday_stop_pct"])
        if ith and len(df) >= 2:
            low_today = float(df["Low"].iloc[-1])
            if low_today <= (1 - ith) * close_prev:
                intraday_cuts[sym] = round((1 - ith) * close_prev, 4)

    crash_event = bool(n_eval > 0 and n_crash >= n_eval * float(
        cfg["bear_threshold"]))  # mismo % que el bear: >=30%
    bear_count = sum(1 for s in ticker_status.values() if s["bear_choch"])

    # Con n=0 no hay evidencia: permanecer en cash, nunca fabricar un
    # régimen bear mediante la comparación 0 >= 0.
    if n > 0 and (bear_count >= n * cfg["bear_threshold"] or crash_event):
        regime = "bear"
    elif n > 0 and bull_count >= n * cfg["bull_threshold"]:
        regime = "bull"
    else:
        regime = "cash"

    return {"regime": regime, "bull_count": bull_count,
            "bear_count": bear_count, "n": n,
            "crash_event": crash_event, "crash_active": False,
            "intraday_cuts": intraday_cuts,
            # Estado por ticker: `bear_choch` marca los subyacentes con cambio
            # de carácter bajista. Se calculaba desde el principio pero no se
            # devolvía, así que nadie podía consumirlo — de ahí que el bot
            # fuera long-only pese a tener la señal (AGENTS.md §40).
            "ticker_status": ticker_status,
            "summary": (f"{regime}: bull {bull_count}/{n}, bear {bear_count}/{n}, "
                        f"crash={crash_event} ({n_crash}/{n_eval}), "
                        f"intraday_cuts={list(intraday_cuts)}")}


def apply_crash_cooldown(regime: dict, bot_state: dict,
                         today: datetime = None) -> dict:
    """Aplica el cool-down de 5 días del crash_event: si se activó, marca
    el régimen como bear hasta 5 días después, evitando cortes/reentradas
    el mismo día durante pánicos en fases. Persiste crash_lock en bot_state."""
    today = today or datetime.utcnow()
    if regime["crash_event"]:
        bot_state["crash_lock"] = today.strftime("%Y-%m-%d")
        regime["crash_active"] = True
        regime["regime"] = "bear"
    elif bot_state.get("crash_lock"):
        lock_date = datetime.strptime(bot_state["crash_lock"], "%Y-%m-%d")
        if (today - lock_date).days < DEFAULT_REGIME_CFG["crash_cooldown_days"]:
            regime["crash_active"] = True
            regime["regime"] = "bear"
        else:
            bot_state.pop("crash_lock", None)
    return regime
