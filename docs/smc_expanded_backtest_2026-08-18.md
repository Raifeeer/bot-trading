# SMC ampliado — resultado de investigación y backtest

**Fecha de corte:** 2026-08-18. **Estado:** `RESEARCH_ONLY`; no se conectó al executor.

## Pregunta

¿Añadir FVG, MSS, order blocks con sweep y confluencia SMC como filtros de la estrategia `DayBreakout` mejora retorno o drawdown frente al baseline?

## Investigación

Se creó y validó la skill `/home/ubuntu/skills/smc-expanded/SKILL.md` con la referencia `/home/ubuntu/skills/smc-expanded/references/research.md`. Las fuentes consultadas definen FVG como una estructura de tres velas con no solapamiento, BOS/CHoCH como rupturas confirmadas por cierres de cuerpo y order block estricto como la última vela contraria antes de desplazamiento y ruptura de estructura.[1] [2] [3]

La investigación también mostró que SMC no tiene una definición única para breaker, mitigation, external swing, OTE, killzone u order block. El OHLCV no revela órdenes institucionales ni stops reales. Por eso el motor usa nombres de features y evidencia geométrica, no afirmaciones de flujo institucional.

## Metodología

Se usaron barras históricas reales 15m de Alpaca IEX para SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ, desde 2025-08-18 hasta 2026-08-18. La muestra permite probar la capa estructural intradía, pero **no valida la cascada MTF completa 1D/4H/15M/5M** porque no hay cache histórico equivalente para todos esos marcos.

El baseline replica `DayBreakout`: Donchian 10, entradas largas 10:00–15:30 ET, stop 2.5 ATR, salida por canal o máximo 20 barras, asignación igual por símbolo, slippage de 5 bps y comisión $0. Las variantes fueron:

| Variante | Requisito adicional |
|---|---|
| FVG filter | FVG alcista fresco y no llenado |
| MSS filter | Ruptura alcista con cuerpo >= 1.5 ATR |
| OB + sweep | Order block alcista válido y sweep/reclaim alcista |
| Confluence | Al menos dos de FVG, MSS, OB y sweep |

## Resultados

| Ventana | Baseline | FVG | MSS | OB+sweep | Confluencia |
|---|---:|---:|---:|---:|---:|
| Selloff primavera 2026 | +8.30% / −4.48% | **+9.07% / −4.71%** | +2.38% / −1.65% | +0.07% / 0.00% | +7.50% / −2.90% |
| Recuperación mayo 2026 | +6.07% / −2.75% | **+6.24% / −2.71%** | +1.53% / −1.10% | +0.42% / 0.00% | +2.34% / −2.25% |
| Verano 2026 | −6.73% / −13.09% | −10.80% / −14.53% | **−1.18% / −2.66%** | −0.49% / −0.73% | −4.81% / −7.70% |
| Últimos 30 días | −0.87% / −5.96% | −2.69% / −5.65% | −1.93% / −2.03% | **−0.11% / −0.11%** | −1.50% / −2.99% |
| Periodo completo | +7.41% / −13.94% | +5.73% / −12.88% | +3.03% / −2.55% | +0.00% / −0.73% | +5.40% / −7.04% |

Las celdas muestran `retorno / drawdown máximo`. FVG superó al baseline en primavera y recuperación, pero perdió claramente en verano y periodo completo. MSS redujo mucho el drawdown y evitó gran parte de la caída del verano, pero sacrificó retorno y tuvo solo 77 operaciones medias por ventana. OB+sweep produjo muy pocas operaciones —3.2 de media—, por lo que sus cifras no son estadísticamente confiables. La confluencia redujo drawdown en todas las ventanas, pero no superó el retorno de forma consistente.

## Decisión

**No promover SMC ampliado a filtro de entradas.** Ninguna variante superó al baseline en al menos tres de cinco ventanas con drawdown no peor. La variante más interesante para una futura observación shadow es `MSS filter` por su reducción de drawdown, no por aumento de profits. FVG queda como hipótesis secundaria; OB+sweep queda descartado provisionalmente por cobertura demasiado baja.

La skill y el módulo puro quedan disponibles para investigación, pero no se conectan a `bot.py`, no cambian `influence_entries` y no reciben acceso al executor.

## Limitaciones

La prueba es parcial 15m y usa OHLCV. No incorpora 1D/4H/5M sincronizados, footprint, delta, bid/ask, open interest, sesiones London/New York o killzones. Los conceptos visuales fueron convertidos a reglas aproximadas y las señales que reducen operaciones pueden parecer robustas solo porque permanecen en efectivo. El resultado no es P&L de opciones.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/smc-expanded/SKILL.md`
- Referencia: `/home/ubuntu/skills/smc-expanded/references/research.md`
- Módulo: `strategies/smc_expanded.py`
- Tests: `tests/test_smc_expanded.py`
- Motor: `scripts/run_smc_expanded_backtests.py`
- Resultados: `/home/ubuntu/backtests/smc_expanded_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/smc_expanded_backtests_2026-08-18_deltas.csv`

**Basis:** proxy de acciones/subyacente con asignación igual por símbolo; no P&L exacto de opciones. **Time:** datos hasta 2026-08-18. **Assumptions:** barras 15m, entrada tras cierre confirmado, stop 2.5 ATR, máximo 20 barras, slippage 5 bps, comisión $0. **Sources & confidence:** Alpaca IEX OHLCV y fuentes educativas SMC; confianza media para la comparación 15m y baja para generalizar a MTF/opciones. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [TrendSpider — Fair Value Gap Trading Strategy](https://trendspider.com/learning-center/fair-value-gap-trading-strategy/)
[2] [Daily Price Action — SMC Market Structure](https://dailypriceaction.com/blog/smc-market-structure/)
[3] [Trading Wyckoff — Smart Money Concepts Complete Guide](https://tradingwyckoff.com/en/smart-money-concepts/)
