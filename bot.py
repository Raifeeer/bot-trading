"""Bot de trading en vivo: loop principal.

Flujo por tick (cada barra nueva o por sondeo cada N minutos):
  1. Actualizar datos del universo (barras nuevas)
  2. Verificar circuit breakers del risk manager
  3. Escanear estrategias de subyacente → señales
  4. Para señales nuevas: construir estructura de opciones y pedir aprobación
     del risk manager (riesgo por estructura)
  5. Ejecutar órdenes en Alpaca (paper/real, o dry-run)
  6. Gestionar posiciones abiertas (reglas de gestión de prima / DTE)
  7. Persistir estado y publicar eventos para el dashboard

Uso:
  APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python bot.py [--dry-run]
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Logging primero: así las excepciones de los imports de abajo sí se registran
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger("bot")
logger.info("BOOT: logging configured")

DEFAULT_DEFINED_RISK_SHADOW_CFG = {
    "enabled": True,
    "mode": "shadow",
    "influence_entries": False,
    "orders_allowed": False,
    "max_symbols": 8,
    "max_spread_bps": 800.0,
}

from config import get_config
from data.feed import MarketDataFeed

try:
    from state.firestore_state import (write_state_snapshot,
                                      append_equity_point,
                                      read_last_equity,
                                      read_challenge_armed)
    FIRESTORE_ENABLED = True
except Exception:  # noqa: BLE001
    logger.exception("Firestore NO disponible (import de state.firestore_state falló)")
    FIRESTORE_ENABLED = False
from strategies.day_trading import DayMomentum, DayBreakout
try:
    from state.telegram_notify import (notify_position_open,
                                       notify_position_close,
                                       notify_risk_halt)
except ImportError:
    def notify_position_open(*a, **k):
        return False

    def notify_position_close(*a, **k):
        return False

    def notify_risk_halt(*a, **k):
        return False
try:
    from state.telegram_bot import (update_state as _tg_update_state,
                                    start_tg_bot)
except ImportError:
    def _tg_update_state(_s):
        pass

    def start_tg_bot():
        import threading
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t
from strategies.swing_trading import SwingTrend
from options.chains import OptionFeed, SpreadBuilder
from options.strategy import OptionsStrategy
from options.option_details import enrich_positions
from risk.manager import RiskManager
from execution.alpaca_executor import AlpacaExecutor, ExecutionError
from strategies.setup_confluence import SETUP_NAMES, analyze_setup_confluence
from options.defined_risk_shadow import evaluate_defined_risk_shadow
logger.info("BOOT: imports complete")


def _latest_bar_key(data: dict) -> str:
    """Devuelve una clave estable de la última barra disponible."""
    return max(
        (str(df.index[-1]) for df in data.values()
         if df is not None and not df.empty),
        default="unknown",
    )


def _entry_context_key(data: dict, regime: dict) -> str:
    """Identifica barra cerrada + régimen + estado del piso para entradas."""
    regime_name = (regime or {}).get("regime", "unknown")
    floor_below = bool((regime or {}).get("floor", {}).get("below_floor"))
    return f"{_latest_bar_key(data)}|{regime_name}|floor={floor_below}"


def _setup_shadow_snapshot(cached: dict, tickers: list[str], setup_cfg: dict) -> dict:
    """Evalúa todos los setups sobre barras cerradas sin enviar órdenes.

    `cached` tiene la forma timeframe -> símbolo -> DataFrame. La función
    reemplaza el snapshot anterior, no acumula histórico en el estado local.
    ``influence_entries`` se registra como configuración, pero no concede
    autoridad a la capa: el RiskManager y las estrategias existentes siguen
    siendo la única ruta de órdenes hasta una promoción explícita.
    """
    if not setup_cfg.get("enabled", False):
        return {"enabled": False, "mode": "disabled", "symbols": {}}
    by_symbol = {}
    for symbol in tickers:
        frames = {
            tf: symbol_data[symbol]
            for tf, symbol_data in cached.items()
            if isinstance(symbol_data, dict) and symbol in symbol_data
        }
        result = analyze_setup_confluence(symbol, frames)
        by_symbol[symbol] = result
    counts = {
        setup: {"bull": 0, "bear": 0, "neutral": 0, "confirmed": 0}
        for setup in (*SETUP_NAMES, "mtf_confluence")
    }
    for result in by_symbol.values():
        for observation in result.get("observations", []):
            setup = observation.get("setup")
            if setup not in counts:
                continue
            direction = observation.get("direction", "neutral")
            status = observation.get("status", "neutral")
            counts[setup][direction] = counts[setup].get(direction, 0) + 1
            if status == "confirmed":
                counts[setup]["confirmed"] += 1
    return {
        "enabled": True,
        "mode": setup_cfg.get("mode", "shadow"),
        "influence_entries": bool(setup_cfg.get("influence_entries", False)),
        "source_version": "setup-confluence-v1",
        "counts": counts,
        "symbols": by_symbol,
    }


def _defined_risk_shadow_snapshot(cached: dict, tickers: list[str], regime: dict, state: dict, builder: SpreadBuilder, shadow_cfg: dict) -> dict:
    """Evalúa spreads candidatos sin crear órdenes ni cambiar decisiones.

    Se deduplica por la última barra diaria disponible, régimen y estado del
    piso: las cadenas no se vuelven a consultar cada minuto, pero la señal se
    renueva al cambiar el contexto de mercado. El resultado conserva siempre
    ``orders_allowed=False`` y ``influence_entries=False``.
    """
    if not shadow_cfg.get("enabled", False):
        return {"enabled": False, "mode": "disabled", "orders_allowed": False, "symbols": {}}
    daily = cached.get("1d") or {}
    context_data = daily if daily else cached.get("15min", {}) or cached.get("5min", {}) or {}
    context = f"{_latest_bar_key(context_data)}|{(regime or {}).get('regime', 'unknown')}|floor={(regime or {}).get('floor', {}).get('below_floor', False)}"
    previous = state.get("defined_risk_shadow_observations")
    if state.get("_defined_risk_shadow_context") == context and previous:
        return previous
    ticker_frames = {}
    for symbol in tickers:
        ticker_frames[symbol] = {
            timeframe: symbol_data[symbol]
            for timeframe, symbol_data in cached.items()
            if isinstance(symbol_data, dict) and symbol in symbol_data
        }
    snapshot = evaluate_defined_risk_shadow(
        builder.feed,
        ticker_frames,
        (regime or {}).get("regime", "cash"),
        bool((regime or {}).get("floor", {}).get("below_floor")),
        shadow_cfg,
    )
    snapshot["context_key"] = context
    state["_defined_risk_shadow_context"] = context
    return snapshot


def _enriched_positions(executor: AlpacaExecutor) -> list:
    """Piernas crudas de Alpaca enriquecidas con option_details (DTE, greeks).

    Nunca bloquea el tick: si el enriquecimiento falla, devuelve las piernas
    tal cual salieron del executor."""
    try:
        if executor.dry_run:
            return []
        legs = _positions_with_timeout(executor)
        try:
            from data.feed import MarketDataFeed
            feed = MarketDataFeed(executor.cfg)
        except Exception:  # noqa: BLE001
            feed = None
        return enrich_positions(legs, feed=feed)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo enriqueciendo posiciones (publicando crudas)")
        try:
            return _positions_with_timeout(executor)
        except Exception:  # noqa: BLE001
            return []


def key_if_any(executor: AlpacaExecutor) -> bool:
    """True si el executor tiene credenciales reales configuradas."""
    key = os.environ.get("APCA_API_KEY_ID") or executor.cfg["broker"].get("api_key")
    secret = os.environ.get("APCA_API_SECRET_KEY") or executor.cfg["broker"].get("secret_key")
    return bool(key and secret)

STATE_FILE = "data/bot_state.json"


def _call_with_timeout(fn, timeout_s: float, label: str):
    """Ejecuta una llamada externa en hilo daemon con timeout duro."""
    result, error = {}, {}

    def _run():
        try:
            result["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            error["exc"] = exc

    t = threading.Thread(target=_run, daemon=True, name=f"timeout-{label}")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"{label} no respondió en {timeout_s:.0f}s")
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def _positions_with_timeout(executor: AlpacaExecutor, timeout_s: float = 30.0) -> list:
    """Lee posiciones de Alpaca sin bloquear el proceso principal indefinidamente."""
    return _call_with_timeout(executor.positions, timeout_s, "Alpaca positions")


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, default=str)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"positions": [], "decisions": [], "orders": []}


def reconcile_positions_with_broker(executor: AlpacaExecutor, state: dict) -> int:
    """Reconstruye en `state["positions"]` los spreads abiertos en Alpaca que
    el estado local desconoce.

    `data/bot_state.json` vive en el filesystem efímero del contenedor: un
    redeploy, un reinicio de instancia o que Cloud Run levante una instancia
    nueva lo resetean a cero, mientras que las posiciones siguen abiertas en
    Alpaca (fuente de verdad del broker). Sin esta reconciliación el bot
    queda ciego a esas posiciones: no evalúa su TP/SL/DTE y no las cuenta
    para el límite de `max_open_positions`. Se ejecuta una vez al arrancar.
    Devuelve el número de posiciones reconstruidas.
    """
    from options.option_details import parse_occ
    try:
        legs = _positions_with_timeout(executor)
    except TimeoutError as exc:
        logger.error("Reconciliación: %s; se continúa sin reconstrucción", exc)
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("Reconciliación: no se pudo leer posiciones de Alpaca")
        return 0
    legs = [leg for leg in legs if leg.get("asset_class") == "us_option"]
    if not legs:
        return 0

    known_symbols = {
        spec.get("symbol")
        for pos in state["positions"]
        for spec in (pos.get("legs") or [])
    }
    unknown = [leg for leg in legs if leg["symbol"] not in known_symbols]
    if not unknown:
        return 0

    by_underlying = {}
    for leg in unknown:
        occ = parse_occ(leg["symbol"])
        if occ is None:
            continue
        by_underlying.setdefault(occ["underlying"], []).append((leg, occ))

    reconstructed = 0
    for underlying, group in by_underlying.items():
        # Solo se reconstruyen verticales de 2 patas (long + short, mismo
        # tipo y vencimiento): es la única estructura que abre este bot hoy.
        # Otras formas quedan sin reconstruir y se registran en el log para
        # revisión manual, en vez de adivinar una estructura incorrecta.
        by_exp_type = {}
        for leg, occ in group:
            key = (occ["expiration_date"], occ["option_type"])
            by_exp_type.setdefault(key, []).append((leg, occ))
        for (exp, otype), pair in by_exp_type.items():
            if len(pair) != 2:
                logger.warning(
                    "Reconciliación: %s %s %s no forma un vertical de 2 patas "
                    "(%d patas encontradas); no se reconstruye automáticamente",
                    underlying, exp, otype, len(pair))
                continue
            (leg_a, occ_a), (leg_b, occ_b) = pair
            long_leg, short_leg = ((leg_a, occ_a), (leg_b, occ_b)) \
                if leg_a["qty"] > 0 else ((leg_b, occ_b), (leg_a, occ_a))
            if long_leg[0]["qty"] <= 0 or short_leg[0]["qty"] >= 0:
                logger.warning(
                    "Reconciliación: %s %s %s no tiene una pata long y otra "
                    "short claras; no se reconstruye automáticamente",
                    underlying, exp, otype)
                continue
            direction = "call" if otype == "CALL" else "put"
            structure = (f"{direction}_spread_{underlying}_"
                        f"{long_leg[1]['strike']}_{short_leg[1]['strike']}")
            net_premium = float(long_leg[0]["avg_entry"]) - float(short_leg[0]["avg_entry"])
            state["positions"].append({
                "symbol": underlying,
                "strategy": "reconciled_broker",
                "kind": "put" if otype == "PUT" else "call",
                "structure": structure,
                "net_premium": net_premium,
                "max_risk": abs(net_premium) * 100,
                "legs": [
                    {"symbol": long_leg[0]["symbol"], "side": "buy",
                     "qty": abs(int(long_leg[0]["qty"]))},
                    {"symbol": short_leg[0]["symbol"], "side": "sell",
                     "qty": abs(int(short_leg[0]["qty"]))},
                ],
                "entry_orders": [],
                "entry_ts": datetime.utcnow().isoformat(),
                "reconciled": True,
            })
            reconstructed += 1
            logger.warning(
                "Reconciliación: reconstruida posición %s (%s) desde Alpaca; "
                "no estaba en el estado local del bot", underlying, structure)
    return reconstructed


def bear_entry_candidates(regime: dict, state: dict, cfg: dict) -> list:
    """Subyacentes con CHoCH bajista aptos para abrir un put spread.

    Solo actúa cuando el régimen NO es bull: es el hueco que dejaba el bot
    long-only (en bear se quedaba quieto). Excluye lo que ya está en cartera
    y respeta el límite propio del motor bajista.
    """
    b = options_bear_cfg(cfg)
    # SOLO en régimen "bear" (>=30% del universo con CHoCH, o crash_event), no
    # en cualquier cosa que no sea bull. El régimen "cash" (lateral y bear
    # SUAVE bajo SMA200 sin CHoCH) tiene prohibido operar defensivas por
    # docs/skills/wheel_skill.md §3: ahí la volatilidad realizada infla el
    # precio de los put spreads y las defensivas perdieron (S75 -32.9%,
    # S76 -6.6%) mientras que quedarse en cash gano (+26.7%, S78).
    if not b["enabled"] or regime.get("regime") != "bear":
        return []
    abiertos = {p["symbol"] for p in state.get("positions", [])}
    n_puts = sum(
        1 for p in state.get("positions", [])
        if p.get("kind") == "put"
        or "put" in str(p.get("structure", "")).lower()
    )
    if n_puts >= b["max_positions"]:
        return []
    cupo = b["max_positions"] - n_puts
    ts = regime.get("ticker_status") or {}
    return [sym for sym, st in ts.items()
            if st.get("bear_choch") and sym not in abiertos][:cupo]


def recovery_sizing(equity: float, floor_res: dict, cfg: dict) -> dict:
    """Tamaño permitido según la fase del piso (ver risk/floor.py).

    FASE `recuperacion` (equity < $100k, reto sin armar): el bot calcula una
    prima objetivo para volver a $100,000, pero el número de contratos se
    limita antes de enviar órdenes al presupuesto seguro de recuperación: el
    menor entre `max_risk_per_trade_pct` y `max_daily_loss_usd`. La prima
    objetivo sirve para priorizar el tamaño, no para saltarse los breakers.

    FASE `reto` (reto armado): vuelve al estado regular — tope de prima de
    config y 1 contrato. La transición es automática vía el latch del piso,
    sin intervención ni fecha que recordar.

    Devuelve {"unlimited": bool, "target_premium": float|None,
              "max_premium_net": float|None}.
    """
    reto_cfg = ((cfg.get("universo", {}) or {}).get("options_reto") or {})
    cap_regular = float(reto_cfg.get("max_premium_net", 0.50))
    if (floor_res or {}).get("phase") != "recuperacion":
        return dict(unlimited=False, target_premium=None,
                    max_premium_net=cap_regular)

    objetivo = float((floor_res or {}).get("target") or 100_000.0)
    brecha = max(0.0, objetivo - float(equity))
    tp_mult = float(premium_exit_cfg(cfg)["tp_mult"])
    ganancia_pct = max(tp_mult - 1.0, 0.01)
    target = brecha / ganancia_pct if brecha > 0 else 0.0
    return dict(unlimited=True, target_premium=target,
                max_premium_net=None)


def contracts_for_target(structure, target_premium: float,
                         cash_disponible: float,
                         max_premium_total: float | None = None) -> int:
    """Nº de contratos objetivo con caja y presupuesto de riesgo acotados.

    Devuelve 0 cuando ni un contrato cabe en el presupuesto seguro; el
    llamador debe descartar la entrada antes de enviar ninguna pata. En
    recuperación, ``max_premium_total`` limita una pérdida única al menor
    entre el riesgo por operación y el breaker diario absoluto.
    """
    prima_uno = abs(float(structure.net_premium))
    if prima_uno <= 0:
        return 0
    presupuesto = max(0.0, float(cash_disponible))
    if max_premium_total is not None:
        presupuesto = min(presupuesto, max(0.0, float(max_premium_total)))
    n_budget = int(presupuesto // prima_uno)
    if n_budget < 1:
        return 0
    n_objetivo = int(target_premium // prima_uno) if target_premium > 0 else 1
    return min(max(n_objetivo, 1), n_budget)


def recovery_risk_budget(equity: float, cfg: dict) -> float:
    """Presupuesto máximo de prima para una única entrada de recuperación."""
    risk_cfg = cfg.get("risk", {}) or {}
    pct = max(0.0, float(risk_cfg.get("max_risk_per_trade_pct", 0.0)))
    by_trade = float(equity) * pct / 100.0
    daily = risk_cfg.get("max_daily_loss_usd")
    if daily is None:
        return max(0.0, by_trade)
    return max(0.0, min(by_trade, float(daily)))


def _option_order_specs(structure, cfg, closing=False, contracts: int = 1):
    """Prepara órdenes por pata con una cotización válida y precio límite.

    Alpaca no acepta limit orders de opciones a 0.0. Se prevalidan todas las
    patas antes de enviar la primera para no dejar un spread parcialmente
    ejecutado por una cotización ausente.
    """
    execution = cfg.get("execution", {}) or {}
    order_type = execution.get("order_type", "limit")
    offset_pct = float(execution.get("limit_offset_pct", 0.0)) / 100.0
    specs = []
    for leg in structure.legs:
        side = "buy" if leg.quantity > 0 else "sell"
        if closing:
            side = "sell" if side == "buy" else "buy"
        contract = leg.contract
        quote = contract.ask if side == "buy" else contract.bid
        if quote is None or float(quote) <= 0:
            quote = contract.mid or contract.last
        if order_type == "limit":
            if quote is None or float(quote) <= 0:
                raise ExecutionError(
                    f"Sin cotización válida para {contract.symbol} al {side}")
            factor = 1.0 + offset_pct if side == "buy" else 1.0 - offset_pct
            limit_price = max(0.01, round(float(quote) * factor, 2))
        else:
            limit_price = None
        specs.append({
            "symbol": contract.symbol,
            "side": side,
            # `contracts` escala las dos patas por igual: el spread mantiene
            # su ratio 1:1 y por tanto el riesgo definido. En fase de reto
            # vale 1 (comportamiento histórico).
            "qty": abs(int(leg.quantity)) * max(1, int(contracts)),
            "order_type": order_type,
            "limit_price": limit_price,
        })
    return specs


# ---------------------------------------------------------------------------
# Gestión de posiciones abiertas
# ---------------------------------------------------------------------------

def strat_by_name(name):
    """Referencia global a las estrategias para poder resetear el cooldown."""
    return _STRATS.get(name)

_STRATS = {}


def trading_mode(dry_run: bool = False) -> str:
    """Devuelve el modo operativo en texto para las alertas."""
    if dry_run:
        return "DRY-RUN"
    base = os.environ.get("APCA_API_BASE_URL", "")
    return "PAPER" if "paper" in base else "REAL"


def _regime_snapshot(feed, tickers, state, equity_now: float,
                     cfg_risk: dict) -> dict:
    """Clasifica el régimen global S78 (bull/bear/cash) con los contadores
    validados en los backtests (hallazgo16/hallazgo17) + defensas:
    crash_event 3% (cool-down 5 días) e intraday_cuts del 4% (hallazgo18).
    El crash_lock persiste en state para sobrevivir reinicios.
    Devuelve el dict de risk.regime con 'below_floor' aplicado."""
    from risk.regime import classify_regime, apply_crash_cooldown
    from risk.floor import check_floor
    # 210 días cubre el SMA200 + margen; las descargas 1d ya traen 100,
    # pedir 210 aquí solo en el análisis de régimen (descarga adicional
    # barata: yfinance la cachea por ticker y timeframe).
    data_1d = feed.history(tickers, "1d", days=400) or {}
    regime = classify_regime(data_1d, tickers, cfg=cfg_risk)
    regime = apply_crash_cooldown(regime, state)
    floor_res = check_floor(float(equity_now), state, cfg=cfg_risk)
    regime["floor"] = floor_res
    return regime


def _manage_open_position(feed, builder, strat, pos):
    """Evalúa si la posición abierta debe cerrarse. Devuelve (signal_type o
    None, razón). Usa evaluate_exit de options.strategy con la prima actual."""
    from options.strategy import evaluate_exit, OptionsPosition
    spot = feed.history([pos["symbol"]], "1d", days=2)[pos["symbol"]]["close"].iloc[-1]
    entry_premium = abs(pos["net_premium"])
    # Reconstruir la estructura con los strikes guardados en el spread
    st = builder.vertical_spread_from(pos)
    contracts = [leg.contract for leg in st.legs]
    contracts = builder.feed.snapshots(contracts, spot)
    # Guarda: si alguna pata no tiene cotización válida, no evaluar salida
    # con datos ausentes (evaluate_exit usa st.net_premium, que cae a 0.0
    # sin bid/ask/last y dispararía un TP/SL falso).
    for leg in st.legs:
        c = leg.contract
        if c.last is None and (c.bid is None or c.ask is None):
            return None, ""
    if entry_premium <= 0:
        entry_premium = 1e-9
    # Recalcular días al vencimiento (usar la expiración de la pata short/lejana)
    exps = sorted(l.contract.expiration for l in st.legs)
    dte = (exps[-1] - datetime.utcnow().date()).days if exps else 30
    op = OptionsPosition(st, entry_premium, datetime.utcnow())
    cfg_ = get_config()
    pec = exit_cfg_for_position(pos, cfg_)
    reason = evaluate_exit(st, op, dte, spot,
                           tp_mult=pec["tp_mult"], sl_mult=pec["sl_mult"],
                           close_dte=pec["close_dte"])
    if reason:
        return "EXIT", reason
    return None, ""


def strat_structure_for(pos, strat=None, builder=None):
    """Reconstruye una posición; sobrevive a reinicios/config changes.

    Las patas guardadas en `pos` son preferibles. Si la estrategia original ya
    no está habilitada, se usa el `builder` global del loop.
    """
    active_builder = getattr(strat, "builder", None) or builder
    if active_builder is None:
        raise RuntimeError(f"Sin builder para reconstruir {pos.get('symbol')}")
    return active_builder.vertical_spread_from(pos)

def options_map_cfg(cfg):
    """Parámetros de estructura del PERFIL RETO ($100→$200). Si el perfil está
    activo en config, sobreescribe dirección, deltas, prima máxima y rango
    DTE que usa OptionsStrategy para construir los spreads."""
    uni = cfg.get("universo", {}) or {}
    reto = uni.get("options_reto") or {}
    if not reto:
        return {"direction": "bull"}
    return dict(
        direction=reto.get("direction", "bull"),
        delta_long=reto.get("delta_long", 0.30),
        delta_short=reto.get("delta_short", 0.15),
        max_premium_net=reto.get("max_premium_net", 0.50),
        dte_min=reto.get("dte_min", 14),
        dte_max=reto.get("dte_max", 60),
    )

def options_bear_cfg(cfg):
    """Parámetros del motor bajista (put spreads sobre CHoCH bear).

    Validado en la ronda 5 (AGENTS.md §40): `put_choch` con tp1.5/sl0.5 y
    prima >= $100 da 75% de ventanas bajistas en positivo (mediana +6.8%) y
    bate al cash (-1.3%). Los dos umbrales son parte del resultado, no
    preferencias: por debajo de $100 de prima las 4 comisiones del spread se
    comen la ventaja, y con el tp1.4/sl0.25 de los calls nunca cruza.
    """
    uni = (cfg.get("universo", {}) or {}).get("options_bear") or {}
    return dict(
        enabled=bool(uni.get("enabled", False)),
        delta_long=float(uni.get("delta_long", 0.30)),
        delta_short=float(uni.get("delta_short", 0.10)),
        dte_min=int(uni.get("dte_min", 14)),
        dte_max=int(uni.get("dte_max", 35)),
        min_premium_net=float(uni.get("min_premium_net", 100.0)),
        tp_mult=float(uni.get("tp_premium_mult", 1.5)),
        sl_mult=float(uni.get("sl_premium_mult", 0.50)),
        close_dte=int(uni.get("close_dte", 7)),
        max_positions=int(uni.get("max_positions", 2)),
    )


def exit_cfg_for_position(pos: dict, cfg: dict) -> dict:
    """Multiplicadores de salida SEGÚN EL TIPO de posición.

    Los calls y los puts necesitan salidas distintas y no es un detalle: en la
    ronda 5, `put_choch` con el tp1.4/sl0.25 de los calls nunca alcanza
    ventaja, y con tp1.5/sl0.5 sí. Aplicar la misma salida a ambos anularía
    el motor bajista.
    """
    es_put = (pos.get("kind") == "put"
              or "put" in str(pos.get("structure", "")).lower())
    if es_put:
        b = options_bear_cfg(cfg)
        return dict(tp_mult=b["tp_mult"], sl_mult=b["sl_mult"],
                    close_dte=b["close_dte"])
    return premium_exit_cfg(cfg)


def premium_exit_cfg(cfg):
    """Multiplicadores de gestión de prima por posición (reto $100→$200):
    tp_mult en prima para el take profit y sl_mult para el stop. Los defaults
    (+50% / -85%) se mantienen si el config no define valores de reto."""
    uni = (cfg.get("universo", {}) or {}).get("options_reto") or {}
    risk = cfg.get("risk", {}) or {}
    return dict(
        tp_mult=uni.get("tp_premium_mult", risk.get("prem_tp_mult", 1.5)),
        sl_mult=uni.get("sl_premium_mult", risk.get("prem_sl_mult", 0.15)),
        close_dte=uni.get("close_dte", 7),
    )

def build_strategies(cfg, spread_builder):
    strats = {}
    map_cfg = options_map_cfg(cfg)
    if cfg["strategies"]["day_momentum"]["enabled"]:
        strats["opt_day_momentum"] = OptionsStrategy(
            DayMomentum(cfg["strategies"]["day_momentum"]["params"]),
            spread_builder, map_cfg)
    if cfg["strategies"]["day_breakout"]["enabled"]:
        strats["opt_day_breakout"] = OptionsStrategy(
            DayBreakout(cfg["strategies"]["day_breakout"]["params"]),
            spread_builder, map_cfg)
    if cfg["strategies"]["swing_trend"]["enabled"]:
        strats["opt_swing_trend"] = OptionsStrategy(
            SwingTrend(cfg["strategies"]["swing_trend"]["params"]),
            spread_builder, map_cfg)
    global _STRATS
    _STRATS = dict(strats)
    return strats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--poll-minutes", type=float, default=None,
        help="Compatibilidad: intervalo completo en minutos; sobrescribe poll-seconds",
    )
    parser.add_argument(
        "--poll-seconds", type=float,
        default=float(os.environ.get("POLL_SECONDS", "60")),
        help="Intervalo entre ciclos completos; mínimo seguro 15 s",
    )
    args = parser.parse_args()
    if args.poll_minutes is not None:
        args.poll_seconds = args.poll_minutes * 60.0
    args.poll_seconds = max(15.0, float(args.poll_seconds))

    logger.info("BOOT: entering main")
    cfg = get_config()
    logger.info("BOOT: config loaded")
    risk_shadow_boot_cfg = dict(DEFAULT_DEFINED_RISK_SHADOW_CFG)
    risk_shadow_boot_cfg.update(cfg.get("defined_risk_shadow", {}) or {})
    logger.info(
        "BOOT: defined-risk shadow enabled=%s mode=%s influence_entries=%s orders_allowed=%s",
        risk_shadow_boot_cfg["enabled"], risk_shadow_boot_cfg["mode"],
        risk_shadow_boot_cfg["influence_entries"], False)
    feed = MarketDataFeed(cfg["data"]["provider"])
    rm = RiskManager(cfg["risk"])
    executor = AlpacaExecutor(dry_run=args.dry_run)
    logger.info("BOOT: executor created")
    start_tg_bot()
    logger.info("BOOT: Telegram thread requested")
    try:
        _call_with_timeout(executor.connect, 45.0, "Alpaca connect")
        account = _call_with_timeout(executor.account_snapshot, 30.0,
                                    "Alpaca account snapshot")
        equity0 = float(account["equity"])
        logger.info("BOOT: Alpaca connected and account snapshot loaded")
    except (ExecutionError, TimeoutError) as e:
        if not args.dry_run:
            raise ExecutionError(f"Alpaca no disponible: {e}") from e
        # dry-run sin credenciales: capital simulado desde configuración
        equity0 = float(os.environ.get("BOT_START_CAPITAL", 100_000.0))
        logger.warning("Alpaca no configurado: %s · operación simulada con capital inicial %.0f", e, equity0)
    rm.capital = equity0
    rm.reset_day(equity0)

    no_alpaca = executor.dry_run and not key_if_any(executor)
    logger.info("BOOT: starting option feed and strategies")
    option_feed = OptionFeed(sim=no_alpaca)
    builder = SpreadBuilder(option_feed)
    strats = build_strategies(cfg, builder)
    logger.info("BOOT: strategies built")
    state = load_state()
    logger.info("BOOT: local state loaded")
    if FIRESTORE_ENABLED and ("_floor_below" not in state
                              or "_challenge_armed" not in state):
        # data/bot_state.json es efímero (se resetea en cada redeploy/reinicio
        # de instancia); sin esto el bot "olvida" si ya estaba bajo el piso y
        # puede reenviar "PISO ROTADO" espontáneamente aunque el equity no
        # haya cruzado nada de verdad (AGENTS.md §34).
        #
        # `_challenge_armed` es más delicado: es un latch de una sola dirección
        # (una vez tocados los $100k rige el piso del reto para siempre). Si se
        # perdiera en un redeploy, el bot volvería a modo recuperación —con un
        # piso más bajo— y el piso del reto dejaría de proteger. Se recupera de
        # Firestore, que sí es persistente.
        from risk.floor import active_floor
        floor_cfg = (cfg.get("risk", {}) or {}).get("floor", {})
        armed_prev = read_challenge_armed()
        if armed_prev is not None and "_challenge_armed" not in state:
            state["_challenge_armed"] = armed_prev
        logger.info("BOOT: reading persistent floor state")
        last_equity = read_last_equity()
        if last_equity is not None and "_floor_below" not in state:
            floor, phase, armed = active_floor(last_equity, state, floor_cfg)
            state["_floor_below"] = last_equity < floor
            logger.info(
                "Piso reconstruido desde Firestore: equity=%.2f fase=%s "
                "floor=%.2f reto_armado=%s below=%s",
                last_equity, phase, floor, armed, state["_floor_below"])
    if not no_alpaca:
        logger.info("BOOT: reconciling Alpaca positions")
        n_reconciled = reconcile_positions_with_broker(executor, state)
        if n_reconciled:
            logger.warning(
                "Reconciliación al arrancar: %d posición(es) reconstruida(s) "
                "desde Alpaca que no estaban en el estado local", n_reconciled)
            save_state(state)

    tickers = cfg["universo"]["tickers"]
    logger.info("Bot iniciado: %d estrategias, %d tickers, poll=%.0fs, dry_run=%s",
                len(strats), len(tickers), args.poll_seconds, args.dry_run)

    # Watchdog: si ningún tick completo en MAX_TICK_SECONDS, el proceso se
    # reinicia y Cloud Run recrea la instancia automáticamente.
    # El umbral es amplio a propósito (25 min): el primer tick tras un cold
    # start de Cloud Run tarda ~20-23 min (arranque Telegram + Alpaca + tres
    # descargas con fallback a yfinance por ticker). Los ticks regulares con
    # cache terminan en 5-7 min; si un tick excede 25 min el proceso está de
    # verdad colgado y el watchdog lo reinicia.
    _hb = {"ts": [time.time()]}
    def _watchdog():
        # Usar SIEMPRE os._exit(), nunca el exit() del módulo sys: el
        # watchdog corre en un hilo daemon secundario, y el exit() de sys
        # lanza SystemExit, que el excepthook por defecto de threading
        # ignora en silencio fuera del hilo principal (no termina el
        # proceso ni los demás hilos); comprobado en vivo el
        # 15 ago 2026: el bot quedó colgado 37s después del log CRITICAL de
        # "reiniciando el proceso", que en realidad no reiniciaba nada. Solo
        # os._exit() mata el proceso completo a nivel de SO sin importar qué
        # hilo lo invoque.
        while True:
            time.sleep(60)
            if time.time() - _hb["ts"][-1] > 1500:
                logger.critical("Watchdog: sin ticks completos en 25 min; "
                                "reiniciando el proceso")
                os._exit(1)
            # Hilo de Telegram: si no actualiza su heartbeat en 10 min
            # (p.ej. socket colgado esperando a DeepSeek), reiniciar el
            # proceso para recrear el hilo TG fresco.
            try:
                from state.telegram_bot import (tg_heartbeat_ts,
                                               TG_HB_TIMEOUT_S)
                if time.time() - tg_heartbeat_ts() > TG_HB_TIMEOUT_S:
                    logger.critical("Watchdog TG: hilo de Telegram congelado "
                                    "más de %.0f s; reiniciando el proceso",
                                    TG_HB_TIMEOUT_S)
                    os._exit(1)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()

    # Solo reevalúa entradas cuando cambia la barra cerrada o el contexto de
    # régimen/piso. La gestión de posiciones y el heartbeat siguen corriendo
    # cada ciclo. Esto evita duplicar señales/órdenes al bajar la cadencia a 1m.
    last_entry_context = {}
    cycle_id = 0

    while True:
        cycle_id += 1
        cycle_started = time.monotonic()
        phase_times = {}
        try:
            snap = _call_with_timeout(executor.account_snapshot, 30.0,
                                      "Alpaca account snapshot")
            equity = snap["equity"]
            rm.check_circuit_breakers(equity)
            if rm.is_halted():
                logger.critical("BOT DETENIDO por circuit breaker. Equity=%.2f", equity)
                try:
                    notify_risk_halt(f"Equity actual: ${equity:,.2f}")
                except Exception:  # noqa: BLE001
                    logger.exception("Fallo notificando halt de riesgo")
                time.sleep(600)
                continue

            # 0. RÉGIMEN S78 (S1-S89, hallazgos 16-18) + piso de equity:
            #    bull -> permitir entradas; bear/cash -> no entrar.
            #    crash_event -3% en >=30% del universo -> bear (cool-down 5d).
            #    intraday_cuts del 4% (hallazgo18) -> cierre de la posición
            #    de ese subyacente al gestionar (se evalúa abajo).
            try:
                regime = _regime_snapshot(feed, tickers, state, equity, cfg.get("risk", {}))
                state["regime"] = regime
                logger.info("RÉGIMEN %s", regime.get("summary", regime))
                if regime.get("floor", {}).get("crossed"):
                    notify_risk_halt(regime["floor"]["reason"])
                if regime["regime"] != "bull":
                    state["regime_lock"] = regime["regime"]
                else:
                    state.pop("regime_lock", None)
            except Exception:  # noqa: BLE001
                logger.exception("Fallo clasificando régimen; entradas "
                                 "permitidas solo si hay datos previos")
                regime = state.get("regime", {})

            # 0b. Tamaño permitido según la fase del piso. En `recuperacion`
            #     se levanta el tope de prima y se escala el nº de contratos
            #     para cerrar la brecha hasta $100k; al armarse el reto vuelve
            #     solo al comportamiento regular, sin fecha que recordar.
            sizing = recovery_sizing(equity, regime.get("floor") or {}, cfg)
            acct_cash = float(snap.get("cash") or equity)
            for _s in strats.values():
                if hasattr(_s, "cfg") and isinstance(_s.cfg, dict):
                    _s.cfg["max_premium_net"] = sizing["max_premium_net"]
            if sizing.get("unlimited"):
                logger.warning(
                    "FASE RECUPERACIÓN: objetivo %.2f, prima objetivo %.2f, "
                    "presupuesto seguro %.2f, caja %.2f, piso %.2f",
                    (regime.get("floor") or {}).get("target", 100_000.0),
                    sizing["target_premium"],
                    recovery_risk_budget(equity, cfg), acct_cash,
                    (regime.get("floor") or {}).get("floor", 99_000.0))

            # 1. datos con el timeframe propio de cada estrategia:
            #    swing usa 1d (210 días para SMA200+ATR); day usa 5m/15m
            tf_by_strat = {}
            for sname, strat in strats.items():
                tf = getattr(strat.base, "timeframe",
                             None) or getattr(strat, "timeframe", "1d")
                # 1d: 100 días basta para SMA200 + ATR14 (no hace falta 210);
                # reduce el tiempo de descarga en un ~50%.
                days = 100 if tf == "1d" else (10 if tf == "15min" else 5)
                tf_by_strat[sname] = (tf, days)
            cached = {}
            failed_tfs = []
            signal_stats = {
                "cycle_id": cycle_id,
                "poll_seconds": args.poll_seconds,
                "scanned": 0,
                "tradable": 0,
                "bull_gate": 0,
                "approved": 0,
                "orders": 0,
                "bear_candidates": 0,
                "by_strategy": {},
                "by_symbol": {},
            }
            for sname, strat in strats.items():
                tf, days = tf_by_strat[sname]
                if tf not in cached:
                    d = feed.history(tickers, tf, days=days)
                    cached[tf] = d
                    if d:
                        logger.info("Datos %s: %d tickers (%d barras)", tf,
                                    len(d), len(next(iter(d.values()))))
                    else:
                        # Sin ese timeframe: no matar el tick; el resto de
                        # estrategias con otros timeframes sí pueden operar
                        # y este timeframe se reintenta en el siguiente ciclo.
                        logger.error("Sin datos %s; tick continúa sin él", tf)
                        failed_tfs.append(tf)
                data = cached[tf]
                if not data or tf in failed_tfs:
                    continue
                strat_diag = signal_stats["by_strategy"].setdefault(
                    sname, {"timeframe": tf, "scanned": 0,
                            "tradable": 0, "reasons": {}})
                entry_context = _entry_context_key(data, regime)
                if last_entry_context.get(sname) == entry_context:
                    reason = "same_bar_context"
                    strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + len(data)
                    continue
                last_entry_context[sname] = entry_context
                # 2-4. señales → estructuras
                for sym, df in data.items():
                    sym_diag = signal_stats["by_symbol"].setdefault(
                        sym, {"strategies": {}})["strategies"].setdefault(
                            sname, {"timeframe": tf, "scanned": 0,
                                    "tradable": 0, "reasons": {}})
                    min_bars = 60 if tf == "1d" else 20
                    if len(df) < min_bars:
                        reason = "insufficient_history"
                        strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + 1
                        sym_diag["reasons"][reason] = sym_diag["reasons"].get(reason, 0) + 1
                        continue
                    sig = strat.scan(df, symbol=sym)
                    signal_stats["scanned"] += 1
                    strat_diag["scanned"] += 1
                    sym_diag["scanned"] += 1
                    if sig.tradable:
                        signal_stats["tradable"] += 1
                        strat_diag["tradable"] += 1
                        sym_diag["tradable"] += 1
                    else:
                        reason = "not_tradable"
                        strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + 1
                        sym_diag["reasons"][reason] = sym_diag["reasons"].get(reason, 0) + 1
                    # Régimen S78: solo se abren entradas en régimen bull
                    # (bear/cash = cash; el piso de equity también bloquea).
                    if sig.tradable and strat.last_structure and \
                            regime.get("regime") == "bull" and \
                            not (regime.get("floor") or {}).get("below_floor"):
                        # Filtro anti-earnings: no entrar en posiciones N días
                        # antes de reportes de ganancias (riesgo de gap y
                        # IV crush). La decisión queda registrada como
                        # EARNINGS_RISK para auditoría y Telegram.
                        from data.earnings import blocked as _earnings_blocked
                        eh = cfg.get("risk", {}).get("earnings_horizon_days", 2)
                        if _earnings_blocked(sym, eh):
                            reason = "earnings_blocked"
                            strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + 1
                            sym_diag["reasons"][reason] = sym_diag["reasons"].get(reason, 0) + 1
                            state["decisions"].append({
                                "ts": datetime.utcnow().isoformat(),
                                "decision": "EARNINGS_RISK",
                                "symbol": sym,
                                "reason": (f"Earnings próximo (horizonte "
                                           f"{eh}d); entrada bloqueada"),
                                "signal_type": sig.signal_type.value if hasattr(sig.signal_type, "value") else str(sig.signal_type),
                            })
                            logger.info("Entrada %s bloqueada por earnings",
                                        sym)
                            strat.reset()
                            continue
                        signal_stats["bull_gate"] += 1
                        strat_diag["reasons"]["bull_gate"] = strat_diag["reasons"].get("bull_gate", 0) + 1
                        sym_diag["reasons"]["bull_gate"] = sym_diag["reasons"].get("bull_gate", 0) + 1
                        st = strat.last_structure
                        entry_px = abs(st.net_premium)
                        dec = rm.approve_position(sym, sig, entry_px, equity,
                                                  [type("P", (), {"symbol": p["symbol"]})()
                                                   for p in state["positions"]])
                        if dec.decision == "APPROVED":
                            signal_stats["approved"] += 1
                            strat_diag["reasons"]["approved"] = strat_diag["reasons"].get("approved", 0) + 1
                            sym_diag["reasons"]["approved"] = sym_diag["reasons"].get("approved", 0) + 1
                            # Tamaño según la fase del piso: en recuperación se
                            # escala para cerrar la brecha hasta $100k; en fase
                            # de reto vuelve a 1 contrato (ver recovery_sizing).
                            n_contratos = 1
                            if sizing.get("unlimited"):
                                n_contratos = contracts_for_target(
                                    st, sizing["target_premium"],
                                    float(acct_cash),
                                    max_premium_total=recovery_risk_budget(
                                        equity, cfg))
                                if n_contratos == 0:
                                    logger.info(
                                        "RECUPERACIÓN: %s descartado, ni un "
                                        "contrato cabe en el presupuesto seguro",
                                        sym)
                                    strat.reset()
                                    continue
                                logger.warning(
                                    "RECUPERACIÓN: %s escalado a %d contratos "
                                    "(prima/contrato %.2f, prima total %.2f, "
                                    "objetivo %.2f, presupuesto seguro %.2f)",
                                    sym, n_contratos, abs(st.net_premium),
                                    abs(st.net_premium) * n_contratos,
                                    sizing["target_premium"],
                                    recovery_risk_budget(equity, cfg))
                            # Validar TODAS las cotizaciones antes de enviar la
                            # primera pata; evita spreads parciales y precios 0.
                            order_specs = _option_order_specs(
                                st, cfg, contracts=n_contratos)
                            submitted = []
                            for spec in order_specs:
                                submitted.append(executor.submit_option_order(
                                    spec["symbol"], spec["side"], spec["qty"],
                                    order_type=spec["order_type"],
                                    limit_price=spec["limit_price"]))
                            signal_stats["orders"] += len(submitted)
                            strat_diag["reasons"]["orders_submitted"] = strat_diag["reasons"].get("orders_submitted", 0) + len(submitted)
                            sym_diag["reasons"]["orders_submitted"] = sym_diag["reasons"].get("orders_submitted", 0) + len(submitted)
                            state["positions"].append({
                                "symbol": sym, "strategy": sname,
                                "structure": st.name,
                                "net_premium": st.net_premium,
                                "max_risk": st.max_risk,
                                "legs": order_specs,
                                "entry_orders": submitted,
                                "entry_ts": datetime.utcnow().isoformat(),
                            })
                            state["decisions"].append(dict(
                                ts=datetime.utcnow().isoformat(), **vars(dec)))
                            logger.info("POSICIÓN ABIERTA %s %s %s prima=%.2f",
                                        sym, sname, st.name, st.net_premium)
                            try:
                                notify_position_open(sym, sname, st.name,
                                                     st.net_premium,
                                                     st.max_risk, trading_mode())
                            except Exception:  # noqa: BLE001
                                logger.exception("Fallo notificando apertura")
                            strat.reset()
                            save_state(state)
                        else:
                            reason = f"risk_rejected:{dec.reason}"
                            strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + 1
                            sym_diag["reasons"][reason] = sym_diag["reasons"].get(reason, 0) + 1
                    elif sig.tradable:
                        if not strat.last_structure:
                            reason = "no_structure"
                        elif regime.get("regime") != "bull":
                            reason = "regime_not_bull"
                        elif (regime.get("floor") or {}).get("below_floor"):
                            reason = "below_floor"
                        else:
                            reason = "entry_gate_unknown"
                        strat_diag["reasons"][reason] = strat_diag["reasons"].get(reason, 0) + 1
                        sym_diag["reasons"][reason] = sym_diag["reasons"].get(reason, 0) + 1

            setup_cfg = cfg.get("setups", {}) or {}
            setup_started = time.monotonic()
            setup_snapshot = _setup_shadow_snapshot(cached, tickers, setup_cfg)
            state["setup_observations"] = setup_snapshot
            signal_stats["setup_confluence"] = {
                "mode": setup_snapshot.get("mode"),
                "symbols": len(setup_snapshot.get("symbols", {})),
                "counts": setup_snapshot.get("counts", {}),
            }
            phase_times["setups_s"] = round(time.monotonic() - setup_started, 3)
            risk_shadow_started = time.monotonic()
            risk_shadow_cfg = dict(DEFAULT_DEFINED_RISK_SHADOW_CFG)
            risk_shadow_cfg.update(cfg.get("defined_risk_shadow", {}) or {})
            risk_shadow_cfg["influence_entries"] = False
            risk_shadow_cfg["orders_allowed"] = False
            defined_risk_snapshot = _defined_risk_shadow_snapshot(
                cached, tickers, regime, state, builder, risk_shadow_cfg)
            state["defined_risk_shadow_observations"] = defined_risk_snapshot
            signal_stats["defined_risk_shadow"] = {
                "mode": defined_risk_snapshot.get("mode"),
                "orders_allowed": False,
                "symbols": len(defined_risk_snapshot.get("symbols", {})),
                "counts": defined_risk_snapshot.get("counts", {}),
            }
            phase_times["defined_risk_shadow_s"] = round(
                time.monotonic() - risk_shadow_started, 3)
            if setup_cfg.get("influence_entries"):
                logger.warning(
                    "SETUPS: influence_entries solicitado pero bloqueado; "
                    "la capa permanece shadow hasta promoción validada"
                )
            phase_times["entries_s"] = round(time.monotonic() - cycle_started, 3)

            # 4b. MOTOR BAJISTA: put spreads sobre CHoCH bear (AGENTS.md §40).
            #     Cubre el hueco que dejaba el bot long-only: en régimen bear
            #     no abría nada. `put_choch` es lo único del corpus con
            #     ventaja fuera de muestra (75% de ventanas bajistas en
            #     positivo, mediana +6.8%, batiendo al cash).
            try:
                bcfg = options_bear_cfg(cfg)
                candidatos = bear_entry_candidates(regime, state, cfg)
                signal_stats["bear_candidates"] = len(candidatos)
                if candidatos and not (regime.get("floor") or {}).get("below_floor") \
                        and not rm.is_halted():
                    for sym in candidatos:
                        try:
                            st = builder.vertical_spread(
                                sym, None, "bear",
                                bcfg["delta_long"], bcfg["delta_short"],
                                dte_min=bcfg["dte_min"], dte_max=bcfg["dte_max"])
                        except Exception as e:  # noqa: BLE001
                            logger.info("BEAR: sin estructura para %s (%s)", sym, e)
                            continue
                        prima_uno = abs(st.net_premium)
                        n_contratos = 1
                        if sizing.get("unlimited"):
                            n_contratos = contracts_for_target(
                                st, sizing["target_premium"], float(acct_cash),
                                max_premium_total=recovery_risk_budget(
                                    equity, cfg))
                        if n_contratos == 0:
                            logger.info(
                                "BEAR: %s descartado, ni un contrato cabe en "
                                "el presupuesto seguro", sym)
                            continue
                        prima_total = prima_uno * n_contratos
                        # Umbral medido en la ronda 5: por debajo de esta prima
                        # las 4 comisiones del spread se comen la ventaja.
                        if prima_total < bcfg["min_premium_net"]:
                            logger.info(
                                "BEAR: %s descartado, prima total %.2f < mínimo "
                                "%.2f (la comisión anularía la ventaja)",
                                sym, prima_total, bcfg["min_premium_net"])
                            continue
                        order_specs = _option_order_specs(
                            st, cfg, contracts=n_contratos)
                        submitted = [executor.submit_option_order(
                            s["symbol"], s["side"], s["qty"],
                            order_type=s["order_type"],
                            limit_price=s["limit_price"]) for s in order_specs]
                        signal_stats["orders"] += len(submitted)
                        state["positions"].append({
                            "symbol": sym, "strategy": "bear_put_choch",
                            "kind": "put",
                            "structure": st.name,
                            "net_premium": st.net_premium,
                            "max_risk": st.max_risk,
                            "legs": order_specs,
                            "entry_orders": submitted,
                            "entry_ts": datetime.utcnow().isoformat(),
                        })
                        logger.warning(
                            "PUT SPREAD ABIERTO %s %s prima/contrato=%.2f "
                            "contratos=%d prima_total=%.2f (régimen %s)",
                            sym, st.name, prima_uno, n_contratos, prima_total,
                            regime.get("regime"))
                        try:
                            notify_position_open(sym, "bear_put_choch", st.name,
                                                 st.net_premium, st.max_risk,
                                                 trading_mode())
                        except Exception:  # noqa: BLE001
                            logger.exception("Fallo notificando apertura bajista")
                        save_state(state)
            except Exception:  # noqa: BLE001
                logger.exception("Fallo en el motor bajista; el tick continúa")

            phase_times["bear_s"] = round(time.monotonic() - cycle_started, 3)

            # 5-6. gestionar posiciones abiertas (evaluar salida y cerrar)
            for i, p in enumerate(list(state["positions"])):
                try:
                    # Hallazgo18: stop intradiario 4% sobre el subyacente:
                    # si el low del día rompió (1-0.04)*close_prev, cerrar
                    # la posición de ese subyacente de inmediato (antes de
                    # evaluar el resto de reglas de prima/DTE).
                    cuts = (regime or {}).get("intraday_cuts", {})
                    if p["symbol"] in cuts:
                        sig_type, reason = "EXIT", ("intraday_stop_4pct: "
                            f"{p['symbol']} <= {cuts[p['symbol']]}")
                    else:
                        sig_type, reason = _manage_open_position(
                            feed, builder, strats.get(p["strategy"]), p)
                    if sig_type:
                        # Cerrar patas solo después de validar cotizaciones;
                        # nunca emitir una limit order de opción a 0.0.
                        st = strat_structure_for(p, strats.get(p["strategy"]), builder)
                        close_specs = _option_order_specs(st, cfg, closing=True)
                        closed_legs = []
                        for spec in close_specs:
                            closed_legs.append(executor.submit_option_order(
                                spec["symbol"], spec["side"], spec["qty"],
                                order_type=spec["order_type"],
                                limit_price=spec["limit_price"]))
                        entry_px = abs(p.get("net_premium") or 0.0)
                        current_net = 0.0
                        try:
                            st_close = strat_structure_for(p, strats.get(p["strategy"]), builder)
                            for leg in st_close.legs:
                                c = leg.contract
                                px = c.last or ((c.bid + c.ask) / 2.0 if c.bid and c.ask else None) or 0.0
                                sign = 1 if leg.quantity > 0 else -1
                                current_net += sign * px
                        except Exception:  # noqa: BLE001
                            logger.exception("No se pudo recalcular prima al cerrar")
                        pnl = (entry_px - abs(current_net)) * 100
                        state["positions"].pop(i)
                        if FIRESTORE_ENABLED:
                            try:
                                from state.firestore_state import append_trade
                                append_trade({
                                    "ts": datetime.utcnow().isoformat(),
                                    "symbol": p["symbol"],
                                    "strategy": p["strategy"],
                                    "structure": p.get("structure", ""),
                                    "entry_premium": entry_px,
                                    "exit_value": abs(current_net),
                                    "pnl": pnl,
                                    "exit_reason": reason,
                                    "dte": p.get("dte"),
                                })
                            except Exception:  # noqa: BLE001
                                logger.exception("Fallo publicando trade a Firestore")
                        state["decisions"].append({
                            "ts": datetime.utcnow().isoformat(),
                            "position": p, "exit_reason": reason,
                            "signal_type": sig_type, "close_legs": closed_legs,
                            "action": "POSITION_CLOSED", "pnl": pnl,
                        })
                        logger.info("Posición cerrada %s (%s): %s pnl=%.2f",
                                    p["symbol"], p["strategy"], reason, pnl)
                        try:
                            notify_position_close(p["symbol"], p["strategy"],
                                                  p.get("structure", ""), reason,
                                                  pnl, trading_mode())
                        except Exception:  # noqa: BLE001
                            logger.exception("Fallo notificando cierre")
                        strat_by_name(p["strategy"]).reset()
                        save_state(state)
                except Exception as e:  # noqa: BLE001
                    logger.exception("Error gestionando posición %s: %s",
                                     p["symbol"], e)

            phase_times["positions_s"] = round(time.monotonic() - cycle_started, 3)
            state["tick_diagnostics"] = signal_stats
            logger.info("SEÑALES tick: %s", signal_stats)
            save_state(state)
            phase_times["pre_publish_s"] = round(time.monotonic() - cycle_started, 3)
            signal_stats["phase_seconds"] = dict(phase_times)
            publish_started = time.monotonic()
            acct = (_call_with_timeout(executor.account_snapshot, 30.0,
                                        "Alpaca account snapshot")
                    if not executor.dry_run else {
                "equity": equity, "cash": equity, "portfolio_value": equity,
                "buying_power": equity * 4})
            logger.info("FIRESTORE_ENABLED=%s (antes de write_state_snapshot)",
                        FIRESTORE_ENABLED)
            enriched_positions = _enriched_positions(executor)
            if FIRESTORE_ENABLED:
                try:
                    risk_cfg = cfg.get("risk", {}) or {}
                    max_risk_pct = float(risk_cfg.get(
                        "max_risk_per_trade_pct",
                        rm.cfg.get("max_risk_per_trade_pct", 1.0)))
                    max_positions = int(risk_cfg.get(
                        "max_open_positions",
                        rm.cfg.get("max_open_positions", 5)))
                    write_state_snapshot({
                        "equity": equity,
                        "cash": acct.get("cash", equity),
                        "buying_power": acct.get("buying_power", None),
                        "positions": state["positions"],
                        "alpaca_positions": enriched_positions,
                        "orders_executed": executor.order_log[-50:] if not executor.dry_run else [],
                        "risk": {
                            # Canonical display field: percentage points (5.0 = 5%).
                            "risk_per_trade_pct": max_risk_pct,
                            # Unambiguous machine-readable fraction for consumers
                            # that calculate with the value (0.05 = 5%).
                            "risk_per_trade_fraction": max_risk_pct / 100.0,
                            "max_risk_per_trade_pct": max_risk_pct,
                            "max_positions": max_positions,
                            "max_open_positions": max_positions,
                            "halted": rm.is_halted(),
                            "regime": (regime or {}).get("regime", "unknown"),
                            "regime_summary": (regime or {}).get("summary", ""),
                            "crash_active": (regime or {}).get("crash_active", False),
                            "floor": (regime or {}).get("floor", {}),
                        },
                        "trading_mode": "DRY-RUN" if args.dry_run else (
                            "PAPER" if "paper" in (os.environ.get("APCA_API_BASE_URL") or "") else "REAL"),
                        "strategies": list(strats.keys()),
                        "universe": cfg["universo"].get("tickers", []),
                        "tick_diagnostics": signal_stats,
                        "setup_observations": state.get("setup_observations", {}),
                        "defined_risk_shadow_observations": state.get("defined_risk_shadow_observations", {}),
                        "decisions_today": [d for d in state["decisions"]
                                            if d.get("ts", "").startswith(
                                                datetime.utcnow().strftime("%Y-%m-%d"))],
                    })
                    append_equity_point(equity)
                except Exception:  # noqa: BLE001
                    logger.exception("Error publicando estado a Firestore")
            try:
                from state.telegram_bot import update_state as _up
                _up({"equity": equity, "cash": acct.get("cash", equity),
                     "dry_run": args.dry_run,
                     "buying_power": acct.get("buying_power"),
                     "positions": state["positions"],
                     "alpaca_positions": enriched_positions,
                     "risk": {"halted": rm.is_halted(),
                                "regime": (regime or {}).get("regime", "unknown"),
                                "regime_summary": (regime or {}).get("summary", "")},
                     "universe": cfg["universo"].get("tickers", []),
                     "trading_mode": trading_mode(),
                     "decisions_today": [d for d in state["decisions"]
                                         if d.get("ts", "").startswith(
                                             datetime.utcnow().strftime("%Y-%m-%d"))]})
            except Exception:  # noqa: BLE001
                logger.exception("Fallo actualizando estado Telegram")
            phase_times["publish_s"] = round(time.monotonic() - publish_started, 3)
            phase_times["total_s"] = round(time.monotonic() - cycle_started, 3)
            signal_stats["phase_seconds"] = phase_times
            _hb["ts"].append(time.time())
            logger.info("CYCLE TIMING id=%d total=%.3fs entries=%.3fs setups=%.3fs risk_shadow=%.3fs bear=%.3fs positions=%.3fs publish=%.3fs sleep=%.3fs",
                        cycle_id, phase_times["total_s"],
                        phase_times.get("entries_s", 0.0),
                        phase_times.get("setups_s", 0.0),
                        phase_times.get("defined_risk_shadow_s", 0.0),
                        phase_times.get("bear_s", 0.0),
                        phase_times.get("positions_s", 0.0),
                        phase_times.get("publish_s", 0.0),
                        args.poll_seconds)
            logger.info("Tick OK — equity=%.2f posiciones=%d", equity, len(state["positions"]))

        except Exception as e:  # noqa: BLE001
            logger.exception("Error en el loop: %s", e)

        # El loop es secuencial: nunca solapa ciclos. La siguiente evaluación
        # empieza después de terminar esta y esperar el intervalo configurado.
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
