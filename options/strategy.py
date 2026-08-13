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
            "strong_threshold": 0.7,
            "direction": "bull",          # bull→call spread, bear→put spread
            "delta_long": 0.40,
            "delta_short": 0.20,
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
                        self.cfg["delta_long"], self.cfg["delta_short"])
                else:
                    self.last_structure = self.builder.vertical_spread(
                        state.get("symbol", ""), spot, "bear",
                        self.cfg["delta_long"], self.cfg["delta_short"])
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
                  days_to_expiry: int, spot_now: float) -> str:
    """Devuelve la razón de salida si aplica, '' si mantener."""
    premium_now = current_structure.net_premium
    entry, now = pos.entry_premium, premium_now

    if pos.is_debit:
        # débito: TP +50%, SL -100% (riesgo definido del spread)
        if now >= entry * 1.5:
            return "tp_premio_50"
        if now <= entry * 0.15:
            return "sl_debito_total"
    else:
        # crédito: TC al 50% del cobrado, SL si la prima neta se duplica
        if now <= entry * 0.5:
            return "tc_credito_50"
        if now >= abs(entry) * 2:
            return "sl_credito_doble"

    # gestión temporal: 21 DTE o 50% del tiempo con poca ganancia
    if days_to_expiry <= 21 and now > 0:
        return "gestion_21dte"
    return ""
