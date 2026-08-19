# Failure/retest de breakout — fuentes y formalización

**Fecha:** 19 de agosto de 2026.

## Alcance

El motor actual `opt_day_breakout` confirma una ruptura de canal Donchian de 10 barras, pero no clasifica por separado aceptación, fallo o retest. Esta investigación evalúa si una capa observacional puede registrar qué ocurre después de la primera ruptura sin modificar las entradas.

## Evidencia

La revisión de reglas técnicas de Bajgrowicz y Scaillet muestra que resultados aparentes de reglas técnicas pueden sufrir falsas descubiertas, falta de persistencia y sensibilidad a costes; la lección para este motor es que una definición flexible de “retest” permite sobreajuste y debe congelarse antes del backtest [1].

El concepto practitioner de falso breakout describe un movimiento que cruza un soporte/resistencia y vuelve a cerrar dentro del rango; es una definición operativa útil, pero no evidencia académica de rentabilidad [2]. La idea de retest —antigua resistencia que actúa como soporte después de romper— también es una heurística de estructura, no una garantía de continuación [3].

## Definición determinista para Polaris

1. Calcular el nivel de ruptura usando el máximo Donchian previo y excluir la barra actual.
2. Marcar `break_confirmed` cuando una barra cerrada cierra por encima del nivel.
3. Dentro de las siguientes `retest_max_bars` barras, marcar `retest_touched` si el mínimo alcanza el nivel dentro de una tolerancia ATR.
4. Marcar `accepted` si una barra posterior cierra por encima del nivel y supera el máximo de la barra de retest.
5. Marcar `failed` si una barra cierra de nuevo por debajo del nivel antes de aceptación.
6. Para long-only, solo `accepted` puede evaluarse como continuación; `failed` se registra para medir falsos breakouts, nunca como short.
7. Entrada simulada en la apertura siguiente a aceptación; stops/targets teóricos y costes explícitos.

## Riesgos

Un retest de 1–3 barras puede ser demasiado estricto en 5m y uno de 5–10 barras puede capturar cualquier consolidación. La tolerancia ATR y la elección de nivel influyen mucho. El motor debe compararse contra DayBreakout y contra Breakout20/55, reportando señales solapadas, trades, retorno, drawdown y latencia.

## Referencias

[1] [Bajgrowicz and Scaillet — Technical Trading Revisited: False Discoveries, Persistence Tests, and Transaction Costs](https://ideas.repec.org/p/chf/rpseri/rp0805.html).

[2] [False Breakout Trading Strategy — Price Action](https://priceaction.com/price-action-university/strategies/false-break-out/).

[3] [Break and Retest Trading Strategy — practitioner explanation](https://www.youtube.com/watch?v=68HBYHeOxm0).
