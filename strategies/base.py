"""Interfaz base para todas las estrategias."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class SignalType(Enum):
    LONG = "long"
    SHORT = "short"
    EXIT = "exit"
    NONE = "none"


@dataclass
class Signal:
    symbol: str
    signal_type: SignalType
    score: float = 0.0            # fuerza de la señal (0-1)
    stop_price: float = None      # stop-loss sugerido
    target_price: float = None    # take-profit sugerido
    reason: str = ""
    ts: datetime = field(default_factory=datetime.utcnow)
    strategy: str = ""

    @property
    def tradable(self) -> bool:
        return self.signal_type in (SignalType.LONG, SignalType.SHORT)


class Strategy(ABC):
    """Toda estrategia debe implementar scan().

    scan() recibe el historial completo de barras del símbolo y devuelve la
    señal vigente en la última barra cerrada. El motor llama a scan() en cada
    barra nueva (vectorizado en backtest, evento a evento en vivo).
    """

    name: str = "base"
    timeframe: str = "1d"

    @abstractmethod
    def scan(self, df, **state) -> Signal:
        ...

    def parameters(self):
        """Parámetros para optimización / logging."""
        return {}
