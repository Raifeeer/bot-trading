# Relative strength / cross-sectional momentum — fuentes y hallazgos

**Fecha:** 19 de agosto de 2026.

## Pregunta

Evaluar si clasificar los símbolos del universo Polaris por retorno relativo y seleccionar líderes/rezagados puede cubrir una brecha que los motores independientes no observan, sin confundir momentum cross-sectional de horizonte mensual con una señal intradía validada.

## Fuente 1 — momentum cross-sectional fundacional

**URL:** https://doi.org/10.2307/2328882

El trabajo de Jegadeesh y Titman, *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency*, es la referencia fundacional de la idea de comprar ganadores recientes y vender perdedores recientes. La página DOI no pudo extraerse por un error de red en esta sesión; se conserva como referencia primaria y no se usan cifras no verificadas.

**Aplicación:** El detector de Polaris debe declarar el horizonte de formación y no transferir automáticamente evidencia de décadas/mensual a barras de 5m/15m.

## Fuente 2 — momentum crashes

**URL:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2371227

Daniel y Moskowitz describen que las estrategias momentum han presentado retornos altos históricamente, pero también asimetría negativa y episodios fuertes y persistentes de pérdidas. El resumen identifica los estados de pánico, después de caídas de mercado y con volatilidad alta, junto con rebotes del mercado, como contextos de riesgo para momentum.

**Aplicación:** El backtest debe incluir régimen bull/bear/crash, volatilidad o un proxy de dispersión, y no permitir que una rotación basada solo en ranking añada exposición en rebotes violentos tras selloffs. El gate de crash se evalúa como escenario, no se promueve por defecto.

## Fuente 3 — factor momentum en varios mercados

**URL:** https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly

AQR documenta factores Value and Momentum Everywhere como carteras long/short de coste cero en ocho mercados/activos, incluyendo acciones de EE. UU., Reino Unido, Europa y Japón, índices, bonos, divisas y commodities.

**Aplicación:** La fuente respalda que relative strength puede formalizarse como ranking cross-sectional y que el benchmark debe estar declarado. No demuestra un edge en el universo pequeño de ocho tickers, ni autoriza cortas intradía.

## Fuente 4 — evidencia reciente y costes

**URL:** https://www.tandfonline.com/doi/full/10.1080/13504851.2025.2472032

El resultado de búsqueda sobre *Cross-sectional factor momentum: evidence from multiple formation periods* menciona que el análisis considera múltiples periodos de formación y discute resultados ajustados por costes de transacción y rebalanceo menos frecuente. La página completa requiere acceso parcial; se tratará como fuente secundaria de contraste, no como fuente de parámetros.

## Especificación inicial para Polaris

| Dimensión | Hipótesis conservadora |
|---|---|
| Universo | Solo los símbolos disponibles del universo reto; no usar survivorship externo |
| Benchmark | Retorno relativo contra equal-weight del universo y contra SPY/QQQ solo si existe historia as-of |
| Formación | 5d, 10d y 20d para 5m/15m; 20d y 60d para diario, congelados antes del test |
| Señal | líder = percentil superior; rezagado = percentil inferior, separado por dirección |
| Normalización | retorno excess frente a benchmark y z-score cross-sectional opcional |
| Rebalanceo | no más de una vez por sesión en intradía; semanal en diario |
| Costes | slippage y coste de turnover; no asumir que ranking es gratis |
| Riesgo | long-only primero; short solo observacional por política RiskManager |
| Crash | evaluar gate separado; no cambiar el floor ni los circuit breakers |

La evidencia externa justifica probar la hipótesis y controlar reversals/costes, pero no justifica conectar el motor a entradas live. El próximo paso es revisar los caches disponibles y formalizar el benchmark sin look-ahead.
