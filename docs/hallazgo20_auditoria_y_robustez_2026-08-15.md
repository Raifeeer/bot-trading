# Hallazgo 20 — Auditoría profunda, robustez y walk-forward

**Fecha:** 15 de agosto de 2026
**Repositorio:** `Raifeeer/bot-trading`
**Commit de referencia previo:** `60866ab`
**Naturaleza:** investigación PAPER; no cambia Cloud Run ni envía órdenes.

## 1. Auditoría de código

La auditoría estática y funcional corrigió varios problemas confirmados. En `loop_backtests.py`, los filtros `above_sma200` y `volume_spark` usaban la última fila del DataFrame completo y podían leer datos posteriores a la fecha de decisión; ahora calculan exclusivamente sobre `hist <= d`. Se añadió `slippage_pct` opcional para spreads, con ajuste de entrada y salida; el valor 0% conserva compatibilidad legacy, pero las rondas de investigación usan 3% salvo que se indique lo contrario.

En `data/feed.py`, se normalizaron timestamps naive/aware con un helper UTC único. La rama de ventanas totalmente recientes ya no intenta consultar Alpaca con un rango invertido; usa Yahoo directamente. También se eliminaron `datetime.utcnow()` y un import muerto. Los contratos de riesgo, polaridad long/short de opciones, precios límite cero, reconstrucción de patas y rollover diario ya fueron corregidos en commits anteriores y tienen pruebas deterministas asociadas.

## 2. Estrategias evaluadas

La matriz ejecutó 73 configuraciones con cuatro ventanas: lateral 2025-09–2025-12, selloff 2026-01–2026-04, ciclo reciente 2026-04–2026-08-14 y últimos 30 días. Incluyó `regime_hold_cash`, `hold_weekly`, `smc_daily`, `put_choch`, `breakout20` y `breakout55`, con niveles de riesgo, DTE, deltas y slippage. La matriz usó yfinance mediante `MarketDataFeed`, 520 días de historia y excluyó el calendario actual de earnings por no ser point-in-time.

Los motores `regime_hold_cash` y breakout fueron los únicos que mostraron configuraciones positivas en una mayoría de ventanas; `smc_daily` fue negativo en la mayoría de sensibilidades y con drawdowns altos. Los positivos más altos se concentraron en ventanas recientes y tuvieron riesgo de dependencia de régimen.

## 3. Walk-forward

El primer walk-forward seleccionó `regime_hold_cash` con train 2025-09–2026-03, validation 2026-04–2026-06 y test 2026-07–2026-08-14. El test terminó en $93.9677 (-6.0323%), con 42 operaciones, profit factor 0.4851 y drawdown -9.62%.

El walk-forward rodante confirmó dependencia temporal: fold A seleccionó `regime_hold_cash` y obtuvo +39.5727% en abril–junio; fold B seleccionó el mismo motor pero obtuvo -7.4418% en julio–agosto.

## 4. Sensibilidad y ensembles

La sensibilidad ejecutó 156 combinaciones con riesgo, slippage y costes equity. `regime_hold_cash` alcanzó 75% de ventanas positivas en sus mejores costes, con retorno mediano aproximadamente 16%–17%, pero su peor ventana fue negativa. `breakout55` llegó a 75% de ventanas positivas en algunas configuraciones, pero varias tuvieron pocas operaciones y peor ventana negativa. `smc_daily` fue descartado como candidato actual por retornos medianos negativos y drawdowns elevados.

Un ensemble fijo 70% `regime_hold_cash` + 30% `breakout55` produjo la mejor mediana de la prueba combinada: +13.493%, peor ventana -5.208%, drawdown mediano -10.238% y 3/4 ventanas positivas. El ensemble walk-forward seleccionó 50/50 en fold A y 30/70 en fold B; los tests fueron +34.985% y -2.232%, respectivamente. La reducción del drawdown no elimina la pérdida fuera de muestra ni justifica despliegue.

## 5. Contexto de mercado

El contexto fechado está en `docs/market_context_2026-08-15.md`. Las fuentes describen: venta tecnológica y rebote incompleto el 9 de junio; recuperación V-shaped y casi 10% de drawdown en abril; caída de Brent cercana al 40% en el segundo trimestre y rally AI en junio; y lateralidad/AI wobble alrededor de la decisión de tipos de diciembre de 2025. Las noticias se usan solo para etiquetar ventanas y nunca como información posterior a la decisión histórica.

## 6. Decisión

No se cambia la estrategia PAPER de producción por estos resultados. No hay evidencia de que una meta ficticia de $100→$200 sea robusta o alcanzable en corto plazo. La siguiente ronda válida debe usar datos point-in-time de opciones/earnings, más ventanas fuera de muestra y un modelo de fills que incluya bid/ask, liquidez, assignment y riesgo de gap. Hasta entonces, los candidatos breakout/regime se mantienen como investigación.

## Artefactos

- `backtests/research_matrix_2026-08-15.csv`
- `backtests/sensitivity_2026-08-15.csv`
- `backtests/sensitivity_summary_2026-08-15.csv`
- `backtests/walk_forward_2026-08-15.csv`
- `backtests/rolling_walk_forward_2026-08-15.csv`
- `backtests/ensemble_research_2026-08-15.csv`
- `backtests/ensemble_walk_forward_2026-08-15.csv`
- `docs/market_context_2026-08-15.md`

## Referencias de mercado

[1] [Reuters, S&P 500/Nasdaq fall as tech selling resumes, 9 jun 2026](https://www.reuters.com/business/media-telecom/wall-st-futures-tick-up-chips-extend-gains-2026-06-09/)
[2] [CNBC, recovery after tech sell-off, 9 jun 2026](https://www.cnbc.com/2026/06/09/stock-market-sell-off-sp-500-nasdaq-tech-chips-fed-hikes.html)
[3] [J.P. Morgan, V-shaped rebound after Iran conflict drawdown, 24 abr 2026](https://www.jpmorgan.com/insights/markets-and-economy/top-market-takeaways/tmt-why-are-stocks-at-record-highs-with-no-iran-resolution)
[4] [Reuters, quarterly gains and oil decline, 30 jun 2026](https://www.reuters.com/world/china/global-markets-global-markets-2026-06-30/)
[5] [CNBC, market sideways and AI wobble, 4 dic 2025](https://www.cnbc.com/2025/12/03/stock-market-today-live-updates.html)

## 7. Cierre de auditoría estática

Después de la revisión se ejecutó Ruff con reglas F/B sobre todo el repositorio: **0 hallazgos**. También pasó `python3 -m compileall -q .`. Los tests deterministas de feed/caché, riesgo y ejecución pasaron; el test del asistente también termina en OK, aunque registra que `gpt-4o-mini` no está soportado por el proxy actual y debe sustituirse por un modelo permitido si se quiere probar la llamada LLM real.

Se limpiaron imports, variables muertas, cierres con captura tardía, f-strings sin interpolación y nombres de iteradores no utilizados en scripts auxiliares. Estos cambios no se desplegaron a Cloud Run; quedan en el commit de auditoría para revisión y posterior decisión de publicación.
