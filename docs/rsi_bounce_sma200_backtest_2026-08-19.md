# RSI bounce sobre SMA200 — 2026-08-19

## Decisión

**Decisión: `RESEARCH_ONLY`; no integrar en producción, ni siquiera como shadow por ahora.** El motor es determinista y los tests pasan, pero las variantes 15m quedan por debajo de DayBreakout en la cobertura completa y el supuesto resultado positivo de 5m depende de muy pocos trades y no tiene baseline completo comparable. El walk-forward no solapado tampoco muestra una mejora estable.

La hipótesis queda documentada para futuras pruebas, pero no se añade a `bot.py` ni a `config.yaml`. Producción mantiene únicamente las capas shadow previamente verificadas.

## Hipótesis y límites

RSI se usa como confirmación de recuperación después de sobreventa, no como alarma automática de compra. El detector exige precio sobre SMA200, opcionalmente SMA50>SMA200, un mínimo de RSI bajo el umbral y una recuperación que rompe el máximo de las barras previas. La entrada simulada ocurre en la apertura siguiente; el stop/target son teóricos.

La evidencia consultada no demuestra que RSI 14 intradía genere alpha reproducible. Poterba y Summers documentan autocorrelación positiva a horizontes cortos y negativa a horizontes largos, pero no prueban RSI ni una regla 5m/15m [1]. La investigación de reversión corta destaca que los costes de inmediatez pueden absorber o superar el retorno aparente cuando se incluyen costes [2]. Por ello, RSI bounce se evalúa como hipótesis de mean reversion condicionada por régimen, no como señal segura.

## Metodología

Se evaluaron **72 variantes** y **402 filas** sobre caches reales OHLCV de Alpaca IEX: 5m y 15m, con daily setup history para el régimen. La cobertura usable fue PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI quedó fuera por falta de histórico intradía utilizable.

Las dimensiones fueron RSI 2/5/14, umbral 20/25/30, SMA50>SMA200 activado o no y gate `none`/`bull`. La gestión usa entrada en la siguiente apertura, stop basado en ATR/estructura, target 1.5R, máximo de 36 barras en 5m o 20 barras en 15m y 5 bps de slippage por lado. No se usa información futura para RSI, SMA, ATR, régimen, fills o stops.

El baseline es DayBreakout S78 en 15m. Las ventanas de matriz son `recent_5d`, `prior_5d`, `prior_10d`, `recent_20d`, `full_available` y `recent_40d` cuando existe cobertura. El 5m no se compara contra el baseline 15m en `full_available` porque no hay ventana temporal equivalente completa.

## Resultados de cobertura completa

| Configuración | Retorno full | Max drawdown | Delta retorno vs baseline | Delta drawdown vs baseline | Trades | Lectura |
|---|---:|---:|---:|---:|---:|---|
| DayBreakout S78 15m | **+8.485%** | −3.097% | — | — | 156 | Referencia |
| RSI2 <30 + gate bull | +6.292% | −3.266% | −2.193 pp | −0.169 pp | 130 | Mejor 15m, pero inferior |
| RSI2 <25 + gate bull | +4.961% | −3.248% | −3.524 pp | −0.151 pp | 122 | Inferior |
| RSI2 <30 + SMA50>SMA200 + gate bull | +4.764% | −3.259% | −3.721 pp | −0.162 pp | 121 | Inferior |
| RSI5 <20 + gate bull | +0.478% | −4.389% | −8.007 pp | −1.293 pp | 31 | Inferior y más riesgo |
| RSI14 <30 + gate bull | −2.447% | −3.074% | −10.932 pp | +0.022 pp | 16 | No aporta retorno |
| RSI14 <20 sin gate | −2.138% | −2.341% | −10.623 pp | +0.755 pp | 7 | Muestra demasiado pequeña |

En 15m ninguna variante supera el retorno de DayBreakout en `full_available`. Algunas reducen drawdown, pero a costa de menor exposición y retorno; eso no demuestra una mejora de la estrategia. Las variantes RSI2 sin gate se degradan con rapidez: RSI2<30 sin filtro SMA termina en −15.094% y DD −20.096%, mostrando el riesgo de comprar sobreventa sin régimen.

En 5m, la mejor fila agregada fue RSI14<20 sin SMA adicional y sin gate, con 4 ventanas positivas y 4 trades totales. Ese resultado es insuficiente: cuatro operaciones no permiten estimar robustez, no hay comparación full equivalente y el resultado está dominado por la selección de una configuración extremadamente selectiva.

## Walk-forward no solapado

Se ejecutaron cinco folds cronológicos de 15m tras excluir 20 sesiones de warm-up. Algunos folds no tuvieron trades del baseline ni del candidato; se conservan como evidencia de no-signal, no se rellenan artificialmente.

| Fold | Baseline | RSI2<30 bull | RSI5<20 bull | RSI14<30 bull | RSI14<20 none |
|---|---:|---:|---:|---:|---:|
| 1 | 0.000% | 0.000% | 0.000% | 0.000% | 0.000% |
| 2 | +0.384% | −1.002% | −0.761% | −0.692% | −0.935% |
| 3 | 0.000% | 0.000% | 0.000% | 0.000% | −0.189% |
| 4 | +8.948% | +8.821% | +2.019% | −0.977% | −0.851% |
| 5 | −1.038% | −1.331% | −0.759% | −0.759% | −0.175% |

La configuración RSI2<30 bull queda por debajo del baseline en los tres folds con actividad: −1.387 pp, −0.127 pp y −0.293 pp. RSI5<20 bull solo mejora en el fold 5 y cae fuertemente en el fold 4. RSI14<30 bull no muestra ventaja. Los folds sin actividad son importantes operativamente, pero no convierten al motor en una fuente de alpha.

## Riesgos y siguiente prueba posible

La principal debilidad es la **reversión contra tendencia**: en el conjunto completo, la sobreventa intradía aparece muchas veces antes de nuevas caídas. El filtro SMA200 evita parte del daño, pero no distingue una corrección saludable de una ruptura de régimen. Además, la concentración por símbolo —especialmente PLTR y BB en las filas más rentables— impide afirmar que el resultado sea universal.

Si se retoma esta línea, la siguiente prueba debe congelar RSI2<30 + gate bull, usar al menos tres meses nuevos, incluir leave-one-symbol-out, separar días de crash y medir fills de opciones reales. Ningún resultado debe conectarse a entradas hasta superar ese protocolo.

## Artefactos

- `strategies/rsi_bounce_sma200.py`
- `tests/test_rsi_bounce_sma200.py`
- `scripts/run_rsi_bounce_backtests.py`
- `scripts/analyze_rsi_bounce_backtests.py`
- `scripts/run_rsi_bounce_walkforward.py`
- `docs/rsi_bounce_research_sources_2026-08-19.md`
- `backtests/rsi_bounce_backtests_2026-08-19.csv`
- `backtests/rsi_bounce_backtest_trades_2026-08-19.csv`
- `backtests/rsi_bounce_backtest_comparison_2026-08-19.csv`
- `backtests/rsi_bounce_backtest_variant_summary_2026-08-19.csv`
- `backtests/rsi_bounce_walkforward_2026-08-19.csv`

## Referencias

[1] [Poterba and Summers, Mean Reversion in Stock Prices: Evidence and Implications](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=227278).

[2] [Short-term reversals, returns to liquidity provision and the costs of immediacy](https://ideas.repec.org/a/eee/jbfina/v138y2022ics0378426622000309.html).
