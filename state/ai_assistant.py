"""Asistente conversacional con IA para el Telegram de Polaris.

Si está configurado (DEEPSEEK_API_KEY o OPENAI_API_KEY con base compatible),
responde en lenguaje natural a cualquier mensaje que NO sea un comando de la
lista fija, usando el estado real del bot como contexto.

Si no hay clave configurada, el comportamiento es el original: el mensaje
recibe la respuesta de "no entendí el comando".

Compatible con:
  - DeepSeek API directa  (DEEPSEEK_API_KEY, modelo deepseek-chat)
  - Cualquier API OpenAI-compatible (OPENAI_API_BASE + OPENAI_API_KEY)
  - OpenAI directa (OPENAI_API_KEY sin base)

Todo se hace con urllib, sin dependencias nuevas, para que funcione en el
contenedor de Cloud Run sin rebuilds pesados.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger("polaris.ai")

DEEPSEEK_KEY = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
OPENAI_BASE = (os.environ.get("OPENAI_API_BASE") or "").strip()
OPENAI_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
ENABLED = bool(DEEPSEEK_KEY or OPENAI_KEY)

_context_cache = {"snapshot": {}, "updated_at": 0.0}

SYSTEM_PROMPT = (
    "Eres Polaris, el asistente de trading de opciones del usuario. "
    "Respondes siempre en español, de forma breve y precisa, usando los "
    "datos del estado actual del bot que se te pasan como contexto. "
    "NUNCA inventes datos: si el contexto no incluye la información "
    "pedida, dilo con honestidad y sugiere cómo obtenerla. "
    "No das consejos de inversión personalizada: aclaras que el bot opera "
    "en modo {mode} y que las cifras son de papel. "
    "Usa formato Markdown de Telegram (*bold*, `código`), sin HTML. "
    "Responde en máximo 1000 caracteres."
)

COMMANDS = ("/estado", "/posiciones", "/historial", "/señales", "/senales",
            "/sinyales", "/riesgo", "/ayuda", "/help", "/start")


def enabled() -> bool:
    return ENABLED


def update_context(snapshot: dict) -> None:
    """Actualiza el contexto que el LLM usa para responder."""
    if not ENABLED:
        return
    try:
        copy = dict(snapshot)
        # recortar listas para no gastar tokens
        for k in ("orders_executed", "decisions_today"):
            lst = copy.get(k)
            if isinstance(lst, list):
                copy[k] = lst[-20:]
        _context_cache["snapshot"] = copy
        _context_cache["updated_at"] = time.time()
    except Exception:  # noqa: BLE001
        logger.exception("Fallo cacheando contexto IA")


def _call_llm(prompt: str) -> str | None:
    """Llama al LLM configurado y devuelve el texto de respuesta."""
    if not ENABLED:
        return None
    # DeepSeek primero; luego API OpenAI-compatible
    configs = []
    if DEEPSEEK_KEY:
        configs.append(("https://api.deepseek.com", DEEPSEEK_KEY,
                        DEEPSEEK_MODEL, True))
    if OPENAI_KEY:
        base = OPENAI_BASE or "https://api.openai.com/v1"
        configs.append((base.rstrip("/"), OPENAI_KEY, OPENAI_MODEL,
                        base != "https://api.openai.com/v1"))
    for base, key, model, _compat in configs:
        url = f"{base}/chat/completions"
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}]
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.3,
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            content = data.get("choices") or []
            if content:
                return content[0].get("message", {}).get("content", "")
            logger.warning("LLM %s sin choices: %s", model, json.dumps(data)[:200])
        except (urllib.error.URLError, OSError) as e:
            logger.warning("LLM %s falla, probando siguiente: %s", model, e)
        except Exception:  # noqa: BLE001
            logger.exception("LLM error inesperado")
    return None


def _build_context() -> str:
    """Serializa el estado del bot en texto compacto para el LLM."""
    s = _context_cache["snapshot"]
    pay = (s.get("payload") or s)
    lines = [
        f"Modo: {pay.get('trading_mode', '?')}",
        f"Equity: ${pay.get('equity', 0):,.2f}",
        f"Cash: ${pay.get('cash', 0):,.2f}",
        f"Buying power: ${pay.get('buying_power', 0):,.2f}",
        f"Posiciones abiertas (lógica del bot): {len(pay.get('positions') or [])}",
        f"Circuito de riesgo activo: {bool((pay.get('risk') or {}).get('halted', False))}",
    ]
    for p in (pay.get("positions") or [])[:5]:
        lines.append(
            f"- Posición {p.get('symbol','?')}: {p.get('structure','?')} "
            f"prima ${abs(p.get('net_premium') or 0):.2f} "
            f"riesgo máx ${abs(p.get('max_risk') or 0):.2f}")
    alp = pay.get("alpaca_positions") or []
    if alp:
        lines.append("Posiciones reales en Alpaca:")
        for p in alp[:5]:
            lines.append(f"- {p.get('symbol','?')} {p.get('side','?')} "
                         f"{p.get('qty','?')} "
                         f"${p.get('market_value', 0):,.2f}")
    else:
        lines.append("Posiciones reales en Alpaca: ninguna")
    closed = [d for d in (pay.get("decisions_today") or [])
              if d.get("action") == "POSITION_CLOSED"]
    if closed:
        pnl = sum(d.get("pnl", 0.0) for d in closed)
        lines.append(f"Cerradas hoy: {len(closed)} · P&L hoy: ${pnl:+,.2f}")
    else:
        lines.append("Cerradas hoy: 0 · P&L hoy: $0.00")
    recent = (pay.get("decisions_today") or [])[-8:]
    if recent:
        lines.append("Decisiones recientes:")
        for d in recent:
            sym = (d.get("position") or {}).get("symbol", "?")
            lines.append(f"- {d.get('ts','')[-8:]} {sym}: {d.get('action','?')}")
    return "\n".join(lines)


def answer(user_text: str) -> str | None:
    """Responde con IA si está habilitada y el texto no es un comando.

    Devuelve la respuesta o None (no habilitado / es un comando).
    """
    if not ENABLED:
        return None
    txt = (user_text or "").strip()
    if txt.lower() in COMMANDS:
        return None
    ctx = _build_context()
    prompt = (f"ESTADO ACTUAL DEL BOT:\n{ctx}\n\n"
              f"PREGUNTA DEL USUARIO:\n{txt}")
    resp = _call_llm(prompt)
    if not resp:
        return None
    return resp.strip() or None
