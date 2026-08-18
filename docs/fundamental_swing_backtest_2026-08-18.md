# Filtros fundamentales swing — investigación y backtest

**Fecha de corte:** 2026-08-18. **Estado:** `RESEARCH_ONLY`; no se conectó a `bot.py`.

## Pregunta

¿P/E, crecimiento de revenue/EPS, deuda y ranking fundamental mejoran el motor live `SwingTrend` para operaciones swing?

## Investigación

Se creó y validó `/home/ubuntu/skills/fundamental-swing/SKILL.md`, con investigación en `references/research.md`. La SEC ofrece Company Facts y Submissions en `data.sec.gov`; los datos XBRL se actualizan cuando se diseminan filings y cada fact debe conservar `filed`, `accn`, formulario y periodo.[1] FINRA recomienda revisar 10-K/10-Q, EPS, P/E, P/S y D/E, y comparar ratios dentro de industria y mercado.[2] Fidelity explica que P/E es precio/EPS, distingue trailing y forward P/E y advierte que P/E puede variar mucho por industria y quedar desactualizado entre filings.[3] NBER estudia el uso de trailing P/E en price targets, pero esto no prueba que un P/E gate simple genere alpha.[4]

## Datos y cobertura

Se descargaron Company Facts y submissions SEC para SOFI, PLTR, F, TSLA, AMD, NOK y BB. SOFI, PLTR, F, TSLA, AMD y BB tienen facts us-gaap utilizables. NOK devuelve cero tags us-gaap en Company Facts, por lo que se excluyó; TQQQ se excluyó porque es ETF y no una empresa operativa comparable con P/E o D/E.

El backtest final utiliza **PLTR, F, TSLA, AMD y BB**, snapshots a la fecha de filing y cinco ventanas. No se imputaron valores faltantes ni se usaron forward estimates. Los ratios se recalculan con facts disponibles antes de la fecha de decisión; la entrada se comprueba en el cruce de SwingTrend y se ejecuta en la apertura siguiente con slippage.

## Reglas

| Variante | Regla |
|---|---|
| Baseline | SwingTrend: SMA20/50, precio sobre SMA200, stop 3 ATR, objetivo 6 ATR, máximo 20 días |
| Value quality | P/E positivo bajo el percentil 60, revenue growth no negativo, D/E bajo percentil 70 |
| Growth quality | Revenue growth TTM >15%, EPS growth positivo cuando comparable, D/E controlado |
| Fundamental rank | Ranking cross-sectional de revenue growth, EPS growth y D/E; selección sobre mediana con cobertura |
| Quality combo | Unión de value quality y growth quality |

La muestra es pequeña: el motor exacto de SwingTrend generó una media de solo 2.6 trades por ventana para el baseline. Eso obliga a interpretar los porcentajes como evidencia preliminar.

## Resultados medios

| Variante | Retorno medio | Delta retorno vs baseline | Drawdown medio | Trades medios | Ventanas que superan retorno |
|---|---:|---:|---:|---:|---:|
| Baseline | **+4.83%** | 0.00 pp | −1.26% | 2.6 | 0/5 |
| Fundamental rank | +2.75% | −2.08 pp | −1.02% | 1.2 | 0/5 |
| Quality combo | +3.20% | −1.63 pp | −0.52% | 1.0 | 0/5 |
| Value quality | +3.20% | −1.63 pp | −0.52% | 1.0 | 0/5 |
| Growth quality | +1.27% | −3.56 pp | −0.49% | 0.6 | 0/5 |

Ningún filtro fundamental superó el retorno del baseline en ninguna de las cinco ventanas. Todos redujeron el número de operaciones. También redujeron el drawdown promedio, pero eso se debe en parte a que bloquearon operaciones y permanecieron más tiempo en efectivo; no es evidencia de mayor rentabilidad.

## Decisión

**No incorporar filtros fundamentales al código operativo ni a la capa de entradas de Polaris.** El resultado sugiere que pueden funcionar como filtros defensivos de selección, pero en esta muestra destruyeron retorno al descartar señales de SwingTrend. Tampoco los conectaría en shadow todavía porque la cobertura es baja y la frecuencia de trades es demasiado pequeña para inferir una ventaja.

Una segunda ronda solo tendría sentido con más años de datos, un universo mayor, normalización por industria y snapshots SEC reconstruidos por filing. No debe usarse P/E con empresas de EPS negativo ni utilizar el valor actual de una base fundamental para simular fechas pasadas.

## Limitaciones

Los datos de SEC son adecuados para evitar look-ahead de fecha de filing, pero los tags XBRL no son idénticos entre empresas. El universo tiene sectores heterogéneos, pocos símbolos y solo cinco empresas utilizables. El resultado es P&L del subyacente, no de opciones. La mayor parte del resultado se apoya en pocas operaciones; no hay evidencia suficiente de robustez.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/fundamental-swing/SKILL.md`
- Investigación: `/home/ubuntu/skills/fundamental-swing/references/research.md`
- Cache SEC: `/home/ubuntu/backtests/fundamental_history/`
- Snapshots: `/home/ubuntu/backtests/fundamental_history/snapshots/`
- Motor: `scripts/run_fundamental_swing_backtests.py`
- Resultados: `/home/ubuntu/backtests/fundamental_swing_backtests_2026-08-18_results.csv`
- Deltas: `/home/ubuntu/backtests/fundamental_swing_backtests_2026-08-18_deltas.csv`

**Basis:** SwingTrend long-only sobre subyacente. **Time:** datos de precio recientes y facts SEC disponibles hasta 2026-08-18. **Assumptions:** P/E trailing, growth TTM, D/E, retraso de un día post-filing, entrada en apertura siguiente, slippage 5 bps. **Sources & confidence:** SEC, FINRA, Fidelity y NBER; confianza baja-media por universo pequeño, facts faltantes y pocas operaciones. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [SEC — EDGAR Application Programming Interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
[2] [FINRA — Evaluating Stocks](https://www.finra.org/investors/investing/investment-products/stocks/evaluating-stocks)
[3] [Fidelity — What is price-to-earnings ratio?](https://www.fidelity.com/learning-center/trading-investing/pe-ratio)
[4] [NBER — Expected EPS × Trailing P/E](https://www.nber.org/papers/w32942)
