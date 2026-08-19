"""Gate de datos para estrategias de earnings-event.

No inventa un backtest cuando faltan calendario histórico as-of y quotes/IV
históricos. Produce una decisión auditable y una tabla por símbolo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA", "SOFI"]
OPTION_MANIFEST = Path("/home/ubuntu/backtests/online_option_history_2026-08-19/manifest.json")
OUT = Path("/home/ubuntu/backtests/earnings_event_backtest_2026-08-19")


def main() -> None:
    option_manifest = json.loads(OPTION_MANIFEST.read_text(encoding="utf-8"))
    rows = []
    for symbol in SYMBOLS:
        rows.append({"symbol": symbol, "historical_earnings_asof": False, "historical_iv": False, "historical_bid_ask": False, "post_event_quotes": False, "decision": "REJECT_DATA"})
    result = pd.DataFrame(rows)
    result.to_csv(f"{OUT}_coverage.csv", index=False)
    manifest = {"decision": "REJECT_DATA", "reason": "Current data/earnings.py uses yfinance.Ticker(calendar) with a 24h cache of the currently known date; it does not provide historical as-of earnings dates. The option cache has daily OHLC only, without historical bid/ask or IV and without post-event intraday quotes.", "symbols": SYMBOLS, "earnings_provider_current": "yfinance current calendar, not historical point-in-time", "option_source_manifest": option_manifest, "required_for_valid_backtest": ["historical earnings announcements known as-of each decision date", "historical option bid/ask", "historical IV by strike and expiry", "intraday underlying bars around announcement", "post-event quotes with timestamps"]}
    Path(f"{OUT}_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
