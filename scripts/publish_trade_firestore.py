"""Publica la posición manual del spread TQQQ a Firestore (DB 'polaris',
Native) usando la MISMA estructura que el bot publica y el dashboard lee
(polaris/{YYYY-MM-DD}: payload.positions[], payload.decisions_today,
payload.equity, payload.risk, payload.universe, payload.strategies;
equity_curve[] e signals[] como campos del doc).
"""
import os
from datetime import date, datetime, timezone

os.environ.setdefault("FIRESTORE_DATABASE", "polaris")

TODAY = date.today().isoformat()
NOW = datetime.now(timezone.utc).isoformat()

from google.cloud import firestore

db = firestore.Client(database="polaris")
day_ref = db.collection("polaris").document(TODAY)

# Estructura del spread exactamente como la espera mapPositions() del dashboard
positions = [
    {
        "id": "TQQQ260918C00085000",
        "symbol": "TQQQ",
        "strategy": "S78 regime-aware",
        "structure": "debit_call_spread",
        "side": "debit",
        "legs": [
            {"symbol": "TQQQ260918C00085000", "side": "long", "entry_price": 2.32,
             "current_price": 2.30, "qty": 10},
            {"symbol": "TQQQ260918C00100000", "side": "short", "entry_price": 0.35,
             "current_price": 0.37, "qty": -10},
        ],
        "entry_price": 76.95,          # spotEntry
        "spot": 76.95,                 # spotNow
        "premium": 1.97,               # currentPremium
        "entry_premium": 1.97,
        "max_risk": 1.97,              # riesgo max = prima neta
        "delta_long": 0.31,
        "delta_short": 0.07,
        "iv": 0.53,
        "dte": 35,
        "entry_ts": NOW,
        "exit_rule": "TP+40% prima / SL-75% prima / cierre 7DTE / stop suby -4%",
        "pnl": -20.0,
        "notes": ("Spread debit call 85/100 Sep-18-2026, 10 contratos. "
                  "Breakeven 86.97. Abierto manualmente replicando el "
                  "motor S78."),
    },
]

signals = [
    {
        "ts": NOW,
        "symbol": "TQQQ",
        "strategy": "S78 regime-aware + stop intradiario 4%",
        "type": "LONG",
        "score": 0.85,
        "reason": ("Regimen bull: TQQQ 76.95 > SMA200 60.2. Indice S&P 500 en "
                   "maximo historico (7800+). VIX 14.6 (primas baratas). "
                   "Catalizador: recorte Fed sept (~90% prob). Estructura: "
                   "call debit 85/100 Sep-18, 35 DTE, delta long 0.31, "
                   "prima neta $1.97, riesgo max $1,970 (1.97% equity)."),
        "approved": True,
    },
]

# snapshot del día (payload completo, como lo escribe bot.py)
payload = {
    "account": {"equity": 99779.50, "cash": 98029.50,
                "buying_power": 98029.50, "status": "ACTIVE",
                "trading_mode": "PAPER"},
    "equity": 99779.50,
    "cash": 98029.50,
    "buying_power": 98029.50,
    "open_positions": 1,
    "trading_mode": "PAPER",
    "regime": "bull",
    "universe": ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"],
    "strategies": ["S78 regime-aware", "The Wheel (perfil reto)"],
    "risk": {"max_positions": 5, "risk_per_trade_pct": 2.0,
             "daily_limit_pct": 5.0, "total_limit_pct": 20.0,
             "tp_mult": 1.4, "sl_mult": 0.75, "close_dte": 7,
             "intraday_stop_pct": 4.0, "drawdown_daily_pct": 0.22,
             "drawdown_total_pct": 0.22, "halted": False,
             "day_trade_count": 1},
    "positions": positions,
    "alpaca_positions": positions,
    "orders_executed": [{"ticker": "TQQQ", "action": "open debit call spread",
                         "price": 1.97, "qty": 10, "time": NOW,
                         "pnl": None}],
    "decisions_today": [
        {"ts": NOW, "symbol": "TQQQ", "strategy": "S78 regime-aware",
         "type": "LONG", "score": 0.85,
         "reason": "regimen bull, indice en maximo historico, VIX bajo, "
                   "catalizador Fed; spread debit 85/100 Sep-18",
         "approved": True},
    ],
}

equity_curve = [{"t": NOW, "value": 99779.50}]

day_ref.set({
    "updated_at": NOW,
    "payload": payload,
    "signals": signals,
    "equity_curve": equity_curve,
}, merge=True)

# subcolección spreads para consulta futura (histórico manual)
day_ref.collection("spreads").document("TQQQ260918C00085000").set({
    "symbol": "TQQQ",
    "long_leg": "TQQQ260918C00085000",
    "short_leg": "TQQQ260918C00100000",
    "qty": 10,
    "long_entry": 2.32,
    "short_entry": 0.35,
    "net_premium": 1.97,
    "breakeven": 86.97,
    "dte_at_entry": 35,
    "close_at_dte": 7,
    "tp_premium": 2.76,
    "sl_premium": 0.49,
    "intraday_stop_spot_pct": -4.0,
    "created_at": NOW,
})
print("Publicado a Firestore (polaris/%s). Posiciones: %d | Señales: %d" %
      (TODAY, len(positions), len(signals)))
