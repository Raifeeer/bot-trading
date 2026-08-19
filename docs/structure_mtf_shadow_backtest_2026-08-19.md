# Estructura MTF shadow — implementación y backtest

## Objetivo

Se añadió una capa de observabilidad que compara swings fractales confirmados en `1d`, `15min` y `5min`. La puntuación usa pesos `1d=0.50`, `15min=0.30` y `5min=0.20`. Una señal bull o bear solo se considera fuerte si la estructura muestra simultáneamente máximos y mínimos crecientes o decrecientes en el marco evaluado.

La capa no tiene acceso al executor. El wrapper de `bot.py` fuerza `mode=shadow`, `influence_entries=false` y `orders_allowed=false`, incluso si una configuración antigua intenta solicitar autoridad operativa.

## Reglas anti-look-ahead

El detector solo recibe barras cerradas. Un swing fractal de orden 3 necesita las barras posteriores de confirmación dentro del DataFrame entregado. En el backtest, los datos diarios usados para el régimen son estrictamente anteriores al día evaluado; para cada barra de 15 minutos solo se usan datos de 5 minutos hasta el cierre de esa barra; ningún futuro se pasa al detector.

## Cobertura de datos

El backtest utiliza datos reales cacheados: histórico diario, 15 minutos de Alpaca IEX y 5 minutos de Alpaca IEX para los últimos 55 días. Siete de los ocho símbolos tuvieron cobertura completa: `PLTR`, `F`, `TSLA`, `AMD`, `NOK`, `BB` y `TQQQ`. `SOFI` no tuvo histórico diario disponible en el cache y se excluyó explícitamente; no se imputaron barras.

La ventana disponible para la evaluación MTF va del 25 de junio al 18 de agosto de 2026, con subventanas consecutivas de 5, 10 y 20 días. La contabilidad es una proxy del subyacente basada en `DayBreakout` y el régimen S78; no es P&L exacto de opciones.

## Variantes comparadas

| Variante | Regla |
|---|---|
| `baseline` | DayBreakout actual con puerta S78 bull |
| `mtf_strict` | Entrada solo con dirección MTF bull |
| `daily_bull` | Entrada solo con estructura diaria bull |
| `intraday_bull` | Entrada solo con 15min y 5min bull |
| `score_positive` | Entrada con score MTF positivo |

## Resultados

| Variante | Delta medio de retorno frente al baseline | Ventanas con retorno superior | Delta medio de drawdown | Trades totales |
|---|---:|---:|---:|---:|
| `daily_bull` | +0.026 pp | 3/5 | +0.392 pp | 0 |
| `intraday_bull` | −0.128 pp | 0/5 | +0.146 pp | 5 |
| `mtf_strict` | −0.095 pp | 0/5 | +0.217 pp | 3 |
| `score_positive` | −0.095 pp | 0/5 | +0.217 pp | 3 |

El `daily_bull` no es un ganador real: tuvo cero operaciones y solo parece superar al baseline porque el baseline perdió ligeramente en algunas ventanas. El filtro MTF estricto y el filtro intradía bloquearon operaciones que el baseline habría tomado y terminaron con menor retorno acumulado. El drawdown absoluto fue pequeño en esta muestra, pero la cobertura temporal es demasiado corta para afirmar una ventaja.

## Decisión

La estructura MTF queda implementada **solo como shadow**. No se habilita como filtro de entradas. El backtest preliminar no demuestra una mejora de profit; la variante diaria necesita más muestras y no puede considerarse válida con cero trades. Antes de una posible promoción se requieren varias semanas adicionales de observación, ventanas históricas más largas con 5m real, walk-forward no solapado y una comparación directa contra las señales actuales de las tres estrategias live.

## Validación

La suite del repositorio terminó con `129 tests OK`, `1 skipped` y `2 expected failures` heredados. Los archivos nuevos de la capa pasan compilación y Ruff en las reglas funcionales `E9/F/B`. Quedan advertencias estilísticas preexistentes en `bot.py` fuera de esta integración.

**Conclusión:** la capa mejora la información disponible para el agente y el dashboard, pero no tiene permiso para cambiar operaciones. Este documento es investigación experimental en PAPER y no constituye asesoría financiera ni garantía de rentabilidad.
