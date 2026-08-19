# Failure/retest de breakout — 2026-08-19

## Decisión

**Decisión: `RESEARCH_ONLY`; no integrar en producción ni como shadow por ahora.** El detector clasifica de forma reproducible rupturas aceptadas, fallidas y expiradas, pero ninguna configuración supera a DayBreakout en retorno full. Las variantes con mejor drawdown lo consiguen porque reducen drásticamente la cantidad de entradas, no porque produzcan más retorno.

## Definición congelada

Se calculó un nivel de ruptura con el máximo Donchian previo. Una barra cerrada por encima del nivel crea `break_confirmed`. En las siguientes 1, 3 o 5 barras, el mínimo puede tocar el nivel dentro de `0.25 ATR`; después, una barra cerrada que recupera el nivel y supera el máximo de retest marca `accepted`. Un cierre bajo el nivel antes de aceptación marca `failed`; si no ocurre ninguno, `expired`.

Las señales aceptadas se simulan con entrada en la apertura siguiente, stop por debajo del nivel con buffer ATR, target 1.5R, máximo de 36 barras en 5m o 20 en 15m, cierre intradía y 5 bps de slippage por lado. Los estados `failed` y `expired` solo son observaciones; nunca generan cortas.

## Cobertura y anti-look-ahead

Se evaluaron **72 variantes**, **402 filas** y **5,454 trades simulados** sobre caches reales OHLCV de Alpaca IEX en 5m/15m. La cobertura usable fue PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI quedó fuera por falta de histórico intradía válido.

El nivel Donchian y volumen usan solo datos previos. El retest está limitado a la ventana definida. El régimen diario se alinea al cierre previo. Las entradas usan la apertura posterior a aceptación. Las ventanas 5m no se comparan contra el baseline 15m en `full_available` cuando no existe equivalencia temporal.

## Resultados completos

| Configuración | Retorno full | Max drawdown | Delta retorno vs S78 | Delta DD vs S78 | Trades | Secuencias | Aceptadas | Fallidas | Expiradas |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DayBreakout S78 15m | +8.485% | −3.097% | — | — | 156 | — | — | — | — |
| LB55, retest 5, sin volumen, gate bull | +0.995% | −0.836% | −7.490 pp | +2.261 pp | 34 | 445 | 34 | 205 | 206 |
| LB55, retest 3, sin volumen, gate bull | +0.871% | −0.809% | −7.614 pp | +2.288 pp | 28 | 476 | 28 | 180 | 268 |
| LB55, retest 5, volumen 1.0x, gate bull | +0.694% | −1.134% | −7.791 pp | +1.963 pp | 36 | 408 | 36 | 181 | 191 |
| LB20, retest 3, sin volumen, gate bull | +0.669% | −0.465% | −7.816 pp | +2.632 pp | 29 | 758 | 29 | 282 | 447 |
| LB10, retest 3, volumen 1.0x, gate bull | −0.084% | −0.978% | −8.569 pp | +2.119 pp | 34 | 797 | 34 | 296 | 467 |

La variante con más retorno en las ventanas parciales no rescata la cobertura completa. Los gates bull reducen la degradación, pero también dejan al motor con tasas de aceptación bajas: aproximadamente 4–8% en muchas variantes 15m. Sin gate, el número de entradas aumenta y el retorno full se vuelve marcadamente negativo; por ejemplo, LB20 retest 5 sin volumen termina en −8.301% y DD −8.309%.

El retest de una barra no produce entradas aceptadas en esta especificación porque se exige una barra posterior para confirmar aceptación. Es un resultado de la definición congelada, no un dato que deba reinterpretarse para mejorar el resultado.

## Walk-forward no solapado

Se ejecutaron cinco folds cronológicos 15m. Dos folds tuvieron poca o ninguna actividad del baseline; se conservan como no-signal y no se imputan. Entre los folds activos, la configuración LB55/retest5 sin volumen/gate bull obtuvo −0.066% frente a +0.822% del baseline en el fold 2, +0.955% frente a +8.948% en el fold 4 y +0.102% frente a −1.038% en el fold 5. Solo mejora en el último fold y pierde por amplio margen en el periodo fuerte.

| Fold | Baseline S78 | LB55 RT5 bull | Delta retorno | Lectura |
|---|---:|---:|---:|---|
| 1 | 0.000% | 0.000% | 0.000 pp | Sin señal |
| 2 | +0.822% | −0.066% | −0.887 pp | Inferior |
| 3 | 0.000% | 0.000% | 0.000 pp | Sin señal |
| 4 | +8.948% | +0.955% | −7.993 pp | Inferior en tendencia fuerte |
| 5 | −1.038% | +0.102% | +1.140 pp | Mejor, muestra pequeña |

El patrón es coherente con la hipótesis: esperar un retest evita parte del ruido y reduce drawdown, pero llega tarde a movimientos fuertes y pierde la mayor parte de la continuación que ya capturó DayBreakout.

## Riesgos y siguiente investigación posible

El estado `failed` es útil para auditar la calidad del breakout existente, pero convertirlo en una entrada short exigiría una política distinta, datos de opciones bear y validación separada de cortas. También debe evitarse doble conteo: una secuencia de retest puede solaparse con Breakout20/55 y con el motor bearish de breakdown/retest.

Si se retoma esta línea, la siguiente prueba debería estudiar únicamente su valor como **métrica de calidad de señales** del DayBreakout, no como motor independiente: porcentaje de breakouts aceptados/fallidos por régimen, símbolo y volumen. El resultado no debe conectarse a entradas hasta contar con una muestra nueva y un protocolo leave-one-symbol-out.

## Artefactos

- `strategies/failure_retest_breakout.py`
- `tests/test_failure_retest_breakout.py`
- `scripts/run_failure_retest_backtests.py`
- `scripts/analyze_failure_retest_backtests.py`
- `scripts/run_failure_retest_walkforward.py`
- `docs/failure_retest_research_sources_2026-08-19.md`
- `backtests/failure_retest_backtests_2026-08-19.csv`
- `backtests/failure_retest_backtest_trades_2026-08-19.csv`
- `backtests/failure_retest_state_summary_2026-08-19.csv`
- `backtests/failure_retest_comparison_2026-08-19.csv`
- `backtests/failure_retest_variant_summary_2026-08-19.csv`
- `backtests/failure_retest_walkforward_2026-08-19.csv`

## Referencias

[1] [Bajgrowicz and Scaillet — Technical Trading Revisited: False Discoveries, Persistence Tests, and Transaction Costs](https://ideas.repec.org/p/chf/rpseri/rp0805.html).

[2] [False Breakout Trading Strategy — Price Action](https://priceaction.com/price-action-university/strategies/false-break-out/).

[3] [Break and Retest Trading Strategy — practitioner explanation](https://www.youtube.com/watch?v=68HBYHeHxis).
