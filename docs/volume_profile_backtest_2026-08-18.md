# Volume Profile sobre DayBreakout — resultado de investigación

**Fecha de corte:** 2026-08-18. **Estado:** `RESEARCH_ONLY`; no se conectó al executor.

## Pregunta

¿Usar Volume Profile de la sesión anterior como filtro de la estrategia live `DayBreakout` mejora el retorno o el drawdown frente al baseline actual?

## Metodología

Se utilizaron barras históricas reales de 15 minutos del feed IEX de Alpaca, desde 2025-08-18 hasta 2026-08-18, para los ocho símbolos del universo Polaris: SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ. El cache contiene datos para los ocho símbolos; no se rellenaron faltantes.

La estrategia baseline replica la lógica de `DayBreakout`: canal Donchian de 10 velas, entrada larga entre 10:00 y 15:30 America/New_York, stop de 2.5 ATR, salida por ruptura del mínimo del canal o máximo de 20 barras. La posición se dimensiona con una asignación igual por símbolo sobre $100,000; se aplica slippage de 5 bps y comisión de $0.

El perfil se construye únicamente con sesiones RTH cerradas anteriores a la decisión. Se probaron bins 24/48/96, Value Area de 68%/70%/80%, lookback de 1/3/5 sesiones y cinco variantes: baseline, filtro VAH, filtro POC, aceptación VAH+volumen relativo y confluencia VAH+POC. La matriz contiene 675 combinaciones.

La primera corrida detectó una inflación contable: la compra no reducía el efectivo, por lo que el mark-to-market duplicaba el capital. Se corrigió el débito de efectivo, se repitió la matriz completa y solo se utilizan los resultados corregidos de la segunda corrida.

## Resultados medios por ventana

| Ventana | Baseline | POC filter | VAH filter | Aceptación VAH+volumen |
|---|---:|---:|---:|---:|
| Selloff primavera 2026 | +9.94% / −3.76% | +6.01% / −3.36% | +5.93% / −2.61% | +5.10% / −2.01% |
| Recuperación mayo 2026 | +8.58% / −3.01% | +6.47% / −2.34% | +6.40% / −1.63% | +4.60% / −1.59% |
| Verano 2026 | −6.74% / −14.31% | −1.19% / −8.61% | −0.95% / −5.70% | −0.31% / −3.63% |
| Últimos 30 días | +1.66% / −5.29% | +4.77% / −2.37% | +2.96% / −2.21% | +1.68% / −1.78% |
| Periodo completo | +15.82% / −12.16% | +5.71% / −14.57% | +7.33% / −11.27% | +5.69% / −7.89% |

Cada celda muestra `retorno / drawdown máximo`. Los filtros redujeron la pérdida del verano y mejoraron el retorno de los últimos 30 días, pero quedaron por debajo del baseline en primavera, recuperación y periodo completo. El filtro POC tuvo el mejor resultado reciente, pero empeoró el drawdown del periodo completo. La variante de aceptación redujo el drawdown completo, pero sacrificó cerca de diez puntos porcentuales de retorno frente al baseline.

## Decisión

**No promover Volume Profile a filtro de entradas.** Ninguna variante superó al baseline en al menos tres de cinco ventanas con drawdown no peor. En promedio, los deltas de retorno frente al baseline fueron −1.50 puntos porcentuales para POC, −1.52 para VAH y −2.50 para aceptación. La mejora observada en verano y últimos 30 días no fue suficiente para demostrar robustez fuera de muestra.

La skill `volume-profile` queda creada y validada como conocimiento reusable. El motor de backtest queda disponible para una futura segunda ronda, pero la estrategia permanece fuera de producción. La conclusión es específica a este proxy de OHLCV 15m y no demuestra que un Volume Profile basado en transacciones reales, footprint o datos de mayor calidad no pueda comportarse de otra manera.

## Limitaciones

El perfil asigna todo el volumen de cada vela al precio típico; no conoce el precio de cada transacción, agresor comprador/vendedor, bid/ask ni profundidad. Por tanto, no representa order flow real. La muestra es OHLCV de Alpaca IEX, no un histórico de opciones ni P&L de spreads. Tampoco se probó 5m por falta de cache intradía equivalente. Las variantes de parámetros fueron exploratorias y no deben interpretarse como optimización definitiva.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/volume-profile/SKILL.md`
- Investigación: `/home/ubuntu/skills/volume-profile/references/research.md`
- Cache: `/home/ubuntu/backtests/volume_profile_history/`
- Motor: `scripts/run_volume_profile_backtests.py`
- Resultados: `/home/ubuntu/backtests/volume_profile_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/volume_profile_backtests_2026-08-18_deltas.csv`
- Manifest: `/home/ubuntu/backtests/volume_profile_backtests_2026-08-18_manifest.json`

**Basis:** retorno sobre subyacente con capital igual por símbolo, no P&L exacto de opciones. **Time:** datos hasta 2026-08-18. **Assumptions:** RTH 09:30–16:00 ET, entrada 10:00–15:30 ET, 5 bps de slippage, sin comisión, stop 2.5 ATR y máximo 20 barras. **Sources & confidence:** Alpaca IEX OHLCV intradía; confianza media para el proxy de subyacente y baja para inferir rendimiento de opciones. **Compliance:** This is research and analysis only, not personalized financial advice.
