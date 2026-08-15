"""Módulo de OPCIONES: cadenas, contratos, Greeks y selección de strikes.

Capas:
  1. OptionFeed      — obtiene contratos y snapshots (Alpaca real / simulado mock)
  2. greeks          — cálculo de delta/gamma/theta/vega/IV implícita (Black-Scholes)
  3. strike selectors — reglas de selección: delta target, OTM %, spread width
  4. SpreadBuilder  — construye estructuras: long call/put, vertical spreads,
                      iron condors (configuración de patas)

Nota de arquitectura: las señales de entrada siguen viniendo del análisis del
subyacente (estrategias en strategies/). Este módulo traduce la señal en una
estructura de opciones concreta y supervisa su gestión hasta el vencimiento.
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import List, Optional

import numpy as np

logger = logging.getLogger("options")

def _f(v):
    """Formato tolerante a None (Alpaca paper no siempre entrega greeks)."""
    return f"{v:.2f}" if v is not None else "n/d"

def _f_pct(v):
    return f"{v:.0%}" if v is not None else "n/d"

# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class OptionType(Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class OptionContract:
    symbol: str                     # p. ej. SPY260821C00500000 (OCC)
    underlying: str
    option_type: OptionType
    strike: float
    expiration: date
    multiplier: int = 100
    # datos de mercado (snapshot)
    bid: float = None
    ask: float = None
    last: float = None
    iv: float = None                # implied volatility
    delta: float = None
    gamma: float = None
    theta: float = None
    vega: float = None
    volume: int = 0
    open_interest: int = 0
    updated_at: datetime = None

    @property
    def mid(self) -> float:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last or 0.0

    @property
    def spread_bps(self) -> float:
        if self.bid and self.ask and self.bid > 0:
            return (self.ask - self.bid) / self.bid * 10000
        return float("inf")

    @property
    def occ_symbol(self) -> str:
        return self.symbol


@dataclass
class Leg:
    """Una pata de una estructura de opciones."""
    contract: OptionContract
    quantity: int            # +1 comprar, -1 vender
    premium: float = None    # prima esperada/observada

    @property
    def net_premium(self) -> float:
        px = self.premium if self.premium is not None else self.contract.mid
        return px * self.quantity * self.contract.multiplier


@dataclass
class OptionStructure:
    """Estructura completa (1 o más patas)."""
    name: str
    legs: List[Leg]
    underlying: str = ""
    rationale: str = ""
    max_risk: float = None       # riesgo máximo teórico en USD
    max_profit: float = None
    breakevens: List[float] = field(default_factory=list)

    @property
    def net_premium(self) -> float:
        return sum(l.net_premium for l in self.legs)

    @property
    def net_delta(self) -> float:
        return sum((l.contract.delta or 0) * l.quantity * l.contract.multiplier
                   for l in self.legs)

    @property
    def is_credit(self) -> bool:
        return self.net_premium < 0


# ---------------------------------------------------------------------------
# Greeks: Black-Scholes
# ---------------------------------------------------------------------------

def _d1(S, K, T, r, sigma):
    return (np.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * np.sqrt(T))


def black_scholes_price(S, K, T, r, sigma, otype: OptionType):
    """Precio teórico BS. T en años, r tasa libre de riesgo anual."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if otype == OptionType.CALL else max(K - S, 0.0)
    from scipy.stats import norm
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * np.sqrt(T)
    if otype == OptionType.CALL:
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def greeks(S, K, T, r, sigma, otype: OptionType):
    """Devuelve (delta, gamma, theta, vega) en escala por contrato (x100)."""
    from scipy.stats import norm
    if T <= 0 or sigma <= 0:
        return (1.0 if otype == OptionType.CALL else -1.0, 0.0, 0.0, 0.0)
    d1 = _d1(S, K, T, r, sigma)
    nd1 = norm.pdf(d1)
    sqrtT = np.sqrt(T)
    delta = norm.cdf(d1) if otype == OptionType.CALL else norm.cdf(d1) - 1
    gamma = nd1 / (S * sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    theta = (-(S * nd1 * sigma) / (2 * sqrtT)
             - (r * K * np.exp(-r * T) * norm.cdf(d2 if otype == OptionType.CALL else -d2))) / 365.0
    vega = S * nd1 * sqrtT / 100.0   # por 1 punto de IV
    return delta, gamma, theta, vega


def implied_volatility(price, S, K, T, r, otype: OptionType,
                       tol=1e-6, max_iter=100) -> Optional[float]:
    """IV implícita por Newton-Raphson con bisección de respaldo sobre BS.

    Maneja casos degenerados: deep ITM (prima ≈ intrínseco, vega ≈ 0) y
    deep OTM (prima ≈ 0): en ambos devuelve None para no contaminar deltas.
    """
    if T <= 0 or price <= 0:
        return None
    intrinsic = (S - K) if otype == OptionType.CALL else (K - S)
    if intrinsic > 0 and price - intrinsic < max(T * S * 0.02, 0.05):
        return None   # prima ≈ intrínseco: sin información de volatilidad
    sigma = 0.30
    for _ in range(max_iter):
        px = black_scholes_price(S, K, T, r, sigma, otype)
        _, _, _, vega = greeks(S, K, T, r, sigma, otype)
        vega_usd = vega * 100
        if vega_usd < 1e-12:
            break
        diff = px - price
        if abs(diff) < tol:
            return sigma
        sigma -= diff / vega_usd
        sigma = max(0.03, min(sigma, 3.0))
    # verificación final: si no converge, bisección
    lo, hi = 0.03, 3.0
    if black_scholes_price(S, K, T, r, lo, otype) > price:
        return None   # incluso a IV mínima el modelo sobreprecia -> deep ITM
    if black_scholes_price(S, K, T, r, hi, otype) < price:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if black_scholes_price(S, K, T, r, mid, otype) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def price_to_greeks(contract: OptionContract, spot: float, r: float = 0.045):
    """Rellena greeks + IV de un contrato desde su precio de mercado."""
    T = max((contract.expiration - date.today()).days, 0) / 365.0
    price = contract.mid or contract.last
    if not price or T <= 0 or not spot:
        return
    iv = contract.iv or implied_volatility(price, spot, contract.strike, T, r,
                                           contract.option_type)
    if iv is None:
        return
    delta, gamma, theta, vega = greeks(spot, contract.strike, T, r, iv,
                                       contract.option_type)
    contract.iv, contract.delta = iv, delta
    contract.gamma, contract.theta, contract.vega = gamma, theta, vega


# ---------------------------------------------------------------------------
# Feed de opciones (Alpaca)
# ---------------------------------------------------------------------------

def _alpaca_client():
    import os
    from alpaca.trading.client import TradingClient
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
    except ImportError:  # alpaca-py antiguo
        from alpaca.data.client import StockHistoricalDataClient as OptionHistoricalDataClient
    from config import get_config
    cfg = get_config()
    key = os.environ.get("APCA_API_KEY_ID") or cfg["broker"].get("api_key")
    secret = os.environ.get("APCA_API_SECRET_KEY") or cfg["broker"].get("secret_key")
    if not key or not secret:
        raise RuntimeError("Sin credenciales de Alpaca (APCA_API_KEY_ID / APCA_API_SECRET_KEY)")
    return (TradingClient(key, secret, paper=cfg["broker"].get("paper", True)),
            OptionHistoricalDataClient(api_key=key, secret_key=secret))


class _SimOptionFeed:
    """Feed simulado para modo dry-run sin credenciales de Alpaca.

    Genera contratos sintéticos con pricing Black-Scholes sobre el spot real
    del subyacente, replicando la interfaz de OptionFeed.contracts/snapshots.
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def contracts(self, underlying, otype=None, expiration_ge=None,
                  expiration_le=None, max_results=200):
        """Cadena sintética: strikes ATM ±20 con expiración 30 DTE."""
        from config import get_config
        from data.feed import MarketDataFeed
        cfg = self.cfg or get_config()
        spot = MarketDataFeed(cfg["data"].get("provider", "yfinance")) \
            .history([underlying], "1d", days=1).get(underlying)
        _c = "Close" if spot is not None and "Close" in spot.columns else "close"
        spot_px = float(spot.iloc[-1][_c]) if spot is not None and len(spot) else None
        today = date.today()
        exp = today + timedelta(days=30)
        if not (expiration_ge <= exp <= expiration_le):
            return []
        out = []
        if spot_px:
            for i in range(-15, 16):
                K = round(spot_px * (1 + 0.02 * i), 2)
                iv = 0.45  # IV sintética (regla Abacus: ROC ~1%/mes en delta -0.15)
                mid = black_scholes_price(spot_px, K, 30 / 365, 0.045, iv,
                                          otype or OptionType.CALL)
                delta, _g, _t, _v = greeks(spot_px, K, 30 / 365, 0.045, iv,
                                             otype or OptionType.CALL)
                out.append(OptionContract(
                    symbol=f"SIM_{underlying}_{exp:%y%m%d}_{otype.value}_{K}",
                    underlying=underlying,
                    option_type=otype or OptionType.CALL,
                    strike=K, expiration=exp,
                    bid=mid * 0.98, ask=mid * 1.02, last=mid, iv=iv,
                    volume=100, open_interest=1000,
                    delta=delta, gamma=_g, theta=_t, vega=_v))
        logger.info("SIM %s: %d contratos sintéticos", underlying, len(out))
        return out

    def snapshots(self, contracts, spot=None):
        return contracts  # ya vienen con precio teórico


class OptionFeed:
    """Obtiene contratos de opciones y snapshots vía Alpaca."""

    def __init__(self, client=None, sim=False):
        if sim or client is not None:
            self.trading, self.data = client, client
            self._sim = bool(sim)
        else:
            try:
                self.trading, self.data = _alpaca_client()
                self._sim = False
                # Los snapshots de opciones van por el data client de opciones
                # (el TradingClient no los expone: AttributeError en REST).
                try:
                    from alpaca.data.historical.option import OptionHistoricalDataClient
                    from config import get_config
                    cfg = get_config()
                    key = os.environ.get("APCA_API_KEY_ID") or cfg["broker"].get("api_key")
                    secret = os.environ.get("APCA_API_SECRET_KEY") or cfg["broker"].get("secret_key")
                    self.data = OptionHistoricalDataClient(key, secret)
                except Exception as e:  # noqa: BLE001
                    logger.warning("OptionHistoricalDataClient no disponible (%s); "
                                   "snapshots por trading client", e)
            except RuntimeError:
                self.trading, self.data = _SimOptionFeed(), _SimOptionFeed()
                self._sim = True
                logger.warning("OptionFeed en modo simulado (sin credenciales de Alpaca)")

    def contracts(self, underlying: str, otype: OptionType = None,
                  expiration_ge: date = None, expiration_le: date = None,
                  max_results: int = 200) -> List[OptionContract]:
        """Lista contratos del subyacente con filtros básicos (con reintentos
        ante límites de velocidad de la API de Alpaca)."""
        import time
        from alpaca.trading.requests import GetOptionContractsRequest
        from alpaca.trading.enums import ContractType
        req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            type=ContractType(otype.value) if otype else None,
            expiration_date_gte=expiration_ge,
            expiration_date_lte=expiration_le,
            limit=max_results,
        )
        resp = None
        for attempt in range(4):
            try:
                resp = self.trading.get_option_contracts(req)
                break
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if attempt < 3 and ("429" in name or "Connection" in name
                                    or "Remote" in name or "Rate" in name
                                    or "aborted" in str(e)):
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        if resp is None:
            raise RuntimeError(f"Sin respuesta de /options/contracts para {underlying}")
        # alpaca-py real: OptionContractsResponse.option_contracts (lista directa)
        contracts = resp.option_contracts if resp.option_contracts else []
        out = []
        for c in contracts:
            out.append(OptionContract(
                symbol=c.symbol, underlying=underlying,
                option_type=OptionType(c.type.lower() if isinstance(c.type, str) else c.type.value),
                strike=float(c.strike_price), expiration=c.expiration_date,
                open_interest=int(c.open_interest or 0) or 0,
            ))
        logger.info("%s: %d contratos de opciones", underlying, len(out))
        return out

    def snapshots(self, contracts: List[OptionContract], spot: float = None) -> List[OptionContract]:
        """Rellena bid/ask/last/greeks/volume/OI vía snapshots de Alpaca.

        spot: precio del subyacente; si Alpaca no entrega greeks (p. ej. paper),
        se calculan localmente con Black-Scholes + IV implícita.
        """
        # Lote de 25 símbolos por solicitud (límite de la API REST de
        # snapshots) para respetar el rate limit de 60 req/min.
        import time as _time
        from alpaca.data.requests import OptionSnapshotRequest
        pending = [c for c in contracts if c.bid is None and c.last is None]
        batch = 25
        for i in range(0, len(pending), batch):
            group = pending[i:i + batch]
            try:
                s = self.data.get_option_snapshot(
                    OptionSnapshotRequest(symbol_or_symbols=[c.symbol for c in group]))
                snaps = s if isinstance(s, dict) else {}
            except Exception as e:  # noqa: BLE001
                logger.warning("lote de snapshots falló: %s", e)
                continue
            for c in group:
                snap = snaps.get(c.symbol)
                if snap is None:
                    continue
                if getattr(snap, "latest_quote", None):
                    c.bid, c.ask = snap.latest_quote.bid_price, snap.latest_quote.ask_price
                if getattr(snap, "latest_trade", None):
                    c.last = snap.latest_trade.price
                    c.volume = snap.latest_trade.size or 0
                if getattr(snap, "greeks", None):
                    c.delta, c.gamma = snap.greeks.delta, snap.greeks.gamma
                    c.theta, c.vega = snap.greeks.theta, snap.greeks.vega
                    c.iv = getattr(snap.greeks, "implied_volatility", None)
                if c.iv is None and (c.bid or c.last):
                    price_to_greeks(c, spot or 0.0)
            if i + batch < len(pending):
                _time.sleep(1.0)
        return contracts


# ---------------------------------------------------------------------------
# Selectores de strike
# ---------------------------------------------------------------------------

def select_strikes(chain: List[OptionContract], spot: float = None,
                   delta_target: float = 0.30, otype: OptionType = None,
                   spread_width: int = 1, max_spread_bps: float = 800.0) -> List[OptionContract]:
    """Selecciona contratos líquidos y ordenados por proximidad al delta objetivo.

    spread_width: si > 1, retorna varios strikes en escalera para construir
    spreads (p. ej. width=2 → strike ITM (leg long) + strike OTM (leg short)).
    El orden de retorno es siempre [más ITM, más OTM].
    """
    cands = [c for c in chain if c.option_type == (otype or c.option_type)
             and c.mid > 0.05 and c.spread_bps <= max_spread_bps
             and (c.volume >= 10 or c.open_interest >= 100)
             and c.delta is not None]
    cands.sort(key=lambda c: c.strike)
    if not cands:
        return []
    if spot is None:
        # Sin precio de referencia: ordenar solo por proximidad al delta objetivo
        pool = list(cands)
    elif otype == OptionType.CALL:
        # Call spread: long = strike más cercano al delta objetivo (menos OTM),
        # short = strike más OTM. Devolver escalera ascendente por strike.
        pool = [c for c in cands if c.strike >= spot] or cands[-spread_width:]
    else:
        # Put spread: long = strike más cercano al delta objetivo (menos OTM),
        # short = strike más OTM (menor). Devolver escalera descendente por strike.
        pool = [c for c in cands if c.strike <= spot] or cands[:spread_width]
    if pool and pool[0].delta is not None:
        pool.sort(key=lambda c: abs((c.delta or 0) - (delta_target if otype == OptionType.CALL else -delta_target)))
    sel = sorted(pool[:spread_width], key=lambda c: c.strike,
                 reverse=(otype == OptionType.PUT))
    return sel


# ---------------------------------------------------------------------------
# Constructor de estructuras (spreads avanzados)
# ---------------------------------------------------------------------------

class SpreadBuilder:
    """Construye estructuras de opciones a partir de una señal direccional."""

    def __init__(self, feed: OptionFeed):
        self.feed = feed

    def _chain(self, underlying, otype, spot=None, dte_min=14, dte_max=60,):  # DTE parametrizable para el reto $100→$200
        today = date.today()
        chain = self.feed.contracts(
            underlying, otype,
            expiration_ge=today + timedelta(days=dte_min),
            expiration_le=today + timedelta(days=dte_max),
        )
        chain = [c for c in chain if dte_min <= (c.expiration - today).days <= dte_max]
        # spot de referencia: el más cercano al delta long (para calls, strike
        # entre long y short; para puts, equivalente). Si no se pasa, se usa
        # el strike del primer candidato ITM/ATM.
        if spot is None and chain:
            try:
                chain = self.feed.snapshots(chain)
            except Exception:  # noqa: BLE001
                pass
            ref = [c for c in chain if (c.delta or 0) >= 0.45 and c.mid > 0.05]
            spot = ref[0].strike if ref else chain[0].strike
        return self.feed.snapshots(chain), spot

    def long_call(self, underlying, spot, delta=0.30) -> OptionStructure:
        chain, _ = self._chain(underlying, OptionType.CALL, spot)
        sel = select_strikes(chain, spot, delta_target=delta)
        if not sel:
            raise RuntimeError(f"No hay calls con delta ~{delta} para {underlying}")
        c = sel[0]
        return OptionStructure(
            f"long_call_{underlying}_{c.strike}",
            [Leg(c, +1)], underlying,
            rationale=f"Long call delta {_f(c.delta)}, IV {_f_pct(c.iv)}",
            max_risk=abs(c.mid) * c.multiplier,
        )

    def vertical_spread(self, underlying, spot=None, direction: str = "bull",
                        delta_long=0.40, delta_short=0.20,
                        dte_min=14, dte_max=60) -> OptionStructure:
        """Call spread alcista o put spread bajista."""
        otype = OptionType.CALL if direction == "bull" else OptionType.PUT
        chain, _ = self._chain(underlying, otype, spot, dte_min=dte_min,
                               dte_max=dte_max)
        long_leg = select_strikes(chain, spot, delta_target=delta_long)
        if not long_leg:
            raise RuntimeError(f"No hay strikes suficientes para spread en {underlying}")
        # Ambas patas DEBEN compartir la misma expiración (riesgo definido):
        # fijar la cadena a la expiración de la pata long y re-seleccionar short.
        l = long_leg[0]
        same_exp = [c for c in chain if c.expiration == l.expiration
                    and c.option_type == otype]
        short_leg = select_strikes(same_exp, spot, delta_target=delta_short)
        if not short_leg:
            raise RuntimeError(f"No hay strike short en exp {l.expiration} "
                               f"para spread en {underlying}")
        s = short_leg[0]
        # Asegurar que el short está estrictamente más OTM que el long,
        # aunque ambos targets resuelvan al mismo strike o se crucen.
        # IMPORTANTE: buscar SOLO dentro de la misma expiración del long.
        chain_by_strike = sorted(same_exp, key=lambda c: c.strike)
        if direction == "bull":
            while s is not None and s.strike <= l.strike:
                above = [c for c in chain_by_strike if c.strike > s.strike
                         and c.mid > 0.05]
                s = above[0] if above else None
            if s is None:
                raise RuntimeError("No hay strike short por encima del long (call spread)")
        else:
            while s is not None and s.strike >= l.strike:
                below = [c for c in chain_by_strike if c.strike < s.strike
                         and c.mid > 0.05]
                s = below[-1] if below else None
            if s is None:
                raise RuntimeError("No hay strike short por debajo del long (put spread)")
        net = l.mid - s.mid
        max_risk = abs(net) * l.multiplier
        width = abs(s.strike - l.strike) * l.multiplier
        max_profit = width - max_risk if direction == "bull" else width - max_risk
        return OptionStructure(
            f"{'call' if direction == 'bull' else 'put'}_spread_{underlying}_{l.strike}_{s.strike}",
            [Leg(l, +1), Leg(s, -1)], underlying,
            rationale=(f"{direction} spread: long delta {_f(l.delta)} @ {l.strike}, "
                       f"short delta {_f(s.delta)} @ {s.strike}, "
                       f"IV {_f_pct(l.iv)}/{_f_pct(s.iv)}"),
            max_risk=max_risk, max_profit=max_profit,
            breakevens=[l.strike + (s.mid - l.mid)],
        )

    def vertical_spread_from(self, pos: dict) -> OptionStructure:
        """Reconstruye la estructura de una posición abierta desde su registro
        guardado (pos: {symbol, structure, net_premium, max_risk}).
        Intenta en orden: (a) strikes codificados en el nombre de la
        estructura (p. ej. call_spread_AAPL_125.0_130.0); (b) re-escaneo de la
        cadena para recuperar los strikes originales y su prima actual."""
        name, sym = pos.get("structure", ""), pos["symbol"]
        strikes = [float(x) for x in name.split("_")[-2:]
                   if x.replace(".", "").isdigit()]
        otype = OptionType.CALL if "call" in name else OptionType.PUT
        direction = "bull" if "call" in name else "bear"
        try:
            # No aplicar dte_min=14 al reconstruir: una posición viva puede
            # haber envejecido por debajo de ese umbral.
            chain, spot = self._chain(sym, otype, dte_min=0, dte_max=365)
        except RuntimeError as err:
            raise RuntimeError(f"No se pudo reconstruir cadena de {sym}") from err

        persisted = pos.get("legs") or []
        if persisted:
            by_symbol = {c.symbol: c for c in chain}
            legs = []
            for spec in persisted:
                c = by_symbol.get(spec.get("symbol"))
                if c is None:
                    break
                side = spec.get("side", "buy")
                legs.append(Leg(c, +1 if side == "buy" else -1))
            if len(legs) == len(persisted):
                net = sum(l.contract.mid * l.quantity for l in legs)
                return OptionStructure(
                    name, legs, sym,
                    rationale="reconstruida por símbolos persistidos",
                    max_risk=abs(net) * 100)

        if len(strikes) == 2:
            legs = []
            for s in strikes:
                cands = [c for c in chain if abs(c.strike - s) < 0.01
                         and c.option_type == otype]
                if not cands:
                    raise RuntimeError(f"Strike {s} no encontrado en {sym}")
                legs.append(Leg(cands[0], +1 if len(legs) == 0 else -1))
            net = legs[0].contract.mid - legs[1].contract.mid
            return OptionStructure(
                name, legs, sym,
                rationale=f"reconstruida: {direction} spread {strikes[0]}/{strikes[1]}",
                max_risk=abs(net) * 100)
        raise RuntimeError(f"No se pudieron recuperar strikes de {name}")

    def iron_condor(self, underlying, spot,
                    delta_short=0.20, delta_long=0.05) -> OptionStructure:
        """Iron condor: put spread OTM bajista + call spread OTM alcista."""
        put_c, _ = self._chain(underlying, OptionType.PUT, spot)
        call_c, _ = self._chain(underlying, OptionType.CALL, spot)
        ps = select_strikes(put_c, spot, delta_target=-delta_short)
        pl = select_strikes(put_c, spot, delta_target=-delta_long)
        cs = select_strikes(call_c, spot, delta_target=delta_short)
        cl = select_strikes(call_c, spot, delta_target=delta_long)
        if not all([ps, pl, cs, cl]):
            raise RuntimeError(f"Strikes insuficientes para iron condor en {underlying}")
        legs = [Leg(ps[0], -1), Leg(pl[0], +1), Leg(cs[0], -1), Leg(cl[0], +1)]
        net = sum(l.net_premium for l in legs)
        width = (min(cs[0].strike, ps[0].strike) - max(pl[0].strike, cs[0].strike)) * 100
        return OptionStructure(
            f"iron_condor_{underlying}", legs, underlying,
            rationale="Iron condor delta-neutral: cobra prima, gana si el subyacente "
                      "se queda en el rango entre los strikes vendidos",
            max_risk=abs(net) + abs(width), max_profit=abs(net),
        )
