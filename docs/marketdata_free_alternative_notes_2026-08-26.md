# Alternativas gratuitas de datos de opciones — evidencia externa

Fecha de consulta: 26 de agosto de 2026.

## Market Data App

- Página de opciones: https://www.marketdata.app/data/options/
- Plan Free Forever: https://www.marketdata.app/docs/account/plans/free-forever/
- Trader Trial: https://www.marketdata.app/docs/account/plans/trader-trial/
- Límites: https://www.marketdata.app/docs/api/rate-limiting/
- Autenticación: https://www.marketdata.app/docs/api/authentication/

La documentación oficial declara que Free Forever cuesta $0/mes, no requiere tarjeta, ofrece 100 créditos API diarios, datos con al menos 24 horas de retraso y hasta un año de histórico. El Trader Trial declara $0 durante 30 días, no requiere tarjeta, no auto-factura al terminar y convierte la cuenta a Free Forever si no se contrata un plan. El trial ofrece 100.000 créditos diarios y un año de histórico para tickers distintos de AAPL; AAPL tiene excepciones de cobertura.

La página de opciones declara que las cotizaciones EOD históricas incluyen bid, ask, bidSize, askSize, last, volumen, open interest, cadena histórica, expiraciones históricas y `firstTraded`. También declara que el histórico de opciones llega hasta 2010 y contiene contratos expirados, delistados y ajustados. La misma página dice que no ofrece histórico intradía ni datos de trades a nivel de transacción. Por tanto, esta fuente puede servir para una validación EOD preliminar, pero no demuestra fills intradía, NBBO tick-by-tick, lifecycle de órdenes ni fills parciales.

La autenticación usa Bearer Token. La documentación ofrece una demo pública de endpoints de opciones para contratos AAPL, por lo que una respuesta exitosa con AAPL no prueba que el token tenga entitlement para otros símbolos. En la cuenta revisada, la pantalla mostró OPRA `Not Entitled`, API Usage `0/100000` y exigencia de Trader plan o superior para OPRA. Una consulta protegida de TSLA respondió HTTP 401 y consumió cero créditos. No se generaron cargos.

## Alpaca

- Histórico de opciones: https://docs.alpaca.markets/us/docs/historical-option-data

Alpaca declara que su feed Indicative es un derivado gratuito de OPRA y que sus quotes/trades no son quotes OPRA reales; también declara que el feed OPRA está disponible solo para usuarios suscritos. Por ello, Indicative no se acepta como execution-realistic OOS.

## Cboe DataShop

- All Access API: https://datashop.cboe.com/cboe-all-access-api

Cboe declara un trial gratuito de 14 días, pero exige autorización de tarjeta. También declara que el trial no es elegible para acceso SIP. Por eso no satisface el requisito actual de no usar tarjeta.

## OptionData.io

- Histórico: https://www.optiondata.io/historical_data/

La página declara histórico de trades desde febrero de 2025 mediante API SQL, con campos de trades, bid/ask y metadatos cuando están disponibles. No se confirmó un plan gratuito sin tarjeta ni se verificó acceso para Polaris; no se usa como fuente actual.

## Conclusión de la evidencia

No se encontró una fuente gratuita y sin tarjeta que combine simultáneamente el universo Polaris, histórico intradía OPRA/NBBO, cadena point-in-time, lifecycle y datos suficientes para fills realistas. Market Data App es la alternativa gratuita más útil para EOD, pero sus resultados deben etiquetarse `EOD_PRELIMINARY` y no `EXECUTION_REALISTIC_OOS`.
