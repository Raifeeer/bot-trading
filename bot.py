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

from config import get_config
from data.feed import MarketDataFeed

try:
    from state.firestore_state import (write_state_snapshot, append_signal,
                                      append_equity_point)
    FIRESTORE_ENABLED = True
except ImportError:
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
from options.strategy import OptionsStrategy, OptionsPosition, evaluate_exit
from risk.manager import RiskManager
from execution.alpaca_executor import AlpacaExecutor, ExecutionError


def key_if_any(executor: AlpacaExecutor) -> bool:
    """True si el executor tiene credenciales reales configuradas."""
    key = os.environ.get("APCA_API_KEY_ID") or executor.cfg["broker"].get("api_key")
    secret = os.environ.get("APCA_API_SECRET_KEY") or executor.cfg["broker"].get("secret_key")
    return bool(key and secret)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger("bot")

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


def _manage_open_position(feed, builder, strat, pos):
    """Evalúa si la posición abierta debe cerrarse. Devuelve (signal_type o
    None, razón). Usa evaluate_exit de options.strategy con la prima actual."""
    from options.strategy import evaluate_exit, OptionsPosition
    from options.chains import OptionContract
    from datetime import timedelta
    spot = feed.history([pos["symbol"]], "1d", days=2)[pos["symbol"]]["close"].iloc[-1]
    entry_premium = abs(pos["net_premium"])
    # Reconstruir la estructura con los strikes guardados en el spread
    st = builder.vertical_spread_from(pos)
    contracts = [leg.contract for leg in st.legs]
    contracts = feed.snapshots(contracts, spot)
    # Recalcular prima neta actual del spread
    net = 0.0
    for leg in st.legs:
        c = leg.contract
        px = c.last or ((c.bid + c.ask) / 2.0 if c.bid and c.ask else None)
        if px is None:
            return None, ""
        sign = 1 if leg.quantity > 0 else -1
        net += sign * px
    net = abs(net) * (-1 if st.direction == "bear" and st.kind == "vertical" else 1)
    if entry_premium <= 0:
        entry_premium = 1e-9
    # Recalcular días al vencimiento (usar la expiración de la pata short/lejana)
    exps = sorted(l.contract.expiration for l in st.legs)
    dte = (exps[-1] - datetime.utcnow().date()).days if exps else 30
    op = OptionsPosition(st, entry_premium, datetime.utcnow())
    reason = evaluate_exit(st, op, dte, spot)
    if reason:
        return "EXIT", reason
    return None, ""


def strat_structure_for(pos, strat):
    """Reconstruye la estructura de la posición desde el registro guardado."""
    try:
        return strat.builder.vertical_spread_from(pos)
    except RuntimeError:
        # fallback: re-escanear el subyacente para reconstruir strikes
        df = strat.base.scan
        raise

def build_strategies(cfg, spread_builder):
    strats = {}
    if cfg["strategies"]["day_momentum"]["enabled"]:
        strats["opt_day_momentum"] = OptionsStrategy(
            DayMomentum(cfg["strategies"]["day_momentum"]["params"]),
            spread_builder, {"direction": "bull"})
    if cfg["strategies"]["day_breakout"]["enabled"]:
        strats["opt_day_breakout"] = OptionsStrategy(
            DayBreakout(cfg["strategies"]["day_breakout"]["params"]),
            spread_builder, {"direction": "bull"})
    if cfg["strategies"]["swing_trend"]["enabled"]:
        strats["opt_swing_trend"] = OptionsStrategy(
            SwingTrend(cfg["strategies"]["swing_trend"]["params"]),
            spread_builder, {"direction": "bull"})
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

    tickers = cfg["universo"]["tickers"]
    logger.info("Bot iniciado: %d estrategias, %d tickers, poll=%.0fmin, dry_run=%s",
                len(strats), len(tickers), args.poll_minutes, args.dry_run)

    # Watchdog: si ningún tick completo en MAX_TICK_SECONDS, el proceso se
    # reinicia y Cloud Run recrea la instancia automáticamente.
    import sys as _sys
    _hb = {"ts": [time.time()]}
    def _watchdog():
        while True:
            time.sleep(60)
            if time.time() - _hb["ts"][-1] > 720:
                logger.critical("Watchdog: sin ticks completos en 12 min; "
                                "reiniciando el proceso")
                _sys.exit(1)
    threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()

    while True:
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

            # 1. datos con el timeframe propio de cada estrategia:
            #    swing usa 1d (210 días para SMA200+ATR); day usa 5m/15m
            tf_by_strat = {}
            for sname, strat in strats.items():
                tf = getattr(strat.base, "timeframe",
                             None) or getattr(strat, "timeframe", "1d")
                days = 210 if tf == "1d" else (10 if tf == "15min" else 5)
                tf_by_strat[sname] = (tf, days)
            cached = {}
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
                        logger.warning("Sin datos %s; reintentando en 5 min", tf)
                        skip_tick = True
                if skip_tick:
                    break
                data = cached[tf]
                if not data:
                    continue
                # 2-4. señales → estructuras
                for sym, df in data.items():
                    if len(df) < (60 if tf == "1d" else 20):
                        continue
                    sig = strat.scan(df, symbol=sym)
                    if sig.tradable and strat.last_structure:
                        st = strat.last_structure
                        entry_px = abs(st.net_premium)
                        dec = rm.approve_position(sym, sig, entry_px, equity,
                                                  [type("P", (), {"symbol": p["symbol"]})()
                                                   for p in state["positions"]])
                        if dec.decision == "APPROVED":
                            # ejecutar las patas del spread
                            for leg in st.legs:
                                executor.submit_option_order(
                                    leg.contract.symbol,
                                    "buy" if leg.quantity > 0 else "sell",
                                    abs(leg.quantity))
                            state["positions"].append({
                                "symbol": sym, "strategy": sname,
                                "structure": st.name,
                                "net_premium": st.net_premium,
                                "max_risk": st.max_risk,
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

            # 5-6. gestionar posiciones abiertas (evaluar salida y cerrar)
            for i, p in enumerate(list(state["positions"])):
                try:
                    sig_type, reason = _manage_open_position(
                        feed, builder, strats.get(p["strategy"]), p)
                    if sig_type:
                        # cerrar patas del spread (vender lo comprado, etc.)
                        st = strat_structure_for(p, strats.get(p["strategy"]))
                        closed_legs = []
                        for leg in st.legs:
                            r = executor.submit_option_order(
                                leg.contract.symbol,
                                "sell" if leg.quantity > 0 else "buy",
                                abs(leg.quantity))
                            closed_legs.append(r)
                        entry_px = abs(p.get("net_premium") or 0.0)
                        current_net = 0.0
                        try:
                            st_close = strat_structure_for(p, strats.get(p["strategy"]))
                            for leg in st_close.legs:
                                c = leg.contract
                                px = c.last or ((c.bid + c.ask) / 2.0 if c.bid and c.ask else None) or 0.0
                                sign = 1 if leg.quantity > 0 else -1
                                current_net += sign * px
                        except Exception:  # noqa: BLE001
                            logger.exception("No se pudo recalcular prima al cerrar")
                        pnl = (entry_px - abs(current_net)) * 100
                        state["positions"].pop(i)
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
            if FIRESTORE_ENABLED:
                try:
                    write_state_snapshot({
                        "equity": equity,
                        "cash": acct.get("cash", equity),
                        "buying_power": acct.get("buying_power", None),
                        "positions": state["positions"],
                        "alpaca_positions": executor.positions() if not executor.dry_run else [],
                        "orders_executed": executor.order_log[-50:] if not executor.dry_run else [],
                        "risk": {
                            "risk_per_trade_pct": cfg["risk"].get("risk_per_trade_pct", 0.01),
                            "max_positions": cfg["risk"].get("max_positions", 5),
                            "halted": rm.is_halted(),
                        },
                        "trading_mode": "DRY-RUN" if args.dry_run else (
                            "PAPER" if "paper" in (os.environ.get("APCA_API_BASE_URL") or "") else "REAL"),
                        "strategies": list(strats.keys()),
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
                     "alpaca_positions": executor.positions() if not executor.dry_run else [],
                     "risk": {"halted": rm.is_halted()},
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
