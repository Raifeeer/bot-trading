"""Reproducible A/B comparison for PAPER research.

This script is research-only: it never calls Alpaca order endpoints, Cloud Run,
or Firestore writes. Baseline and candidate specs share one in-memory dataset,
identical windows, universe, cost overlays, and engine commit.

Usage:
  python3 scripts/run_ab_comparison.py \
    --baseline-key regime_hold_cash_recent_2026 \
    --candidate-key breakout55_recent_2026_r15

The keys are resolved from ``run_research_matrix.build_specs``. For a custom
parameter change, pass JSON files with one spec per window via
``--baseline-json`` and ``--candidate-json``. Each JSON object must contain
``key`` plus the same fields accepted by ``loop_backtests.run_scenario``.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import UNI_RETO, run_scenario  # noqa: E402
from scripts.run_research_matrix import build_specs, metrics  # noqa: E402

OUT = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
OUT.mkdir(parents=True, exist_ok=True)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def resolve_specs(args: argparse.Namespace) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    if bool(args.baseline_json) != bool(args.candidate_json):
        raise SystemExit("baseline-json y candidate-json deben proporcionarse juntos")
    if args.baseline_json:
        def load(path: str) -> list[tuple[str, dict]]:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                rows = [rows]
            result = []
            for row in rows:
                item = copy.deepcopy(row)
                key = item.pop("key")
                result.append((key, item))
            return result
        return load(args.baseline_json), load(args.candidate_json)

    available = dict(build_specs())
    if args.baseline_key not in available:
        raise SystemExit(f"baseline desconocido: {args.baseline_key}")
    if args.candidate_key not in available:
        raise SystemExit(f"candidate desconocido: {args.candidate_key}")
    baseline = [(args.baseline_key, available[args.baseline_key])]
    candidate = [(args.candidate_key, available[args.candidate_key])]
    return baseline, candidate


def run_one(label: str, key: str, spec: dict, data: dict) -> dict:
    started = time.time()
    try:
        equity, trades, curve, dd_pct, max_eq = run_scenario(
            key, copy.deepcopy(spec), data
        )
        row = metrics(key, spec, equity, trades, curve, time.time() - started)
        row.update({
            "arm": label,
            "status": "ok",
            "engine_max_drawdown_pct": round(float(dd_pct), 4),
            "max_equity": round(float(max_eq), 4),
        })
        return row
    except Exception as exc:  # noqa: BLE001
        return {
            "arm": label,
            "key": key,
            "window": "..".join(spec.get("window_dates", ("", ""))),
            "motor": spec.get("motor"),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def paired_row(base: dict, cand: dict) -> dict:
    numeric = (
        "equity_final", "return_pct", "trades", "win_rate_pct",
        "profit_factor", "max_drawdown_pct", "engine_max_drawdown_pct",
    )
    result = {
        "baseline_key": base.get("key"),
        "candidate_key": cand.get("key"),
        "window": cand.get("window") or base.get("window"),
        "baseline_status": base.get("status"),
        "candidate_status": cand.get("status"),
    }
    for field in numeric:
        b = base.get(field)
        c = cand.get(field)
        result[f"baseline_{field}"] = b
        result[f"candidate_{field}"] = c
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            result[f"delta_{field}"] = round(float(c) - float(b), 6)
        else:
            result[f"delta_{field}"] = None
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-key", default="regime_hold_cash_recent_2026")
    parser.add_argument("--candidate-key", default="breakout55_recent_2026_r15")
    parser.add_argument("--baseline-json")
    parser.add_argument("--candidate-json")
    parser.add_argument("--provider", default=os.environ.get("DATA_PROVIDER", "yfinance"))
    parser.add_argument("--output-prefix", default="ab_comparison")
    args = parser.parse_args()

    baseline, candidate = resolve_specs(args)
    if len(baseline) != len(candidate):
        raise SystemExit("baseline y candidate deben tener el mismo número de ventanas")

    baseline_windows = [spec[1].get("window_dates") for spec in baseline]
    candidate_windows = [spec[1].get("window_dates") for spec in candidate]
    if baseline_windows != candidate_windows:
        raise SystemExit("baseline y candidate deben usar las mismas ventanas")

    all_tickers = sorted({
        ticker
        for _, spec in baseline + candidate
        for ticker in spec.get("tickers", UNI_RETO)
    })
    feed = MarketDataFeed(args.provider)
    print(f"Descargando una vez {len(all_tickers)} tickers para A/B...")
    data = feed.history(all_tickers, "1d", days=520)
    if not data:
        raise SystemExit("No se obtuvieron datos; no se ejecutó ningún brazo")

    base_rows = []
    cand_rows = []
    for (base_key, base_spec), (cand_key, cand_spec) in zip(baseline, candidate, strict=True):
        base_rows.append(run_one("baseline", base_key, base_spec, data))
        cand_rows.append(run_one("candidate", cand_key, cand_spec, data))

    pairs = [paired_row(b, c) for b, c in zip(base_rows, cand_rows, strict=True)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = OUT / f"{args.output_prefix}_{stamp}"
    paired_path = prefix.with_suffix(".csv")
    pd.DataFrame(pairs).to_csv(paired_path, index=False)
    meta_path = prefix.with_suffix(".json")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": git_commit(),
        "provider": args.provider,
        "universe": all_tickers,
        "windows": [list(w) for w in baseline_windows],
        "data_loaded_once": True,
        "orders_submitted": False,
        "source_hash": hashlib.sha256(
            json.dumps(sorted(data), separators=(",", ":")).encode()
        ).hexdigest(),
        "baseline": base_rows,
        "candidate": cand_rows,
        "paired_csv": str(paired_path),
        "decision_rule": {
            "do_not_promote_on_return_alone": True,
            "require_out_of_sample_positive_or_non_degrading": True,
            "require_drawdown_not_worse": True,
            "require_cost_and_slippage_declared": True,
            "paper_only_until_reviewed": True,
        },
    }
    meta_path.write_text(json.dumps(manifest, indent=2, default=str) + "", encoding="utf-8")
    print(paired_path)
    print(meta_path)


if __name__ == "__main__":
    main()


"""The matrix key defaults are illustrative; use --help and inspect build_specs
for exact keys in the current repository. The script intentionally fails closed
when the two arms differ in windows or when no data is available.
"""


"""No live orders are possible from this module: run_scenario is the offline
backtest engine and the script never imports an executor or Cloud client.
"""
