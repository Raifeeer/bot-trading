# Overlay relative-strength priority sobre DayBreakout — 2026-08-19

## Decisión

**Decisión: `RESEARCH_ONLY`; no integrar en bot.py/config.yaml y no desplegar.** El overlay filtra señales existentes de DayBreakout por líderes cross-sectional as-of, pero no mejora el retorno full del baseline. El gate bull reduce drawdown y exposición, aunque parte de la aparente mejora en ventanas recientes es simplemente permanecer en efectivo cuando DayBreakout pierde.

## Diferencia frente a la rotación ya estudiada

La rotación pura construía una cartera diaria long-only o long-short de líderes y rezagados. Este estudio no construye una cartera ni rebalancea: conserva la señal, stop, hold máximo y costes de DayBreakout, y solo pregunta si una señal intradía existente pertenece a un símbolo ubicado entre los top-k del universo diario. El ranking se calcula con retornos de 20 o 60 sesiones hasta el cierre previo; la entrada conserva la apertura de la siguiente barra tras la señal DayBreakout.

## Cobertura y reglas

Se evaluaron 16 variantes sobre datos diarios reales de `setup_history` y barras intradía 15m de Alpaca IEX: horizonte 20/60, top-k 1/2, retorno positivo exigido o solo ranking relativo, y gate `none`/`bull`. La cobertura fue de 7 símbolos: PLTR, F, TSLA, AMD, NOK, BB y TQQQ. SOFI no tenía cache diario utilizable.

El baseline es DayBreakout S78 vigente, con 5 bps de slippage por lado, stop ATR y máximo de barras sin alterar. El overlay es long-only y no introduce cortas. Las sesiones sin cierre diario previo válido quedan sin líderes, fail-closed.

## Resultados completos

| Variante full | Retorno | Max drawdown | Delta retorno vs baseline | Delta DD vs baseline | Trades | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| DayBreakout S78 | +8.485% | −3.097% | — | — | 156 | — | — |
| H60/K2, ranking relativo, gate bull | +3.219% | −1.495% | −5.266 pp | +1.602 pp | 42 | 42.86% | 1.483 |
| H20/K2, retorno positivo, gate bull | +2.963% | −4.025% | −5.522 pp | −0.929 pp | 46 | 50.00% | 1.342 |
| H20/K1, ranking relativo, gate bull | +2.532% | −1.969% | −5.953 pp | +1.128 pp | 22 | 54.55% | 1.663 |
| H60/K1, retorno positivo, gate bull | +0.980% | −1.218% | −7.505 pp | +1.878 pp | 21 | 47.62% | 1.369 |
| H20/K2, ranking relativo, sin gate | −0.769% | −10.791% | −9.254 pp | −7.695 pp | 310 | 39.35% | 0.983 |
| H60/K2, retorno positivo, sin gate | −6.430% | −9.004% | −14.915 pp | −5.907 pp | 301 | 32.89% | 0.848 |

El mejor resultado full es H60/K2 con gate bull, pero sigue 5.266 puntos porcentuales por debajo del baseline. El beneficio de drawdown se explica por la reducción de 156 a 42 trades y por la exposición condicionada al régimen, no por una mejora de selección que aumente el retorno.

## Ventanas recientes y robustez

En la ventana reciente de 20 sesiones el baseline hizo −0.568%. Los overlays bull tuvieron entre 0 y 1 trade y terminaron entre 0.000% y −0.366%; la aparente mejora de +0.568 pp proviene de no operar, por lo que no es evidencia suficiente de alpha. Sin gate, el overlay sí operó más, pero empeoró: H20/K1 terminó −1.421% y H60/K2 −4.197% en esa ventana.

En las seis ventanas del análisis, los mejores overlays bull lograron tres ventanas con retorno superior y tres con criterio conjunto de retorno/drawdown no peor que −0.25 pp, pero todos quedaron por debajo del baseline en full. Esta combinación no satisface un criterio de promoción porque mezcla periodos de cash con selección de señales y no demuestra mejora uniforme.

## Concentración por símbolo

El ledger agregado de trades estuvo concentrado y no uniforme. NOK aportó aproximadamente `$35,775` de P&L agregado, mientras BB aportó aproximadamente `−$95,926` y PLTR `−$21,769` en las variantes combinadas. Estos totales no son una cartera única ni deben interpretarse como rendimiento operativo; muestran que la conclusión es sensible al universo pequeño y a ciertos símbolos.

| Símbolo | Trades agregados | P&L agregado de variantes | Lectura |
|---|---:|---:|---|
| NOK | 525 | +$35,775 | Contribución positiva concentrada |
| TSLA | 178 | +$5,076 | Positiva moderada |
| TQQQ | 81 | +$4,683 | Positiva, muestra menor |
| F | 269 | −$3,776 | Negativa leve |
| AMD | 649 | −$18,424 | Negativa y muy operada |
| PLTR | 276 | −$21,769 | Negativa |
| BB | 648 | −$95,926 | Principal fuente de deterioro |

## Limitaciones y decisión para Polaris

El universo es pequeño, no incluye SPY/QQQ en los caches diarios y el overlay no se probó todavía con un ledger leave-one-symbol-out formal. Las ventanas recientes tienen solo dos trades de baseline. El resultado no es un P&L de opciones y no considera spread específico de cada contrato.

No añadir una capa live. Si se retoma, deberá probarse con un universo más amplio y con un análisis leave-one-symbol-out que confirme que no depende de BB, NOK o cualquier ticker individual. El ranking puede conservarse como herramienta de diagnóstico offline, pero no debe filtrar entradas sin evidencia adicional.

## Artefactos

- `strategies/relative_strength_priority.py`
- `tests/test_relative_strength_priority.py`
- `scripts/run_relative_strength_priority_backtests.py`
- `scripts/analyze_relative_strength_priority_backtests.py`
- `/home/ubuntu/backtests/relative_strength_priority_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_priority_trades_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_priority_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_priority_variant_summary_2026-08-19.csv`
