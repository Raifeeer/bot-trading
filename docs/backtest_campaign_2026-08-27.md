# Campaña de backtesting de motores y combinaciones — 27 de agosto de 2026

## Alcance y decisión

Se ejecutaron tres bloques de investigación usando datos reales cacheados o descargados mediante los runners existentes. El objetivo fue localizar efectos positivos descriptivos en motores alcistas, bajistas y combinaciones, y comprobar si sobreviven a ventanas temporales separadas. La decisión es **no promover automáticamente ningún motor a producción PAPER** con base solo en esta campaña. El candidato con mejor equilibrio entre retorno y drawdown es `regime_aware`, pero necesita un holdout independiente, datos de opciones con quotes point-in-time y una prueba PAPER separada antes de afectar órdenes.

## Fuentes y reproducibilidad

La primera matriz fue `scripts/run_research_matrix.py`, ejecutada con `DATA_PROVIDER=yfinance`, universo `UNI_RETO` de ocho símbolos y 520 días de historia. Produjo 73 corridas en cuatro ventanas: `lateral_2025` (2025-09-01 a 2025-12-31), `selloff_2026` (2026-01-01 a 2026-04-30), `recent_2026` (2026-04-01 a 2026-08-14) y `latest_30d` (2026-07-01 a 2026-08-14). Las configuraciones usaron slippage explícito de 2–5%, comisión de $0.65 por pata cuando aplicaba, costes de equity de 0.2% y parámetros fijados antes de revisar el resultado de cada ventana. Artefactos: `/home/ubuntu/backtests/campaign_2026-08-27_matrix/`.

La segunda matriz fue `scripts/run_ensemble_research.py`, que combinó `regime_hold_cash` con `breakout20` o `breakout55` con pesos del breakout de 30%, 50%, 70% y 100% en las mismas cuatro ventanas. Artefactos: `/home/ubuntu/backtests/campaign_2026-08-27_ensemble/`.

La tercera prueba fue `scripts/run_relative_strength_walkforward.py`, ejecutada con `PYTHONPATH=/home/ubuntu/bot-trading` para corregir un fallo de importación del runner. Evaluó cuatro variantes en cuatro folds temporales, con costes de 5 y 20 bps en las variantes correspondientes. Artefacto principal: `/home/ubuntu/backtests/relative_strength_walkforward_2026-08-19.csv`; se conserva la fecha histórica del nombre porque el runner existente la fija, aunque la ejecución se realizó el 27 de agosto.

El backtest de opciones EOD del 26 de agosto (`docs/options_eod_preliminary_research_2026-08-26.md`) se conserva como referencia separada: 1.800 combinaciones con OHLC diario de opciones cacheado de Alpaca, no como validación de ejecución MLeg. Sus datos terminan el 7 de agosto de 2026 y deben mantenerse clasificados `EOD_PRELIMINARY` / `REJECTED_FOR_EXECUTION_OOS`.

## Matriz de motores

| Motor | Corridas | Retorno medio | Mediana | Corridas positivas | Drawdown medio | Peor drawdown | Profit factor medio |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hold_weekly` | 4 | 20.2521% | 16.0815% | 75.0000% | -19.0567% | -23.0107% | 1.3169 |
| `regime_aware` | 9 | 15.6975% | 12.2913% | 66.6667% | -4.9085% | -9.6792% | 1.4061 |
| `regime_hold_cash` | 4 | 13.5320% | 16.1918% | 75.0000% | -15.0945% | -25.0933% | 1.2508 |
| `breakout55` | 8 | 9.2867% | 2.7567% | 62.5000% | -14.9706% | -25.5463% | 1.6980 |
| `breakout20` | 8 | 1.8721% | 0.9383% | 50.0000% | -17.9823% | -34.5745% | 1.0198 |
| `put_choch` | 4 | -11.7645% | -11.7645% | 0.0000% | -13.1647% | -26.3295% | 0.1454 |
| `smc_daily` | 36 | -17.3234% | -16.5149% | 13.8889% | -27.8357% | -59.9036% | 0.6710 |

El resultado de `regime_aware` es atractivo descriptivamente porque mantiene retorno positivo en tres de cuatro configuraciones y el drawdown agregado es menor que el de los breakouts. Sin embargo, sus resultados no son uniformes: en `latest_30d` fue -3.4992%, y la ventana reciente positiva concentra gran parte del efecto. `put_choch`, que es la base del motor bajista de Polaris, fue negativo en ambas ventanas donde se probó y no debe considerarse validado por esta matriz.

## Ventanas por motor

| Ventana | `regime_aware` | `breakout55` | `breakout20` | `put_choch` | Observación |
|---|---:|---:|---:|---:|---|
| `lateral_2025` | — | 5.4433% | 7.3926% | — | Breakouts positivos, con drawdowns de hasta -34.5745%. |
| `selloff_2026` | 12.2913% | 2.7567% | -17.7739% | -23.5289% | El régimen superó a los breakouts; CHoCH fue débil. |
| `recent_2026` | 38.3005% | 28.9470% | 21.3222% | — | Ventana muy favorable; no basta para promoción. |
| `latest_30d` | -3.4992% | 0.0000% | -3.4524% | 0.0000% | El efecto positivo no se mantuvo en el tramo más reciente disponible. |

## Combinaciones de motores

La combinación más consistente de la segunda matriz fue `regime_hold_cash` con 30% de `breakout55`: retorno positivo en tres de cuatro ventanas, mediana de retorno de 13.4930% entre ventanas y drawdown mediano de -10.2377%. La versión con 50% de `breakout55` obtuvo mediana de 11.6950% y drawdown mediano de -9.4551%. Con 70% de breakout, la mediana bajó a 9.8970%.

Aunque estas combinaciones producen beneficios descriptivos, el holdout separado matiza el resultado: con datos de entrenamiento de septiembre de 2025 a abril de 2026 y holdout de mayo a agosto de 2026, `ensemble_breakout55_wb0.30` produjo 22.7480% en entrenamiento y 8.2880% en holdout, mientras que `ensemble_breakout55_wb0.50` produjo 15.6400% y 14.1000%. Sus drawdowns en entrenamiento/holdout fueron respectivamente -20.5455%/-17.5179% y -18.9371%/-12.5005%. El efecto sobrevive en signo, pero con drawdown material y sin una valoración de fill realista de opciones.

## Holdout de motores principales

| Variante | Entrenamiento | Holdout | DD entrenamiento | DD holdout | Lectura |
|---|---:|---:|---:|---:|---|
| `regime_aware` | 5.2481% | 20.2038% | -6.8600% | -8.6515% | Mejor equilibrio; candidato de investigación, no promoción. |
| `breakout55` | -2.1290% | 28.6339% | -25.5463% | 0.0000% | Positivo en holdout, pero inconsistente y con DD previo alto. |
| `breakout20` | 2.4402% | 21.7293% | -23.8230% | -7.3239% | Retorno positivo, pero riesgo histórico alto. |
| `regime_hold_cash` | 33.4083% | -0.4321% | -22.7335% | -25.0625% | No generaliza al holdout. |
| `hold_weekly` | 34.6505% | 18.5684% | -24.6570% | -17.4609% | Positivo, pero demasiado expuesto para usarlo como señal de opciones. |

## Relative strength walk-forward

El mejor resultado medio fue `rs_h20_k1_r5_bull_long_only_all_c5`: 23.4549% entre cuatro folds, drawdown medio -6.1130%, pero con retornos de 48.6631%, 45.1563%, 0.0000% y 0.0000%. El resultado depende de dos folds favorables y de periodos sin exposición; no es evidencia suficiente para incorporarlo al motor de opciones. La variante long/short promedió 14.9162% y tuvo drawdown medio -5.6983%, pero quedó por debajo de la variante long-only y del benchmark equal-weight en varios folds. El resultado positivo no debe confundirse con una validación de spreads de opciones.

## Conclusiones y decisión

La campaña sí encontró efectos positivos descriptivos: `regime_aware`, `breakout55` y algunas combinaciones régimen-plus-breakout fueron positivas en ventanas recientes o en el holdout. También encontró fallos claros: `put_choch` y `smc_daily` fueron débiles en esta matriz, y varios resultados positivos se concentran en una sola fase de mercado o conviven con drawdowns altos.

No se promueve ningún motor automáticamente. La siguiente prueba útil sería un A/B PAPER sin autoridad de órdenes de `regime_aware` frente al baseline, con el mismo universo, barras y timestamps, y luego una canary separada solo si supera un holdout verdaderamente independiente. El motor bajista actual tampoco debe declararse rentable porque el override de prima mínima no está representado en un OOS con NBBO.

El tope PAPER de `$50` no se incorpora retrospectivamente al P&L de estos backtests. Cualquier operación real dentro de PAPER puede perder hasta `$50` de prima más comisiones en una sola posición, mientras el breaker diario permanece en `$20`; la discrepancia debe mantenerse visible y no interpretarse como una garantía de pérdida máxima diaria de `$20`.

> **Estado final:** `RESEARCH_ONLY`. No hay evidencia execution-realistic OOS suficiente para prometer rentabilidad, recuperar el equity o eliminar la supervisión operativa.
