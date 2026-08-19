"""Cache histórico 5m para validar estructura multi-timeframe.

Descarga únicamente barras reales Alpaca IEX del tramo reciente que permite la
suscripción, no coloca órdenes y no rellena datos faltantes.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from data.feed import _clean
from loop_backtests import UNI_RETO

OUT = Path("/home/ubuntu/backtests/structure_mtf_history")
GCLOUD = "/home/ubuntu/tools/google-cloud-sdk/bin/gcloud"
PROJECT = "gen-lang-client-0746441136"


def _read_secret(name: str) -> str:
    return subprocess.check_output(
        [GCLOUD, "secrets", "versions", "access", "latest", f"--secret={name}",
         f"--project={PROJECT}"],
        text=True,
    ).strip()


def _load_alpaca_secret() -> None:
    key = _read_secret("alpaca-key")
    secret = _read_secret("alpaca-secret")
    if not key or not secret:
        raise RuntimeError("Los secretos Alpaca no pueden estar vacíos")
    os.environ["APCA_API_KEY_ID"] = key
    os.environ["APCA_API_SECRET_KEY"] = secret


def _fetch_iex(symbol: str, start: str, end: str) -> pd.DataFrame:
    client = StockHistoricalDataClient(os.environ["APCA_API_KEY_ID"],
                                       os.environ["APCA_API_SECRET_KEY"])
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed=DataFeed.IEX,
    )
    frame = client.get_stock_bars(request).df
    if frame.empty:
        return frame
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.loc[symbol].copy()
    frame.index.name = "timestamp"
    return _clean(frame)


def main() -> None:
    _load_alpaca_secret()
    OUT.mkdir(parents=True, exist_ok=True)
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=55)
    manifest: list[dict[str, object]] = []
    for symbol in UNI_RETO:
        try:
            df = _fetch_iex(symbol, start.isoformat(), end.isoformat())
            path = OUT / f"{symbol}.pkl"
            df.to_pickle(path)
            manifest.append({"symbol": symbol, "rows": len(df),
                             "start": str(df.index.min()) if len(df) else None,
                             "end": str(df.index.max()) if len(df) else None,
                             "status": "ok"})
            print(f"{symbol}: {len(df)} barras 5m")
        except (RuntimeError, ValueError, OSError) as exc:
            manifest.append({"symbol": symbol, "rows": 0, "status": "error",
                             "error": f"{type(exc).__name__}: {exc}"})
            print(f"{symbol}: error {type(exc).__name__}")
    pd.DataFrame(manifest).to_json(OUT / "manifest.json", orient="records", indent=2)
    print(f"total_ok={sum(r['status'] == 'ok' for r in manifest)} total={len(manifest)}")


if __name__ == "__main__":
    main()
