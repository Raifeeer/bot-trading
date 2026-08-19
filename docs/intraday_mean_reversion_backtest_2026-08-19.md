# Mean-reversion intradía VWAP/ATR — 2026-08-19

## Decisión

**Decisión: `RESEARCH_ONLY`; no integrar en bot.py/config.yaml, no crear capa shadow y no desplegar.** La hipótesis de comprar extensiones bajo VWAP con reclaim posterior reduce parte del riesgo en algunas variantes, pero no supera a DayBreakout en retorno full y muestra pérdidas persistentes cuando se opera sin un gate bull fuerte.

## Definición congelada

Se calculó VWAP desde 09:30 ET usando típico de cada barra ponderado por volumen. La desviación fue `z_vwap=(close−VWAP)/ATR`. Una extensión ocurre cuando `z_vwap` cae por debajo de 1.0, 1.5 o 2.0 ATR. Se exige reclaim de VWAP o de −0.25/−0.5 ATR en una barra posterior; la entrada simulada es la apertura siguiente. El objetivo es el VWAP de la extensión, el stop está bajo el mínimo de extensión menos 0.10 ATR y el máximo de tenencia es 12 barras en 5m o 20 en 15m.

La confirmación se descarta si el VWAP objetivo queda por debajo de la entrada; esto evita generar longs con expectativa geométrica negativa. Solo se evaluaron longs, una señal por símbolo/sesión y 5 bps de slippage por lado. Los gates fueron `none`, `bull` y `no_crash`.

## Cobertura

La matriz ejecutó **36 variantes**, **204 filas** y **8,498 trades** sobre caches intradía reales de Alpaca IEX. La cobertura fue PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI no tenía histórico intradía válido. Las variantes 5m se reportan, pero no se comparan contra `full_available` de DayBreakout 15m como si fueran la misma muestra temporal.

## Resultados full 15m

| Variante | Retorno | Max drawdown | Delta retorno vs S78 | Delta DD vs S78 | Trades | Confirmaciones | Profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| DayBreakout S78 | +8.485% | −3.097% | — | — | 156 | — | — |
| Extensión 2.0 ATR, reclaim 0.25, gate bull | +0.602% | −0.557% | −7.882 pp | +2.540 pp | 25 | 25 | 1.685 |
| Extensión 1.0 ATR, reclaim 0.25, gate bull | −1.445% | −1.600% | −9.930 pp | +1.497 pp | 79 | 79 | 0.570 |
| Extensión 2.0 ATR, reclaim 0.50, gate bull | −1.590% | −1.919% | −10.075 pp | +1.178 pp | 34 | 34 | 0.543 |
| Extensión 1.5 ATR, reclaim 0.25, gate bull | −1.638% | −1.638% | −10.122 pp | +1.459 pp | 48 | 48 | 0.366 |
| Extensión 2.0 ATR, reclaim 0.25, sin gate | −5.920% | −6.015% | −14.405 pp | −2.918 pp | 171 | 171 | 0.503 |
| Extensión 1.0 ATR, reclaim 0.50, sin gate | −21.589% | −21.599% | −30.073 pp | −18.502 pp | 697 | 697 | 0.365 |

El mejor candidato 15m reduce drawdown principalmente porque toma 25 trades frente a 156 del baseline y solo opera en sesiones bull. No hay evidencia de que aumente el retorno o capture oportunidades que DayBreakout pierda.

## 5m y ventanas recientes

La mejor variante 5m fue extensión 2.0 ATR/reclaim 0.25 sin gate, con delta medio de +0.299 pp en las cuatro ventanas comparables. Sin embargo, acumuló solo 48 trades, tuvo profit factor medio 0.951 y no tiene comparación full válida contra el baseline 15m. En la ventana reciente de 20 días produjo +0.030% frente a −0.568% del baseline, pero con 24 trades contra 2 del baseline; la muestra es demasiado pequeña para promoción.

Los gates bull en la ventana reciente llegan a cero o un trade. La mejora aparente frente a un baseline negativo es, en varios casos, permanecer en efectivo, no una reversión capturada de manera demostrable.

## Walk-forward no solapado

Se probaron cinco folds cronológicos 15m. La variante mejor posicionada, extensión 2.0 ATR/reclaim 0.25/gate bull, obtuvo −0.234% frente a +0.822% del baseline en fold 2, 0.000% frente a 0.000% en fold 3, +0.722% frente a +8.948% en fold 4 y +0.120% frente a −1.038% en fold 5. Los folds 1 y 3 tuvieron poca o ninguna actividad. La única mejora clara fue el fold 5, con dos trades, y no compensa la pérdida en el periodo fuerte.

| Fold | Baseline S78 | Mean-reversion 2.0/0.25 bull | Delta | Lectura |
|---|---:|---:|---:|---|
| 1 | 0.000% | 0.000% | 0.000 pp | Sin señal |
| 2 | +0.822% | −0.234% | −1.056 pp | Inferior |
| 3 | 0.000% | 0.000% | 0.000 pp | Sin señal |
| 4 | +8.948% | +0.722% | −8.226 pp | Inferior en tendencia fuerte |
| 5 | −1.038% | +0.120% | +1.158 pp | Mejor, muestra pequeña |

## Diagnóstico por estados y símbolos

El detector registró muchas extensiones sin reclaim. En la variante full 15m 2.0/0.25 bull hubo 84 extensiones, 25 confirmaciones, 56 `no_reclaim` y 3 `confirmation_no_edge`. Esto confirma el riesgo de sobreventa persistente: una extensión bajo VWAP no implica que el precio vuelva pronto.

La agregación de trades de todas las variantes fue negativa en todos los símbolos: F −$22,267, TSLA −$30,522, PLTR −$35,889, AMD −$39,836, TQQQ −$39,963, BB −$43,740 y NOK −$45,331. Estos totales combinan variantes y no son una cartera única; sirven como control contra una conclusión concentrada en un solo ticker.

## Limitaciones y decisión para Polaris

El universo es pequeño y faltan SOFI y benchmarks externos intradía. La VWAP utilizada es de barras OHLCV, no de trades tick-by-tick. No se modeló spread específico de opciones ni fills de patas. La muestra reciente contiene muy pocas operaciones del baseline. La mean-reversion debe permanecer separada de RSI bounce y del setup VWAP ya existente para evitar doble conteo.

No conectar el detector a producción. Si se retoma, la investigación útil sería estudiar su valor como **filtro de riesgo/alerta de persistencia** —porcentaje de extensiones sin reclaim por régimen— en lugar de usarlo como motor de entrada. Cualquier futura integración tendría que empezar en shadow y requerir walk-forward, leave-one-symbol-out y un benchmark intradía comparable.

## Artefactos

- `strategies/intraday_mean_reversion.py`
- `tests/test_intraday_mean_reversion.py`
- `scripts/run_intraday_mean_reversion_backtests.py`
- `scripts/analyze_intraday_mean_reversion_backtests.py`
- `scripts/run_intraday_mean_reversion_walkforward.py`
- `docs/intraday_mean_reversion_research_sources_2026-08-19.md`
- `/home/ubuntu/backtests/intraday_mean_reversion_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/intraday_mean_reversion_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/intraday_mean_reversion_variant_summary_2026-08-19.csv`
- `/home/ubuntu/backtests/intraday_mean_reversion_walkforward_2026-08-19.csv`

## Referencias

[1] [Heston, Korajczyk and Sadka — Intraday Patterns in the Cross-Section of Stock Returns](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2010.01573.x).

[2] [Miwa — Short-Term Return Reversals and Intraday Transactions](https://www.worldscientific.com/doi/abs/10.1142/S2010139219500022).

[3] [Mitchell and Bialkowski — Optimal VWAP Tracking](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2333916).

[4] [Bhatti — Momentum Exhaustion and Fair Value Reversion: An ADX-conditioned VWAP Strategy in FX Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6454659).

[5] [Opportunity-Set Bias in Mean-Reversion Trading Systems](https://concretumgroup.com/opportunity-set-bias-in-mean-reversion-trading-systems/).
