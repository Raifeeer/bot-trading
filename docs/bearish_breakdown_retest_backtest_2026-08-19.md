# Motor bearish de breakdown/retest — backtest e integración shadow

**Fecha de corte:** 19 de agosto de 2026. **Clasificación:** `RESEARCH_ONLY` para decisiones operativas; `SHADOW_CANDIDATE` para observabilidad en PAPER.

## Pregunta

Determinar si un motor intradía de ruptura bajista de soporte seguida de retest fallido aporta información complementaria al `DayBreakout` vigente y, si la evidencia no es suficiente para modificar entradas, conectarlo en modo exclusivamente shadow.

## Método

La corrida usa caches de barras reales de Alpaca IEX disponibles localmente: 15 minutos y 5 minutos para siete símbolos del universo (`PLTR`, `F`, `TSLA`, `AMD`, `NOK`, `BB`, `TQQQ`). `SOFI` queda fuera por falta de histórico intradía disponible y no se imputa. Las cinco ventanas son `recent_5d`, `prior_5d`, `recent_20d`, `prior_20d` y `recent_60d`, con ventanas cronológicas explícitas.

El detector calcula el soporte únicamente con barras previas, exige ruptura bajo el soporte con buffer ATR y volumen relativo, espera un retest dentro del límite configurado y confirma el rechazo con una vela bearish. La entrada simulada se realiza en la apertura de la barra siguiente; no se mantienen posiciones overnight. Se usa riesgo por operación de 0.5%, slippage de 5 bps y comparación contra el `DayBreakout` configurado actualmente con la puerta S78. No se presenta como P&L real de opciones: es una evaluación del motor subyacente con una simulación de riesgo definida.

> El resumen de retorno se calcula como media ponderada igualmente por símbolo. No se suman porcentajes de cuentas independientes como si fueran el retorno de un único portafolio.

## Resultado agregado

La variante seleccionada para la observación shadow es `br15_lb20_v12_rt3`: 15 minutos, soporte rolling de 20 barras, volumen mínimo 1.2 veces la referencia y retest máximo de 3 barras.

| Variante | Gate bear/crash | Ventanas con delta positivo | Delta medio de retorno vs baseline | Delta medio de drawdown | Trades totales |
|---|---:|---:|---:|---:|---:|
| `br15_lb20_v12_rt3` | No | 2/5 | +0.523 pp | +0.262 pp | 135 |
| `br15_lb20_v12_rt3` | Sí | 3/5 | +0.464 pp | +0.541 pp | 83 |
| `br15_lb20_v10_rt3` | No | 2/5 | +0.360 pp | +0.106 pp | 157 |
| `br15_lb10_v12_rt3` | No | 2/5 | +0.227 pp | −0.107 pp | 162 |
| Variantes 5m | Mixto | 0–2/5 | Negativo en conjunto | Generalmente peor | 187–328 |

La variante elegida no supera el criterio de promoción: sin gate solo gana en 2 de 5 ventanas; con gate gana en 3 de 5, pero el drawdown medio comparativo empeora. Además, el rendimiento reciente de 20 días es negativo para todas las variantes 15m, y las variantes 5m son consistentemente inferiores. El resultado, por tanto, no justifica activar el motor como filtro de entradas ni como estrategia que envíe órdenes.

## Integración realizada

Se añadió `strategies/bearish_breakdown_retest.py` y el wrapper `_bearish_breakdown_shadow_snapshot()` en `bot.py`. La integración:

1. Usa el cache de barras cerradas de `15min` por símbolo.
2. Fuerza por código `mode=shadow`, `influence_entries=false` y `orders_allowed=false`, aunque YAML contenga valores peligrosos.
3. Registra por símbolo `confirmed`, `no_setup`, `insufficient_data`, `missing_data` o `error`.
4. Publica el snapshot en Firestore como `bearish_breakdown_shadow_observations`.
5. Resume conteos en `tick_diagnostics.bearish_breakdown_shadow`.
6. Mide la latencia en `CYCLE TIMING` mediante `breakdown_shadow`.
7. No accede al executor, sizing, strikes, RiskManager ni piso de equity para alterar decisiones.

La configuración congelada de observación es la variante 15m `lookback=20`, `volume_min=1.2` y `retest_max_bars=3`, con `support_mode=rolling_support`.

## Validación

La suite completa quedó en **132 tests pasados, 1 omitido y 2 expected failures heredados**. La compilación de módulos y Ruff F/B pasaron. Los avisos no bloqueantes de Ruff en `bot.py` son preexistentes de estilo y zona horaria; el conjunto nuevo de archivos no añade errores F/B y pasa la validación focalizada. La skill `/home/ubuntu/skills/bearish-breakdown-retest/SKILL.md` pasó `quick_validate.py`.

## Decisión

Mantener el motor como **shadow activo en PAPER**, sin influencia sobre entradas y sin órdenes. Antes de considerar una promoción se requiere acumular observaciones en producción, completar walk-forward no solapado con más historia y símbolos, repetir sensibilidad a slippage y evaluar falsos breakouts. Cualquier posible promoción debe conservar al RiskManager, el piso, los circuit breakers, la validación de cotizaciones y el modo PAPER como autoridades finales.

## Artefactos reproducibles

- `scripts/run_bearish_breakdown_retest_backtests.py`
- `scripts/analyze_bearish_breakdown_retest.py`
- `/home/ubuntu/backtests/bearish_breakdown_retest_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/bearish_breakdown_retest_variant_summary_2026-08-19.csv`
- `/home/ubuntu/backtests/bearish_breakdown_retest_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/bearish_breakdown_retest_baseline_2026-08-19.csv`
- `/home/ubuntu/backtests/bearish_breakdown_retest_analysis_2026-08-19_manifest.json`

## Nota financiera

Este documento es investigación experimental sobre una cuenta PAPER y no demuestra rentabilidad futura. No es asesoramiento financiero personalizado.
