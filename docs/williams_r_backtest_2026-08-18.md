# Williams %R — resultado de investigación y backtest

**Fecha de corte:** 2026-08-18. **Estado:** `RESEARCH_ONLY`; no se conectó al executor.

## Pregunta

¿Williams %R aporta información incremental frente al baseline de `DayBreakout` y frente a RSI cuando se usa como filtro o confirmación de entradas?

## Investigación

Se creó y validó la skill `/home/ubuntu/skills/williams-r/SKILL.md`, con referencia en `/home/ubuntu/skills/williams-r/references/research.md`. Fidelity y StockCharts definen %R como el inverso escalado del Fast Stochastic: `%R = -100 * (Highest High - Close) / (Highest High - Lowest Low)`, con rango 0 a −100 y periodo base 14.[1] [2]

Las lecturas 0 a −20 indican que el cierre está cerca de la parte alta del rango y −80 a −100 que está cerca de la parte baja; no son por sí solas señales de venta o compra porque pueden persistir en tendencias fuertes. StockCharts recomienda confirmar con el cruce de −50. Investopedia distingue %R de RSI: %R compara la posición del cierre dentro del rango high-low, mientras RSI mide la consistencia de subidas y bajadas.[2] [3] TrendSpider describe %R como más sensible que RSI cuando ambos usan el mismo periodo.[4]

## Metodología

Se utilizaron barras históricas reales de 15 minutos de Alpaca IEX para SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ, desde 2025-08-18 hasta 2026-08-18. El backtest es parcial 15m y no valida la cascada MTF completa ni el P&L de opciones.

El baseline replica `DayBreakout`: Donchian 10, entrada larga entre 10:00 y 15:30 ET, stop 2.5 ATR, salida por canal o máximo 20 barras, asignación igual por símbolo, slippage 5 bps y comisión $0. Se probaron periodos %R/RSI 8, 14 y 28, cinco ventanas de mercado y estas variantes:

| Variante | Regla |
|---|---|
| WR pullback | %R estuvo <= −80 en las últimas 10 barras y cruza sobre −50 |
| WR overbought filter | Bloquea el breakout si %R >= −20 |
| WR midline confirm | Permite el breakout si %R > −50 |
| RSI pullback | RSI estuvo <= 30 y cruza sobre 50 |
| RSI midline confirm | Permite el breakout si RSI > 50 |

La matriz final contiene 90 combinaciones. Cada señal usa solo barras cerradas y mantiene igual el baseline, costes y salidas.

## Resultados medios frente al baseline

| Variante | Delta medio de retorno | Delta medio de drawdown | Ventanas con mayor retorno | Trades medios |
|---|---:|---:|---:|---:|
| WR midline confirm | −0.02 pp | +0.38 pp | 4/15 | 382.7 |
| RSI midline confirm | −0.13 pp | +0.74 pp | 4/15 | 369.6 |
| WR pullback | −4.57 pp | +2.74 pp | 1/15 | 209.6 |
| WR overbought filter | −4.36 pp | +4.40 pp | 3/15 | 90.7 |
| RSI pullback | −2.64 pp | +6.02 pp | 4/15 | 58.3 |

El baseline tuvo un retorno medio de 36.88% en el conjunto de resultados agregados y aproximadamente 399 operaciones medias por combinación. Los filtros de mitad de rango quedaron cerca del baseline, pero no lo superaron de manera consistente. Las variantes pullback y overbought redujeron mucho la actividad y sacrificaron retorno medio.

El criterio de robustez exigía superar al baseline en al menos 8 de 15 celdas ventana-periodo y no empeorar el drawdown más de 0.25 puntos porcentuales. Ninguna variante cumplió ese criterio.

## Decisión

**No promover Williams %R a filtro de entradas.** El cruce de −50 puede servir como feature de observación, pero no mostró una ventaja incremental robusta sobre `DayBreakout`. Tampoco justificó sustituir RSI: la variante RSI de confirmación tuvo un delta medio negativo y la variante RSI pullback sacrificó aún más retorno.

Williams %R queda como `RESEARCH_ONLY`, sin módulo live, sin cambios a `bot.py` y sin `influence_entries`. La skill queda disponible para futuras pruebas de sensibilidad, pero la evidencia actual no justifica incorporación.

## Limitaciones

%R es un indicador OHLC muy cercano al estocástico y puede ser redundante con RSI, EMA y Donchian. El histórico es 15m de Alpaca IEX, no datos de opciones. No se probaron sesiones separadas, divergencias avanzadas ni una cascada MTF. El resultado no permite afirmar que %R no tenga utilidad en otros activos o marcos, solo que no mejoró este baseline bajo estas reglas y ventanas.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/williams-r/SKILL.md`
- Investigación: `/home/ubuntu/skills/williams-r/references/research.md`
- Módulo: `strategies/williams_r.py`
- Tests: `tests/test_williams_r.py`
- Motor: `scripts/run_williams_r_backtests.py`
- Resultados: `/home/ubuntu/backtests/williams_r_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/williams_r_backtests_2026-08-18_deltas.csv`

**Basis:** proxy de subyacente con asignación igual por símbolo, no P&L exacto de opciones. **Time:** datos hasta 2026-08-18. **Assumptions:** 15m, entrada tras cierre confirmado, Donchian 10, stop 2.5 ATR, máximo 20 barras, slippage 5 bps y comisión $0. **Sources & confidence:** Alpaca IEX OHLCV y fuentes educativas; confianza media para la comparación 15m y baja para generalizar a opciones/MTF. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [Fidelity — Williams %R](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/williams-r)
[2] [StockCharts ChartSchool — Williams %R](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/williams-r)
[3] [Investopedia — Comparing Williams %R and RSI](https://www.investopedia.com/ask/answers/031115/what-are-main-differences-between-williams-r-oscillator-relative-strength-index-rsi.asp)
[4] [TrendSpider — RSI and Williams %R](https://trendspider.com/blog/trendspider-strategy-guide-video-analysis-of-the-rsi-and-williams-r/)
