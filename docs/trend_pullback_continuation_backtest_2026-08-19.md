# Trend pullback / continuación EMA-VWAP — 2026-08-19

## Decisión

**Decisión: integrar únicamente como `shadow` en PAPER; no promover a filtro operativo ni permitir órdenes.** La mejor configuración sin filtro de volumen supera ligeramente a DayBreakout en la cobertura completa, pero aumenta drawdown. La configuración elegida para observación —EMA 9/21, alineación VWAP, volumen mínimo 1.2x, 15 minutos, long-only— no supera el retorno completo del baseline, pero mejora el drawdown y muestra una señal más selectiva. El walk-forward muestra una ventaja de retorno en 3 de 5 folds y mejora de drawdown en 4 de 5 folds; no es evidencia suficiente para influir en entradas.

La capa se conecta al loop solamente para registrar observaciones bajo `trend_pullback_shadow_observations`. El wrapper fuerza `mode=shadow`, `influence_entries=false` y `orders_allowed=false`, no importa el executor y no puede modificar RiskManager, floor, circuit breakers, sizing ni posiciones.

## Hipótesis

Una tendencia previa puede continuar después de un retroceso ordenado hacia una EMA o VWAP de sesión. El detector exige EMA rápida sobre EMA lenta, pendiente de tendencia, impulso mínimo medido en ATR, retroceso hacia la zona, cierre posterior que rompe el micro extremo del pullback y, en la variante elegida, volumen relativo mínimo de 1.2x. La entrada simulada se ejecuta en la apertura siguiente a la barra de confirmación; el stop y target son teóricos y no se conectan al executor.

La literatura de time-series momentum documenta persistencia de retornos en horizontes de uno a doce meses sobre futuros líquidos, con reversión parcial posterior [1]. Esa evidencia respalda estudiar continuidad de tendencia, pero no demuestra alpha intradía para acciones u opciones de Polaris. La revisión sobre trend following con costes destaca que la frecuencia y el lookback deben evaluarse junto con los costes de transacción [2]. Por eso la matriz incluye slippage y volumen, y la promoción queda bloqueada hasta más evidencia fuera de muestra.

## Metodología

Se usaron caches reales OHLCV de Alpaca IEX: `structure_mtf_history` para 5m, `volume_profile_history` para 15m y `setup_history` para régimen diario. El universo solicitado tenía ocho símbolos; SOFI no contó porque no tenía cache intradía utilizable en esta corrida. Se usaron PLTR, F, TSLA, AMD, NOK, BB y TQQQ.

Se ejecutaron **144 variantes** y **798 filas** de métricas. Las dimensiones fueron 5m/15m, EMA 9/21, 12/26 y 20/50, alineación o no con VWAP, volumen libre o mínimo 1.2x, gates none/bull/directional y dirección long/both. Las variantes `both` solo son investigación; la configuración shadow live usa `long` y `allow_shorts=false`. El coste modelado fue 5 bps de slippage por lado, entrada en la siguiente apertura, salida por stop/target o máximo de barras y sin overnight.

El baseline es DayBreakout con la configuración S78 actual. El arnés reutiliza warm-up histórico para ATR/Donchian, pero reporta métricas solo dentro de cada ventana. EMA, ATR, VWAP y volumen se calculan con información hasta la confirmación. El walk-forward utiliza cinco folds consecutivos no solapados de 20 sesiones.

## Resultados completos

| Variante | Retorno full | Max drawdown | Delta retorno vs baseline | Delta drawdown vs baseline | Trades |
|---|---:|---:|---:|---:|---:|
| DayBreakout S78 | +8.485% | −3.097% | — | — | 156 |
| EMA 9/21 + VWAP, sin volumen | **+9.223%** | −4.403% | +0.738 pp | −1.306 pp | 268 |
| EMA 9/21 + VWAP + volumen 1.2x | +8.390% | **−2.148%** | −0.095 pp | **+0.949 pp** | 134 |
| EMA 9/21 + sin VWAP + volumen 1.2x | +8.128% | −2.541% | −0.357 pp | +0.556 pp | 143 |
| EMA 9/21 + sin VWAP + volumen 1.2x + gate bull | +4.927% | −1.556% | −3.557 pp | +1.541 pp | 24 |

La variante sin volumen tiene un pequeño exceso de retorno, pero necesita 268 trades frente a 156 y tiene drawdown materialmente peor. La variante con volumen 1.2x sacrifica 0.095 puntos porcentuales de retorno y mejora el drawdown en 0.949 puntos porcentuales, con aproximadamente la mitad de trades. Es un mejor candidato de observación, no una razón para cambiar entradas live.

## Walk-forward no solapado

La shortlist se evaluó en cinco bloques consecutivos de 20 sesiones. Los deltas positivos de drawdown significan que el drawdown del candidato fue menor que el baseline.

| Fold | Baseline retorno | EMA9/21 + VWAP sin vol | EMA9/21 + VWAP + vol1.2 | EMA9/21 sin VWAP + vol1.2 | Vol1.2 + gate bull |
|---|---:|---:|---:|---:|---:|
| 1 | −0.568% | −0.629% / DD −1.884 pp | −0.004% / DD −0.213 pp | −0.004% / DD −0.213 pp | 0.000% / DD +0.657 pp |
| 2 | −0.252% | +1.216% / DD −0.086 pp | +0.752% / DD +0.315 pp | +0.752% / DD +0.315 pp | 0.000% / DD +0.691 pp |
| 3 | −0.208% | −1.508% / DD −1.914 pp | +0.057% / DD +0.424 pp | +0.291% / DD +0.651 pp | +0.525% / DD +1.600 pp |
| 4 | +4.943% | +3.481% / DD +0.348 pp | +2.857% / DD +0.685 pp | +2.857% / DD +0.685 pp | +3.296% / DD +0.681 pp |
| 5 | +4.573% | +3.131% / DD +0.490 pp | +2.949% / DD +0.581 pp | +3.398% / DD +0.567 pp | +1.269% / DD +0.997 pp |

La variante seleccionada con volumen supera al baseline en retorno en los folds 1, 2 y 3, y queda por debajo en los dos folds alcistas finales. Mejora el drawdown en cuatro folds y empeora ligeramente en el primero. La muestra todavía es pequeña y el resultado no debe interpretarse como ventaja estable.

## Observaciones de riesgo

Las variantes sin volumen producen demasiadas señales y mayor sensibilidad al ruido. Los gates bull reducen mucho la exposición y el drawdown, pero también dejan el motor fuera del mercado en buena parte de las ventanas; sus retornos no son comparables a una estrategia permanentemente invertida sin reportar esa exposición. Las variantes bear son solo observacionales y permanecen bloqueadas por política.

La concentración por símbolo es relevante: PLTR y NOK dominan varios resultados positivos de la matriz. Antes de cualquier promoción futura se necesita un ledger de exposición y un análisis leave-one-symbol-out. El backtest es sobre subyacente diario/intradía, no sobre fills de opciones, bid/ask, IV o riesgo de patas.

## Integración segura

Se añadió `trend_pullback_shadow` a `config/config.yaml` con 15m, EMA 9/21, alineación VWAP, volumen 1.2x, long-only y `allow_shorts=false`. `bot.py` publica:

- `trend_pullback_shadow_observations` en el estado persistido.
- `trend_pullback_shadow` dentro de `signal_stats`.
- `trend_pullback_shadow_s` en `CYCLE TIMING`.

Si faltan barras, la observación queda `missing_data` o `insufficient_data`. Si el detector falla, queda `error` por símbolo y el tick continúa. La autoridad permanece en RiskManager y las capas live actuales.

## Artefactos

- `strategies/trend_pullback_continuation.py`
- `tests/test_trend_pullback_continuation.py`
- `tests/test_trend_pullback_shadow.py`
- `scripts/run_trend_pullback_backtests.py`
- `scripts/analyze_trend_pullback_backtests.py`
- `scripts/run_trend_pullback_walkforward.py`
- `docs/trend_pullback_research_sources_2026-08-19.md`
- `backtests/trend_pullback_backtests_2026-08-19.csv`
- `backtests/trend_pullback_backtest_trades_2026-08-19.csv`
- `backtests/trend_pullback_backtest_comparison_2026-08-19.csv`
- `backtests/trend_pullback_backtest_variant_summary_2026-08-19.csv`
- `backtests/trend_pullback_walkforward_2026-08-19.csv`

## Referencias

[1] [Time Series Momentum — Moskowitz, Ooi and Pedersen](https://www.semanticscholar.org/paper/Time-Series-Momentum-Moskowitz-Ooi/797398408f967a6e6bc4570db7df7daeccd6fa61).

[2] [Optimal Trend-Following With Transaction Costs — review of Zakamulin and Giner](https://returnstacked.investresolve.com/academic-review/optimal-trend-following-with-transaction-costs/).
