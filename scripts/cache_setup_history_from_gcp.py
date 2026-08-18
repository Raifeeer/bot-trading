"""Descarga históricos reales usando el secreto Alpaca de Secret Manager.

El valor del secreto se consume solo en memoria y nunca se imprime ni se guarda.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import UNI_RETO  # noqa: E402

OUT = Path("/home/ubuntu/backtests/setup_history")
OUT.mkdir(parents=True, exist_ok=True)


def _read_secret(name: str) -> str:
    return subprocess.check_output([
        "/home/ubuntu/tools/google-cloud-sdk/bin/gcloud",
        "secrets", "versions", "access", "latest",
        f"--secret={name}", "--project=gen-lang-client-0746441136",
    ], text=True).strip()


def _load_alpaca_secret() -> tuple[str, str]:
    key = _read_secret("alpaca-key")
    secret = _read_secret("alpaca-secret")
    if not key or not secret:
        raise RuntimeError("Los secretos separados de Alpaca no pueden estar vacíos")
    return key, secret


def main() -> None:
    key, secret = _load_alpaca_secret()
    os.environ["APCA_API_KEY_ID"] = key
    os.environ["APCA_API_SECRET_KEY"] = secret
    feed = MarketDataFeed("yfinance")
    data = feed.history(UNI_RETO, "1d", days=520)
    for symbol, df in data.items():
        path = OUT / f"{symbol}.pkl"
        df.to_pickle(path)
        print(f"{symbol}: {len(df)} barras guardadas")
    missing = sorted(set(UNI_RETO) - set(data))
    if missing:
        print(f"faltantes: {','.join(missing)}")
    print(f"total_tickers={len(data)}")


if __name__ == "__main__":
    main()
