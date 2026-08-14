"""Estrategia de opciones: traduce señales del subyacente en estructuras.

Reglas de mapeo señal → estructura (configurables):
  - Señal LONG fuerte (score >= 0.7)      → call spread alcista
  - Señal LONG moderada (0.4-0.7)         → long call (delta ~0.30)
  - Señal EXIT sobre posición larga       → cerrar pata larga al mercado
  - Señal SHORT (deshabilitada por riesgo en fase 1)

Gestión de la posición de opciones:
  - Take profit en prima: cerrar al +50% del débito o -50% del crédito cobrado
  - Stop en prima: cerrar al -100% del débito (riesgo máximo definido en
    spreads) o cuando la prima del lado vendido se duplique
  - Gestión temporal: cerrar a los 21 días del vencimiento (evita gamma risk
    de última semana) o al 50% del tiempo transcurrido con poca ganancia
"""
import logging
from dataclasses import dataclass
from datetime import datetime

from strategies.base import Strategy, Signal, SignalType
from options.chains import OptionStructure, SpreadBuilder, OptionType, price_to_greeks

logger = logging.getLogger("options.strategy")


@dataclass
class OptionsPosition:
    structure: OptionStructure
    entry_premium: float       # débito (+) o crédito (-) cobrado por estructura
    entry_ts: datetime
    underlying_signal: str = ""
    exit_rule: str = ""

    @property
    def is_debit(self) -> bool:
        return self.entry_premium > 0


class OptionsStrategy(Strategy):
    """Envoltura: usa una estrategia de subyacente (p. ej. swing_trend o
    day_momentum) como generador de señales, y mapea a estructuras.

    Uso: se instancia con la estrategia base y el SpreadBuilder; el motor la
    trata como cualquier Strategy (scan() devuelve LONG/SHORT/EXIT).
    """
    name = "options_bridge"
    timeframe = "1d"

    def __init__(self, base: Strategy, spread_builder: SpreadBuilder,
                 map_cfg: dict = None):
        self.base = base
        self.builder = spread_builder
        self.name = f"opt_{base.name}"
        self.timeframe = base.timeframe
        self.cfg = {
            "strong_threshold": 0.5,      # más permisivo: reto $100→$200
            "direction": "bull",          # bull→call spread, bear→put spread
            "delta_long": 0.30,           # prima más barata (long menos ITM)
            "delta_short": 0.15,          # short más OTM: spread más estrecho
            "max_premium_net": 0.50,      # prima neta máx $0.50 por spread
            "dte_min": 7,                 # vencimientos cortos para el reto
            "dte_max": 45,
            "spot_source": "last_close",
        }
        self.cfg.update(map_cfg or {})
        self.last_structure = None

    def parameters(self):
        return {**self.base.parameters(), **self.cfg}

    def scan(self, df, **state) -> Signal:
        # 1. Señal del subyacente (la estrategia base no cambia)
        base_sig = self.base.scan(df, **state)
        if base_sig.signal_type == SignalType.EXIT:
            return Signal("opt_bridge", SignalType.EXIT,
                          reason=f"opciones: {base_sig.reason}",
                          strategy=f"opt_{self.base.name}")

        # 2. Si hay señal de entrada y aún no construimos la estructura
        if base_sig.tradable and self.last_structure is None:
            spot = df["close"].iloc[-1]
            try:
                if self.cfg["direction"] == "bull":
                    self.last_structure = self.builder.vertical_spread(
                        state.get("symbol", ""), spot, "bull",
                        self.cfg["delta_long"], self.cfg["delta_short"],
                        dte_min=self.cfg.get("dte_min", 14),
                        dte_max=self.cfg.get("dte_max", 60))
                else:
                    self.last_structure = self.builder.vertical_spread(
                        state.get("symbol", ""), spot, "bear",
                        self.cfg["delta_long"], self.cfg["delta_short"],
                        dte_min=self.cfg.get("dte_min", 14),
                        dte_max=self.cfg.get("dte_max", 60))
                # Filtro de prima neta máxima (reto de capital pequeño):
                # si el spread cuesta más que max_premium_net, no opera.
                max_px = self.cfg.get("max_premium_net")
                if max_px is not None and self.last_structure.net_premium > max_px:
                    logger.info("Prima neta %.2f > %.2f, se descarta %s",
                                self.last_structure.net_premium, max_px,
                                self.last_structure.name)
                    return Signal("opt_bridge", SignalType.NONE,
                                  strategy=f"opt_{self.base.name}")
                sig = Signal("opt_bridge", base_sig.signal_type,
                             score=base_sig.score,
                             strategy=f"opt_{self.base.name}",
                             reason=(f"{self.last_structure.name}: "
                                     f"{self.last_structure.rationale}"))
                return sig
            except RuntimeError as e:
                logger.warning("No se pudo construir estructura: %s", e)
                return Signal("opt_bridge", SignalType.NONE,
                              strategy=f"opt_{self.base.name}")
        return Signal("opt_bridge", SignalType.NONE,
                      strategy=f"opt_{self.base.name}")

    def reset(self):
        self.last_structure = None


# ---------------------------------------------------------------------------
# Gestor de vida de la posición de opciones (reglas de gestión)
# ---------------------------------------------------------------------------

def evaluate_exit(current_structure: OptionStructure, pos: OptionsPosition,
                  days_to_expiry: int, spot_now: float,
                  tp_mult: float = 1.5, sl_mult: float = 0.15,
                  tp_credit_mult: float = 0.5, sl_credit_mult: float = 2.0,
                  close_dte: int = 21, hold_days: int = None,
                  min_gain_after_half_time: float = 0.1) -> str:
    """Devuelve la razón de salida si aplica, '' si mantener.

    Los multiplicadores son configurables (reto $100→$200): tp_mult=1.4
    (TP al +40% de prima) y sl_mult=0.25 (SL al -75% de prima) reemplazan los
    valores por defecto de +50%/-85%.
    """
    premium_now = current_structure.net_premium
    entry, now = pos.entry_premium, premium_now

    if pos.is_debit:
        # débito: TP configurable (defecto +50%), SL configurable (defecto
        # prima al 15% de la entrada = -85%). El reto usa 1.4 / 0.25.
        if now >= entry * tp_mult:
            return "tp_premio"
        if now <= entry * sl_mult:
            return "sl_premio"
    else:
        # crédito: TC configurable al % del cobrado, SL si la prima neta se
        # multiplica por sl_credit_mult (defecto 2.0 = el doble)
        if now <= entry * tp_credit_mult:
            return "tc_credito"
        if now >= abs(entry) * sl_credit_mult:
            return "sl_credito_doble"

    # gestión temporal: cerrar a close_dte del vencimiento o a la mitad del
    # tiempo transcurrido con ganancia menor a min_gain_after_half_time
    if days_to_expiry <= close_dte and now > 0:
        return "gestion_close_dte"
    if hold_days is not None:
        total_life = pos.structure.legs[0].contract.expiration - pos.entry_ts.date() if hasattr(pos.entry_ts, "date") else 30
        if total_life.days > 0 and hold_days >= total_life.days / 2:
            gain = (now - entry) / entry if entry else 0.0
            if gain < min_gain_after_half_time:
                return "gestion_medio_tiempo"
    return ""
