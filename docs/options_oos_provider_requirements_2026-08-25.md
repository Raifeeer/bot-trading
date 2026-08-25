# Requisitos para seleccionar proveedor de datos OOS de opciones

**Objetivo:** encontrar una fuente que permita validar estrategias de opciones con ejecución histórica realista, sin contratarla ni conectarla todavía.

## Requisitos obligatorios

| Criterio | Requisito de aceptación |
|---|---|
| Universo | Opciones estadounidenses sobre acciones/ETF que incluya los símbolos de Polaris y contratos listados en cada fecha histórica |
| Quotes | NBBO histórico bid/ask con timestamp, bid/ask size cuando exista, feed identificado y granularidad suficiente para la estrategia |
| Trades | Trades históricos con timestamp, precio, tamaño y condición de mercado para contrastar fills |
| Cadena point-in-time | Reconstrucción de contratos disponibles por fecha/hora, incluyendo expiración, strike, tipo, OCC symbol y estado de listado |
| Ciclo de vida | Identificación de listing, expiración, ejercicio, asignación, halt, corporate action y delistado cuando aplique |
| Underlying | Barras o quotes/trades del subyacente sincronizables con la decisión de entrada y salida |
| Integridad | Paginación completa, timestamps UTC, esquema estable, checksum/manifest y detección de huecos o duplicados |
| Costes | Licencia explícita para investigación/backtesting, límites de descarga y coste total verificable |
| Reproducibilidad | API o descarga bulk que permita reconstruir el mismo dataset, con fecha de consulta y versión/feed registrados |

## Requisitos reforzados para 0DTE/1DTE

Para 0DTE y 1DTE se exige quote/trade intradía, no barras diarias; timestamp al menos de un minuto y preferiblemente tick/NBBO; estado del contrato y cadena intradía; y tratamiento explícito de spreads bid/ask, latencia, slippage, fills parciales, cierres por expiración y asignación. Un proveedor que solo entrega OHLC diario no supera esta prueba.

## Criterios de descarte

Se descarta un proveedor que solo ofrezca última cotización, snapshots actuales, OHLC sin bid/ask, cadena actual aplicada retrospectivamente, datos sin timestamps, historial con survivorship, feeds no identificados o términos que no permitan el uso de backtesting. Los datos Indicative deben etiquetarse como derivados y no deben sustituir NBBO OPRA sin una validación separada.

## Salida esperada de la comparación

La comparación debe distinguir hechos documentados por el proveedor, inferencias y campos no confirmados. Debe terminar con una recomendación de proveedor principal, una alternativa, el coste o plan que habría que confirmar y un plan de prueba de muestra: un símbolo, una semana, contratos near-ATM y varias sesiones, comprobando continuidad, bid/ask, timestamps, cadena y descarga reproducible antes de cualquier integración.
