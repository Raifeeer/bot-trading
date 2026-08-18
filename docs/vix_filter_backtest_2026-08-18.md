# VIX como filtro de régimen — resultado de investigación y backtest

**Fecha de corte:** 2026-08-18. **Estado:** `SHADOW_CANDIDATE`; no se habilitó para bloquear entradas live.

## Pregunta

¿Un filtro de volatilidad basado en VIX mejora `DayBreakout` al evitar entradas durante estrés, sin confundir volatilidad con dirección?

## Investigación

Se creó y validó `/home/ubuntu/skills/vix-filter/SKILL.md`, con referencia en `/home/ubuntu/skills/vix-filter/references/research.md`. Cboe define VIX como una estimación de volatilidad esperada a 30 días del mercado estadounidense, construida con precios de opciones SPX/SPXW, bid/ask, strikes y tasas.[1] La term structure de Cboe contiene gauges para distintos plazos y no debe confundirse con la dirección del mercado.[2]

La investigación DERA de la SEC muestra que durante episodios extremos la liquidez, los spreads y las reglas de strikes con bid cero pueden afectar movimientos del VIX.[3] Por eso se usó la serie histórica VIXCLS de FRED como observación oficial diaria y no se reconstruyó VIX con OHLCV de acciones.

## Metodología

Se usaron barras históricas 15m reales de Alpaca IEX para SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ, con el VIX diario VIXCLS de FRED. El valor usado para cada entrada fue estrictamente el último cierre VIX anterior a la fecha de negociación. No se usó el cierre del mismo día.

El baseline replica `DayBreakout`: Donchian 10, entrada 10:00–15:30 ET, stop 2.5 ATR, salida por canal o máximo 20 barras, asignación igual por símbolo, slippage 5 bps y comisión $0. Se probaron 13 variantes en cinco ventanas: cuatro umbrales absolutos, tres percentiles rolling de 252 sesiones, tres shocks diarios, z-score 20 y una combinación de VIX 25 + shock 20%.

## Resultados medios frente al baseline

| Variante | Delta medio de retorno | Delta medio de drawdown | Ventanas con mayor retorno | Trades medios |
|---|---:|---:|---:|---:|
| Percentil 70 | **+2.12 pp** | **+2.46 pp** | 3/5 | 283.4 |
| Shock 10% | **+1.69 pp** | +0.68 pp | 3/5 | 350.2 |
| Shock 30% | +0.76 pp | +0.31 pp | 2/5 | 394.4 |
| Combinado 25 + shock | +0.06 pp | +0.54 pp | 2/5 | 368.2 |
| Nivel 20 | +0.04 pp | +0.68 pp | 1/5 | 316.8 |
| Percentil 60 | −1.02 pp | +3.36 pp | 2/5 | 215.6 |
| Percentil 80 | −0.29 pp | +0.63 pp | 1/5 | 335.0 |
| Nivel 25 | −0.70 pp | +0.23 pp | 0/5 | 372.8 |
| Nivel 30 | −0.71 pp | 0.00 pp | 0/5 | 396.6 |
| Shock 20% | −0.06 pp | −0.37 pp | 2/5 | 389.6 |
| Z-score 2 | −0.73 pp | −0.59 pp | 0/5 | 366.6 |
| Nivel 15 | −3.15 pp | +7.31 pp | 1/5 | 32.2 |

El percentil 70 fue el mejor candidato de retorno: en el periodo completo produjo aproximadamente **+11.80% frente a +7.26% del baseline**, y en verano −2.40% frente a −6.73%. Sin embargo, perdió frente al baseline en el selloff de primavera y fue igual en la recuperación de mayo. El shock 10% tuvo aproximadamente **+14.43% frente a +7.26%** en el periodo completo y −0.13% frente a −0.87% en los últimos 30 días, pero también necesita validación independiente porque los periodos se solapan.

El VIX alto no produjo una regla universal. El nivel fijo 15 bloqueó demasiado y destruyó retorno; el nivel 25/30 casi no aportó nada; el shock 20% empeoró el drawdown completo. El resultado favorable se concentró en percentil 70 y shock 10%, no en toda la familia de filtros.

## Decisión

**No promover el VIX como filtro operativo todavía, pero sí conservarlo como `SHADOW_CANDIDATE`.** A diferencia de Volume Profile, SMC ampliado y Williams %R, la señal de VIX mostró una mejora preliminar de retorno en tres de cinco ventanas para dos variantes. Eso justifica observarla en producción shadow, no permitirle bloquear entradas todavía.

La próxima validación debe usar walk-forward: calibrar percentil/threshold en un periodo anterior y evaluar en un periodo posterior independiente. También debe medir oportunidades perdidas, retraso de reentrada y si la mejora proviene solo de permanecer en efectivo. La term structure VIX3M/VIX queda pendiente porque no se obtuvo una serie histórica point-in-time fiable.

## Limitaciones

La muestra de acciones es 15m y el VIX es diario. El backtest mide un gate de exposición al subyacente, no trading de VIX futures/options ni P&L exacto de spreads Polaris. Las cinco ventanas se solapan en `full_recent`, por lo que no son cinco muestras independientes. Cboe advierte que el VIX depende de opciones SPX y de quotes; FRED VIXCLS es una serie histórica diaria, no un feed intradía.[1] [3]

## Reproducibilidad

- Skill: `/home/ubuntu/skills/vix-filter/SKILL.md`
- Investigación: `/home/ubuntu/skills/vix-filter/references/research.md`
- Módulo: `strategies/vix_filter.py`
- Tests: `tests/test_vix_filter.py`
- Cache: `/home/ubuntu/backtests/vix_history/`
- Motor: `scripts/run_vix_filter_backtests.py`
- Resultados: `/home/ubuntu/backtests/vix_filter_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/vix_filter_backtests_2026-08-18_deltas.csv`

**Basis:** proxy de subyacente con baseline DayBreakout; no P&L de opciones. **Time:** datos hasta 2026-08-18 y VIX anterior a cada sesión. **Assumptions:** VIXCLS oficial, 15m Alpaca IEX, 5 bps, comisión $0, Donchian 10, stop 2.5 ATR. **Sources & confidence:** Cboe, SEC DERA, FRED y Alpaca; confianza media-baja por muestra solapada y ausencia de term structure. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [Cboe — VIX Methodology](https://cdn.cboe.com/resources/indices/Volatility_Index_Methodology_Cboe_Volatility_Index.pdf)
[2] [Cboe — VIX Term Structure](https://www.cboe.com/tradable-products/vix/term-structure/)
[3] [SEC DERA — Demystify the Surge in VIX](https://www.sec.gov/files/dera-vix-working-paper-2504.pdf)
[4] [FRED — VIXCLS](https://fred.stlouisfed.org/series/VIXCLS)
