"""Audit historical gamma-wall coverage without inventing unavailable option data."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu/backtests")
CACHES = [
    ROOT / "defined_risk_option_history_2026-08-18/option_bars.pkl",
    ROOT / "wheel_option_history_2026-08-18/option_bars.pkl",
]
VARIANTS = ["oi_only", "gex_proxy", "gamma_flip", "call_wall_filter", "put_wall_filter"]
REQUIRED = {"open_interest", "gamma", "spot", "multiplier"}


def inspect(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "status": "REJECT_DATA", "reason": "cache_missing"}
    frame = pd.read_pickle(path)
    missing = sorted(REQUIRED - set(frame.columns))
    if missing:
        return {"path": str(path), "status": "REJECT_DATA", "reason": "missing_fields",
                "missing_fields": missing, "rows": len(frame), "columns": list(frame.columns)}
    return {"path": str(path), "status": "OK", "rows": len(frame), "columns": list(frame.columns)}


def main() -> None:
    coverage = [inspect(path) for path in CACHES]
    rows = []
    for variant in VARIANTS:
        for item in coverage:
            rows.append({"variant": variant, "cache": item["path"],
                         "status": item["status"], "reason": item.get("reason", ""),
                         "trades": 0, "return_pct": None, "drawdown_pct": None})
    result = pd.DataFrame(rows)
    result.to_csv(ROOT / "gamma_walls_backtests_2026-08-18_results.csv", index=False)
    manifest = {"status": "REJECT_DATA" if any(item["status"] != "OK" for item in coverage) else "OK",
                "variants": VARIANTS, "coverage": coverage,
                "policy": "No proxy backtest without point-in-time OI, gamma, spot and multiplier"}
    (ROOT / "gamma_walls_backtests_2026-08-18_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
