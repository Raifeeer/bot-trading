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
# Modelo configurable. Default: DeepSeek V4 Flash (los nombres legacy
# deepseek-chat / deepseek-reasoner fueron retirados de la API oficial el
# 24-07-2026; ver https://api-docs.deepseek.com/updates/).
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
OPENAI_BASE = (os.environ.get("OPENAI_API_BASE") or "").strip()
OPENAI_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
# Fallbacks: Gemini (Google AI Studio / GCP) y Grok (xAI). Las keys pueden
# venir como variables de entorno directas o cargarse desde Secret Manager
# de GCP si se da el nombre del secret (GCP_PROJECT_ID se inyecta en Cloud
# Run con la service account del proyecto).
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
GROK_KEY = (os.environ.get("GROK_API_KEY") or "").strip()
GROK_MODEL = os.environ.get("GROK_MODEL") or "grok-4-fast"


def _sm_key(secret_name: str) -> str:
    """Lee una key desde Secret Manager de GCP (la SA de Cloud Run necesita
    el rol 'Secret Manager Secret Accessor')."""
    project = (os.environ.get("GCP_PROJECT_ID") or "").strip()
    if not project or not secret_name:
        return ""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_name}/versions/latest"
        return client.access_secret_version(request={"name": name}).payload.data.decode().strip()
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo leer secret %s de Secret Manager", secret_name)
        return ""


# Orden de resolución de keys de fallback (env directo > Secret Manager)
if not GEMINI_KEY:
    GEMINI_KEY = _sm_key(os.environ.get("GEMINI_SECRET_NAME")
                         or "vercel-polaris-web-studio-GEMINI_API_KEY")
if not GROK_KEY:
    GROK_KEY = _sm_key(os.environ.get("GROK_SECRET_NAME")
                       or "polaris-GROK_API_KEY")
ENABLED = bool(DEEPSEEK_KEY or OPENAI_KEY or GEMINI_KEY or GROK_KEY)

_context_cache = {"snapshot": {}, "updated_at": 0.0}
_fund_cache = {}  # texto normalizado -> (ts, str)

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


def _has_ticker_hint(text: str) -> bool:
    """Detecta si el texto probablemente menciona un ticker (palabra de 2-6
    letras MAYÚSCULAS, p.ej. 'TSLA', 'PLTR', '¿cómo va AMD?'). Saludos como
    'hola' no la activan, evitando consultas yfinance innecesarias."""
    import re
    if not text:
        return False
    low = text.lower()
    if low in ("hola", "hi", "hello", "buenas", "hey"):
        return False
    words = re.findall(r"\b([A-Z]{2,6})\b", text)
    skip = {"OK", "NO", "USD", "SMA", "ETF", "API", "LLM", "IA", "P", "E"}
    return any(w not in skip for w in words)


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
            # Timeout corto: en Cloud Run el hilo de Telegram aborta a los
            # 45 s; si la IA tarda más se usa el fallback.
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            content = data.get("choices") or []
            if content:
                return content[0].get("message", {}).get("content", "")
            logger.warning("LLM %s sin choices: %s", model, json.dumps(data)[:200])
        except (urllib.error.URLError, OSError) as e:
            logger.warning("LLM %s falla, probando siguiente: %s", model, e)
        except Exception:  # noqa: BLE001
            logger.exception("LLM error inesperado")
    # Gemini usa su propio endpoint REST (no OpenAI-compatible) y su key va
    # en la query string.
    if GEMINI_KEY:
        try:
            gurl = ("https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{GEMINI_MODEL}:generateContent")
            gpayload = json.dumps({
                "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n"
                                                f"PREGUNTA:\n{prompt}"}]}],
                "generationConfig": {"maxOutputTokens": 1000,
                                     "temperature": 0.3},
            }).encode()
            greq = urllib.request.Request(
                gurl + f"?key={GEMINI_KEY}", data=gpayload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(greq, timeout=30) as r:
                gdata = json.loads(r.read().decode())
            parts = (gdata.get("candidates") or [{}])[0].get("content",
                                                            {}).get("parts",
                                                                    [])
            text = parts[0].get("text", "") if parts else ""
            if text:
                return text
            logger.warning("Gemini sin texto: %s",
                           json.dumps(gdata)[:200])
        except (urllib.error.URLError, OSError) as e:
            logger.warning("Gemini falla, probando Grok: %s", e)
        except Exception:  # noqa: BLE001
            logger.exception("Gemini error inesperado")
    # Grok (xAI) es OpenAI-compatible.
    if GROK_KEY:
        configs.append(("https://api.x.ai/v1", GROK_KEY, GROK_MODEL, True))
        for base, key, model, _compat in configs[-1:]:
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
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode())
                content = data.get("choices") or []
                if content:
                    return content[0].get("message", {}).get("content", "")
                logger.warning("Grok sin choices: %s",
                               json.dumps(data)[:200])
            except (urllib.error.URLError, OSError) as e:
                logger.warning("Grok falla: %s", e)
            except Exception:  # noqa: BLE001
                logger.exception("Grok error inesperado")
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


def _fundamentals(text: str) -> str:
    """Contexto fundamental on-demand con límite de tiempo. El cuerpo lento
    (_fundamentals_slow) corre en un thread; si tarda >15 s se aborta y se
    devuelve un aviso breve, protegiendo el presupuesto de tiempo del hilo
    de Telegram (45 s en total)."""
    import threading as _th
    box = [None]
    def _worker():
        try:
            box[0] = _fundamentals_slow(text)
        except Exception:  # noqa: BLE001
            logger.exception("Fallo en _fundamentals")
    tw = _th.Thread(target=_worker, daemon=True, name="fund")
    tw.start()
    tw.join(15)
    if tw.is_alive():
        logger.warning("_fundamentals tardó >15s; se omite para %r", text[:40])
        return "DATOS FUNDAMENTALES: sin datos (consulta omitida por tiempo)."
    return box[0] or ""


def _fundamentals_slow(text: str) -> str:
    """Cuerpo lento de la consulta fundamental: yfinance (P/E, SMA200,
    earnings) para el primer ticker candidato válido del texto."""
    import re
    from data.earnings import get_earnings

    norm = (text or "").strip().lower()
    hit = _fund_cache.get(norm)
    if hit and (time.time() - hit[0]) < 60:
        return hit[1]
    words = re.findall(r"\b([A-Za-z]{1,6})\b", text or "")
    # Candidatos a ticker: mayúsculas de 1-5 letras, descartando palabras
    # comunes en español/inglés que podrían colisionar.
    SKIP = {"P", "E", "IA", "LLM", "OK", "NO", "USD", "SMA", "ETF", "API",
            "QUE", "COMO", "HOY", "AUN", "SER", "TAN", "PAN", "DOS", "TRES",
            "LAS", "LOS", "POR", "CON", "MAS", "EST", "ERA", "SOLO", "TIENE"}
    for sym in words:
        if len(sym) > 5:
            continue
        if sym.upper() in SKIP:
            continue
        # Yahoo devuelve datos aunque se pida en mayúsculas; si el símbolo
        # devuelto por Yahoo no coincide con el candidato en longitud/tipo,
        # es una palabra falsa (ej. "como" no existe como ticker).
        try:
            import yfinance as yf
            t = yf.Ticker(sym)
            fi = getattr(t, "fast_info", None)
            px = getattr(fi, "last_price", None)
            if px is None or px <= 0:
                continue  # palabra falsa o símbolo inexistente
            hist = None
            sma200 = None
            try:
                hist = t.history(period="1y")["Close"]
                if len(hist) >= 200:
                    sma200 = float(hist.iloc[-200:].mean())
            except Exception:  # noqa: BLE001
                pass
            pe = getattr(fi, "trailing_pe", None)
            earnings = get_earnings(sym)
            result = ("DATOS FUNDAMENTALES (consulta puntual):\n"
                      f"- {sym.upper()}: precio ${px}") + (
                          f" · SMA200 ${sma200:.2f} · precio "
                          f"{'+' if px/sma200-1 >= 0 else ''}"
                          f"{(px/sma200-1)*100:.1f}% vs SMA200"
                          if sma200 else "") + (
                          f" · P/E trailing: {round(pe, 2)}" if pe else "") + (
                          f" · Próximo earnings: {earnings['earnings_date']}"
                          if earnings.get("earnings_date") else "")
            _fund_cache[norm] = (time.time(), result)
            return result
        except Exception:  # noqa: BLE001
            continue
    result = ""
    _fund_cache[norm] = (time.time(), result)
    return result


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
    # Fundamentos on-demand solo si la pregunta parece mencionar un ticker
    # (palabra corta en mayúsculas o símbolo de 2-6 letras): saludos y
    # preguntas generales no los necesitan y yfinance puede tardar >30 s.
    fund = "" if not _has_ticker_hint(txt) else _fundamentals(txt)
    prompt = (f"ESTADO ACTUAL DEL BOT:\n{ctx}\n"
              f"{fund}\n"
              f"PREGUNTA DEL USUARIO:\n{txt}")
    resp = _call_llm(prompt)
    if not resp:
        return None
    return resp.strip() or None
