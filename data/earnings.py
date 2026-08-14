"""Calendario de earnings con filtro de bloqueo para entradas.

Fuente: yfinance (gratuito; Ticker.calendar devuelve 'Earnings Date' con
estimaciones de EPS e ingresos). Las fechas de earnings no cambian por hora,
así que se hace caché por símbolo durante 24 h.

Uso en el bot: cualquier ticker con earnings en los próximos
`horizon_days` (default 2) se bloquea para NUEVAS entradas — el gap de
earnings puede mover el precio un +/-5-20% en el pre/post-market donde las
opciones se revalorizan de golpe (IV crush + gap), invalidando el análisis
técnico que el bot hace sobre el mercado regular.
"""
import logging
import time
from datetime import date, timedelta

logger = logging.getLogger("feed.earnings")

_cache = {}  # sym -> (epoch_ts, {date or None, eps_avg, ...})


def _fetch(symbol: str) -> dict:
    import yfinance as yf

    cal = {}
    try:
        cal = yf.Ticker(symbol).calendar or {}
    except Exception:  # noqa: BLE001
        logger.warning("earnings: yfinance falló para %s", symbol)
    ed = cal.get("Earnings Date")
    d = None
    if ed:
        # Puede ser lista de 2 fechas (rango estimado) o una sola fecha
        first = ed[0] if isinstance(ed, list) else ed
        if hasattr(first, "date"):
            d = first.date()
        elif hasattr(first, "year"):
            d = first
    eps = cal.get("Earnings Average")
    return {"earnings_date": d, "eps_estimate": eps}


def get_earnings(symbol: str) -> dict:
    """Devuelve {earnings_date: date|None, eps_estimate: float|None} con
    caché de 24 h."""
    now = time.time()
    entry = _cache.get(symbol)
    if entry and (now - entry[0]) < 86400 and entry[1].get("earnings_date"):
        return entry[1]
    info = _fetch(symbol)
    _cache[symbol] = (now, info)
    return info


def blocked(symbol: str, horizon_days: int = 2) -> bool:
    """True si el ticker reporta earnings en los próximos `horizon_days`
    (incluye hoy). Los earnings en rango bloquean NUEVAS entradas."""
    info = get_earnings(symbol)
    ed = info.get("earnings_date")
    if not ed:
        return False
    today = date.today()
    return today <= ed <= today + timedelta(days=max(horizon_days, 0))


def block_reason(symbol: str, horizon_days: int = 2) -> str:
    info = get_earnings(symbol)
    ed = info.get("earnings_date")
    eps = info.get("eps_estimate")
    if blocked(symbol, horizon_days):
        return (f"Earnings {ed} (eps est. {eps}) en rango de {horizon_days}d")
    if ed:
        return ""
    return ""
