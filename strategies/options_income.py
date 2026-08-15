"""Estrategia de INCOME por prima — The Wheel (CSP + Covered Calls).

Basada en el material de la comunidad Abacus (The Wheel, CSP/CC de Carlos Amec):
  1. Vender Cash-Secured Put con delta <= 0.20, ROC objetivo 1-2% mensual,
     solo en subyacentes sin earnings esa semana y spot por encima de SMA200.
  2. Si asignan el put -> pasar a Covered Call sobre las 100 acciones.
  3. Vender CC OTM con ROC >= 1% mensual; rollear strikes hacia arriba si el
     precio sube. Rollear el put si baja (mismo strike genera credito extra).

Clase principal: WheelStrategy — implementa IncomeStrategy (señales + estructura).
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta

from options.chains import (Leg, OptionFeed, OptionStructure,
                            OptionType, select_strikes)
from strategies.base import Signal, SignalType

logger = logging.getLogger("income")

DEFAULT_DELTA_SHORT = 0.20      # delta maximo del short (regla Abacus)
DEFAULT_ROC_MONTHLY_MIN = 0.01  # ROC mensual minimo sobre colateral
DEFAULT_DTE_MIN, DEFAULT_DTE_MAX = 21, 45


@dataclass
class WheelState:
    """Estado de la rueda por subyacente."""
    underlying: str
    phase: str = "csp"          # "csp" o "cc" (tenemos 100 acciones)
    shares: int = 0
    csp_strike: float = None    # strike del put vendido
    csp_premium: float = None
    cc_strike: float = None
    cc_premium: float = None

    @property
    def has_shares(self) -> bool:
        return self.shares >= 100


def roc_monthly(underlying, chain) -> dict:
    """ROC mensual estimado por strike: prima / colateral / meses hasta venc.

    colateral CSP  = strike * 100
    colateral CC   = max(strike, entrada) * 100 (aprox strike)
    """
    out = {}
    months_by_c = {c.symbol: max(1, round((c.expiration - date.today()).days / 30))
                   for c in chain}
    for c in chain:
        # ROC = prima recibida / colateral = (mid*100) / (strike*100) = mid/strike
        m = months_by_c[c.symbol]
        if c.strike and m:
            out[c.symbol] = (c.mid or 0) / c.strike / m
    return out


class WheelStrategy:
    """The Wheel: CSP -> (asignacion) -> CC -> reinicio."""

    name = "wheel"

    def __init__(self, feed: OptionFeed, config: dict = None):
        cfg = config or {}
        self.feed = feed
        self.delta_short = cfg.get("delta_short", DEFAULT_DELTA_SHORT)
        self.roc_min = cfg.get("roc_monthly_min", DEFAULT_ROC_MONTHLY_MIN)
        self.dte_min = cfg.get("dte_min", DEFAULT_DTE_MIN)
        self.dte_max = cfg.get("dte_max", DEFAULT_DTE_MAX)
        self.states: dict = {}

    # ------------------------------------------------------------------
    # Filtros del universo (reglas Abacus)
    # ------------------------------------------------------------------
    @staticmethod
    def no_earnings_this_week(symbol: str, news: list = None) -> bool:
        """Rechaza subyacentes con reporte de resultados esta semana.

        news: lista de dict con keys (date, symbols, category/source).
        """
        if not news:
            return True
        window_start = (date.today() - timedelta(days=4)).isoformat()[:10]
        for n in news:
            nd = str(n.get("date", ""))[:10]
            syms = (n.get("symbols") or "").upper()
            if nd >= window_start and symbol.upper() in syms.split(","):
                cat = (n.get("category") or n.get("source") or "").lower()
                if "earn" in cat or "earning" in cat or "benzinga" in cat:
                    return False
        return True

    def _spot_above_sma200(self, feed, symbol: str) -> bool:
        df = feed.history([symbol], "1d", days=220).get(symbol)
        if df is None or len(df) < 201:
            return True  # sin historial suficiente: no filtrar
        _c = "Close" if "Close" in df.columns else "close"
        return float(df.iloc[-1][_c]) > float(df[_c].rolling(200).mean().iloc[-1])

    # ------------------------------------------------------------------
    # Señales
    # ------------------------------------------------------------------
    def scan_universe(self, universe, feed, context: dict = None) -> list:
        """Devuelve señales Wheel para subyacentes sin posicion abierta."""
        ctx = context or {}
        news = ctx.get("news") or []
        out = []
        for sym in universe:
            st = self.states.get(sym, WheelState(sym))
            if st.has_shares or st.phase == "cc":
                continue  # manejado por generate_cc_signal
            if not self.no_earnings_this_week(sym, news):
                logger.info("Wheel %s: omitido por earnings esta semana", sym)
                continue
            try:
                spot_ok = self._spot_above_sma200(feed, sym)
            except Exception as e:  # noqa: BLE001
                logger.warning("Wheel %s: no pude verificar SMA200 (%s)", sym, e)
                spot_ok = True
            if not spot_ok:
                continue
            try:
                df = feed.history([sym], "1d", days=5)
            except Exception as e:  # noqa: BLE001
                logger.warning("Wheel %s: sin spot (%s)", sym, e)
                continue
            df = df.get(sym)
            if df is None or not len(df):
                continue
            out.append(Signal(symbol=sym, signal_type=SignalType.SHORT,
                              score=0.8, stop_price=None, target_price=None,
                              reason=("wheel_csp: delta<=0.20, ROC>=1%%/mes, "
                                      "sin earnings, spot>SMA200"),
                              strategy="wheel"))
        return out

    # ------------------------------------------------------------------
    # Estructuras
    # ------------------------------------------------------------------
    def csp_structure(self, underlying: str, spot: float) -> OptionStructure:
        """CSP delta<=0.20, DTE 21-45, ROC>=1% mensual sobre colateral."""
        today = date.today()
        chain = self.feed.contracts(
            underlying, OptionType.PUT,
            expiration_ge=today + timedelta(days=self.dte_min),
            expiration_le=today + timedelta(days=self.dte_max),
        )
        chain = [c for c in chain
                 if self.dte_min <= (c.expiration - today).days <= self.dte_max]
        chain = self.feed.snapshots(chain, spot)
        roc = roc_monthly(underlying, chain)
        cands = [c for c in chain
                 if c.mid > 0.10 and roc.get(c.symbol, 0) >= self.roc_min
                 and (c.volume >= 10 or c.open_interest >= 500)]
        sel = select_strikes(cands, spot, delta_target=self.delta_short,
                             otype=OptionType.PUT)
        if not sel:
            # degradacion: aceptar el strike con mayor ROC disponible
            sel = sorted(chain, key=lambda c: roc.get(c.symbol, 0), reverse=True)[:1]
        if not sel:
            raise RuntimeError(f"No hay CSP valido para {underlying}")
        c = sel[0]
        return OptionStructure(
            f"csp_{underlying}_{c.strike}",
            [Leg(c, -1)], underlying,
            rationale=(f"CSP Wheel: strike {c.strike} (delta {_f_p(c.delta)}), "
                       f"prima ${c.mid:.2f}, ROC {_f_pct(roc.get(c.symbol, 0))}/mes, "
                       f"DTE {(c.expiration - today).days}"),
            max_risk=c.strike * 100 - c.mid * 100,   # colateral - prima
        )

    def cc_structure(self, underlying: str, spot: float) -> OptionStructure:
        """Covered Call sobre 100 acciones: strike OTM, ROC>=1% mensual."""
        today = date.today()
        chain = self.feed.contracts(
            underlying, OptionType.CALL,
            expiration_ge=today + timedelta(days=14),
            expiration_le=today + timedelta(days=45),
        )
        chain = [c for c in chain
                 if 14 <= (c.expiration - today).days <= 45]
        chain = self.feed.snapshots(chain, spot)
        roc = roc_monthly(underlying, chain)
        cands = [c for c in chain if c.strike >= spot
                 and roc.get(c.symbol, 0) >= self.roc_min]
        if not cands:
            cands = sorted(chain, key=lambda c: roc.get(c.symbol, 0),
                           reverse=True)[:1]
        if not cands:
            raise RuntimeError(f"No hay CC valido para {underlying}")
        c = cands[0]
        return OptionStructure(
            f"cc_{underlying}_{c.strike}",
            [Leg(c, -1)], underlying,
            rationale=(f"CC Wheel: strike {c.strike} (delta {_f_p(c.delta)}), "
                       f"prima ${c.mid:.2f}, ROC {_f_pct(roc.get(c.symbol, 0))}/mes"),
            max_risk=0.0, max_profit=(c.strike - spot + c.mid) * 100,
        )


def _f_p(v):
    return f"{v:.2f}" if v is not None else "n/d"


def _f_pct(v):
    return f"{v:.0%}" if v is not None else "n/d"
