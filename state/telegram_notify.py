"""Notificaciones de Telegram para el bot Polaris.

Envía alertas al chat configurado cuando el bot:
- abre una posición
- cierra una posición (TP / SL / gestión)
- se detiene por el circuito de riesgo

El token se toma de la env TELEGRAM_BOT_TOKEN y el chat de TELEGRAM_CHAT_ID.
Si no están configuradas, el módulo no falla: las llamadas se vuelven no-op.
"""
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("polaris.telegram")

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
ENABLED = bool(TOKEN and CHAT_ID)


def _send(text: str) -> bool:
    if not ENABLED:
        logger.debug("Telegram no configurado (TELEGRAM_BOT_TOKEN/CHAT_ID vacías); salto")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
            logger.info("Telegram enviado: %s", ok)
            return ok
    except (urllib.error.URLError, OSError) as e:
        logger.error("Telegram falla: %s", e)
        return False


def notify_position_open(symbol: str, strategy: str, structure: str,
                         net_premium: float, max_risk: float, mode: str = "PAPER") -> bool:
    text = (f"🟢 <b>POLARIS — posición abierta</b>\n"
            f"📈 <code>{symbol}</code> · {strategy}\n"
            f"🔧 {structure}\n"
            f"💰 Prima neta: ${net_premium:.2f}\n"
            f"⚠️ Riesgo máx: ${max_risk:.2f}\n"
            f"🤖 Modo: {mode}")
    return _send(text)


def notify_position_close(symbol: str, strategy: str, structure: str,
                          result: str, pnl: float, mode: str = "PAPER") -> bool:
    emoji = "✅" if pnl >= 0 else "❌"
    text = (f"{emoji} <b>POLARIS — posición cerrada</b>\n"
            f"📈 <code>{symbol}</code> · {strategy}\n"
            f"🔧 {structure}\n"
            f"🎯 Motivo: {result}\n"
            f"📊 P&amp;L: ${pnl:+.2f}\n"
            f"🤖 Modo: {mode}")
    return _send(text)


def notify_risk_halt(reason: str = "") -> bool:
    text = (f"🛑 <b>POLARIS — circuito de riesgo activado</b>\n"
            f"El bot detuvo la apertura de nuevas posiciones.\n"
            f"{reason}\n"
            f"Revise el dashboard para más detalles.")
    return _send(text)


def notify_error(context: str, detail: str = "") -> bool:
    text = (f"⚠️ <b>POLARIS — alerta</b>\n"
            f"{context}\n"
            f"{detail}")
    return _send(text)


if __name__ == "__main__":
    notify_risk_halt("Prueba de configuración de Telegram.")
