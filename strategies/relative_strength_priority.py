"""Overlay puro de priorización de líderes sobre señales existentes."""
from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.relative_strength_rotation import evaluate_relative_strength


def evaluate_priority(
    frames: dict[str, pd.DataFrame],
    *,
    horizon_bars: int = 20,
    top_k: int = 2,
    gate: str = "bull",
    current_regime: str = "bull",
    only_positive: bool = True,
    asof_timestamp: str | None = None,
) -> dict[str, Any]:
    """Rankear líderes as-of y marcar qué señales pasarían un overlay bull."""
    if top_k < 1:
        raise ValueError("top_k debe ser positivo")
    if gate not in {"none", "bull"}:
        raise ValueError("gate no soportado")
    top_percentile = max(0.500001, 1.0 - (top_k / max(1, len(frames))))
    result = evaluate_relative_strength(
        frames,
        horizon_bars=horizon_bars,
        top_percentile=top_percentile,
        bottom_percentile=0.0,
        only_positive=only_positive,
        allow_shorts=False,
        benchmark="equal_weight_universe",
        asof_timestamp=asof_timestamp,
    )
    valid = [observation for observation in result.get("observations", []) if observation.get("rank") is not None]
    leaders = sorted(valid, key=lambda observation: (-float(observation["return_formation"]), observation["symbol"]))[:top_k]
    leader_symbols = {observation["symbol"] for observation in leaders if observation.get("status") == "leader"}
    gate_allows = gate == "none" or current_regime == "bull"
    observations = []
    for observation in result.get("observations", []):
        enriched = dict(observation)
        enriched.update(
            {
                "priority_candidate": observation.get("symbol") in leader_symbols,
                "would_pass_overlay": observation.get("symbol") in leader_symbols and gate_allows,
                "overlay_gate": gate,
                "current_regime": current_regime,
                "mode": "shadow",
                "influence_entries": False,
                "orders_allowed": False,
            }
        )
        observations.append(enriched)
    return {
        **result,
        "observations": observations,
        "top_k": top_k,
        "horizon_bars": horizon_bars,
        "only_positive": only_positive,
        "overlay_gate": gate,
        "current_regime": current_regime,
        "leader_symbols": sorted(leader_symbols),
        "mode": "shadow",
        "influence_entries": False,
        "orders_allowed": False,
        "risk_authority": "risk_manager_only",
        "source_version": "relative-strength-priority-v1",
    }
