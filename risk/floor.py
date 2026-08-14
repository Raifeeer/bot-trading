"""Guarda del piso de equity (regla del dueño, agosto 2026).

Regla: la cuenta paper no debe bajar de $99,900. Mientras el equity esté por
debajo del piso, el bot no abre nuevas posiciones (solo gestiona las
existentes con sus stops propios de prima). Cuando el equity recupera el
piso, se reactiva la operativa normal. El evento se notifica por Telegram
al cruzar el umbral (no en cada tick).
"""
import logging

logger = logging.getLogger("risk.floor")

DEFAULT_FLOOR_CFG = {
    "equity_floor": 99900.0,
}


def check_floor(equity: float, bot_state: dict, cfg: dict = None) -> dict:
    """Devuelve {"below_floor": bool, "crossed": bool, "reason": str}.

    crossed=True solo cuando el estado cambia (entrar/salir del piso), para
    que Telegram avise una sola vez por evento."""
    cfg = {**DEFAULT_FLOOR_CFG, **(cfg or {})}
    floor = float(cfg["equity_floor"])
    below = equity < floor
    was_below = bool(bot_state.get("_floor_below"))
    crossed = below != was_below
    bot_state["_floor_below"] = below
    if below:
        if crossed:
            reason = (f"PISO ROTADO: equity ${equity:,.2f} bajo "
                      f"${floor:,.0f}; sin nuevas entradas hasta recuperar")
        else:
            reason = f"equity ${equity:,.2f} aún bajo el piso ${floor:,.0f}"
        return {"below_floor": True, "crossed": crossed, "reason": reason}
    if crossed and was_below:
        return {"below_floor": False, "crossed": True,
                "reason": f"PISO RECUPERADO: equity ${equity:,.2f} >= "
                          f"${floor:,.0f}; operativa reactivada"}
    return {"below_floor": False, "crossed": False, "reason": ""}
