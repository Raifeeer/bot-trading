# Requisitos de datos para un OOS válido de opciones

**Corte de investigación:** 25 de agosto de 2026. Este documento no recomienda operaciones ni autoriza promociones.

## Conclusión

El catálogo actual de Polaris no permite afirmar que una estrategia de opciones sea rentable fuera de muestra. El manifiesto de datos existente (`online_strategy_backtests_2026-08-19_manifest.json`) indica que la fuente fue Alpaca, con contratos históricos y barras OHLC diarias entre el 1 de abril y el 7 de agosto de 2026. También indica que no había bid/ask intradía y que no estaban disponibles la pertenencia histórica de la cadena ni los timestamps de listado. Por eso los resultados de 0DTE/1DTE están correctamente marcados como `REJECT_DATA`, mientras que las estructuras BWB solo pueden tratarse como una aproximación diaria `RESEARCH_ONLY`.

## Verificación de la fuente Alpaca

La documentación oficial de Alpaca describe históricos de opciones y la disponibilidad de datos de barras, trades y quotes en la familia de datos de mercado [1]. La referencia específica de `OptionHistoricalDataClient` expone `get_option_bars` para barras agregadas, `get_option_trades` para trades históricos y `get_option_latest_quote` para la última cotización; la misma referencia no expone un método `get_option_quotes` histórico en la versión del SDK instalada en el entorno de Polaris [2]. La referencia REST de barras confirma que los resultados son agregados y paginados mediante `next_page_token` [3].

La documentación de datos históricos también distingue entre el feed Indicative y OPRA. Indicative no representa quotes OPRA reales y sus trades tienen retraso; OPRA es el BBO consolidado, pero requiere la suscripción correspondiente [4]. Por tanto, una descarga de barras diaria o una última cotización no debe presentarse como evidencia de fills históricos con bid/ask real.

## Datos mínimos antes de promover una estrategia

| Requisito | Estado actual | Consecuencia |
|---|---|---|
| OHLC histórico de opciones | Disponible en barras diarias | Útil para investigación preliminar, no suficiente para fills intradía |
| Trades históricos | El SDK los expone | No sustituyen el NBBO disponible al momento de la decisión |
| Bid/ask histórico intradía | No está en el cache existente; el SDK local no expone `get_option_quotes` | No validar precio de entrada, slippage ni salida de 0DTE/1DTE |
| Cadena point-in-time | No disponible en el manifest existente | Riesgo de look-ahead y survivorship en contratos elegibles |
| Timestamps de listado/delistado | No disponible en el manifest existente | No se puede reconstruir el universo histórico sin sesgo |
| Costes, comisiones y fills parciales | No están demostrados con quotes históricas | P&L no es ejecución-realista |
| Walk-forward con purging/embargo | No verificable en todas las tablas históricas | No usar para promoción |

## Regla operativa

Hasta conseguir una fuente con bid/ask histórico sincronizado, cadena point-in-time y evidencia de costes/fills, todas las familias nuevas permanecen en `RESEARCH_ONLY` o `shadow`. No se modifica `config/config.yaml`, no se desactiva `risk.halt_new_entries`, no se conectan proveedores externos de opciones y no se cambia el executor multi-pata por inferencia de resultados.

La siguiente evaluación válida debe guardar, por cada decisión, el timestamp, símbolo OCC, expiración, strike, tipo, bid, ask, tamaño disponible si existe, feed, underlying timestamp, señal, régimen, precio de entrada/salida, comisión, slippage, motivo de fill o rechazo y estado final. El corte de entrenamiento debe estar separado del test por un embargo verificable de al menos una sesión y la selección de parámetros debe hacerse solo dentro del entrenamiento.

## Referencias

[1]: https://alpaca.markets/sdks/python/market_data.html "Alpaca-py Market Data"
[2]: https://alpaca.markets/sdks/python/api_reference/data/option/historical.html "Alpaca-py OptionHistoricalDataClient"
[3]: https://docs.alpaca.markets/reference/optionbars "Alpaca Historical Option Bars API"
[4]: https://docs.alpaca.markets/us/docs/historical-option-data "Alpaca Historical Option Data"
