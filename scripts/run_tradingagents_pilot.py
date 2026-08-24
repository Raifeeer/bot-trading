"""Run a small, isolated TradingAgents research pilot.

This script deliberately has no Alpaca imports, no broker credentials, and no
order path. It records only model decisions and realized Yahoo Finance returns
for a later comparison. The date is a historical information cutoff; news
providers are expected to apply their own as-of filtering.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    return tuple(item.strip() for item in raw.split(",") if item.strip()) or default


TICKERS = _env_tuple("TRADINGAGENTS_PILOT_TICKERS", ("AMD", "BB", "TQQQ"))
TRADE_DATES = _env_tuple("TRADINGAGENTS_PILOT_DATES", ("2026-07-15",))
SELECTED_ANALYSTS = _env_tuple(
    "TRADINGAGENTS_PILOT_ANALYSTS", ("market", "social", "news", "fundamentals")
)
OUTPUT_DIR = Path(
    os.getenv(
        "TRADINGAGENTS_PILOT_OUTPUT",
        "/home/ubuntu/backtests/tradingagents_pilot_2026-08-24",
    )
)


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _future_return(ticker: str, trade_date: str, horizon_days: int = 5) -> dict:
    """Fetch a post-cutoff close-to-close return from Yahoo, if available."""
    start = datetime.strptime(trade_date, "%Y-%m-%d")
    end = start + timedelta(days=horizon_days + 10)
    try:
        frame = yf.Ticker(ticker).history(
            start=trade_date,
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=False,
        )
        closes = frame["Close"].dropna()
        if len(closes) < 2:
            return {"status": "unavailable", "return_5d": None, "actual_bars": 0}
        actual = min(horizon_days, len(closes) - 1)
        value = float((closes.iloc[actual] / closes.iloc[0]) - 1.0)
        return {
            "status": "ok",
            "return_5d": value,
            "actual_bars": int(actual),
            "start_close": float(closes.iloc[0]),
            "end_close": float(closes.iloc[actual]),
        }
    except Exception as exc:  # research output records provider failure, not a trade
        return {"status": "error", "return_5d": None, "actual_bars": 0, "error": str(exc)}


def _compact_state(state: dict) -> dict:
    keys = (
        "final_trade_decision",
        "trader_investment_plan",
        "investment_plan",
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
    )
    return {key: _jsonable(state.get(key)) for key in keys if key in state}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = DEFAULT_CONFIG.copy()
    config.update(
        {
            "deep_think_llm": os.getenv("TRADINGAGENTS_PILOT_DEEP_MODEL", "gpt-5-mini"),
            "quick_think_llm": os.getenv("TRADINGAGENTS_PILOT_QUICK_MODEL", "gpt-5-nano"),
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "max_recur_limit": 100,
            "news_article_limit": 8,
            "global_news_article_limit": 5,
            "temperature": 0.0,
            "llm_max_retries": 1,
            "output_language": "English",
            "results_dir": str(OUTPUT_DIR / "reports"),
            "data_cache_dir": str(OUTPUT_DIR / "cache"),
            "memory_log_path": str(OUTPUT_DIR / "trading_memory.md"),
        }
    )

    manifest = {
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "tickers": list(TICKERS),
        "trade_dates": list(TRADE_DATES),
        "selected_analysts": list(SELECTED_ANALYSTS),
        "models": {
            "deep": config["deep_think_llm"],
            "quick": config["quick_think_llm"],
        },
        "temperature": config["temperature"],
        "debate_rounds": config["max_debate_rounds"],
        "risk_rounds": config["max_risk_discuss_rounds"],
        "data_vendors": config["data_vendors"],
        "execution": "none; analysis/reporting only",
    }
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    graph = TradingAgentsGraph(
        selected_analysts=SELECTED_ANALYSTS,
        debug=False,
        config=config,
    )
    results = []
    for trade_date in TRADE_DATES:
        for ticker in TICKERS:
            started = time.perf_counter()
            row = {
                "ticker": ticker,
                "trade_date": trade_date,
                "execution_path": "isolated_analysis_only",
                "orders_allowed": False,
            }
            try:
                state, rating = graph.propagate(ticker, trade_date)
                row.update(
                    {
                        "status": "ok",
                        "rating": rating,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "decision": _compact_state(state),
                        "forward_outcome": _future_return(ticker, trade_date),
                    }
                )
            except Exception as exc:  # keep the matrix moving and preserve the failure
                row.update(
                    {
                        "status": "error",
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "error": str(exc),
                        "forward_outcome": _future_return(ticker, trade_date),
                    }
                )
            results.append(row)
            print(json.dumps(row, ensure_ascii=False))

    manifest["run_finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["completed_rows"] = sum(row["status"] == "ok" for row in results)
    manifest["failed_rows"] = sum(row["status"] == "error" for row in results)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(_jsonable(results), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
