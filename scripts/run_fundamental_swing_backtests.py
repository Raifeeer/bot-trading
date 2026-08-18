"""Backtest point-in-time fundamental gates over the live SwingTrend logic."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HISTORY = Path("/home/ubuntu/backtests/setup_history")
SNAPSHOTS = Path("/home/ubuntu/backtests/fundamental_history/snapshots")
OUT = Path("/home/ubuntu/backtests")
CAPITAL = 100_000.0
SYMBOLS = ["PLTR", "F", "TSLA", "AMD", "BB"]
VARIANTS = ["baseline", "value_quality", "growth_quality", "fundamental_rank", "quality_combo"]
SLIPPAGE_BPS = 5.0
FAST = 20
SLOW = 50
TREND = 200
ATR_PERIOD = 14
STOP_MULT = 3.0
TARGET_MULT = 6.0
MIN_HOLD = 2
MAX_HOLD = 20


def _atr(frame: pd.DataFrame) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat([frame["high"] - frame["low"],
                    (frame["high"] - prev).abs(),
                    (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _load_price(symbol: str) -> pd.DataFrame:
    frame = pd.read_pickle(HISTORY / f"{symbol}.pkl").copy()
    frame.index = (pd.to_datetime(frame.index, utc=True)
                   .tz_convert("America/New_York").tz_localize(None).normalize())
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame["fast"] = frame["close"].rolling(FAST).mean()
    frame["slow"] = frame["close"].rolling(SLOW).mean()
    frame["trend"] = frame["close"].rolling(TREND).mean()
    frame["atr"] = _atr(frame)
    frame["cross_up"] = (frame["fast"].shift(1) <= frame["slow"].shift(1)) & (frame["fast"] > frame["slow"])
    frame["cross_down"] = (frame["fast"].shift(1) >= frame["slow"].shift(1)) & (frame["fast"] < frame["slow"])
    return frame.dropna(subset=["open", "high", "low", "close"])


def _load_fundamentals() -> pd.DataFrame:
    frame = pd.read_csv(SNAPSHOTS / "all_snapshots.csv")
    frame["decision_date"] = pd.to_datetime(frame["decision_date"])
    return frame


def _make_flags(fundamentals: pd.DataFrame) -> pd.DataFrame:
    df = fundamentals.copy()
    date_groups = []
    for date, group in df.groupby("decision_date"):
        group = group.copy()
        valid_pe = group["pe"].where(group["pe"] > 0)
        valid_de = group["de"].where(group["de"] >= 0)
        pe_cut = valid_pe.quantile(0.60)
        de_cut = valid_de.quantile(0.70)
        group["value_quality"] = (group["pe"] > 0) & (group["pe"] <= pe_cut) & (group["revenue_growth"] >= 0) & (group["de"] <= de_cut)
        group["growth_quality"] = (group["revenue_growth"] > 0.15) & ((group["eps_growth"] > 0) | group["eps_growth"].isna()) & (group["de"] <= de_cut)
        enough = group[["revenue_growth", "eps_growth", "de"]].notna().sum(axis=1) >= 2
        score = (group["revenue_growth"].rank(pct=True).fillna(0.0)
                 + group["eps_growth"].rank(pct=True).fillna(0.0)
                 - group["de"].rank(pct=True).fillna(0.0))
        group["fundamental_rank"] = enough & (score >= score[enough].median() if enough.any() else False)
        group["quality_combo"] = group["value_quality"] | group["growth_quality"]
        date_groups.append(group)
    return pd.concat(date_groups, ignore_index=True)


def _fundamental_ok(flags: pd.DataFrame, symbol: str, date: pd.Timestamp, variant: str) -> bool:
    if variant == "baseline":
        return True
    cutoff = pd.Timestamp(date).tz_localize(None) - pd.Timedelta(days=1)
    eligible = flags[(flags["symbol"] == symbol) & (flags["decision_date"] <= cutoff)]
    if eligible.empty:
        return False
    return bool(eligible.sort_values("decision_date").iloc[-1][variant])


def _windows(last: pd.Timestamp) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    end = last.normalize() + pd.Timedelta(days=1)
    return {
        "selloff_spring_2026": (pd.Timestamp("2026-03-01"), pd.Timestamp("2026-05-01")),
        "recovery_may_2026": (pd.Timestamp("2026-05-01"), pd.Timestamp("2026-06-01")),
        "summer_2026": (pd.Timestamp("2026-06-01"), end),
        "latest_30d": (end - pd.Timedelta(days=30), end),
        "full_recent": (end - pd.Timedelta(days=365), end),
    }


def _simulate(frame: pd.DataFrame, flags: pd.DataFrame, symbol: str, variant: str,
              start: pd.Timestamp, end: pd.Timestamp, allocation: float) -> tuple[list[dict[str, object]], pd.Series]:
    data = frame.sort_index()
    cash = allocation
    shares = 0.0
    entry_price = None
    stop_price = None
    target_price = None
    entry_date = None
    held = 0
    trades: list[dict[str, object]] = []
    equity: list[tuple[pd.Timestamp, float]] = []
    for i in range(1, len(data) - 1):
        date = data.index[i]
        row = data.iloc[i]
        if date < start - pd.Timedelta(days=260) or date >= end:
            continue
        if shares > 0:
            held += 1
            stop_hit = float(row["low"]) <= float(stop_price)
            target_hit = float(row["high"]) >= float(target_price)
            cross_down = bool(row["cross_down"])
            if stop_hit or target_hit or held >= MAX_HOLD or (cross_down and held >= MIN_HOLD):
                exit_price = float(stop_price) if stop_hit else (float(target_price) if target_hit else float(row["close"]))
                exit_price *= 1.0 - SLIPPAGE_BPS / 10_000.0
                pnl = shares * (exit_price - float(entry_price))
                cash += shares * exit_price
                trades.append({"symbol": symbol, "entry_date": str(entry_date), "exit_date": str(date),
                               "entry_price": float(entry_price), "exit_price": exit_price,
                               "pnl": pnl, "reason": "stop" if stop_hit else ("target" if target_hit else "signal_or_max")})
                shares = 0.0
                entry_price = stop_price = target_price = entry_date = None
                held = 0
        in_window = start <= date < end
        next_row = data.iloc[i + 1]
        signal = bool(row["cross_up"]) and bool(pd.notna(row["trend"]) and row["close"] > row["trend"])
        if shares == 0 and in_window and signal and _fundamental_ok(flags, symbol, date, variant):
            fill = float(next_row["open"]) * (1.0 + SLIPPAGE_BPS / 10_000.0)
            atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0
            if atr > 0 and fill > 0:
                shares = allocation / fill
                cash -= shares * fill
                entry_price = fill
                stop_price = max(0.01, float(row["close"]) - STOP_MULT * atr)
                target_price = float(row["close"]) + TARGET_MULT * atr
                entry_date = data.index[i + 1]
                held = 0
        mark = cash + shares * float(row["close"])
        equity.append((date, mark))
    if shares > 0:
        last = data[data.index < end].iloc[-1]
        exit_price = float(last["close"]) * (1.0 - SLIPPAGE_BPS / 10_000.0)
        cash += shares * exit_price
        trades.append({"symbol": symbol, "entry_date": str(entry_date), "exit_date": str(last.name),
                       "entry_price": float(entry_price), "exit_price": exit_price,
                       "pnl": shares * (exit_price - float(entry_price)), "reason": "window_end"})
        if equity:
            equity[-1] = (equity[-1][0], cash)
    return trades, pd.Series(dict(equity)).sort_index()


def _stats(trades: list[dict[str, object]], curve: pd.Series) -> dict[str, float]:
    if curve.empty:
        return {"return_pct": 0.0, "drawdown_pct": 0.0, "trades": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0}
    dd = curve / curve.cummax() - 1.0
    pnl = pd.Series([float(t["pnl"]) for t in trades]) if trades else pd.Series(dtype=float)
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {"return_pct": float((curve.iloc[-1] / CAPITAL - 1.0) * 100.0),
            "drawdown_pct": float(dd.min() * 100.0), "trades": float(len(trades)),
            "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0,
            "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)}


def main() -> None:
    prices = {symbol: _load_price(symbol) for symbol in SYMBOLS}
    fundamentals = _make_flags(_load_fundamentals())
    last = min(frame.index.max() for frame in prices.values())
    windows = _windows(last)
    allocation = CAPITAL / len(SYMBOLS)
    rows = []
    for window, (start, end) in windows.items():
        for variant in VARIANTS:
            all_trades = []
            curves = []
            for symbol, frame in prices.items():
                trades, curve = _simulate(frame, fundamentals, symbol, variant, start, end, allocation)
                all_trades.extend(trades)
                if not curve.empty:
                    curves.append(curve.rename(symbol))
            portfolio = pd.concat(curves, axis=1).ffill().sum(axis=1) if curves else pd.Series(dtype=float)
            rows.append({"window": window, "variant": variant, **_stats(all_trades, portfolio)})
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "fundamental_swing_backtests_2026-08-18_results.csv", index=False)
    manifest = {"symbols": SYMBOLS, "fundamentals": "SEC Company Facts as-of filed", "price_source": "Alpaca cache daily",
                "variants": VARIANTS, "windows": list(windows), "rebalance": "entry-time gate, prior filed-date snapshot",
                "excluded": {"NOK": "SEC no us-gaap facts", "TQQQ": "ETF not corporate fundamental"}}
    (OUT / "fundamental_swing_backtests_2026-08-18_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"rows={len(result)} symbols={SYMBOLS}")


if __name__ == "__main__":
    main()
