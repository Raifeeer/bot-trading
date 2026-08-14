# Skill: Pipeline de datos (yfinance, Alpaca, feed multi-proveedor)

**Archivos de referencia:** `data/feed.py`, la integración de feeds en `bot.py` (paso 1 del tick) y `risk/regime.py` (datos diarios para el régimen).

## 1. Arquitectura del feed

El feed es multi-proveedor con degradación automática por ticker: Alpaca data API como principal configurado (`data.provider: alpaca`), yfinance como respaldo universal. El motivo histórico: el **plan free de datos de Alpaca rechaza el stream SIP reciente** con el error `"subscription does not permit querying recent SIP data"`, así que en la práctica yfinance es el proveedor que más se usa y Alpaca queda para órdenes y snapshot de cuenta.

| Tiempo | Uso en el bot | Ventana descargada por tick |
|---|---|---|
| `1d` | Swing + régimen S78 (SMA200, ATR, CHoCH estructural) | 100 días (para 1d bastan; el régimen pide 400 días en su ruta propia) |
| `15min` | Day breakout (Donchian) | 10 días |
| `5min` | Day momentum (EMA, RSI) | 5 días |
| `1min` | Habilitado en config, no usado por defecto | — |

## 2. Defensas anti-congelamiento (las más importantes del sistema)

La fuente de inestabilidad nº1 del sistema es el market data de Yahoo. Tres capas la contienen:

1. **Socket timeout por ticker:** `fetch_yfinance` fuerza `socket.setdefaulttimeout(45)` durante la descarga de cada ticker y lo restaura después. Yahoo puede colgarse sin lanzar excepción; sin esto, un solo ticker congelado paraliza el tick.
2. **Tolerancia por timeframe:** si un timeframe no devuelve datos, el tick **continúa** con los demás timeframes y reintenta el fallido en el siguiente ciclo. Nunca se mata un tick completo por un proveedor lento.
3. **Watchdog de 12 minutos:** un hilo fuerza `sys.exit(1)` si no hay un tick completo en 12 minutos; Cloud Run recrea el contenedor (minScale=1). Existe precisamente porque yfinance puede colgarse silenciosamente.

La consecuencia operativa: un tick completo dura típicamente **10–12 minutos** (las descargas de 1d para el régimen dominan), dentro de la ventana de 25 minutos del watchdog. Es normal; no alarmarse si los ticks no salen cada 5 minutos exactos.

## 3. El snapshot de cuenta de Alpaca

Cada tick comienza con `executor.account_snapshot()` (endpoint REST gratuito, siempre disponible en paper): equity, cash, buying power y las **posiciones crudas** (`alpaca_positions`), que incluyen las piernas separadas de cada spread con `avg_entry`, `market_value`, `unrealized_pl` y `unrealized_pl_pct`. Este snapshot es la fuente de verdad de posiciones para el dashboard (el frontend prioriza `alpaca_positions` cuando `payload.positions` está vacío — ver `docs/skills/infra_skill.md`).

## 4. Lo que el bot NO usa (decisiones deliberadas)

**TradingView:** el dueño descartó su API; todo el análisis se hace con datos propios (yfinance/Alpaca) — no hay dependencia externa de charting. **Streaming SIP de Alpaca:** no disponible en paper sin plan; se suple con polling de 5 minutos + websocket de equity (gratuito, usado para el stop intradiario del 4%). **Datos fundamentalizados en tiempo real:** el bot es técnico; el filtro anti-earnings (`earnings_horizon_days: 2`) es la única defensa fundamental, y el análisis fundamental profundo (deuda, P/E, cash flow) se consideró innecesario para esta estrategia de spreads cortos (decisión del dueño).

## 5. Costes y límites

yfinance no tiene quota documentada; en la práctica tolera las ~40–60 llamadas por tick del bot sin bloqueo. Alpaca paper: órdenes ilimitadas con el plan Basic, sin comisiones en acciones y ~$0.65/pata en opciones. El stream de equity de Alpaca (websocket gratuito) alimenta el stop intradiario. No hay plan de datos de nivel profesional contratado: cualquier estrategia que requiera ticks sub-segundo o Greeks intradiarios reales necesitará un upgrade de Alpaca data subscription o un proveedor alternativo (documentar el cambio en el AGENTS.md si ocurre).

## 6. Criterios de uso por el agente

Antes de añadir una nueva fuente de datos: verificar que existe un timeout por llamada, un fallback por ticker y que el nuevo proveedor no puede congelar el tick completo. Si se añade un timeframe nuevo, recordar actualizar `tf_by_strat` del paso 1 de `bot.py` (los días de historia por timeframe) y el test correspondiente. El patrón de ventanas por timeframe (100 días para 1d, 10 para 15min, 5 para 5min) fue descubierto para reducir ~50% el tiempo del tick: no revertirlo sin medir.
