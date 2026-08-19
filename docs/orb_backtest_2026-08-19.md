# Evaluación Opening Range Breakout — 2026-08-19

## Decisión ejecutiva

**Resultado: `RESEARCH_ONLY`; no integrar ORB en producción, ni siquiera como filtro operativo.** El detector puro y los tests son correctos, pero la evidencia del backtest no supera el criterio de robustez de Polaris. Algunas variantes de 5 minutos, especialmente `orb_5min_r5_short_vol12_none`, tuvieron un periodo reciente favorable, pero la ventana completa disponible de 5 minutos fue negativa y el drawdown fue material. Las variantes de 15 minutos fueron inferiores al baseline DayBreakout en retorno medio y, en general, también en drawdown.

La skill reusable `opening-range-breakout` queda creada y validada para futuras investigaciones. El módulo `strategies/opening_range_breakout.py` y su suite determinista quedan en el repositorio como código de investigación, pero no se conectan a `bot.py`, no se añaden a Firestore y no se despliegan a Cloud Run.

## Datos y metodología

El estudio usa caches reales de Alpaca IEX ya presentes en `/home/ubuntu/backtests/`: 5m de `structure_mtf_history`, 15m de `volume_profile_history` y datos diarios de `setup_history` para el régimen S78. El universo previsto contiene ocho símbolos: SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ. En esta corrida todos los símbolos tuvieron archivos intradía y diario; la cobertura 5m abarcó aproximadamente 38 sesiones comunes desde el 25 de junio hasta el 18 de agosto de 2026, mientras que 15m cubrió aproximadamente un año.

Los timestamps se convierten a `America/New_York`. El rango comienza a las 09:30 ET, excluye premarket y after-hours, y las señales solo pueden producirse después de cerrar el rango. La entrada simulada ocurre en la apertura de la barra siguiente. Se aplican 5 bps de slippage por lado, sin comisiones adicionales, sin overnight y sin inferir P&L de opciones a partir de OHLCV del subyacente. El filtro de volumen usa una media de barras anteriores desplazada; el ATR y el régimen no usan información posterior a la decisión.

Se evaluaron 60 variantes combinando timeframe de 5m/15m, rango de 5/15/30 minutos según disponibilidad, dirección long/short/both, volumen mínimo 1.2x o sin filtro y gate direccional o ninguno. Las ventanas fueron `recent_5d`, `prior_5d`, `prior_10d`, `recent_20d`, `full_available` y, para 15m, `recent_40d`. La comparación contra DayBreakout se hizo por las mismas fechas; la ventana completa de 5m se conserva como evidencia descriptiva, pero no se usa como comparación directa porque el baseline 15m tiene más historia.

## Baseline

| Ventana | Retorno | Max drawdown | Trades |
|---|---:|---:|---:|
| recent_5d | -0.5681% | -0.6573% | 2 |
| prior_5d | 0.0000% | 0.0000% | 0 |
| prior_10d | 0.0000% | 0.0000% | 0 |
| recent_20d | -0.5681% | -0.6573% | 2 |
| full_available 15m | +8.4848% | -3.0969% | 156 |
| recent_40d | -0.8199% | -1.2562% | 6 |

El baseline usado es `DayBreakout` con la configuración vigente y gate de régimen bull S78. El hecho de que algunas ventanas tengan cero operaciones es una característica del sistema actual, no una imputación de retorno.

## Resultados destacados

| Variante | Ventanas comparables | Resultado resumido | Lectura |
|---|---:|---|---|
| `orb_5min_r5_short_vol12_none` | 4/4 positivas frente al baseline en las ventanas recientes | delta medio +2.0117 pp; 150 trades agregados; delta medio de drawdown -1.4593 pp | Interesante, pero la ventana completa 5m fue -1.9764% con -6.5339% de drawdown; no robusta |
| `orb_5min_r5_short_novol_directional` | 3/4 positivas | delta medio +2.2767 pp; 112 trades; delta medio de drawdown -1.5207 pp | Muy dependiente del periodo; ventana completa -2.8209% y -7.2976% de drawdown |
| `orb_5min_r5_long_vol12_directional` | 2/4 positivas | delta medio +0.2240 pp; solo 6 trades; delta medio de drawdown +0.0794 pp | Muestra insuficiente y ventaja pequeña |
| `orb_15min_r30_long_vol12_directional` | 2/6 positivas | delta medio -0.7851 pp; 121 trades; delta medio de drawdown -0.0190 pp | Drawdown parecido, pero retorno inferior al baseline |
| `orb_15min_r15_long_vol12_directional` | 2/6 positivas | delta medio -1.6460 pp; 137 trades; delta medio de drawdown -0.7846 pp | Menor retorno y menor riesgo, no mejora el objetivo |

La variante 5m más atractiva produjo +3.4798% en la ventana reciente de 20 días, pero -1.9764% en toda su cobertura disponible. La variante short con gate direccional produjo +3.9926% en recent_20d y -2.8209% en full_available. Esa inversión de signo es precisamente el patrón que el control anti-sobreajuste debe descartar.

## Limitaciones y controles

La cobertura 5m es más corta que la 15m y no contiene años completos ni suficientes regímenes macroeconómicos. El backtest usa el subyacente y no modela la conversión a opciones, spreads, IV, bid/ask, assignment o liquidez de las patas. El filtro `Stocks in Play` descrito en la literatura no se implementó porque el ranking point-in-time de un universo amplio y el calendario de noticias no están disponibles en los caches actuales. No se usaron resultados de la literatura como parámetros operativos.

La definición de robustez aplicada exige varias ventanas favorables, drawdown no materialmente peor, muestra suficiente y estabilidad fuera de la ventana reciente. Ninguna variante cumple simultáneamente todos esos requisitos. No se ejecutó despliegue ni se modificó el modo PAPER del bot.

## Archivos reproducibles

- `strategies/opening_range_breakout.py`
- `tests/test_opening_range_breakout.py`
- `scripts/run_orb_backtests.py`
- `scripts/analyze_orb_backtests.py`
- `/home/ubuntu/backtests/orb_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/orb_backtest_trades_2026-08-19.csv`
- `/home/ubuntu/backtests/orb_backtests_2026-08-19_manifest.json`
- `/home/ubuntu/backtests/orb_backtest_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/orb_backtest_variant_summary_2026-08-19.csv`
- `docs/orb_research_sources_2026-08-19.md`

La validación local del detector fue de **4 tests pasados** y Ruff F/B limpio. Antes de una futura reconsideración se requiere ampliar la cobertura 5m, incluir folds cronológicos no solapados y reconstruir un filtro de actividad relativa point-in-time.
