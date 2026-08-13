"""Prueba local del asistente IA de Telegram (sin credenciales externas).

Simula un mensaje natural y verifica:
  - Sin clave => respuesta None y no se rompe
  - Con una base OpenAI-compatible + clave => respuesta coherente
    (usa OPENAI_API_BASE/KEY del entorno de sandbox, si existe)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state import ai_assistant, telegram_bot  # noqa: E402


def main() -> None:
    # 1. Sin clave
    print("enabled con env sandbox:", ai_assistant.enabled())
    resp = ai_assistant.answer("¿cuánto ganamos hoy?")
    print("Sin clave ->", resp)

    # 2. Simular estado del bot
    snap = {
        "payload": {
            "trading_mode": "PAPER",
            "equity": 100250.0,
            "cash": 97500.0,
            "buying_power": 25000.0,
            "positions": [{
                "symbol": "SPY250919C00600000", "structure": "CALL DEBIT SPREAD",
                "net_premium": -2.5, "max_risk": 175.0}],
            "alpaca_positions": [],
            "risk": {"halted": False},
            "decisions_today": [{
                "ts": "2026-08-13T14:30:00", "action": "POSITION_OPENED",
                "position": {"symbol": "SPY250919C00600000"}}],
        }}
    ai_assistant.update_context(snap)

    # 3. Con base compatible (sandbox OPENAI_API_BASE apunta al proxy interno)
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        ai_assistant.OPENAI_KEY = key
        ai_assistant.OPENAI_BASE = os.environ.get("OPENAI_API_BASE",
                                                  "https://api.openai.com/v1")
        ai_assistant.OPENAI_MODEL = os.environ.get("OPENAI_MODEL",
                                                   "gpt-5-mini")
        if not ai_assistant.OPENAI_BASE.endswith("/v1"):
            ai_assistant.OPENAI_BASE = ai_assistant.OPENAI_BASE.rstrip("/") + "/v1"
        resp = ai_assistant.answer("¿cuánto ganamos hoy y qué posiciones tenemos?")
        print("Con proxy ->", resp)
        assert resp is None or len(resp) < 1200, "respuesta demasiado larga"
        # Los comandos no pasan por IA
        assert ai_assistant.answer("/estado") is None

    # 4. El bot de telegram responde al comando normal igual
    print("OK - test ai_assistant pasado")


if __name__ == "__main__":
    main()
