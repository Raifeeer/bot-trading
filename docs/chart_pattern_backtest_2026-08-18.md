# Patrones chartistas objetivos — resultado de investigación y backtest

**Fecha de corte:** 2026-08-18. **Estado:** `RESEARCH_ONLY`; no se conectó a `bot.py`.

## Pregunta

¿Dobles techos/suelos, triángulos, flags y cabeza-hombros, formalizados con pivots y rupturas confirmadas, mejoran `DayBreakout` o constituyen una estrategia independiente útil para Polaris?

## Investigación

Se creó y validó `/home/ubuntu/skills/chart-patterns/SKILL.md`, con referencia en `/home/ubuntu/skills/chart-patterns/references/research.md`. Fidelity define los patrones como formaciones delimitadas por líneas de tendencia que no se activan hasta un breakout, y recomienda filtros de confirmación y stops protectores.[1] StockCharts clasifica patrones de reversión y continuación, pero advierte que son subjetivos, pueden fallar y deben evaluarse con frecuencia histórica.[2] Investopedia destaca que en doble techo/suelo la ruptura del valle o pico intermedio es crítica; actuar solo con dos picos/valles produce falsas lecturas.[3]

La literatura de Friesen, Weller y Dunham presenta una explicación conductual de por qué algunas formas pueden coincidir con autocorrelaciones, pero no demuestra que un detector simple sea rentable después de costes.[4] Lo, Mamaysky y Wang muestran que la formalización matemática cambia la detección respecto a la inspección visual.[5]

## Formalización

Se implementó `strategies/chart_patterns.py` con pivots únicos confirmados después de dos barras a la derecha; la señal solo se activa en una barra posterior al breakout con buffer 0.1 ATR. Se probaron:

| Variante | Regla |
|---|---|
| Double bottom filter | Solo permite un breakout largo de DayBreakout después de doble suelo confirmado |
| Triangle filter | Solo permite breakout largo después de triángulo confirmado |
| Flag filter | Solo permite breakout largo después de flag alcista confirmado |
| Inverse H&S filter | Solo permite breakout largo después de cabeza-hombros invertido |
| Pattern confluence | Permite si uno de los patrones alcistas está confirmado |
| Bear pattern block | Bloquea si hay patrón bajista confirmado |
| Standalone | Opera únicamente con la señal positiva del patrón correspondiente |

El detector de double top y cabeza-hombros superior se registra como señal bajista, pero el motor analizado no abrió shorts porque el baseline live evaluado es long-only. Esto evita fingir que una prueba long demuestra una estrategia bajista.

## Metodología

Se utilizaron barras 15m reales de Alpaca IEX para SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ. Cada variante se comparó con el mismo `DayBreakout`: Donchian 10, entrada 10:00–15:30 ET, stop 2.5 ATR, salida por canal o máximo 20 barras, asignación igual por símbolo, slippage 5 bps y comisión $0.

Se probaron cinco ventanas: selloff de primavera, recuperación de mayo, verano, últimos 30 días y año reciente. La matriz contiene 55 celdas. Las cinco ventanas se solapan en `full_recent`, por lo que no son cinco muestras independientes.

## Resultados medios frente al baseline

| Variante | Delta medio de retorno | Delta medio de drawdown | Ventanas con mayor retorno | Trades medios |
|---|---:|---:|---:|---:|
| Flag standalone | **+4.32 pp** | +4.81 pp | 5/5 | 250.2 |
| Flag filter | **+2.26 pp** | +4.59 pp | 4/5 | 209.0 |
| Bear pattern block | −0.01 pp | −0.01 pp | 0/5 | 399.0 |
| Triangle standalone | −0.94 pp | +4.55 pp | 2/5 | 150.6 |
| Inverse H&S standalone | −2.26 pp | +6.37 pp | 1/5 | 37.8 |
| Double bottom standalone | −4.42 pp | +2.93 pp | 2/5 | 156.8 |
| Pattern confluence filter | −2.54 pp | +2.32 pp | 1/5 | 287.6 |
| Triangle filter | −3.33 pp | +5.29 pp | 2/5 | 93.4 |
| Inverse H&S filter | −2.43 pp | +7.22 pp | 2/5 | 19.8 |
| Double bottom filter | −5.19 pp | +4.32 pp | 1/5 | 111.4 |

Los flags fueron el único grupo que aumentó retorno de forma consistente: el standalone fue mejor en las cinco ventanas. Sin embargo, el drawdown medio empeoró aproximadamente **4.81 puntos porcentuales**; el filtro de flag tuvo el mismo problema. El incremento de retorno vino acompañado de mayor exposición y riesgo, no de una mejora gratuita.

Los dobles suelos, triángulos y cabeza-hombros invertidos no añadieron valor consistente. Bloquear patrones bajistas casi no cambió el resultado porque el baseline long-only ya estaba protegido por otras salidas y filtros.

## Decisión

**No promover patrones chartistas a filtro operativo.** El flag queda como `SHADOW_CANDIDATE` para una posible segunda ronda porque aumentó retorno en la muestra, pero no como integración live: el coste en drawdown y la sensibilidad a la definición del impulso/consolidación son demasiado altos. Ningún patrón cumple simultáneamente mejora robusta de retorno y drawdown no peor.

La segunda ronda, si se hace, debe separar flags de continuación alcista y bajista, probar un stop basado en el extremo de la bandera, medir MAE/MFE y usar walk-forward con ventanas no solapadas. No debe elegirse el flag solo por el retorno favorable de esta muestra.

## Limitaciones

Los patrones son formalizaciones de OHLCV, no etiquetas visuales humanas ni order flow. Hay posible redundancia con Donchian, ATR y setups existentes. La detección de pivots introduce retraso; las variantes standalone no representan todavía la estrategia completa del bot de opciones. El resultado es proxy del subyacente long-only, no P&L de opciones.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/chart-patterns/SKILL.md`
- Investigación: `/home/ubuntu/skills/chart-patterns/references/research.md`
- Módulo: `strategies/chart_patterns.py`
- Tests: `tests/test_chart_patterns.py`
- Motor: `scripts/run_chart_pattern_backtests.py`
- Resultados: `/home/ubuntu/backtests/chart_pattern_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/chart_pattern_backtests_2026-08-18_deltas.csv`

**Basis:** proxy de subyacente con DayBreakout long-only, no P&L exacto de opciones. **Time:** datos hasta 2026-08-18. **Assumptions:** 15m Alpaca IEX, entrada tras cierre confirmado, Donchian 10, stop 2.5 ATR, máximo 20 barras, slippage 5 bps y comisión $0. **Sources & confidence:** Fidelity, StockCharts, Investopedia, literatura académica y Alpaca; confianza media-baja por muestra parcial y sensibilidad de detección. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [Fidelity — Identifying Chart Patterns with Technical Analysis](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Idenitfying-Chart-Patterns.pdf)
[2] [StockCharts ChartSchool — Chart Patterns](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns)
[3] [Investopedia — Double Top and Bottom](https://www.investopedia.com/terms/d/double-top-and-bottom.asp)
[4] [Friesen, Weller & Dunham — Price trends and patterns in technical analysis](https://www.sciencedirect.com/science/article/pii/S0378426608002951)
[5] [Lo, Mamaysky & Wang — Foundations of technical analysis](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=296314)
