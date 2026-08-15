"""Bot interactivo de Telegram para Polaris.

Corre en un hilo aparte dentro del contenedor del bot. Responde a comandos
leídos de la cuenta local del bot en Telegram, consultando el estado del
trading (estado local, órdenes de Alpaca y Firestore).

Comandos:
  /estado      - equity, cash, buying power, posiciones abiertas, P&L del día
  /posiciones  - detalle de cada posición abierta (strikes, prima, P&L est.)
  /historial   - últimas operaciones cerradas con resultado
  /señales     - decisiones/señales recientes del risk manager
  /riesgo      - métricas de riesgo: drawdown, halted, uso de capital
  /ayuda       - lista de comandos
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger("polaris.tgbt")

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
ENABLED = bool(TOKEN and CHAT_ID)

_last_update_id = [0]
_state = {}  # se actualiza desde el loop principal del bot

HELP_TEXT = (
    "📡 <b>Comandos Polaris</b>\n"
    "/estado — cuenta y resumen del día\n"
    "/posiciones — posiciones abiertas\n"
    "/historial — últimas operaciones\n"
    "/señales — señales y decisiones recientes\n"
    "/riesgo — métricas de riesgo\n"
    "/ayuda — este menú"
)


def update_state(state_snapshot: dict) -> None:
    """Actualiza el estado que usan los comandos (llamado desde bot.py)."""
    _state.update(state_snapshot)


def _send(text: str) -> bool:
    if not ENABLED:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": text,
                          "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError) as e:
        logger.error("Telegram send falla: %s", e)
        return False


def _esc(v: str) -> str:
    """Escapa caracteres de Telegram HTML."""
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cmd_estado() -> str:
    pay = _state.get("payload") or {}
    equity = pay.get("equity", 0.0)
    cash = pay.get("cash", 0.0)
    bp = pay.get("buying_power") or 0.0
    mode = pay.get("trading_mode", "PAPER")
    pos = len(pay.get("positions") or [])
    halted = (pay.get("risk") or {}).get("halted", False)
    decisions = pay.get("decisions_today") or []
    closed = [d for d in decisions if d.get("action") == "POSITION_CLOSED"]
    pnl = sum(d.get("pnl", 0.0) for d in closed)
    emoji = "🟢" if not halted else "🛑"
    return (f"{emoji} <b>POLARIS — estado</b>\n"
            f"💵 Equity: ${equity:,.2f}\n"
            f"🏦 Cash: ${cash:,.2f}\n"
            f"⚡ Buying power: ${bp:,.2f}\n"
            f"📊 Posiciones: {pos}\n"
            f"📈 Cerradas hoy: {len(closed)} · P&amp;L: ${pnl:+,.2f}\n"
            f"🤖 Modo: {mode}" + ("\n⚠️ <b>CIRCUITO ACTIVO</b>" if halted else ""))


def _cmd_posiciones() -> str:
    pay = _state.get("payload") or {}
    pos = pay.get("positions") or []
    if not pos:
        alp = pay.get("alpaca_positions") or []
        if alp:
            rows = []
            for p in alp[:10]:
                sym = p.get("symbol", "?")
                rows.append(f"▸ <code>{_esc(sym)}</code> · {p.get('side','?')} · "
                            f"{p.get('qty', '?')} · ${p.get('market_value', 0):,.2f}")
            return ("📦 <b>Posiciones Alpaca</b>\n" + "\n".join(rows)[:3800])
        return "📦 <b>Posiciones</b>\nNinguna posición abierta."
    rows = []
    for p in pos:
        rows.append(f"▸ <code>{_esc(p.get('symbol','?'))}</code> · {p.get('strategy','?')}\n"
                    f"   {p.get('structure','?')} · prima "
                    f"${abs(p.get('net_premium') or 0):.2f} · riesgo "
                    f"${abs(p.get('max_risk') or 0):.2f}")
    return ("📦 <b>Posiciones abiertas</b>\n" + "\n".join(rows))[:3800]


def _cmd_historial() -> str:
    pay = _state.get("payload") or {}
    decisions = pay.get("decisions_today") or []
    closed = [d for d in decisions if d.get("action") == "POSITION_CLOSED"]
    if not closed:
        return "📜 <b>Historial</b>\nSin operaciones cerradas hoy."
    rows = []
    for d in closed[-10:]:
        p = d.get("position") or {}
        pnl = d.get("pnl", 0.0)
        e = "✅" if pnl >= 0 else "❌"
        rows.append(f"{e} <code>{_esc(p.get('symbol','?'))}</code> · "
                    f"{p.get('structure','?')} · {d.get('exit_reason','?')}\n"
                    f"   P&amp;L: ${pnl:+,.2f}")
    return ("📜 <b>Últimas operaciones cerradas</b>\n" + "\n".join(rows))[:3800]


def _cmd_señales() -> str:
    pay = _state.get("payload") or {}
    decisions = pay.get("decisions_today") or []
    if not decisions:
        return "📶 <b>Señales</b>\nSin decisiones registradas hoy."
    rows = []
    for d in decisions[-10:]:
        action = d.get("action") or d.get("decision") or "SCAN"
        sym = (d.get("position") or {}).get("symbol", "?")
        ts = d.get("ts", "")[-8:] if isinstance(d.get("ts"), str) else ""
        rows.append(f"▸ {ts} · {_esc(sym)} · {_esc(str(action))}")
    return ("📶 <b>Decisiones recientes</b>\n" + "\n".join(rows))[:3800]


def _cmd_riesgo() -> str:
    pay = _state.get("payload") or {}
    risk = pay.get("risk") or {}
    equity = pay.get("equity", 0.0)
    cap_ini = 100000.0
    dd = (cap_ini - equity) / cap_ini if equity else 0.0
    halted = risk.get("halted", False)
    maxpos = risk.get("max_open_positions", risk.get("max_positions", 5))
    # Canonical Firestore field is percentage points (5.0 = 5%).
    # Legacy snapshots used risk_per_trade_pct as a fraction (0.01 = 1%).
    per_trade = risk.get("max_risk_per_trade_pct")
    if per_trade is None:
        legacy = risk.get("risk_per_trade_pct")
        per_trade = (legacy * 100.0 if legacy is not None and legacy <= 1
                     else legacy)
    per_trade = float(per_trade or 0.0)
    emoji = "🛑" if halted else "🟢"
    return (f"{emoji} <b>POLARIS — riesgo</b>\n"
            f"📉 Drawdown desde inicio: {dd*100:.2f}%\n"
            f"⚠️ Circuito: {'ACTIVO' if halted else 'inactivo'}\n"
            f"🎯 Riesgo por trade: {per_trade:.1f}%\n"
            f"📌 Máx. posiciones: {maxpos}")


# Timeout máximo (segundos) que la IA puede tardar. Pasado ese tiempo se
# aborta la llamada (thread kill por join con timeout) y se usa el fallback;
# así el hilo de Telegram NUNCA queda congelado indefinidamente.
_AI_TIMEOUT_S = 45


def _ai_answer_with_timeout(text: str) -> str | None:
    """Llama a la IA con un límite de tiempo real. Si la llamada se pasa del
    timeout, devuelve None y el flujo cae al fallback (nunca cuelga el hilo).

    Pasa `notify` (envoltura de _send que nunca lanza) hasta answer() para
    que cada etapa lenta (buscar ticker, indicadores técnicos, llamada al
    LLM) avise por Telegram según va ocurriendo, en vez de un solo aviso
    genérico al principio."""
    import threading
    from state.ai_assistant import answer as _ai_answer, update_context
    box = [None]

    def _notify(msg: str) -> None:
        try:
            _send(msg)
        except Exception:  # noqa: BLE001
            logger.exception("Fallo enviando aviso de progreso")

    def _work():
        try:
            update_context(_state)
            box[0] = _ai_answer(text, notify=_notify)
        except Exception:  # noqa: BLE001
            logger.exception("Fallo en respuesta IA")

    t = threading.Thread(target=_work, daemon=True, name="tg-ia")
    t.start()
    t.join(_AI_TIMEOUT_S)
    if t.is_alive():
        logger.warning("IA tardó más de %ds para %r; se usa fallback",
                       _AI_TIMEOUT_S, text[:40])
        return None
    return box[0]


def _handle_message(text: str) -> None:
    txt = (text or "").strip().lower()
    if txt in ("/estado", "estado"):
        resp = _cmd_estado()
    elif txt in ("/posiciones", "/posicion", "posiciones"):
        resp = _cmd_posiciones()
    elif txt in ("/historial", "/trades", "historial"):
        resp = _cmd_historial()
    elif txt in ("/señales", "/senales", "/sinyales", "señales"):
        resp = _cmd_señales()
    elif txt in ("/riesgo", "riesgo"):
        resp = _cmd_riesgo()
    elif txt in ("/ayuda", "/help", "ayuda"):
        resp = HELP_TEXT
    elif txt in ("/start",):
        resp = HELP_TEXT
    else:
        # Fallback conversacional con IA si está configurada. Este camino
        # puede tardar 30-60s (fundamentales + análisis técnico + LLM), así
        # que se avisa de inmediato para que no parezca que el bot no
        # recibió el mensaje.
        try:
            _send("🤖 Dame unos segundos, estoy analizando…")
        except Exception:  # noqa: BLE001
            logger.exception("Fallo enviando aviso de 'analizando'")
        resp = None
        ai_resp = _ai_answer_with_timeout(text)
        if ai_resp:
            resp = f"🤖 Polaris IA\n{ai_resp}"
        if not resp:
            resp = ("❓ No entendí el comando. Usa /ayuda para ver los "
                    "disponibles.")
    try:
        ok = _send(resp)
        logger.info("TG response sent=%s para %r", ok, text[:40])
    except Exception:  # noqa: BLE001
        logger.exception("Fallo enviando respuesta Telegram")


# Heartbeat del hilo de Telegram (el watchdog del bot lo consulta; si el
# hilo TG no actualiza esto en TG_HB_TIMEOUT_S, se reinicia el proceso).
TG_HB = {"ts": [time.time()]}
TG_HB_TIMEOUT_S = 600


def _poll_loop() -> None:
    """Polling de updates (long-polling manual simple)."""
    while True:
        try:
            url = (f"https://api.telegram.org/bot{TOKEN}/getUpdates"
                   f"?offset={_last_update_id[0] + 1}&timeout=10")
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode())
            for upd in data.get("result", []) or []:
                _last_update_id[0] = max(_last_update_id[0],
                                         upd.get("update_id", 0))
                msg = upd.get("message") or {}
                chat = (msg.get("chat") or {}).get("id")
                if msg.get("text"):
                    logger.info("TG update chat=%s (esperado %s): %r",
                                chat, CHAT_ID, msg["text"][:50])
                if chat is not None and str(chat) == str(CHAT_ID) and msg.get("text"):
                    _handle_message(msg["text"])
        except Exception as e:  # noqa: BLE001
            logger.error("Telegram poll falla: %s", e)
        TG_HB["ts"].append(time.time())
        time.sleep(2)


def start_tg_bot() -> threading.Thread:
    """Arranca el hilo de comandos de Telegram (no-op si no está configurado)."""
    if not ENABLED:
        logger.info("Telegram commands desactivado (sin token/chat)")
        t = threading.Thread(target=lambda: None, daemon=True)
        t.start()
        return t
    t = threading.Thread(target=_poll_loop, daemon=True, name="tg-bot")
    t.start()
    logger.info("Telegram commands iniciado (polling)")
    return t


def tg_heartbeat_ts() -> float:
    """Última vez que el hilo de Telegram trabajó (para el watchdog)."""
    return max(TG_HB["ts"])
