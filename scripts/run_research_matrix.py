#!/usr/bin/env python3
"""Run a bounded, reproducible research matrix over dated market windows.

This is research-only. It does not modify Cloud Run or submit orders.
Primary runs exclude the current-state earnings calendar because it is not
point-in-time. Each result records the explicit slippage overlay.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import (  # noqa: E402
    CAPITAL_INICIAL,
    UNI_RETO,
    run_scenario,
)

OUT = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
OUT.mkdir(parents=True, exist_ok=True)

WINDOWS = {
    "lateral_2025": ("2025-09-01", "2025-12-31"),
    "selloff_2026": ("2026-01-01", "2026-04-30"),
    "recent_2026": ("2026-04-01", "2026-08-14"),
    "latest_30d": ("2026-07-01", "2026-08-14"),
}


def spec(name, motor, window, *, risk=0.15, max_pos=2, dte=21,
         delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
         slippage_pct=0.03, commission=0.65, equity_cost_pct=0.002):
    start, end = WINDOWS[window]
    sc = dict(
        name=name,
        motor=motor,
        window_dates=(start, end),
        tickers=UNI_RETO,
        risk_pct=risk,
        max_pos=max_pos,
        dte=dte,
        delta_l=delta_l,
        delta_s=delta_s,
        tp=tp,
        sl=sl,
        max_rv=None,
        anti_earnings=False,
        slippage_pct=slippage_pct,
        equity_cost_pct=equity_cost_pct,
    )
    if commission is not None:
        sc["comision"] = commission
    return sc


def build_specs():
    rows = []
    for window in WINDOWS:
        rows.append((f"hold_{window}", spec(
            f"Hold semanal {window}", "hold_weekly", window,
            risk=0.25, max_pos=8, commission=None, slippage_pct=0.0,
            equity_cost_pct=0.002)))
        rows.append((f"regime_hold_cash_{window}", spec(
            f"Regime hold/cash {window}", "regime_hold_cash", window,
            risk=0.25, max_pos=8, commission=None, slippage_pct=0.0,
            equity_cost_pct=0.002)))
        for risk in (0.10, 0.15, 0.20):
            for slip in (0.02, 0.05):
                rows.append((
                    f"smc_{window}_r{int(risk*100)}_s{int(slip*100)}",
                    spec(f"SMC {window} risk {risk:.0%} slip {slip:.0%}",
                         "smc_daily", window, risk=risk, max_pos=2,
                         dte=21, delta_l=0.30, delta_s=0.10,
                         tp=1.5, sl=0.5, slippage_pct=slip),
                ))
        for dte in (14, 21, 30):
            rows.append((
                f"smc_dte_{window}_{dte}",
                spec(f"SMC {window} DTE {dte}", "smc_daily", window,
                     risk=0.15, max_pos=2, dte=dte,
                     delta_l=0.25, delta_s=0.10,
                     tp=1.3, sl=0.5, slippage_pct=0.03),
            ))
    for window in ("selloff_2026", "recent_2026", "latest_30d"):
        for risk in (0.10, 0.15, 0.20):
            rows.append((
                f"regime_{window}_r{int(risk*100)}",
                spec(f"Regime aware {window} risk {risk:.0%}",
                     "regime_aware", window, risk=risk, max_pos=2,
                     slippage_pct=0.03),
            ))
    for window in ("selloff_2026", "latest_30d"):
        for risk in (0.10, 0.15):
            rows.append(
                (f"put_choch_{window}_r{int(risk*100)}",
                spec(f"Put CHoCH {window} risk {risk:.0%}",
                     "put_choch", window, risk=risk, max_pos=2,
                     dte=21, slippage_pct=0.03),
            ))
    for window in ("lateral_2025", "selloff_2026", "recent_2026", "latest_30d"):
        for motor in ("breakout20", "breakout55"):
            for risk in (0.10, 0.15):
                rows.append((
                    f"{motor}_{window}_r{int(risk*100)}",
                    spec(f"{motor} {window} risk {risk:.0%}", motor, window,
                         risk=risk, max_pos=2, dte=21,
                         delta_l=0.25, delta_s=0.10,
                         tp=1.3, sl=0.5, slippage_pct=0.03),
                ))
    return rows


def metrics(key, sc, equity, trades, equity_curve, elapsed):
    tdf = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    gross_profit = float(tdf.loc[tdf.pnl > 0, "pnl"].sum()) if len(tdf) else 0.0
    gross_loss = float(-tdf.loc[tdf.pnl < 0, "pnl"].sum()) if len(tdf) else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else None
    eq = equity_curve["equity"].astype(float) if len(equity_curve) else pd.Series(dtype=float)
    peak_to_trough = ((eq / eq.cummax()) - 1.0).min() * 100 if len(eq) else 0.0
    return {
        "key": key,
        "window": sc["window_dates"][0] + ".." + sc["window_dates"][1],
        "name": sc["name"],
        "motor": sc["motor"],
        "risk_pct": sc["risk_pct"],
        "max_pos": sc["max_pos"],
        "dte": sc["dte"],
        "delta_l": sc["delta_l"],
        "delta_s": sc["delta_s"],
        "tp": sc["tp"],
        "sl": sc["sl"],
        "slippage_pct": sc.get("slippage_pct", 0.0),
        "commission_usd_per_leg": sc.get("comision", 0.0),
        "equity_final": round(float(equity), 4),
        "return_pct": round((float(equity) / CAPITAL_INICIAL - 1) * 100, 4),
        "trades": int(len(tdf)),
        "win_rate_pct": round(float((tdf.pnl > 0).mean() * 100), 2) if len(tdf) else 0.0,
        "profit_factor": round(pf, 4) if pf is not None else None,
        "max_drawdown_pct": round(float(peak_to_trough), 4),
        "elapsed_s": round(elapsed, 2),
    }


def main():
    specs = build_specs()
    feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
    print(f"Descargando {len(UNI_RETO)} tickers para {len(specs)} configuraciones...")
    data = feed.history(UNI_RETO, "1d", days=520)
    results = []
    for i, (key, sc) in enumerate(specs, 1):
        t0 = time.time()
        try:
            equity, trades, curve, dd_pct, _max_eq = run_scenario(key, sc, data)
            row = metrics(key, sc, equity, trades, curve, time.time() - t0)
            row["engine_max_drawdown_pct"] = round(float(dd_pct), 4)
            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001
            row = {"key": key, "name": sc["name"], "motor": sc["motor"],
                   "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        results.append(row)
        print(f"[{i}/{len(specs)}] {key}: {row.get('return_pct')}% / "
              f"dd={row.get('engine_max_drawdown_pct')} / {row['status']}")

    out = OUT / "research_matrix_2026-08-15.csv"
    pd.DataFrame(results).to_csv(out, index=False)
    meta = OUT / "research_matrix_2026-08-15.json"
    meta.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance via MarketDataFeed; primary runs anti-earnings off",
        "universe": UNI_RETO,
        "windows": WINDOWS,
        "count": len(results),
        "csv": str(out),
    }, indent=2) + "\n", encoding="utf-8")
    print(out)
    print(meta)


if __name__ == "__main__":
    main()
