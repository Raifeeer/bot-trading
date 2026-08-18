"""Build as-of fundamental snapshots from SEC Company Facts."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SEC_ROOT = Path("/home/ubuntu/backtests/fundamental_history")
PRICE_ROOT = Path("/home/ubuntu/backtests/setup_history")
OUT = SEC_ROOT / "snapshots"
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "BB"]


def _facts(data: dict, names: list[str], unit: str = "USD") -> pd.DataFrame:
    for name in names:
        tag = data.get("facts", {}).get("us-gaap", {}).get(name)
        if not tag:
            continue
        units = tag.get("units", {})
        values = units.get(unit) or units.get("USD/shares") or units.get("shares")
        if not values:
            continue
        frame = pd.DataFrame(values)
        if "val" not in frame or "filed" not in frame:
            continue
        frame["fact_name"] = name
        frame["filed"] = pd.to_datetime(frame["filed"], errors="coerce")
        if "end" in frame:
            frame["end"] = pd.to_datetime(frame["end"], errors="coerce")
        return frame
    return pd.DataFrame()


def _latest_asof(frame: pd.DataFrame, asof: pd.Timestamp) -> float | None:
    if frame.empty:
        return None
    valid = frame[frame["filed"] <= asof].copy()
    if "end" in valid:
        valid = valid.sort_values(["filed", "end"])
    else:
        valid = valid.sort_values("filed")
    if valid.empty:
        return None
    return float(valid.iloc[-1]["val"])


def _ttm_asof(frame: pd.DataFrame, asof: pd.Timestamp, count: int = 4) -> float | None:
    if frame.empty:
        return None
    valid = frame[(frame["filed"] <= asof) & frame["end"].notna()].copy()
    valid = valid[valid["form"].isin(["10-Q", "10-K", "20-F", "40-F"])] if "form" in valid else valid
    valid = valid.sort_values(["end", "filed"]).drop_duplicates("end", keep="last")
    if valid.empty:
        return None
    vals = valid.tail(count)["val"].astype(float)
    return float(vals.sum()) if len(vals) >= count else None


def _growth(frame: pd.DataFrame, asof: pd.Timestamp) -> float | None:
    if frame.empty:
        return None
    valid = frame[(frame["filed"] <= asof) & frame["end"].notna()].copy()
    valid = valid[valid["form"].isin(["10-Q", "10-K", "20-F", "40-F"])] if "form" in valid else valid
    valid = valid.sort_values(["end", "filed"]).drop_duplicates("end", keep="last")
    if len(valid) < 8:
        return None
    recent = float(valid.tail(4)["val"].sum())
    prior = float(valid.iloc[-8:-4]["val"].sum())
    return (recent / prior - 1.0) if prior != 0 else None


def _price_dates(symbol: str) -> pd.DatetimeIndex:
    path = PRICE_ROOT / f"{symbol}.pkl"
    if not path.exists():
        return pd.DatetimeIndex([])
    frame = pd.read_pickle(path)
    idx = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York")
    return pd.DatetimeIndex(idx.normalize().unique()).sort_values()


def build_symbol(symbol: str) -> list[dict[str, object]]:
    data = json.loads((SEC_ROOT / f"{symbol}_companyfacts.json").read_text(encoding="utf-8"))
    revenue = _facts(data, ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"])
    eps = _facts(data, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], unit="USD/shares")
    equity = _facts(data, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"])
    liabilities = _facts(data, ["Liabilities"])
    prices = _price_dates(symbol)
    rows = []
    for date in prices:
        asof = pd.Timestamp(date).tz_localize(None)
        rev_ttm = _ttm_asof(revenue, asof)
        eps_ttm = _ttm_asof(eps, asof)
        rev_growth = _growth(revenue, asof)
        eps_growth = _growth(eps, asof)
        eq = _latest_asof(equity, asof)
        debt = _latest_asof(liabilities, asof)
        price_frame = pd.read_pickle(PRICE_ROOT / f"{symbol}.pkl")
        price_frame.index = pd.to_datetime(price_frame.index, utc=True).tz_convert("America/New_York")
        price_rows = price_frame[price_frame.index.normalize() == pd.Timestamp(date).normalize()]
        price = float(price_rows.iloc[0]["close"]) if not price_rows.empty else None
        rows.append({"symbol": symbol, "decision_date": str(asof.date()), "price": price,
                     "revenue_ttm": rev_ttm, "eps_ttm": eps_ttm,
                     "revenue_growth": rev_growth, "eps_growth": eps_growth,
                     "equity": eq, "liabilities": debt,
                     "pe": (price / eps_ttm) if price and eps_ttm and eps_ttm > 0 else None,
                     "de": (debt / eq) if debt is not None and eq and eq > 0 else None})
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows = []
    manifest = {"symbols": {}, "source": "SEC Company Facts as-of filed date"}
    for symbol in SYMBOLS:
        try:
            rows = build_symbol(symbol)
            pd.DataFrame(rows).to_csv(OUT / f"{symbol}.csv", index=False)
            all_rows.extend(rows)
            manifest["symbols"][symbol] = {"status": "ok", "rows": len(rows)}
        except (KeyError, OSError, ValueError) as exc:
            manifest["symbols"][symbol] = {"status": "error", "error": str(exc)}
    pd.DataFrame(all_rows).to_csv(OUT / "all_snapshots.csv", index=False)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
