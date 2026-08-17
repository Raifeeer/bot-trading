"""Gestión de riesgo y dimensionamiento de posiciones.

Reglas implementadas:
  - Riesgo fijo por operación (por defecto 1% del capital)
  - Tamaño de posición derivado de la distancia al stop:
        shares = (capital * riesgo%) / (entry - stop)
  - Límite de posiciones abiertas simultáneas
  - Circuit breaker por drawdown diario y total
  - Prohibición de promediar a la baja
Todo se registra en un log inmutable de decisiones.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from strategies.base import SignalType

logger = logging.getLogger("risk")

MODE_PROFILES = {
    "conservative": {"max_risk_per_trade_pct": 0.5, "max_open_positions": 3,
                     "max_drawdown_daily_pct": 2.0, "max_drawdown_total_pct": 8.0},
    "moderate": {"max_risk_per_trade_pct": 1.0, "max_open_positions": 5,
                 "max_drawdown_daily_pct": 3.0, "max_drawdown_total_pct": 10.0},
    "aggressive": {"max_risk_per_trade_pct": 2.0, "max_open_positions": 8,
                   "max_drawdown_daily_pct": 5.0, "max_drawdown_total_pct": 15.0},
}


@dataclass
class PositionState:
    symbol: str
    side: str = "long"
    shares: float = 0.0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = None
    entry_ts: datetime = field(default_factory=datetime.utcnow)
    bars_held: int = 0
    strategy: str = ""


@dataclass
class RiskDecision:
    ts: datetime
    decision: str            # APPROVED | REJECTED
    symbol: str
    reason: str
    suggested_shares: float = 0.0


class RiskManager:
    def __init__(self, config: dict):
        mode = config.get("mode", "moderate")
        profile = MODE_PROFILES.get(mode, MODE_PROFILES["moderate"])
        self.cfg = {**profile}
        # Las claves de config.yaml prevalecen sobre el perfil
        for k in ("max_risk_per_trade_pct", "max_open_positions",
                  "max_drawdown_daily_pct", "max_drawdown_total_pct",
                  "max_daily_loss_usd"):
            if k in config:
                self.cfg[k] = config[k]
        self.capital = 0.0
        self.positions: List[PositionState] = []
        self.decision_log: List[RiskDecision] = []
        self.day_start_equity = 0.0
        self.halted_today = False
        self.halted_total = False
        self._risk_day = None

    def reset_day(self, equity: float, day=None):
        self.day_start_equity = float(equity)
        self.halted_today = False
        self._risk_day = day or datetime.utcnow().date()

    def ensure_day(self, equity: float, day=None) -> bool:
        """Reset the daily breaker at UTC calendar rollover.

        Returns True when a new risk day was initialized. Total drawdown state
        is intentionally preserved across days.
        """
        current_day = day or datetime.utcnow().date()
        if self._risk_day != current_day:
            self.reset_day(equity, current_day)
            logger.info("RISK nuevo día: equity inicial %.2f", equity)
            return True
        return False

    def check_circuit_breakers(self, equity: float, day=None):
        self.ensure_day(equity, day=day)
        if self.day_start_equity > 0:
            dd_daily = (self.day_start_equity - equity) / self.day_start_equity * 100
            if dd_daily >= self.cfg["max_drawdown_daily_pct"]:
                if not self.halted_today:
                    logger.critical("CIRCUIT BREAKER DIARIO: drawdown %.2f%% (límite %.2f%%)",
                                    dd_daily, self.cfg["max_drawdown_daily_pct"])
                self.halted_today = True

            # Breaker diario en DÓLARES ABSOLUTOS.
            # Los breakers porcentuales están calibrados a la cuenta completa
            # (15% de $99,689 = $14,953), así que a la escala del reto $100
            # son inoperantes: harían falta ~19 pérdidas totales de $777 para
            # que salte uno. Con el tamaño de recuperación sin tope
            # (17 ago 2026) ese hueco es justo el que importa, así que este
            # límite absoluto es el que de verdad corta una mala racha.
            max_usd = self.cfg.get("max_daily_loss_usd")
            if max_usd:
                perdida = self.day_start_equity - equity
                if perdida >= float(max_usd):
                    if not self.halted_today:
                        logger.critical(
                            "CIRCUIT BREAKER DIARIO ($): pérdida %.2f >= "
                            "límite %.2f; sin más entradas hoy",
                            perdida, float(max_usd))
                    self.halted_today = True
        if equity <= 0 or equity >= self.capital > 0:
            pass  # capital aún no inicializado o creciendo
        if self.capital > 0:
            dd_total = (self.capital - equity) / self.capital * 100
            if dd_total >= self.cfg["max_drawdown_total_pct"]:
                if not self.halted_total:
                    logger.critical("CIRCUIT BREAKER TOTAL: drawdown %.2f%%", dd_total)
                self.halted_total = True

    def _log(self, decision, symbol, reason, shares=0.0):
        rec = RiskDecision(datetime.utcnow(), decision, symbol, reason, shares)
        self.decision_log.append(rec)
        logger.info("RISK [%s] %s: %s (%.0f acciones)", decision, symbol, reason, shares)
        return rec

    def is_halted(self) -> bool:
        return self.halted_today or self.halted_total

    def approve_position(self, symbol: str, signal, entry_price: float,
                         capital: float, existing: List[PositionState]) -> RiskDecision:
        self.positions = existing

        # 1. Circuit breaker
        if self.is_halted():
            return self._log("REJECTED", symbol, "bot detenido por circuit breaker")

        # 2. Solo largas aprobadas por ahora
        if signal.signal_type not in (SignalType.LONG, SignalType.SHORT):
            return self._log("REJECTED", symbol, "señal no tradable")

        if signal.signal_type == SignalType.SHORT:
            return self._log("REJECTED", symbol, "cortas deshabilitadas por política")

        # 3. Ya en posición o límite de posiciones
        if any(p.symbol == symbol for p in self.positions):
            return self._log("REJECTED", symbol, "posición ya abierta (sin promedio a la baja)")
        if len(self.positions) >= self.cfg["max_open_positions"]:
            return self._log("REJECTED", symbol,
                             f"límite de {self.cfg['max_open_positions']} posiciones alcanzado")

        # 4. Stop válido
        stop = signal.stop_price or entry_price * 0.97
        if stop >= entry_price:
            return self._log("REJECTED", symbol, "stop >= precio de entrada")

        # 5. Dimensionamiento por riesgo fijo
        risk_per_share = entry_price - stop
        max_risk_usd = capital * self.cfg["max_risk_per_trade_pct"] / 100.0
        shares = min(max_risk_usd / risk_per_share, capital / entry_price)  # nunca apalancado
        shares = float(int(shares))  # acciones enteras

        if shares < 1:
            return self._log("REJECTED", symbol, "tamaño < 1 acción con el riesgo permitido")

        # 6. No exceder el capital disponible (aprox: 100% invertible en swing,
        #    se asume capital asignado por modo)
        needed = shares * entry_price
        if needed > capital:
            shares = int(capital / entry_price)
            if shares < 1:
                return self._log("REJECTED", symbol, "capital insuficiente")

        return self._log("APPROVED", symbol,
                         f"riesgo {self.cfg['max_risk_per_trade_pct']}%, stop {stop:.2f}",
                         shares)
