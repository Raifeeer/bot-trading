# Trend pullback / continuación — fuentes y hallazgos

**Fecha:** 19 de agosto de 2026.

## Fuente 1 — Time Series Momentum

**URL:** https://www.semanticscholar.org/paper/Time-Series-Momentum-Moskowitz-Ooi/797398408f967a6e6bc4570db7df7daeccd6fa61

Moskowitz, Ooi y Pedersen documentan time-series momentum en 58 instrumentos líquidos de futuros de índices, divisas, commodities y bonos. El resumen indica persistencia de retornos de uno a doce meses y reversión parcial en horizontes más largos, consistente con sub-reacción inicial y sobre-reacción posterior.

**Aplicación:** la evidencia apoya estudiar continuidad de tendencia, pero el horizonte es mensual y el universo es de futuros; no valida un pullback intradía de EMA/VWAP sobre acciones u opciones de Polaris.

## Fuente 2 — costes y lookback de trend following

**URL:** https://returnstacked.investresolve.com/academic-review/optimal-trend-following-with-transaction-costs/

La revisión practitioner del trabajo de Zakamulin y Giner explica que los costes de transacción deben formar parte del diseño y que, bajo su modelo, costes más altos favorecen lookbacks más largos para reducir frecuencia de trading. También describe el cruce de medias como una aproximación práctica a reglas de seguimiento de tendencia bajo costes.

**Aplicación:** el backtest debe reportar turnover/slippage y probar una variante con confirmación más lenta. No seleccionar EMA rápida por el mejor resultado histórico reciente.

## Fuente 3 — riesgos de whipsaw y reversión

La literatura anterior y la evidencia de momentum crash indican que la continuidad puede fallar cuando el mercado cambia de régimen o rebota violentamente. Un pullback debe exigir tendencia previa, retroceso controlado, defensa de EMA/VWAP y reanudación posterior; un simple toque de media se clasifica como no_setup.

**Aplicación:** incluir gates bull, bear/crash, slope de media, ATR y máximo de duración. El stop estructural/ATR es teórico en el estudio y el RiskManager live conserva autoridad.

## Especificación inicial para Polaris

| Dimensión | Regla de investigación |
|---|---|
| Tendencia | EMA rápida sobre EMA lenta y pendiente positiva/negativa; opcional SMA200 diario |
| Retroceso | Precio toca zona EMA/VWAP dentro de tolerancia ATR sin romper invalidación |
| Reanudación | Cierre posterior en dirección de tendencia con ruptura del micro máximo/mínimo y volumen opcional |
| Entrada | Próxima apertura tras barra confirmada |
| Salida | Stop detrás de zona/ATR, target R múltiplo, máximo de barras, sin overnight |
| Gates | `none`, `bull`, `directional`, `crash_block` |
| Costes | Slippage por lado y sensibilidad de turnover |
| Seguridad | detector puro, `mode=shadow`, `orders_allowed=false` |

No se infieren parámetros operativos desde las fuentes. El objetivo es comparar la hipótesis contra DayMomentum/DayBreakout y no sustituir la estrategia live.
