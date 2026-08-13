"""Pipeline de datos: descarga y normalización de precios OHLCV.

Soporta dos proveedores:
  - Alpaca (API oficial, requiere API key; incluye datos por minuto)
  - Yahoo Finance (respaldo sin API key; solo datos diarios/intradía limitados)

Todos los datos se normalizan a un DataFrame con columnas:
  [ts, open, high, low, close, volume] y un índice de tiempo UTC.
"""
import logging
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

logger = logging.getLogger("feed")


class DataFeedError(RuntimeError):
    pass


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza y limpia un DataFrame de barras."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise DataFeedError(f"Faltan columnas: {missing}")
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"])
    # sanity: high >= low, high >= open/close, low <= open/close
    bad = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )
    if bad.any():
        logger.warning("Corrigiendo %d barras incoherentes (high/low)", bad.sum())
        df.loc[bad, "high"] = df.loc[bad, [["open", "close"]]].max(axis=1)
        df.loc[bad, "low"] = df.loc[bad, [["open", "close"]]].min(axis=1)
    df["volume"] = df["volume"].fillna(0).astype(float)
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def _alpaca_client():
    """Cliente de datos de Alpaca vía SDK moderno (alpaca-py)."""
    from alpaca.data.historical import StockHistoricalDataClient
    from config import get_config

    cfg = get_config()
    key = os.environ.get("APCA_API_KEY_ID") or cfg["broker"].get("api_key")
    secret = os.environ.get("APCA_API_SECRET_KEY") or cfg["broker"].get("secret_key")
    # Sin url_override: alpaca-py encamina al data endpoint nativo
    # (data.alpaca.markets/v2). Pasarle la base del broker
    # (paper-api.alpaca.markets/v2) generaba rutas /v2/v2/... que Alpaca
    # rechazaba con 404 ("Not Found") para todos los símbolos.
    if not key or not secret:
        raise DataFeedError(
            "Sin credenciales de Alpaca. Define APCA_API_KEY_ID / APCA_API_SECRET_KEY "
            "o config/config.yaml. Usa provider=yfinance para desarrollo sin clave."
        )
    return StockHistoricalDataClient(key, secret)


def fetch_alpaca(symbol: str, timeframe: str, start: str, end: str = None,
                 adjustment: str = "raw") -> pd.DataFrame:
    """Descarga barras de Alpaca. timeframe: 1Min, 5Min, 15Min, 1Day."""
    api = _alpaca_client()
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    tf_map = {"1min": TimeFrame.Minute,
              "5min": TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
              "15min": TimeFrame(amount=15, unit=TimeFrameUnit.Minute),
              "1d": TimeFrame.Day, "1day": TimeFrame.Day}
    tf = tf_map.get(timeframe, TimeFrame.Day)
    req = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=tf,
                           start=start, end=end)
    df = api.get_stock_bars(req).df
    df.index.name = "timestamp"
    return _clean(df)


def fetch_yfinance(symbol: str, timeframe: str, start: str, end: str = None) -> pd.DataFrame:
    """Respaldo con yfinance. Para intradía solo últimos 60 días (límite de Yahoo)."""
    import yfinance as yf

    tf_map = {"1min": "1m", "5min": "5m", "15min": "15m", "1d": "1d"}
    tf = tf_map.get(timeframe, "1d")
    end_dt = pd.Timestamp(end or "now", tz="UTC")
    start_dt = pd.Timestamp(start, tz="UTC")
    if timeframe != "1d" and (end_dt - start_dt).days > 60:
        logger.warning("yfinance limita intradía a ~60 días; se usa el máximo disponible")
    # Reintentos: el cache sqlite de yfinance a veces lanza
    # "database is locked" en llamadas concurrentes.
    import socket as _socket
    _prev_timeout = _socket.getdefaulttimeout()
    _socket.setdefaulttimeout(45)  # evita colgarse indefinidamente con Yahoo
    err = None
    try:
        for attempt in range(3):
            try:
                tkr = yf.Ticker(symbol)
                df = tkr.history(start=start_dt.strftime("%Y-%m-%d"),
                                 end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                                 interval=tf, auto_adjust=False)
                if df.empty:
                    raise DataFeedError(
                        f"yfinance no devolvió datos para {symbol} ({timeframe})")
                df.index.name = "timestamp"
                df.index = pd.to_datetime(df.index, utc=True)
                return _clean(df)
            except DataFeedError:
                raise
            except Exception as e:  # noqa: BLE001
                err = e
                logger.warning("%s yfinance intento %d falló: %s (%s)",
                               symbol, attempt + 1, type(e).__name__, e)
                time.sleep(1.0 * (attempt + 1))
        raise DataFeedError(f"yfinance agotó reintentos para {symbol}: {err}")
    finally:
        _socket.setdefaulttimeout(_prev_timeout)


class MarketDataFeed:
    """Fachada de datos con cache en memoria y respaldo automático."""

    def __init__(self, provider: str = None):
        # yfinance es el proveedor principal: el plan free de datos de
        # Alpaca rechaza las barras recientes ("subscription does not permit
        # querying recent SIP data"). Alpaca se usa para órdenes y cuenta.
        self.provider = provider or os.environ.get("DATA_PROVIDER", "yfinance")
        self._cache = {}

    def bars(self, symbol: str, timeframe: str, start: str, end: str = None,
             force: bool = False) -> pd.DataFrame:
        key = (symbol, timeframe, start, end or "now")
        if not force and key in self._cache:
            return self._cache[key].copy()
        fetch = fetch_alpaca if self.provider == "alpaca" else fetch_yfinance
        df = fetch(symbol, timeframe, start, end)
        self._cache[key] = df
        logger.info("%s %s %s: %d barras (%s)", symbol, timeframe,
                    start, len(df), self.provider)
        return df

    def history(self, symbols, timeframe: str = "1d", days: int = 365) -> dict:
        """Descarga historia para varios símbolos, degradando a yfinance por símbolo si falla."""
        end = datetime.utcnow()
        start = (end - timedelta(days=days)).strftime("%Y-%m-%d")
        out = {}
        for s in symbols:
            try:
                out[s] = self.bars(s, timeframe, start, end.isoformat())
            except Exception as e:  # noqa: BLE001
                if self.provider != "yfinance":
                    logger.warning("%s: %s (%s) — reintento con yfinance", s, type(e).__name__, e)
                    try:
                        out[s] = fetch_yfinance(s, timeframe, start, end.isoformat())
                        continue
                    except Exception as e2:  # noqa: BLE001
                        logger.error("%s sin datos (ningún proveedor): %s", s, e2)
                else:
                    logger.error("No se pudieron obtener datos de %s: %s", s, e)
        return out
