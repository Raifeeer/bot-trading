# Investigación de proveedores OOS de opciones — notas de evidencia

**Fecha de consulta:** 25 de agosto de 2026. Se usó el conector Parallel en modo lectura; no se contrató ni conectó ningún proveedor.

## Alpaca

- https://alpaca.markets/sdks/python/api_reference/data/option/historical.html — La referencia de `OptionHistoricalDataClient` expone `get_option_bars`, `get_option_trades`, `get_option_latest_quote`, `get_option_snapshot` y `get_option_chain`. En el SDK instalado se confirmó por introspección que no existe `get_option_quotes` histórico.
- https://docs.alpaca.markets/reference/optionbars — Las barras históricas de opciones son agregados por contrato y se entregan con paginación `next_page_token`.
- https://docs.alpaca.markets/us/docs/historical-option-data — La página documenta históricos de opciones desde febrero de 2024 y distingue Indicative de OPRA. Indicative no son quotes OPRA reales; OPRA es BBO consolidado y requiere suscripción.

## Databento

- https://databento.com/options — Distribuidor con licencia de datos de opciones de bolsas estadounidenses. La página declara datos en vivo e históricos, OPRA consolidado, last sale y National BBO, instrument definitions, estadísticas/open interest, tick data y más de 1.4 millones de contratos de opciones de acciones estadounidenses. La página muestra OPRA desde 2013 y precio histórico publicado desde $0.04/GB; el coste final depende del dataset/consulta.
- https://databento.com/catalog/opra/OPRA.PILLAR — Catálogo OPRA para last sale, exchange BBO y national BBO de opciones de acciones estadounidenses.

## algoseek

- https://algoseek.com/options — Declara captura lossless del feed OPRA desde 2014, seguimiento completo listing-to-expiry, trades/quotes, trades+NBBO quotes, barras de minuto, security master, open interest y GTH.
- https://algoseek.com/dataset/us-options-trade-and-nbbo-quote/ — Dataset tick-level con trades y NBBO derivado de OPRA TAQ, metadatos de condiciones, complex-order indicators e ISO, referencias de open interest/EOD y cobertura de todas las bolsas estadounidenses que reportan por OPRA. La página ofrece archivo histórico completo y actualizaciones diarias; el precio individual se solicita, y muestra paquete indicativo desde $7,200/mes.
- https://algoseek.com/dataset/us-options-trade-and-top-of-book-quote/ — Añade al trade el NBBO más reciente, top-of-book por bolsa y campos bid/ask/last del subyacente con tamaño y timestamp.
- https://algoseek.com/options-package/ — La página de paquete consultada muestra Options Historical Research Package desde $3,000/mes, sin exchange fees históricos, hasta 10 usuarios y 14 datasets; precio sujeto a confirmación.

## Cboe DataShop

- https://datashop.cboe.com/option-quote-intervals — El resultado oficial describe intervalos de quotes de 1 minuto o N-minuto; cada snapshot incluye NBBO, tamaño, OHLC y volumen. Es un producto agregado, no necesariamente el tick completo.
- https://datashop.cboe.com/option-eod-summary — El resultado oficial describe snapshot EOD con best bid/ask NBBO y tamaño por serie.
- https://datashop.cboe.com/data-products — El catálogo oficial enumera Option Quotes de 1 minuto o N-minuto con NBBO, tamaño, OHLC y volumen, con open interest/calculations opcionales.
- https://datashop.cboe.com/main-channel-tick-data — El resultado oficial indica historia desde enero de 2004 para símbolos activos; no soporta históricos de símbolos inactivos o retirados en ese producto.
- https://datashop.cboe.com/sip-fees — El catálogo muestra tarifas SIP que deben distinguirse del precio del producto histórico y confirmarse antes de contratar.

## ThetaData

- https://thetadata.us/pricing/ — Declara datos de opciones de todos los exchanges, trades/quotes, históricos, Greeks y flat files; el precio no quedó extraído de forma concluyente.
- https://docs.thetadata.us/operations/index_history_eod.html — La documentación EOD muestra campos bid/ask, tamaños, exchanges y condiciones, pero es un reporte EOD; no prueba por sí sola cobertura intradía completa.
- https://http-docs.thetadata.us/operations/get-hist-option-trade.html — El índice de documentación enumera operaciones de históricos de opciones para trades, quotes, trade-quote, OHLC y listados de contratos.
- https://lumibot.lumiwealth.com/backtesting.thetadata.html — Fuente secundaria de integración advierte que algunas series EOD pueden tener gaps aunque exista historia intradía de quotes; sirve como caveat, no como prueba contractual del proveedor.

## Evaluación preliminar

Databento, algoseek, Cboe DataShop y ThetaData superan preliminarmente el bloqueo de “solo OHLC diario” en diferentes grados. Para Polaris, algoseek parece el candidato más directo si se exige lifecycle listing-to-expiry, OPRA lossless, tick-level trade+NBBO y referencias del subyacente; Databento ofrece una alternativa API/bulk con OPRA/NBBO y precio de entrada publicado desde $0.04/GB; Cboe DataShop es atractivo para 1-minuto/N-minuto pero debe comprobarse la cobertura de todas las bolsas y símbolos inactivos; ThetaData expone operaciones de quotes/trades y flat files, pero requiere validar cobertura, límites y licencias antes de elegirlo.

Ninguna opción queda aprobada aún. Falta confirmar para una muestra real de AMD, F, BB, NOK, PLTR, TQQQ y TSLA: existencia de quotes NBBO en las fechas de Polaris, cadena point-in-time, campos de contract lifecycle, acceso al histórico completo, licencia de investigación/backtesting y coste final.
