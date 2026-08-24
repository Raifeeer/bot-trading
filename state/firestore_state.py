"""Sincronización del estado del bot con Firestore (Native).

El bot escribe en Firestore en cada tick su estado consolidado: cuenta,
posiciones, señales, riesgo y métricas del día. El dashboard (Manus o
Vercel) lee esos documentos con el SDK de Firebase/Web para mostrar
datos en vivo.

Documentos:
  polaris/{date}/state      -> estado global del día (snapshot por tick)
  polaris/{date}/signals    -> array de señales del día (append)
  polaris/{date}/equity     -> serie temporal equity (puntos por tick)

Variables de entorno:
  FIRESTORE_PROJECT_ID: proyecto de GCP (opcional, autodetectable)
  FIRESTORE_DATABASE: nombre de la base de datos (default: "polaris",
      una DB en modo Firestore Native creada ex profeso; la (default) del
      proyecto está en modo Datastore y no sirve para el SDK web)
  GOOGLE_APPLICATION_CREDENTIALS: clave de service account (Cloud Run)
"""
import hashlib
import logging
import os
from datetime import date, datetime, timezone
from datetime import timedelta as _timedelta

logger = logging.getLogger("state.firestore")

_state_client = None
_EXIT_LEDGER_COLLECTION = "polaris_exit_ledger"
_TERMINAL_EXIT_STATUSES = {"completed"}
_ACTIVE_EXIT_STATUSES = {
    "submitting", "submitted", "partial_submission", "needs_review"
}


def _get_db():
    """Devuelve el cliente Firestore (lazy init con Application Default
    Credentials: en Cloud Run usa la identidad del servicio)."""
    global _state_client
    if _state_client is None:
        from google.cloud import firestore
        project = None
        database = os.environ.get("FIRESTORE_DATABASE", "polaris")
        _state_client = firestore.Client(project=project, database=database)
    return _state_client


def write_state_snapshot(payload: dict) -> None:
    """Escribe el estado consolidado del tick en
    polaris/{YYYY-MM-DD}/state."""
    try:
        db = _get_db()
        day = date.today().isoformat()
        doc = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        db.collection("polaris").document(day).set(
            doc, merge=True, timeout=30.0)
        logger.info("Estado escrito en Firestore: polaris/%s", day)
    except Exception as e:  # nunca bloquear el bot por el estado
        logger.warning("Fallo al escribir estado en Firestore: %s", e)


def append_signal(signal_payload: dict) -> None:
    """Añade una señal del día a polaris/{day}/signals (array)."""
    try:
        db = _get_db()
        day = date.today().isoformat()
        from google.cloud.firestore_v1.transforms import ArrayUnion
        db.collection("polaris").document(day).update({
            "signals": ArrayUnion([signal_payload])
        })
    except Exception as e:
        logger.warning("Fallo al registrar señal en Firestore: %s", e)


def append_trade(trade: dict) -> None:
    """Añade un trade cerrado a polaris/{day}/trade_history (array)."""
    try:
        db = _get_db()
        day = date.today().isoformat()
        from google.cloud.firestore_v1.transforms import ArrayUnion
        db.collection("polaris").document(day).update({
            "trade_history": ArrayUnion([trade])
        })
    except Exception as e:  # nunca bloquear el bot
        logger.warning("Fallo al publicar trade a Firestore: %s", e)


def read_last_equity() -> float | None:
    """Devuelve el último equity publicado (día de hoy o, si no hay tick
    todavía hoy, el más reciente de los últimos 7 días) o None si no hay
    ninguno / falla la lectura.

    Se usa al arrancar el proceso para reconstruir `_floor_below` (§34 de
    AGENTS.md): el JSON local es efímero y se resetea en cada redeploy, así
    que sin esto el bot "olvida" que ya estaba bajo el piso y puede volver a
    notificar "PISO ROTADO" espontáneamente en cada reinicio aunque el
    equity no haya cruzado nada de verdad.
    """
    try:
        db = _get_db()
        for offset in range(7):
            day = (date.today() - _timedelta(days=offset)).isoformat()
            snap = db.collection("polaris").document(day).get(timeout=10.0)
            if snap.exists:
                payload = (snap.to_dict() or {}).get("payload") or {}
                equity = payload.get("equity")
                if equity is not None:
                    return float(equity)
        return None
    except Exception as e:  # nunca bloquear el arranque del bot
        logger.warning("Fallo leyendo último equity de Firestore: %s", e)
        return None


def read_challenge_armed() -> bool | None:
    """Devuelve si el reto $100->$200 ya quedó armado (equity tocó los $100k)
    según el último snapshot publicado, o None si no hay dato.

    Es un latch de una sola dirección: se lee al arrancar porque el JSON local
    es efímero y perderlo devolvería el bot a modo recuperación (piso más
    bajo), dejando el piso del reto sin efecto (ver risk/floor.py).
    """
    try:
        db = _get_db()
        for offset in range(30):
            day = (date.today() - _timedelta(days=offset)).isoformat()
            snap = db.collection("polaris").document(day).get(timeout=10.0)
            if not snap.exists:
                continue
            payload = (snap.to_dict() or {}).get("payload") or {}
            floor = ((payload.get("risk") or {}).get("floor") or {})
            if "challenge_armed" in floor:
                return bool(floor["challenge_armed"])
        return None
    except Exception as e:  # nunca bloquear el arranque del bot
        logger.warning("Fallo leyendo challenge_armed de Firestore: %s", e)
        return None


def _exit_ledger_id(position_key: str, intent: dict | None = None) -> str:
    """Genera una identidad estable para una posición y su generación."""
    intent = intent or {}
    position = intent.get("position") or {}
    generation = intent.get("entry_ts") or position.get("entry_ts") or ""
    raw = f"{position_key}|{generation}".encode("utf-8")
    return f"exit-{hashlib.sha256(raw).hexdigest()[:40]}"


def _exit_ledger_active(status: str) -> bool:
    return str(status or "").lower() in _ACTIVE_EXIT_STATUSES


def claim_exit_intent(position_key: str, intent: dict) -> dict:
    """Reclama un intent antes de enviar la primera pata.

    ``create`` es deliberadamente no sobrescribible: dos instancias que intenten
    enviar la misma salida reciben el mismo documento y solo una puede reclamarlo.
    """
    ledger_id = _exit_ledger_id(position_key, intent)
    now = datetime.now(timezone.utc).isoformat()
    record = dict(intent)
    record.update({
        "ledger_id": ledger_id,
        "position_key": position_key,
        "active": _exit_ledger_active(record.get("status")),
        "version": 1,
        "created_at": record.get("created_at") or now,
        "updated_at": now,
    })
    try:
        db = _get_db()
        ref = db.collection(_EXIT_LEDGER_COLLECTION).document(ledger_id)
        ref.create(record, timeout=10.0)
        return {"claimed": True, "ledger_id": ledger_id, "record": record}
    except Exception as exc:  # noqa: BLE001
        try:
            from google.api_core.exceptions import AlreadyExists
        except ImportError:
            AlreadyExists = ()
        if AlreadyExists and isinstance(exc, AlreadyExists):
            try:
                existing = ref.get(timeout=10.0)
                if existing.exists:
                    return {
                        "claimed": False, "ledger_id": ledger_id,
                        "record": existing.to_dict() or {},
                    }
            except Exception as read_exc:  # noqa: BLE001
                logger.error("No se pudo leer intent existente %s: %s", ledger_id, read_exc)
        logger.error("No se pudo reclamar exit intent %s: %s", ledger_id, exc)
        return {"claimed": False, "ledger_id": ledger_id, "unavailable": True}


def update_exit_intent(ledger_id: str, updates: dict) -> bool:
    """Actualiza un intent dedicado y deja el estado activo explícito."""
    if not ledger_id:
        return False
    try:
        db = _get_db()
        ref = db.collection(_EXIT_LEDGER_COLLECTION).document(str(ledger_id))
        current = ref.get(timeout=10.0)
        version = int((current.to_dict() or {}).get("version", 0)) + 1 if current.exists else 1
        data = dict(updates)
        if "status" in data:
            data["active"] = _exit_ledger_active(data["status"])
        data.update({
            "version": version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        ref.set(data, merge=True, timeout=10.0)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo actualizar exit intent %s: %s", ledger_id, exc)
        return False


def complete_exit_intent(ledger_id: str, reason: str = "") -> bool:
    """Marca completada una salida solo después de confirmar patas ausentes."""
    updates = {"status": "completed", "active": False}
    if reason:
        updates["completion_reason"] = reason
    return update_exit_intent(ledger_id, updates)


def read_active_exit_ledger() -> dict | None:
    """Lee intents activos de la colección dedicada.

    ``None`` significa fallo de lectura; ``{}`` significa consulta exitosa sin
    intents. El caller puede usar esa diferencia para no resucitar snapshots
    históricos tras una consulta dedicada exitosa.
    """
    try:
        db = _get_db()
        query = db.collection(_EXIT_LEDGER_COLLECTION).where("active", "==", True)
        result = {}
        for snap in query.stream(timeout=10.0):
            record = snap.to_dict() or {}
            position_key = record.get("position_key")
            if position_key:
                result[str(position_key)] = record
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fallo leyendo colección dedicada de exit intents: %s", exc)
        return None


def read_exit_ledger(max_days: int = 30) -> dict | None:
    """Lee el ledger de salidas persistido en los snapshots recientes.

    El filesystem de Cloud Run es efímero. Se usa el snapshot más reciente que
    contenga ``exit_intents`` como autoridad del ledger activo; si el snapshot
    del día actual existe y contiene un diccionario vacío, no se resucitan
    intents de días anteriores ya cerrados. El historial se agrega para
    observabilidad, mientras que las órdenes abiertas se vuelven a consultar
    directamente al broker durante el arranque.
    """
    try:
        dedicated = read_active_exit_ledger()
        if dedicated is not None:
            return {
                "source": "dedicated",
                "source_day": date.today().isoformat(),
                "exit_intents": dedicated,
                "exit_history": [],
                "open_broker_orders": [],
            }
        db = _get_db()
        latest_ledger = None
        history = []
        seen_history = set()
        for offset in range(max(1, int(max_days))):
            day = (date.today() - _timedelta(days=offset)).isoformat()
            snap = db.collection("polaris").document(day).get(timeout=10.0)
            if not snap.exists:
                continue
            payload = (snap.to_dict() or {}).get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if latest_ledger is None and "exit_intents" in payload:
                intents = payload.get("exit_intents")
                normalized_intents = intents if isinstance(intents, dict) else {}
                for position_key, intent in normalized_intents.items():
                    if isinstance(intent, dict) and not intent.get("ledger_id"):
                        intent["ledger_id"] = _exit_ledger_id(position_key, intent)
                latest_ledger = {
                    "source_day": day,
                    "exit_intents": normalized_intents,
                    "open_broker_orders": (
                        payload.get("open_broker_orders")
                        if isinstance(payload.get("open_broker_orders"), list)
                        else []
                    ),
                }
            day_history = payload.get("exit_history")
            if isinstance(day_history, list):
                for item in day_history:
                    if not isinstance(item, dict):
                        continue
                    marker = repr(sorted(item.items(), key=lambda pair: pair[0]))
                    if marker not in seen_history:
                        seen_history.add(marker)
                        history.append(item)
            if latest_ledger is not None and offset >= 1:
                # Un día previo basta para historial; no seguir leyendo documentos
                # indefinidamente en cada arranque.
                break
        if latest_ledger is None:
            return None
        latest_ledger["exit_history"] = history
        return latest_ledger
    except Exception as e:  # nunca bloquear el arranque del bot
        logger.warning("Fallo leyendo exit ledger de Firestore: %s", e)
        return None


def append_equity_point(equity: float) -> None:
    """Guarda un punto de la curva de equity del día."""
    try:
        db = _get_db()
        day = date.today().isoformat()
        from google.cloud.firestore_v1.transforms import ArrayUnion
        db.collection("polaris").document(day).update({
            "equity_curve": ArrayUnion([{
                "t": datetime.now(timezone.utc).isoformat(),
                "value": equity,
            }])
        })
    except Exception as e:
        logger.warning("Fallo al guardar punto de equity: %s", e)
