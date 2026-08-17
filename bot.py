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


def _enriched_positions(executor: AlpacaExecutor) -> list:
    """Piernas crudas de Alpaca enriquecidas con option_details (DTE, greeks).

    Nunca bloquea el tick: si el enriquecimiento falla, devuelve las piernas
    tal cual salieron del executor."""
    try:
        if executor.dry_run:
            return []
        legs = executor.positions()
        try:
            from data.feed import MarketDataFeed
            feed = MarketDataFeed(executor.cfg)
        except Exception:  # noqa: BLE001
            feed = None
        return enrich_positions(legs, feed=feed)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo enriqueciendo posiciones (publicando crudas)")
        try:
            return executor.positions()
        except Exception:  # noqa: BLE001
            return []


def key_if_any(executor: AlpacaExecutor) -> bool:
    """True si el executor tiene credenciales reales configuradas."""
    key = os.environ.get("APCA_API_KEY_ID") or executor.cfg["broker"].get("api_key")
    secret = os.environ.get("APCA_API_SECRET_KEY") or executor.cfg["broker"].get("secret_key")
    return bool(key and secret)

STATE_FILE = "data/bot_state.json"


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
        legs = executor.positions()
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
    n_puts = sum(1 for p in state.get("positions", [])
                 if p.get("kind") == "put")
    if n_puts >= b["max_positions"]:
        return []
    cupo = b["max_positions"] - n_puts
    ts = regime.get("ticker_status") or {}
    return [sym for sym, st in ts.items()
            if st.get("bear_choch") and sym not in abiertos][:cupo]


def recovery_sizing(equity: float, floor_res: dict, cfg: dict) -> dict:
    """Tamaño permitido según la fase del piso (ver risk/floor.py).

    FASE `recuperacion` (equity < $100k, reto sin armar): por decisión
    explícita del dueño (17 ago 2026) el bot opera SIN el tope de prima de
    $12 con el objetivo de volver a $100,000. El tamaño objetivo es el que
    cierra la brecha en un acierto:

        prima_objetivo = (objetivo - equity) / (tp_mult - 1)

    con tp_mult=1.4 (TP +40%) eso son ~$777 para una brecha de $311. AVISO
    EXPLÍCITO: esa prima supera el margen hasta el piso de recuperación
    ($289), así que una única operación perdedora puede dejar la cuenta por
    debajo del piso — el piso solo bloquea entradas nuevas, no limita la
    pérdida de una posición ya abierta. Es el coste aceptado de la decisión.

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
                         cash_disponible: float) -> int:
    """Nº de contratos para acercarse a `target_premium`, acotado por la caja.

    Nunca menos de 1 (si no cabe ni uno, el llamador debe descartar la
    entrada) y nunca más de lo que la caja disponible puede pagar.
    """
    prima_uno = abs(float(structure.net_premium))
    if prima_uno <= 0:
        return 1
    n_objetivo = int(target_premium // prima_uno) if target_premium > 0 else 1
    n_caja = int(max(0.0, cash_disponible) // prima_uno)
    return max(1, min(max(n_objetivo, 1), max(n_caja, 1)))


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
    parser.add_argument("--poll-minutes", type=float, default=5.0)
    args = parser.parse_args()

    cfg = get_config()
    feed = MarketDataFeed(cfg["data"]["provider"])
    rm = RiskManager(cfg["risk"])
    executor = AlpacaExecutor(dry_run=args.dry_run)
    start_tg_bot()
    try:
        executor.connect()
        equity0 = float(executor.account_snapshot()["equity"])
    except ExecutionError as e:
        if not args.dry_run:
            raise
        # dry-run sin credenciales: capital simulado desde configuración
        equity0 = float(os.environ.get("BOT_START_CAPITAL", 100_000.0))
        logger.warning("Alpaca no configurado: %s · operación simulada con capital inicial %.0f", e, equity0)
    rm.capital = equity0
    rm.reset_day(equity0)

    no_alpaca = executor.dry_run and not key_if_any(executor)
    option_feed = OptionFeed(sim=no_alpaca)
    builder = SpreadBuilder(option_feed)
    strats = build_strategies(cfg, builder)
    state = load_state()
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
        last_equity = read_last_equity()
        if last_equity is not None and "_floor_below" not in state:
            floor, phase, armed = active_floor(last_equity, state, floor_cfg)
            state["_floor_below"] = last_equity < floor
            logger.info(
                "Piso reconstruido desde Firestore: equity=%.2f fase=%s "
                "floor=%.2f reto_armado=%s below=%s",
                last_equity, phase, floor, armed, state["_floor_below"])
    if not no_alpaca:
        n_reconciled = reconcile_positions_with_broker(executor, state)
        if n_reconciled:
            logger.warning(
                "Reconciliación al arrancar: %d posición(es) reconstruida(s) "
                "desde Alpaca que no estaban en el estado local", n_reconciled)
            save_state(state)

    tickers = cfg["universo"]["tickers"]
    logger.info("Bot iniciado: %d estrategias, %d tickers, poll=%.0fmin, dry_run=%s",
                len(strats), len(tickers), args.poll_minutes, args.dry_run)

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

    while True:
        skip_tick = False
        try:
            snap = executor.account_snapshot()
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
                    "FASE RECUPERACIÓN: sin tope de prima, objetivo %.2f "
                    "(prima objetivo %.2f, caja %.2f). Una pérdida total en "
                    "una entrada puede dejar el equity bajo el piso %.2f",
                    (regime.get("floor") or {}).get("target", 100_000.0),
                    sizing["target_premium"], acct_cash,
                    (regime.get("floor") or {}).get("floor", 99_400.0))

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
            skip_tick = False
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
                # 2-4. señales → estructuras
                for sym, df in data.items():
                    if len(df) < (60 if tf == "1d" else 20):
                        continue
                    sig = strat.scan(df, symbol=sym)
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
                        st = strat.last_structure
                        entry_px = abs(st.net_premium)
                        dec = rm.approve_position(sym, sig, entry_px, equity,
                                                  [type("P", (), {"symbol": p["symbol"]})()
                                                   for p in state["positions"]])
                        if dec.decision == "APPROVED":
                            # Tamaño según la fase del piso: en recuperación se
                            # escala para cerrar la brecha hasta $100k; en fase
                            # de reto vuelve a 1 contrato (ver recovery_sizing).
                            n_contratos = 1
                            if sizing.get("unlimited"):
                                n_contratos = contracts_for_target(
                                    st, sizing["target_premium"],
                                    float(acct_cash))
                                logger.warning(
                                    "RECUPERACIÓN: %s escalado a %d contratos "
                                    "(prima/contrato %.2f, prima total %.2f, "
                                    "objetivo %.2f) — una pérdida total puede "
                                    "dejar el equity bajo el piso",
                                    sym, n_contratos, abs(st.net_premium),
                                    abs(st.net_premium) * n_contratos,
                                    sizing["target_premium"])
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

            # 4b. MOTOR BAJISTA: put spreads sobre CHoCH bear (AGENTS.md §40).
            #     Cubre el hueco que dejaba el bot long-only: en régimen bear
            #     no abría nada. `put_choch` es lo único del corpus con
            #     ventaja fuera de muestra (75% de ventanas bajistas en
            #     positivo, mediana +6.8%, batiendo al cash).
            try:
                bcfg = options_bear_cfg(cfg)
                candidatos = bear_entry_candidates(regime, state, cfg)
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
                                st, sizing["target_premium"], float(acct_cash))
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

            save_state(state)
            acct = executor.account_snapshot() if not executor.dry_run else {
                "equity": equity, "cash": equity, "portfolio_value": equity,
                "buying_power": equity * 4}
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
            _hb["ts"].append(time.time())
            logger.info("Tick OK — equity=%.2f posiciones=%d", equity, len(state["positions"]))

        except Exception as e:  # noqa: BLE001
            logger.exception("Error en el loop: %s", e)

        if not skip_tick:
            time.sleep(args.poll_minutes * 60)
        else:
            time.sleep(300)


if __name__ == "__main__":
    main()
