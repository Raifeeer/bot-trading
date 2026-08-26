# Investigación EOD preliminar de opciones — 26 de agosto de 2026

## Pregunta

¿Podemos avanzar sin contratar un proveedor OPRA usando los caches gratuitos ya disponibles para obtener evidencia preliminar sobre estructuras de opciones, sin confundirla con una validación OOS de ejecución realista?

## Método

Se procesaron datos reales cacheados de Alpaca, sin datos sintéticos, mediante `scripts/run_defined_risk_backtests.py`. La corrida se aisló en `/home/ubuntu/backtests/free_eod_preliminary_2026-08-26_*` y evaluó 1.800 combinaciones: 10 estructuras, 3 objetivos DTE, 2 anchuras, 3 perfiles de gestión, 2 modos de régimen y 5 ventanas temporales.

Las ventanas fueron `spring_selloff` (2026-04-01 a 2026-04-30), `early_recovery` (2026-05-01 a 2026-05-31), `summer_trend` (2026-06-01 a 2026-08-07), `latest_30d` (2026-07-01 a 2026-08-07) y `full_recent` (2026-04-01 a 2026-08-07). La lógica usa decisiones semanales de viernes, entrada en la primera barra diaria posterior disponible, OHLC diario, deslizamiento lateral por dirección, comisión de 0,65 USD por contrato y fallback a valor intrínseco cuando falta una barra.

El análisis agregado y el heatmap fueron generados por `/tmp/analyze_free_eod_preliminary_2026-08-26.py`. Los artefactos de salida incluyen resultados, curvas de equity, eventos, manifest, tablas por estructura/ventana/gestión y `free_eod_preliminary_2026-08-26_analysis_return_heatmap.png`.

## Hallazgos

| Métrica | Resultado descriptivo |
|---|---:|
| Corridas | 1.800 |
| Media de retorno por corrida | -2,2779% |
| Mediana de retorno por corrida | -0,8403% |
| Corridas positivas | 18,4444% |
| Drawdown medio | -2,6960% |
| Peor drawdown observado | -32,4303% |
| Eventos de fallback por datos faltantes | 19.285 |

Por estructura, las tres medias menos negativas fueron `bull_put_credit` (-0,4576%), `iron_condor` (-0,4863%) y `put_diagonal` (-0,4880%). `bull_put_credit` tuvo mediana positiva de 0,0241% y 51,1111% de corridas positivas, pero su peor retorno fue -7,1523% y su peor drawdown -10,3005%. Las estructuras de calendario y butterfly presentaron resultados agregados especialmente débiles en esta muestra.

El mejor resultado descriptivo en `full_recent` fue una configuración `bull_call_debit`, DTE 45, anchura 0,05, gestión conservadora y régimen `gated`: retorno 4,6240%, PnL 4.623,98 USD, 18 operaciones cerradas, win rate 55,5556%, profit factor 3,7649%, drawdown -0,7666% y 1 hit de pérdida máxima. Sin embargo, la misma corrida compara con un buy-and-hold del subyacente de 57,9919%; por tanto, el resultado de opciones no demuestra una ventaja económica suficiente y no debe promoverse.

El mejor ranking de estabilidad descriptiva fue `bear_call_credit`, DTE 45, anchura 0,10, gestión conservadora y régimen `neutral_ok`: media 0,8789% a través de las cinco ventanas, mediana 0,4243%, peor ventana 0,0455%, drawdown medio -0,6161% y 40 operaciones cerradas. Esto es un ranking de selección sobre la misma muestra, no una prueba independiente; está sujeto a sobreajuste, sesgo de selección y limitaciones del precio diario.

En la ventana `full_recent`, la media de las 360 corridas fue -4,6053%, la mediana -2,2857%, con 13,6111% de corridas positivas y peor retorno -33,8959%. En `latest_30d`, la media fue -1,8590%, la mediana -0,9019%, con 18,3333% de corridas positivas. Esto no respalda afirmar que el conjunto de motores o estructuras sea rentable de forma robusta.

## Evidencia y compuerta de datos

El proveedor gratuito revisado, Market Data App, declara acceso EOD histórico de opciones con bid/ask, tamaños, cadenas y contratos vencidos, además de un plan Free Forever sin tarjeta y un trial de 30 días sin auto-facturación [1] [2] [3]. No obstante, también declara que no ofrece histórico intradía ni trades a nivel de transacción [3]. La cuenta comprobada mostró OPRA `Not Entitled`; una consulta de TSLA respondió HTTP 401 y consumió cero créditos.

Alpaca declara que su feed Indicative es un derivado gratuito de OPRA y que sus cotizaciones no son quotes OPRA reales; el feed OPRA requiere suscripción [4]. Por eso los caches actuales son útiles para investigación exploratoria, pero no pasan la compuerta `EXECUTION_REALISTIC_OOS`.

La corrida queda clasificada como:

```text
status: EOD_PRELIMINARY
promotion: REJECTED_FOR_EXECUTION_OOS
orders_allowed: false
production_config_changed: false
```

## Incertidumbres y sesgos

La selección histórica de contratos no puede verificarse como cadena point-in-time; el delta histórico no está disponible y se usa moneyness como proxy. Las barras diarias no permiten reconstruir NBBO intradía, tamaños disponibles, prioridad, latencia, partial fills, quotes cruzadas ni lifecycle de una orden MLeg. El fallback intrínseco contabilizó 19.285 eventos de datos faltantes en el conjunto repetido de escenarios, lo que puede distorsionar especialmente estructuras con poca cobertura.

El ranking se obtuvo después de evaluar muchas combinaciones en las mismas ventanas. No existe todavía un test holdout verdaderamente separado con embargo independiente; por eso los mejores parámetros no deben tratarse como seleccionados fuera de muestra. El resultado tampoco controla completamente survivorship de contratos, cambios de símbolo o términos ajustados.

## Implicaciones para Polaris

La investigación gratuita permite mejorar la instrumentación, probar el pipeline de análisis y descartar configuraciones claramente débiles. No justifica cambiar `config/config.yaml`, quitar `risk.halt_new_entries`, activar capas shadow, habilitar una estrategia ni ejecutar una canary.

La compuerta OOS completa continúa requiriendo una fuente con NBBO o equivalente intradía, tamaño, lifecycle, cadena point-in-time, timestamps y licencia verificable. Databento sigue siendo el camino recomendado si en el futuro existe acceso autorizado; Market Data App puede servir como fuente EOD auxiliar, no como sustituto completo.

## Referencias

[1]: https://www.marketdata.app/docs/account/plans/free-forever/ "Market Data App — Free Forever Plan"
[2]: https://www.marketdata.app/docs/account/plans/trader-trial/ "Market Data App — Trader Trial"
[3]: https://www.marketdata.app/data/options/ "Market Data App — Options Data"
[4]: https://docs.alpaca.markets/us/docs/historical-option-data "Alpaca — Historical Option Data"

> Esto es investigación y análisis técnico de un sistema PAPER, no asesoramiento financiero personalizado. Los resultados históricos no garantizan rentabilidad futura ni recuperación de pérdidas.
