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


def _alpaca_one(symbol: str, timeframe: str, start: str, end: str = None) -> pd.DataFrame:
    """Descarga de Alpaca GARANTIZANDO un solo símbolo: con varios el SDK
    devuelve MultiIndex (símbolo, timestamp) que rompe _clean()."""
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
    if df.empty:
        raise DataFeedError(f"Alpaca no devolvió datos para {symbol} ({timeframe})")
    if isinstance(df.index, pd.MultiIndex):
        # MultiIndex (símbolo, timestamp): quedarse con la fila del símbolo
        df = df.loc[symbol].copy()
    df.index.name = "timestamp"
    df.index = pd.to_datetime(df.index, utc=True)
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
    # "database is locked" en llamadas concurrentes, y Yahoo throttles las
    # descargas simultáneas (broken pipe / timeout); backoff de 3-9 s ayuda.
    import socket as _socket
    import time as _time
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
                _time.sleep(3.0 * (attempt + 1))
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

    def _segmented(self, symbol: str, timeframe: str, start: str,
                   end: str = None) -> pd.DataFrame:
        """Cascada segmentada: Alpaca IEX es estable para ventanas LEJANAS
        (sin rango 'recent SIP') pero rechaza el rango reciente en el plan
        free; Yahoo cubre el rango reciente (inestable en ráfaga, por eso se
        usa solo donde hace falta). Combina los segmentos en un solo DataFrame."""
        import datetime as _dt

        now = datetime.utcnow()
        end_dt = pd.Timestamp(end or now, tz="UTC")
        pd.Timestamp(start, tz="UTC")
        # El rango 'recent SIP' de Alpaca free cubre ~los últimos 2 días
        # (observado: ventanas que incluyen hoy o ayer fallan con
        # 'subscription does not permit querying recent SIP data').
        sip_cut = pd.Timestamp(now - timedelta(days=2), tz="UTC")
        if end_dt < sip_cut:
            # Todo lejano: Alpaca directo (rápido y estable).
            # _alpaca_df() descarga SIEMPRE un solo símbolo: con múltiples
            # símbolos el SDK devuelve MultiIndex (símbolo, timestamp) que
            # rompe _clean; history() ya descompone por ticker aquí.
            try:
                return _alpaca_one(symbol, timeframe, start, end)
            except Exception as e:  # noqa: BLE001
                logger.warning("%s: Alpaca lejano falló (%s), yfinance", symbol, e)
                return fetch_yfinance(symbol, timeframe, start, end)
        # Ventana mixta: cortar en sip_cut
        cut = sip_cut.strftime("%Y-%m-%d")
        parts = []
        try:
            parts.append(_alpaca_one(symbol, timeframe, start, cut))
        except Exception as e:  # noqa: BLE001
            logger.warning("%s: Alpaca lejano falló (%s), yfinance", symbol, e)
            parts.append(fetch_yfinance(symbol, timeframe, start, cut))
        try:
            parts.append(fetch_yfinance(symbol, timeframe, cut, end))
        except Exception as e:  # noqa: BLE001
            logger.error("%s: Yahoo reciente falló (%s)", symbol, e)
        # Unificar y deduplicar barras coincidentes en la frontera
        merged = pd.concat([p for p in parts if not p.empty])
        if merged.empty:
            raise DataFeedError(f"Ningún proveedor devolvió datos para {symbol}")
        merged = merged[~merged.index.duplicated(keep="last")]
        return _clean(merged)

    def bars(self, symbol: str, timeframe: str, start: str, end: str = None,
             force: bool = False) -> pd.DataFrame:
        key = (symbol, timeframe, start, end or "now")
        if not force and key in self._cache:
            return self._cache[key].copy()
        # Cascada segmentada (alpaca+yfinance) cuando el proveedor base es
        # yfinance: mejora la estabilidad del histórico lejano sin perder el
        # rango reciente que solo Yahoo entrega en el plan free.
        if self.provider == "yfinance":
            df = self._segmented(symbol, timeframe, start, end)
        else:
            df = fetch_alpaca(symbol, timeframe, start, end)
        self._cache[key] = df
        logger.info("%s %s %s: %d barras (%s)", symbol, timeframe,
                    start, len(df), self.provider)
        return df

    def history(self, symbols, timeframe: str = "1d", days: int = 365) -> dict:
        """Descarga historia para varios símbolos en paralelo (cada ticker puede
        tardar 15-20 s con fallback), degradando a yfinance por símbolo si falla."""
        from concurrent.futures import ThreadPoolExecutor

        end = datetime.utcnow()
        start = (end - timedelta(days=days)).strftime("%Y-%m-%d")

        def _one(s):
            try:
                return s, self.bars(s, timeframe, start, end.isoformat())
            except Exception as e:  # noqa: BLE001
                if self.provider != "yfinance":
                    logger.warning("%s: %s (%s) — reintento con yfinance", s, type(e).__name__, e)
                    try:
                        return s, fetch_yfinance(s, timeframe, start, end.isoformat())
                    except Exception as e2:  # noqa: BLE001
                        logger.error("%s sin datos (ningún proveedor): %s", s, e2)
                else:
                    logger.error("No se pudieron obtener datos de %s: %s", s, e)
            return s, None

        out = {}
        # Threads limitados a 4: el cache sqlite de yfinance sufre
        # "database is locked" con más concurrencia; la serialización total
        # tardaba más de 12 min y disparaba el watchdog.
        # Yahoo throttles las descargas simultáneas (broken pipe/timeout);
        # 3 workers equilibra velocidad y estabilidad (serial tardaba >12 min).
        with ThreadPoolExecutor(max_workers=min(len(symbols), 3)) as ex:
            for s, df in ex.map(_one, symbols):
                if df is not None:
                    out[s] = df
        return out
