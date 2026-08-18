"""Evaluación shadow de estructuras de opciones de riesgo definido.

Este módulo solo lee cadenas y snapshots de Alpaca, construye candidatos
informativos y devuelve payload serializable. No importa el executor ni expone
una ruta para enviar órdenes. La decisión operativa sigue perteneciendo a las
estrategias existentes y al RiskManager.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from options.chains import Leg, OptionContract, OptionType, OptionStructure


CANDIDATES = (
    {
        "name": "bear_call_credit",
        "direction": "bear",
        "dte_target": 30,
        "dte_min": 21,
        "dte_max": 45,
        "short_otm": 0.05,
        "long_otm": 0.10,
        "kind": "call",
        "regimes": ("bear",),
    },
    {
        "name": "bull_put_credit",
        "direction": "bull",
        "dte_target": 45,
        "dte_min": 30,
        "dte_max": 45,
        "short_otm": 0.05,
        "long_otm": 0.10,
        "kind": "put",
        "regimes": ("bull",),
    },
    {
        "name": "iron_condor",
        "direction": "neutral",
        "dte_target": 45,
        "dte_min": 30,
        "dte_max": 45,
        "short_otm": 0.05,
        "long_otm": 0.10,
        "kind": "both",
        "regimes": ("cash",),
    },
)


def _spot_from_frames(frames: dict[str, Any]) -> float | None:
    for timeframe in ("1d", "15min", "5min"):
        frame = frames.get(timeframe)
        if frame is None or frame.empty:
            continue
        for column in ("close", "Close"):
            if column in frame.columns:
                value = frame[column].iloc[-1]
                return float(value) if value is not None else None
    return None


def _eligible(contract: OptionContract, max_spread_bps: float) -> bool:
    return bool(
        contract.mid > 0.05
        and contract.spread_bps <= max_spread_bps
        and (contract.volume >= 10 or contract.open_interest >= 100)
    )


def _nearest_expiry(chain: list[OptionContract], target: date) -> date | None:
    expirations = sorted({c.expiration for c in chain})
    return min(expirations, key=lambda exp: abs((exp - target).days)) if expirations else None


def _pick(chain: list[OptionContract], expiration: date, spot: float, kind: OptionType, otm: float, max_spread_bps: float, used: set[str] | None = None) -> OptionContract | None:
    used = used or set()
    target = spot * (1.0 + otm) if kind == OptionType.CALL else spot * (1.0 - otm)
    candidates = [c for c in chain if c.expiration == expiration and c.option_type == kind and c.symbol not in used and _eligible(c, max_spread_bps)]
    return min(candidates, key=lambda c: abs(c.strike - target)) if candidates else None


def _force_order(near: OptionContract, far: OptionContract, kind: OptionType) -> tuple[OptionContract, OptionContract] | None:
    if kind == OptionType.CALL and far.strike > near.strike:
        return near, far
    if kind == OptionType.PUT and far.strike < near.strike:
        return near, far
    return None


def _vertical(chain: list[OptionContract], spot: float, candidate: dict, max_spread_bps: float) -> OptionStructure | None:
    kind = OptionType.CALL if candidate["kind"] == "call" else OptionType.PUT
    expiration = _nearest_expiry(chain, date.today() + timedelta(days=candidate["dte_target"]))
    if expiration is None:
        return None
    short = _pick(chain, expiration, spot, kind, candidate["short_otm"], max_spread_bps)
    if short is None:
        return None
    used = {short.symbol}
    long = _pick(chain, expiration, spot, kind, candidate["long_otm"], max_spread_bps, used)
    if long is None or _force_order(short, long, kind) is None:
        return None
    legs = [Leg(short, -1), Leg(long, +1)]
    net = sum(leg.net_premium for leg in legs)
    width = abs(short.strike - long.strike) * 100.0
    credit = max(-net, 0.0)
    return OptionStructure(
        name=f"{candidate['name']}_{short.underlying}_{expiration}",
        legs=legs,
        underlying=short.underlying,
        rationale="Riesgo definido; candidato shadow, no ejecutable",
        max_risk=max(width - credit, 0.01),
        max_profit=credit,
        breakevens=[],
    )


def _condor(call_chain: list[OptionContract], put_chain: list[OptionContract], spot: float, candidate: dict, max_spread_bps: float) -> OptionStructure | None:
    all_exp = sorted({c.expiration for c in call_chain} & {c.expiration for c in put_chain})
    if not all_exp:
        return None
    target = date.today() + timedelta(days=candidate["dte_target"])
    expiration = min(all_exp, key=lambda exp: abs((exp - target).days))
    short_put = _pick(put_chain, expiration, spot, OptionType.PUT, candidate["short_otm"], max_spread_bps)
    long_put = _pick(put_chain, expiration, spot, OptionType.PUT, candidate["long_otm"], max_spread_bps, {short_put.symbol} if short_put else set())
    short_call = _pick(call_chain, expiration, spot, OptionType.CALL, candidate["short_otm"], max_spread_bps)
    long_call = _pick(call_chain, expiration, spot, OptionType.CALL, candidate["long_otm"], max_spread_bps, {short_call.symbol} if short_call else set())
    if not all([short_put, long_put, short_call, long_call]):
        return None
    if not (long_put.strike < short_put.strike < spot < short_call.strike < long_call.strike):
        return None
    legs = [Leg(short_put, -1), Leg(long_put, +1), Leg(short_call, -1), Leg(long_call, +1)]
    net = sum(leg.net_premium for leg in legs)
    credit = max(-net, 0.0)
    put_width = (short_put.strike - long_put.strike) * 100.0
    call_width = (long_call.strike - short_call.strike) * 100.0
    return OptionStructure(
        name=f"iron_condor_{short_put.underlying}_{expiration}",
        legs=legs,
        underlying=short_put.underlying,
        rationale="Riesgo definido para régimen cash/lateral; candidato shadow",
        max_risk=max(max(put_width, call_width) - credit, 0.01),
        max_profit=credit,
        breakevens=[],
    )


def _serialize_structure(structure: OptionStructure, candidate: dict, regime: str, floor_blocked: bool) -> dict:
    legs = []
    for leg in structure.legs:
        contract = leg.contract
        legs.append({
            "symbol": contract.symbol,
            "side": "buy" if leg.quantity > 0 else "sell",
            "quantity": abs(leg.quantity),
            "type": contract.option_type.value,
            "strike": contract.strike,
            "expiration": contract.expiration.isoformat(),
            "bid": contract.bid,
            "ask": contract.ask,
            "mid": contract.mid,
            "delta": contract.delta,
            "iv": contract.iv,
            "volume": contract.volume,
            "open_interest": contract.open_interest,
        })
    credit = max(-structure.net_premium, 0.0)
    return {
        "strategy": candidate["name"],
        "status": "available" if regime in candidate["regimes"] and not floor_blocked else "regime_or_floor_blocked",
        "regime_allowed": regime in candidate["regimes"],
        "floor_allowed": not floor_blocked,
        "direction": candidate["direction"],
        "dte": (structure.legs[0].contract.expiration - date.today()).days,
        "net_premium_per_share": structure.net_premium,
        "credit_per_contract": credit * 100.0,
        "max_risk_per_contract": structure.max_risk,
        "max_profit_per_contract": structure.max_profit,
        "legs": legs,
        "orders_allowed": False,
        "risk_authority": "RiskManager_not_bypassed",
    }


def _load_chain(feed, symbol: str, kind: OptionType, candidate: dict, spot: float, max_spread_bps: float) -> list[OptionContract]:
    chain = feed.contracts(
        symbol,
        kind,
        expiration_ge=date.today() + timedelta(days=candidate["dte_min"]),
        expiration_le=date.today() + timedelta(days=candidate["dte_max"]),
        max_results=400,
    )
    return feed.snapshots(chain, spot=spot) if chain else []


def evaluate_defined_risk_shadow(feed, ticker_frames: dict[str, dict[str, Any]], regime: str, floor_blocked: bool, cfg: dict) -> dict:
    """Evalúa candidatos de riesgo definido sin tocar el executor.

    El método no tiene acceso al executor y todas las salidas incluyen
    ``orders_allowed=False``. Cualquier fallo de una cadena queda aislado en el
    símbolo/candidato correspondiente.
    """
    shadow_cfg = cfg.get("defined_risk_shadow", {}) or {}
    if not shadow_cfg.get("enabled", False):
        return {"enabled": False, "mode": "disabled", "orders_allowed": False, "symbols": {}}
    max_spread_bps = float(shadow_cfg.get("max_spread_bps", 800.0))
    symbols = list(ticker_frames)[: int(shadow_cfg.get("max_symbols", len(ticker_frames)))]
    output = {"enabled": True, "mode": shadow_cfg.get("mode", "shadow"), "orders_allowed": False, "influence_entries": False, "source_version": "defined-risk-shadow-v1", "symbols": {}}
    for symbol in symbols:
        frames = ticker_frames[symbol]
        spot = _spot_from_frames(frames)
        symbol_out = {"spot": spot, "regime": regime, "candidates": []}
        if not spot or spot <= 0:
            symbol_out["error"] = "missing_spot"
            output["symbols"][symbol] = symbol_out
            continue
        chains: dict[str, list[OptionContract]] = {}
        for candidate in CANDIDATES:
            try:
                if candidate["kind"] in {"call", "both"} and "call" not in chains:
                    chains["call"] = _load_chain(feed, symbol, OptionType.CALL, candidate, spot, max_spread_bps)
                if candidate["kind"] in {"put", "both"} and "put" not in chains:
                    chains["put"] = _load_chain(feed, symbol, OptionType.PUT, candidate, spot, max_spread_bps)
                structure = (_condor(chains.get("call", []), chains.get("put", []), spot, candidate, max_spread_bps) if candidate["kind"] == "both" else _vertical(chains[candidate["kind"]], spot, candidate, max_spread_bps))
                if structure is None:
                    symbol_out["candidates"].append({"strategy": candidate["name"], "status": "unavailable", "reason": "insufficient_liquid_legs", "orders_allowed": False})
                else:
                    symbol_out["candidates"].append(_serialize_structure(structure, candidate, regime, floor_blocked))
            except Exception as exc:  # noqa: BLE001
                symbol_out["candidates"].append({"strategy": candidate["name"], "status": "error", "reason": type(exc).__name__, "orders_allowed": False})
        output["symbols"][symbol] = symbol_out
    counts = {candidate["name"]: {"available": 0, "unavailable": 0, "blocked": 0, "error": 0} for candidate in CANDIDATES}
    for symbol_out in output["symbols"].values():
        for candidate_out in symbol_out.get("candidates", []):
            name = candidate_out["strategy"]
            status = candidate_out.get("status", "error")
            bucket = "blocked" if status == "regime_or_floor_blocked" else status
            if name in counts and bucket in counts[name]:
                counts[name][bucket] += 1
    output["counts"] = counts
    return output
