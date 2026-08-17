"""Guarda del piso de equity, en dos fases (regla del dueño, agosto 2026).

FASE 1 — RECUPERACIÓN (`recuperacion`)
    Mientras el equity esté por debajo de `challenge_target` ($100,000), el
    objetivo es volver a esa cifra. Rige un piso de seguridad más bajo
    (`recovery_floor`) para que el bot pueda operar: con el piso del reto
    ($99,900) por encima del equity actual se producía un bloqueo circular
    —el bot necesitaba ganar para poder operar y necesitaba operar para
    ganar— que lo dejaba inmóvil de forma permanente (17 ago 2026).

FASE 2 — RETO (`reto`)
    Al tocar `challenge_target` por primera vez, la fase queda ARMADA de
    forma permanente y pasa a regir el piso del reto ($99,900): a partir de
    ahí la cuenta se comporta como si solo tuviera $100 y no puede bajar de
    ese piso.

Por qué la fase se ARMA y no se recalcula: si dependiera solo de comparar
equity con el objetivo, romper el piso del reto devolvería al bot a modo
recuperación —que tiene un piso más bajo— y el piso de $99,900 no protegería
nada. El latch (`_challenge_armed`) hace que la protección sea de una sola
dirección. Vive en el estado del bot y se reconstruye desde Firestore al
arrancar, porque el JSON local es efímero (ver AGENTS.md §34).

El evento se notifica por Telegram solo al cruzar un umbral, no en cada tick.
"""
import logging

logger = logging.getLogger("risk.floor")

DEFAULT_FLOOR_CFG = {
    # Piso del reto $100 -> $200; rige una vez armada la fase.
    "equity_floor": 99900.0,
    # Al alcanzarlo se arma el reto de forma permanente.
    "challenge_target": 100000.0,
    # Piso de seguridad durante la recuperación. Debe quedar por debajo del
    # equity de partida o el bot no podría operar; limita cuánto más se puede
    # perder mientras se intenta volver al objetivo.
    "recovery_floor": 99400.0,
}


def _cfg(cfg: dict = None) -> dict:
    return {**DEFAULT_FLOOR_CFG, **(cfg or {})}


def active_floor(equity: float, bot_state: dict, cfg: dict = None) -> tuple:
    """Devuelve (piso_vigente, fase, reto_armado) sin mutar el estado."""
    c = _cfg(cfg)
    armed = bool(bot_state.get("_challenge_armed")) or \
        float(equity) >= float(c["challenge_target"])
    if armed:
        return float(c["equity_floor"]), "reto", True
    return float(c["recovery_floor"]), "recuperacion", False


def check_floor(equity: float, bot_state: dict, cfg: dict = None) -> dict:
    """Devuelve el estado del piso para el tick actual.

    Claves: below_floor, crossed, reason, phase, floor, target,
    challenge_armed. `crossed` solo es True cuando cambia algo (entrar o
    salir del piso, o armar el reto), para que Telegram avise una vez.
    """
    c = _cfg(cfg)
    target = float(c["challenge_target"])
    equity = float(equity)

    was_armed = bool(bot_state.get("_challenge_armed"))
    just_armed = (not was_armed) and equity >= target
    if just_armed:
        bot_state["_challenge_armed"] = True
        logger.warning("RETO ARMADO: equity %.2f alcanzó el objetivo %.2f; "
                       "desde ahora rige el piso %.2f",
                       equity, target, float(c["equity_floor"]))

    floor, phase, armed = active_floor(equity, bot_state, c)
    below = equity < floor
    was_below = bool(bot_state.get("_floor_below"))
    crossed = (below != was_below) or just_armed
    bot_state["_floor_below"] = below

    base = dict(phase=phase, floor=floor, target=target,
                challenge_armed=armed)

    if just_armed:
        return dict(base, below_floor=below, crossed=True,
                    reason=(f"OBJETIVO ALCANZADO: equity ${equity:,.2f} >= "
                            f"${target:,.0f}. Reto $100→$200 activado; "
                            f"piso ${floor:,.0f}"))
    if below:
        if crossed:
            reason = (f"PISO ROTADO ({phase}): equity ${equity:,.2f} bajo "
                      f"${floor:,.0f}; sin nuevas entradas hasta recuperar")
        else:
            reason = (f"equity ${equity:,.2f} aún bajo el piso "
                      f"${floor:,.0f} ({phase})")
        return dict(base, below_floor=True, crossed=crossed, reason=reason)
    if crossed and was_below:
        return dict(base, below_floor=False, crossed=True,
                    reason=(f"PISO RECUPERADO ({phase}): equity "
                            f"${equity:,.2f} >= ${floor:,.0f}; operativa "
                            f"reactivada"))
    return dict(base, below_floor=False, crossed=False, reason="")
