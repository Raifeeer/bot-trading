# Breakout20/55 — fuentes y formalización

**Fecha:** 19 de agosto de 2026.

## Qué cubre ya Polaris

`opt_day_breakout` usa una ruptura Donchian de 10 barras en 15m, empieza a evaluar desde las 10:00 ET y no modela explícitamente la diferencia entre una ruptura de 20/55 barras, confirmación de volumen, fallo o retest. Breakout20/55 no debe tratarse como una señal completamente nueva: es una sensibilidad de lookback y confirmación sobre la misma familia de tendencia.

## Fuentes

[Testing a Price Breakout Strategy Using Donchian Channels](https://open.uct.ac.za/handle/11427/21754) estudia estrategias de seguimiento de tendencia con canales Donchian de 20 y 55 días en futuros sudafricanos. La fuente es un trabajo académico aplicado, no evidencia de que los mismos parámetros funcionen en acciones intradía de Polaris.

[Moskowitz, Ooi and Pedersen — Time Series Momentum](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) documenta momentum de series temporales en 58 instrumentos líquidos de futuros usando retornos pasados y horizontes largos. La evidencia apoya estudiar persistencia de tendencia, pero no fija 20/55 como óptimos intradía ni elimina costes, slippage o cambios de régimen.

[Technical Trading Rule Profitability in Currencies: It's All About Momentum](https://www.sciencedirect.com/science/article/pii/S0275531922001659) analiza reglas técnicas y canales con distintos lookbacks, incluyendo 5, 10, 15, 20, 25 y 50 días, y enfatiza evaluar supervivencia a costes y fuera de muestra. La transferencia a acciones intradía es limitada.

## Especificación de investigación

| Dimensión | Variantes |
|---|---|
| Timeframe | 5m y 15m |
| Canal | Donchian 20 y 55, excluyendo la barra actual |
| Confirmación | cierre fuera del canal; volumen relativo 1.0x/1.2x |
| Dirección | long-only; bear solo observacional |
| Gate | none, bull/S78 |
| Entrada | siguiente apertura tras cierre confirmado |
| Salida | stop ATR, target R, máximo de barras, sin overnight |
| Coste | slippage explícito por lado y sensibilidad |

La comparación principal debe ser temporalmente alineada contra DayBreakout S78. Si el 5m carece de baseline equivalente, no se debe seleccionar una variante por su promedio aislado. La decisión debe incluir folds no solapados, concentración por símbolo y sensibilidad a volumen/costes.

## Riesgos

Un lookback mayor reduce ruido pero puede retrasar entradas y disminuir operaciones; un lookback menor se solapa con el DayBreakout existente y puede duplicar señales. El filtro de volumen puede mejorar selección o simplemente reducir exposición. No se debe confundir menor drawdown con mayor alpha si el motor está fuera del mercado durante las mismas ventanas.
