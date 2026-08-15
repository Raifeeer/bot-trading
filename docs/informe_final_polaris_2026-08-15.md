# Informe final de Polaris — auditoría, backtesting y robustez

**Fecha:** 15 de agosto de 2026
**Repositorio:** [`Raifeeer/bot-trading`](https://github.com/Raifeeer/bot-trading)
**Commit final:** [`ae8437b`](https://github.com/Raifeeer/bot-trading/commit/ae8437b)
**Modo operativo:** PAPER; no se enviaron órdenes reales durante esta investigación.

## Resumen ejecutivo

La incidencia operativa de Firestore quedó resuelta y verificada en Cloud Run. La revisión `polaris-bot-00056-f48` registró `FIRESTORE_ENABLED=True`, una escritura completa con el log `Estado escrito en Firestore`, y posteriormente `Tick OK`; el documento de Firestore avanzó con una curva de 34 puntos y sin los campos temporales `probe`/`diag`. El servicio permanece en PAPER y no se promovió ninguna estrategia nueva.

La auditoría profunda detectó y corrigió una fuga de look-ahead en los filtros SMA200 y volumen, una regresión de timezone en el feed para ventanas recientes, variables y cierres problemáticos en scripts auxiliares, y varios contratos operativos de riesgo y ejecución ya incorporados en commits previos. Ruff F/B terminó con **cero hallazgos**, `compileall` pasó y los tests deterministas de feed, riesgo y ejecución pasaron.

La investigación de estrategias no encontró evidencia robusta para perseguir $100→$200 en corto plazo. `regime_hold_cash` fue el motor más consistente por ventanas, pero el test más reciente del walk-forward terminó negativo. Los motores `breakout20/55` produjeron resultados positivos en ciertos periodos, aunque con pocas operaciones y dependencia del régimen. Un ensemble de régimen y breakout redujo drawdown y suavizó pérdidas, pero siguió negativo en el test más reciente. El resultado correcto es **no desplegar cambios de estrategia** y continuar con datos point-in-time y fills realistas.

## Estado operativo

| Componente | Estado verificado |
|---|---|
| Cloud Run | Servicio `polaris-bot`; revisión 00056 validada; no se hizo redeploy de estrategia después de la auditoría. |
| Firestore/Firebase | Base Native `polaris`; snapshot actualizado y escritura completa verificada. |
| GitHub | `origin/main` actualizado al commit `ae8437b`; árbol local limpio. |
| Vercel | CLI e integración disponibles; no fue necesario tocar el dashboard durante esta investigación. |
| Alpaca | PAPER; no se modificó la configuración de ejecución real. |
| Dashboard | Se confirmó que el bundle productivo usa Firestore real; el contrato de riesgo fue documentado. |

## Auditoría de código y correcciones

La primera auditoría cubrió loop principal, datos, riesgo, Firestore, Telegram, ejecución de opciones, reconstrucción de spreads, backtesting y scripts de estrés. Se corrigió la polaridad de patas long/short, se bloquearon precios límite cero, se persistieron símbolos de patas para reconstrucción, se hizo determinista el rollover diario del circuito de riesgo, se corrigió el régimen sin datos y se alinearon porcentaje y fracción del contrato de riesgo del dashboard/Telegram.

La segunda ronda encontró una fuga importante en `loop_backtests.py`: `above_sma200` y `volume_spark` usaban la última fila del DataFrame completo, por lo que podían leer información posterior a la fecha de decisión. Ambos filtros ahora calculan sobre `hist <= d`. El feed ahora normaliza fechas naive/aware a UTC y evita rangos invertidos cuando una ventana es totalmente reciente. También se añadió un overlay de slippage opcional para opciones y un coste equity round-trip para benchmarks.

La revisión estática completa del repositorio terminó con **0 errores Ruff F/B** y `python3 -m compileall -q .` pasó. Los tests deterministas pasaron: caché/feed, contrato de riesgo y contrato de ejecución. El test del asistente termina en OK, aunque el proxy registra que `gpt-4o-mini` no es un modelo soportado; si se requiere probar la llamada LLM real, debe sustituirse por un modelo permitido.

## Diseño de backtesting

Se usaron datos reales descargados mediante `MarketDataFeed` y yfinance, con 520 días de historia para ocho símbolos del universo PAPER. Las ventanas fueron lateralidad de septiembre–diciembre de 2025, selloff enero–abril de 2026, ciclo reciente abril–14 de agosto de 2026 y últimos 30 días. Las corridas primarias excluyeron el calendario de earnings actual porque no es point-in-time.

La matriz incluyó 73 configuraciones de `regime_hold_cash`, `hold_weekly`, `smc_daily`, `put_choch`, `breakout20` y `breakout55`, con variaciones de riesgo, DTE, deltas y slippage. Se añadieron escenarios breakout de 20 y 55 sesiones: el cierre debe superar el máximo de las barras anteriores y el volumen debe superar 1.2x su referencia, siempre usando solo datos disponibles hasta la fecha de decisión.

La sensibilidad ejecutó 156 configuraciones con riesgo 5–15%, slippage de opciones 1–5% y coste equity de 0.1–0.5% round-trip. Los resultados completos están en `backtests/research_matrix_2026-08-15.csv` y `backtests/sensitivity_2026-08-15.csv`.

## Resultados y robustez

| Motor o construcción | Evidencia principal | Lectura operativa |
|---|---|---|
| `regime_hold_cash` | Mejor consistencia agregada; mejores configuraciones con 3/4 ventanas positivas; peor retorno todavía negativo. | Candidato de investigación, no estrategia validada. |
| `breakout55` | Mediana positiva en varias ventanas y hasta 3/4 ventanas positivas en sensibilidad; pocas operaciones en varios splits. | Posible complemento, alto riesgo de dependencia de muestra. |
| `breakout20` | Positivo en algunas ventanas, pero menor consistencia que breakout55. | No promover sin más datos fuera de muestra. |
| `hold_weekly` | Resultados cercanos a plano o negativos después de costes. | Benchmark, no candidato principal. |
| `smc_daily` | Retorno mediano negativo y drawdowns altos en la mayoría de sensibilidades. | Descartado como candidato actual de afinación. |
| `put_choch` | Pérdidas en selloff de muestra y pocas operaciones recientes. | No usar como motor principal. |

El walk-forward estricto seleccionó `regime_hold_cash` usando train/validation y terminó en el test julio–agosto con **$93.9677 (-6.0323%)**, 42 operaciones, profit factor 0.4851 y drawdown -9.62%. El walk-forward rodante mostró dependencia temporal: el fold abril–junio terminó en +39.5727%, mientras el fold julio–agosto terminó en -7.4418% con el mismo motor seleccionado.

Se probó un ensemble fijo de `regime_hold_cash` y `breakout55`. El mejor resultado agregado fue 70% régimen y 30% breakout, con retorno mediano +13.493%, peor ventana -5.208% y drawdown mediano -10.238%. En el walk-forward del ensemble, el fold A seleccionó 50/50 y obtuvo +34.985% en test; el fold B seleccionó 30/70 y obtuvo -2.232% en test. La mejora de drawdown no elimina la pérdida fuera de muestra y el peso cambia entre folds.

> La evidencia disponible muestra una estrategia dependiente del régimen, no una máquina robusta de duplicación de capital. Optimizar hasta encontrar $100→$200 en una ventana sería sobreajuste, no validación.

## Contexto de mercado

El contexto de mercado se documentó en `docs/market_context_2026-08-15.md`. Reuters y CNBC describieron el 9 de junio una venta tecnológica con rebote incompleto, presión de inflación, expectativas de tipos, riesgo geopolítico y preocupación por valoraciones AI [1] [2]. J.P. Morgan describió el 24 de abril una caída cercana al 10% del S&P 500 seguida de recuperación a niveles preconflicto en 11 sesiones, con una recuperación aproximada de 12.5% desde el 30 de marzo hasta el 22 de abril [3]. Reuters reportó el 30 de junio un trimestre de fuerte rally global, caída de Brent cercana al 40% y sensibilidad a petróleo, dólar, Fed y AI [4]. CNBC describió el 4 de diciembre de 2025 una sesión de lateralidad, expectativas de recorte de la Fed y wobble del AI trade [5].

Estos hechos se usan para etiquetar ventanas de selloff, rebote, lateralidad, concentración y shock energético. No se inyectan como señales automáticas ni se usan noticias posteriores a una decisión histórica.

## Decisión y siguientes pasos

No se desplegará ninguna nueva estrategia en Cloud Run. El bot PAPER conserva su configuración operativa y la revisión 00056 queda como estado estable de Firestore. Antes de cualquier ajuste productivo, el siguiente trabajo debe obtener cadenas de opciones point-in-time, calendario de earnings point-in-time, bid/ask históricos, liquidez, assignment y gaps; después debe repetir walk-forward con más años y una ventana completamente fuera de muestra.

La próxima decisión técnica razonable es construir un dataset de opciones histórico con snapshots fechados y un modelo de fill conservador. Hasta completar eso, `regime_hold_cash`, `breakout20` y `breakout55` deben permanecer como candidatos de investigación y no como cambios del bot. Tampoco se debe interpretar el resultado como asesoramiento financiero ni como expectativa de rentabilidad.

## Artefactos principales

| Artefacto | Uso |
|---|---|
| [`docs/hallazgo20_auditoria_y_robustez_2026-08-15.md`](https://github.com/Raifeeer/bot-trading/blob/main/docs/hallazgo20_auditoria_y_robustez_2026-08-15.md) | Informe técnico reproducible de auditoría y robustez. |
| `backtests/research_matrix_2026-08-15.csv` | Matriz de 73 configuraciones. |
| `backtests/sensitivity_2026-08-15.csv` | 156 combinaciones de sensibilidad. |
| `backtests/rolling_walk_forward_2026-08-15.csv` | Dos folds walk-forward. |
| `backtests/ensemble_walk_forward_2026-08-15.csv` | Selección de pesos de ensemble fuera de muestra. |
| `backtests/charts/matrix_median_returns.png` | Heatmap por motor y ventana. |
| `backtests/charts/ensemble_weight_sensitivity.png` | Sensibilidad al peso breakout. |
| `backtests/charts/ensemble_walk_forward_test.png` | Resultado test por fold y peso. |

## Referencias

[1]: https://www.reuters.com/business/media-telecom/wall-st-futures-tick-up-chips-extend-gains-2026-06-09/ "Reuters, tech selling resumes, 9 jun 2026"
[2]: https://www.cnbc.com/2026/06/09/stock-market-sell-off-sp-500-nasdaq-tech-chips-fed-hikes.html "CNBC, tech sell-off and risks, 9 jun 2026"
[3]: https://www.jpmorgan.com/insights/markets-and-economy/top-market-takeaways/tmt-why-are-stocks-at-record-highs-with-no-iran-resolution "J.P. Morgan, V-shaped rebound, 24 abr 2026"
[4]: https://www.reuters.com/world/china/global-markets-global-markets-2026-06-30/ "Reuters, quarter gains and oil decline, 30 jun 2026"
[5]: https://www.cnbc.com/2025/12/03/stock-market-today-live-updates.html "CNBC, lateralidad y AI wobble, 4 dic 2025"
