# Piloto aislado de TradingAgents — 24 de agosto de 2026

## Pregunta

¿TradingAgents puede aportar una segunda opinión útil para Polaris al combinar análisis técnico, noticias, sentimiento y fundamentales, sin darle acceso al executor ni a las credenciales de Alpaca?

## Método

Se utilizó el repositorio oficial `TauricResearch/TradingAgents`, versión `0.3.1`, en un entorno virtual separado (`/home/ubuntu/venvs/tradingagents`). El piloto no importó módulos de Polaris, no usó credenciales `APCA_*`, no accedió a Firestore y no tuvo ninguna ruta de envío de órdenes.

Se fijaron los modelos del proxy interno en `gpt-5-mini` para razonamiento profundo y `gpt-5-nano` para tareas rápidas, con temperatura `0.0`, una ronda de debate y una ronda de discusión de riesgo. El catálogo de modelos se guardó en `backtests/tradingagents_model_catalog_2026-08-24.json` antes de ejecutar. El resultado de cada corrida incluye ticker, fecha solicitada, rating, latencia y retorno posterior de cinco sesiones obtenido de Yahoo Finance.

Se ejecutaron dos muestras. La primera utilizó los cuatro grupos de analistas (`market`, `social`, `news`, `fundamentals`) sobre AMD, BB y TQQQ con fecha solicitada `2026-07-15`, más AMD con fecha `2026-07-31`. La segunda utilizó únicamente el analista `market` sobre AMD, BB y TQQQ con fecha `2026-07-15`, para separar la señal técnica del efecto de fundamentales/noticias.

## Resultados observados

| Muestra | Ticker | Fecha solicitada | Rating | Retorno posterior de 5 sesiones | Latencia |
|---|---|---:|---|---:|---:|
| Cuatro equipos | AMD | 2026-07-15 | Overweight | +4.38% | 383.8 s |
| Cuatro equipos | BB | 2026-07-15 | Underweight | −15.88% | 403.6 s |
| Cuatro equipos | TQQQ | 2026-07-15 | Underweight | −5.59% | 447.7 s |
| Cuatro equipos | AMD | 2026-07-31 | Overweight | +1.51% | 413.8 s |
| Solo técnico | AMD | 2026-07-15 | Overweight | +4.38% | 266.1 s |
| Solo técnico | BB | 2026-07-15 | Overweight | −15.88% | 263.7 s |
| Solo técnico | TQQQ | 2026-07-15 | Overweight | −5.59% | 268.9 s |

Los cuatro análisis completos coincidieron con la dirección posterior en esta muestra diminuta: Overweight para AMD, que subió durante las cinco sesiones siguientes, y Underweight para BB y TQQQ, que bajaron. El analista técnico aislado clasificó los tres tickers como Overweight; acertó en AMD y falló en BB y TQQQ. Esto sugiere que el bloque completo puede estar capturando riesgos que el análisis técnico aislado no ve, pero el tamaño de muestra es demasiado pequeño para afirmar capacidad predictiva.

## Limitaciones críticas

Este piloto **no es todavía un backtest point-in-time válido**. Aunque se solicitó una fecha histórica, el framework recuperó datos de proveedores actuales y el análisis fundamental de AMD incluyó información del trimestre terminado el 30 de junio de 2026. Es necesario demostrar que esa información ya estaba publicada antes de cada fecha de decisión. Lo mismo aplica a noticias, sentimiento, macro y cualquier dato que Yahoo devuelva sin un histórico completo.

El retorno posterior se calculó únicamente como referencia de dirección, sin simular entradas, spreads de opciones, bid/ask, slippage, comisiones, sizing, stops, latencia de decisión ni restricciones del RiskManager de Polaris. Por tanto, no puede compararse con el P&L del bot ni con el baseline S78/DayBreakout.

La latencia fue alta: aproximadamente 4.4 a 7.5 minutos por análisis completo y 4.4 minutos por análisis técnico. Hubo respuestas HTTP 429 de Reddit y ausencia de `FRED_API_KEY`, por lo que algunas fuentes solicitadas no estuvieron disponibles. Además, `gpt-5-mini` y `gpt-5-nano` no formaban parte de la lista conocida por la versión del repositorio, aunque el proxy sí los expuso en su catálogo y las corridas terminaron correctamente.

El primer piloto completo fue detenido después de tres filas válidas para evitar seguir consumiendo tiempo y llamadas externas; la cuarta fila se ejecutó por separado. No se deben tratar estas cuatro filas como una muestra homogénea de una matriz completa.

## Evaluación para Polaris

TradingAgents parece más útil como **contexto o analista auxiliar** que como generador de órdenes. La comparación técnica sugiere una hipótesis investigable: fundamentales, noticias y riesgo podrían corregir algunos falsos positivos del análisis técnico. Sin embargo, esa hipótesis todavía está contaminada por posible look-ahead y no tiene suficiente muestra.

La integración recomendada es `RESEARCH_ONLY`. No debe instalarse en Cloud Run, no debe recibir credenciales de Alpaca y no debe escribir en Firestore de producción. La siguiente prueba debe usar snapshots congelados de datos, fuentes con fecha de publicación comprobable y un protocolo de decisión previamente registrado. El resultado estructurado debería limitarse a `bullish/neutral/bearish`, confianza, horizonte, argumentos, riesgos y fuentes; nunca debe elegir cantidad, strikes, precio límite, circuit breakers o endpoint.

## Decisión

**No se integra ni se activa en Polaris.** El piloto confirma que el framework funciona técnicamente y que puede producir decisiones razonables, pero no demuestra alpha ni rentabilidad. Antes de darle incluso influencia shadow dentro del bot, hay que construir un conjunto de snapshots point-in-time, repetir varios periodos y comparar el valor marginal contra las estrategias actuales con costes y slippage.

## Archivos y reproducción

El código del piloto está en `scripts/run_tradingagents_pilot.py`. El repositorio aislado está en `/home/ubuntu/research-tradingagents`. Las salidas están en:

- `backtests/tradingagents_pilot_2026-08-24/run.log` — tres filas completas del primer piloto antes de la cancelación controlada.
- `backtests/tradingagents_pilot_2026-08-24_amd_0731/results.json` — AMD en la segunda fecha histórica.
- `backtests/tradingagents_pilot_technical_2026-08-24/results.json` — muestra técnica aislada.
- `backtests/tradingagents_model_catalog_2026-08-24.json` — catálogo de modelos consultado antes de ejecutar.

[1]: https://x.com/franpradasai/status/2087161892162998615?s=46 "Publicación de Fran Pradas"
[2]: https://github.com/TauricResearch/TradingAgents "Repositorio oficial de TradingAgents"
[3]: https://github.com/TauricResearch/TradingAgents/blob/main/README.md "README oficial y advertencia de uso para investigación"
[4]: https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/trading_graph.py "Grafo principal y método propagate"
