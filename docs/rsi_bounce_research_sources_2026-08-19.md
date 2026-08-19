# RSI bounce / reversión sobre SMA200 — fuentes y hallazgos

**Fecha:** 19 de agosto de 2026.

## RSI como indicador

La búsqueda no encontró evidencia académica primaria suficiente para afirmar que el RSI 14, por sí mismo, genere alpha intradía reproducible. Las fuentes practitioner describen al RSI como oscilador de momentum y advierten que un extremo de sobreventa puede persistir durante una tendencia; por tanto, `RSI < 30` no debe tratarse como alarma automática de reversión.

**Aplicación:** el detector exige que el precio esté sobre SMA200 y que RSI cruce de vuelta por encima de un umbral, en lugar de comprar mientras sigue cayendo. La señal se clasifica como hipótesis de rebote, no como predicción cierta.

## Mean reversion y horizontes

[Mean Reversion in Stock Prices: Evidence and Implications](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227278), de Poterba y Summers, resume evidencia de autocorrelación positiva en horizontes cortos y negativa en horizontes largos, con componentes transitorios relevantes en los retornos mensuales.

**Límite:** el resultado no identifica RSI, no prueba una regla concreta de entrada y no se traslada automáticamente a 5m/15m.

## Costes de reversión de corto plazo

[Short-term reversals, returns to liquidity provision and the costs of immediacy](https://ideas.repec.org/a/eee/jbfina/v138y2022ics0378426622000309.html) reporta que los costes de inmediatez pueden superar los retornos de proporcionar liquidez y que, al incluir costes, algunas alphas de fondos dejan de ser significativas.

**Aplicación:** el backtest debe incluir slippage, medir turnover, separar señales de trades y evitar usar la mejor ventana como prueba. Un rebote de RSI puede capturar solo spread/ruido si no se exige confirmación.

## Especificación inicial para Polaris

| Dimensión | Regla de investigación |
|---|---|
| Tendencia mayor | cierre diario sobre SMA200 o SMA50>SMA200 |
| Sobreventa | RSI 2/5/14 bajo umbral congelado |
| Confirmación | RSI cruza de vuelta sobre umbral y cierre supera máximo/micro nivel previo |
| Entrada | apertura siguiente a barra cerrada |
| Salida | stop ATR/estructura, target R, máximo de barras, sin overnight |
| Gates | none, bull/S78, crash_block |
| Dirección | long-only primero; bear solo observacional |
| Costes | slippage por lado y sensibilidad de volumen/turnover |
| Seguridad | detector puro; cualquier integración sería shadow |

Antes de promoción se exige walk-forward no solapado, leave-one-symbol-out y comparación contra DayBreakout/RSI baseline. Las fuentes aportan cautelas y contexto; no fijan parámetros del bot.
