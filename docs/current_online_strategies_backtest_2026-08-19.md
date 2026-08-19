# Estrategias online actuales — investigación y backtest

**Fecha de la ronda:** 19 de agosto de 2026
**Estado:** investigación experimental; ninguna nueva estrategia fue activada en producción.

## Resumen

Se seleccionaron tres familias que tenían atención reciente y podían formalizarse con reglas objetivas: Broken-Wing Butterfly, spreads de crédito 0DTE/1DTE y spreads de eventos de earnings. Cada una recibió una skill específica con referencias profundas y guardarraíles.

La BWB pudo evaluarse con barras diarias reales de opciones de Alpaca, pero no con bid/ask point-in-time ni assignment temprano. El resultado fue negativo y se clasificó `RESEARCH_ONLY`. Los spreads 0DTE/1DTE y la estrategia de earnings no pudieron someterse a un backtest de rendimiento válido porque faltan quotes intradía, cutoff, IV histórica y calendarios as-of. Ambos gates quedaron `REJECT_DATA`.

## Cobertura de datos

El cache de Alpaca incluyó siete símbolos —AMD, BB, F, NOK, PLTR, TQQQ y TSLA— desde 2026-04-01 hasta 2026-08-07. Se seleccionaron 3,163 contratos; 3,047 tuvieron barras históricas y se obtuvieron 61,834 barras diarias.

| Familia | Datos disponibles | Decisión de datos |
|---|---|---|
| BWB | Barras OHLC diarias de opciones; sin bid/ask histórico, delta o IV point-in-time | Proxy diaria; `RESEARCH_ONLY` |
| 0DTE/1DTE | Candidatos de contratos, pero sin quotes intradía, tamaño, cutoff ni ticks | `REJECT_DATA` |
| Earnings | Calendario actual de yfinance, sin histórico as-of; sin IV/bid-ask antes/después | `REJECT_DATA` |

El propio ejemplo público de Alpaca para 0DTE utiliza ticks bid/ask de opciones de Databento, precios ask para largos y bid para cortos, reglas explícitas de assignment, selección cronológica y cierre antes de expiración. Por tanto, no sería metodológicamente correcto presentar las barras diarias actuales como un backtest 0DTE válido.[1]

## Broken-Wing Butterfly

Se probaron BWB de calls y puts por crédito, con DTE de 14, 30 y 45 días, distancias de 5% y 10%, tres perfiles de gestión y dos modos de régimen. El total fue de 360 combinaciones.

| Estructura | Retorno medio | Retorno mediano | Peor retorno | Drawdown medio | Ventanas positivas entre 180 filas |
|---|---:|---:|---:|---:|---:|
| BWB call por crédito | −8.85% | −3.81% | −77.75% | −9.33% | 5 |
| BWB put por crédito | −8.02% | −5.11% | −42.50% | −8.32% | 6 |

Por ventana, ambas variantes fueron negativas en promedio en las cinco temporadas. La BWB call obtuvo −18.42% en el periodo completo y la BWB put −17.22%. La comparación frente a buy-and-hold fue desfavorable: el delta medio fue aproximadamente −28.86 puntos porcentuales para BWB call y −28.03 para BWB put.

Estos resultados no deben interpretarse como una cotización exacta de una BWB live, porque la fuente no tiene bid/ask histórico ni assignment. Aun con esa limitación, el resultado no mostró una señal suficientemente prometedora para justificar una integración. La decisión es `RESEARCH_ONLY`, no `PROMOTE_SHADOW`.

## Spreads 0DTE/1DTE

El cache encontró 630 patas candidatas 0DTE y 528 patas candidatas 1DTE, pero son solo comprobaciones de existencia de contratos. No se ejecutó un P&L de rendimiento porque faltan los datos necesarios para modelar el riesgo real: quotes intradía, timestamps de entrada y salida, bid/ask, tamaño, expiración exacta, cutoff, assignment y liquidación forzosa.

La decisión es `REJECT_DATA`. No se debe activar un spread diario usando resultados diarios o precios midpoint; el error de ejecución puede ser comparable o superior al crédito esperado.

## Earnings-event spreads

La estrategia investigada fue un bull call o bear put debit spread alrededor de earnings, con riesgo máximo igual al débito. La investigación de OIC explica que la IV suele aumentar antes del anuncio y caer cuando se resuelve la incertidumbre; acertar la dirección no garantiza que el spread gane después del IV crush.[2]

El módulo actual `data/earnings.py` usa `yfinance.Ticker(symbol).calendar` y cachea durante 24 horas la fecha actualmente conocida. Eso no permite reconstruir qué fecha de earnings se conocía en cada decisión histórica. Además, el cache de opciones no contiene IV ni bid/ask históricos ni quotes posteriores al anuncio. El gate produjo `REJECT_DATA` para los ocho símbolos del universo.

La literatura de Review of Finance encuentra que curvas IV cóncavas antes de earnings se asocian con saltos y volatilidad posterior, pero también que los participantes pagan una prima por cubrir gamma de evento. Esa evidencia respalda investigar la señal, no asumir que comprar straddles o spreads sea rentable.[3]

## Skills creadas

| Skill | Ubicación | Estado |
|---|---|---|
| Broken-Wing Butterfly | `/home/ubuntu/skills/broken-wing-butterfly/SKILL.md` | Validada |
| Spreads de crédito 0DTE/1DTE | `/home/ubuntu/skills/0dte-credit-spreads/SKILL.md` | Validada |
| Earnings-event spreads | `/home/ubuntu/skills/earnings-event-spreads/SKILL.md` | Validada |

## Decisión de implementación

No se implementó ninguna de las tres estrategias en el flujo de órdenes. La BWB no demostró rendimiento suficiente incluso como proxy diaria; 0DTE/1DTE y earnings no tienen datos suficientes para una conclusión de rendimiento.

La próxima implementación solo tendría sentido si se obtiene una fuente histórica OPRA con bid/ask/ticks, IV y calendario de earnings point-in-time. Hasta entonces, Polaris permanece con sus estrategias live actuales, VIX y estructura MTF en shadow, PAPER, RiskManager como autoridad final y sin nuevas rutas hacia el executor.

## Referencias

[1] [Alpaca-py — Backtesting a 0DTE Bull Put Spread Strategy](https://github.com/alpacahq/alpaca-py/blob/master/examples/options/options-zero-dte-backtesting/options-zero-dte-backtesting.ipynb).
[2] [OIC — The Crush Is Real](https://www.optionseducation.org/news/the-crush-is-real).
[3] [Alexiou, Goyal, Kostakis y Rompolis — Pricing event risk: evidence from concave implied volatility curves](https://academic.oup.com/rof/article/29/4/963/8079062).
[4] [Alpaca — Credit Spreads](https://alpaca.markets/learn/credit-spreads).
[5] [OIC — Bull Put Spread](https://www.optionseducation.org/strategies/all-strategies/bull-put-spread-credit-put-spread).
[6] [IBKR — Broken-Wing Butterfly](https://www.interactivebrokers.com/campus/traders-insight/securities/options/the-broken-wing-butterfly-a-hidden-gem-in-options-trading/).
[7] [OIC — Short Call Calendar Spread](https://www.optionseducation.org/strategies/all-strategies/short-call-calendar-spread-short-call-time-spread).

**Advertencia:** este informe es investigación experimental. No soy asesor financiero y ningún resultado histórico garantiza rendimiento futuro.
