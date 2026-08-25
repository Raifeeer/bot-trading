# Polaris — readiness de estrategias

> Corte: 2026-08-25. Se analizaron archivos históricos locales disponibles, con ventanas que llegan como máximo a 2026-08-19 y datos de mercado que en varios casos terminan el 2026-08-07. El informe es exploratorio y no prueba rentabilidad futura.

## Decisión ejecutiva

No se promueve ninguna estrategia a ejecución automática. Los retornos positivos aislados no superan todavía los requisitos de datos point-in-time, purging/embargo, costes y slippage, walk-forward no solapado, muestra suficiente y prueba de lifecycle del broker. El bot permanece en PAPER contenido con `risk.halt_new_entries=true`.

| Resultado | Cantidad |
|---|---:|
| Archivos evaluables | 44 |
| Candidatos mecánicos pendientes de OOS | 0 |
| Decisiones `PROMOTION_CANDIDATE_PENDING_OOS` | 0 |
| Evidencia insuficiente | 41 |
| Decisiones `RESEARCH_ONLY` | 3 |

## Lectura de los resultados

El catálogo muestra que algunas familias parecen atractivas en determinadas tablas, pero sus controles son insuficientes para autorizar operaciones. `relative_strength` presenta retornos altos en ciertas filas, pero también drawdowns muy elevados; `defined_risk` y algunas variantes de `volume_profile` contienen gaps o no reportan una medición comparable de drawdown; `wheel` tiene limitaciones de capital, asignación y muestra que impiden compararla directamente con spreads de riesgo definido. Estas observaciones sirven para priorizar investigación, no para elegir una configuración live.

| Archivo | Filas | Mediana retorno % | % positivas | Filas robustas mecánicas | OOS marcado | Peor DD % | Gaps | Máx. trades | Decisión |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|
| `defined_risk_backtests_2026-08-18_results.csv` | 1800 | -0.84 | 18.44 | 1 | sí | -32.43 | 19285.00 | 59.00 | `RESEARCH_ONLY` |
| `relative_strength_backtest_comparison_2026-08-19.csv` | 1152 | 16.93 | 71.96 | 0 | no | -46.28 | NA | NA | `INSUFFICIENT_EVIDENCE` |
| `relative_strength_backtests_2026-08-19.csv` | 1164 | 16.61 | 71.91 | 0 | no | -46.28 | NA | NA | `INSUFFICIENT_EVIDENCE` |
| `wheel_backtests_2026-08-18_best_by_window.csv` | 5 | 6.30 | 100.00 | 0 | sí | -0.62 | 8.00 | NA | `INSUFFICIENT_EVIDENCE` |
| `volume_profile_backtests_2026-08-18_deltas.csv` | 25 | 5.69 | 80.00 | 0 | sí | NA | NA | 1245.00 | `INSUFFICIENT_EVIDENCE` |
| `vix_filter_backtests_2026-08-18_deltas.csv` | 65 | 5.17 | 60.00 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `vix_filter_backtests_2026-08-18_results.csv` | 65 | 5.17 | 60.00 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `volume_profile_backtests_2026-08-18_results.csv` | 675 | 5.12 | 83.70 | 0 | sí | NA | NA | 1245.00 | `INSUFFICIENT_EVIDENCE` |
| `setup_confluence_backtests_2026-08-18.csv` | 12 | 4.81 | 66.67 | 0 | sí | -25.50 | NA | 217.00 | `INSUFFICIENT_EVIDENCE` |
| `setup_confluence_analysis_2026-08-18_comparison.csv` | 8 | 2.40 | 62.50 | 0 | sí | NA | NA | 217.00 | `INSUFFICIENT_EVIDENCE` |
| `fundamental_swing_backtests_2026-08-18_deltas.csv` | 25 | 2.12 | 80.00 | 0 | sí | NA | NA | 6.00 | `INSUFFICIENT_EVIDENCE` |
| `fundamental_swing_backtests_2026-08-18_results.csv` | 25 | 2.12 | 80.00 | 0 | sí | NA | NA | 6.00 | `INSUFFICIENT_EVIDENCE` |
| `defined_risk_backtests_2026-08-18_top_full_window.csv` | 30 | 1.03 | 100.00 | 0 | sí | -3.02 | 739.00 | 26.00 | `RESEARCH_ONLY` |
| `williams_r_backtests_2026-08-18_deltas.csv` | 90 | 0.66 | 53.33 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `williams_r_backtests_2026-08-18_results.csv` | 90 | 0.66 | 53.33 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `wheel_backtests_2026-08-18_analyzed.csv` | 25 | 0.65 | 84.00 | 0 | sí | -8.71 | 93.00 | NA | `INSUFFICIENT_EVIDENCE` |
| `wheel_backtests_2026-08-18_results.csv` | 25 | 0.65 | 84.00 | 0 | sí | -8.71 | 93.00 | NA | `INSUFFICIENT_EVIDENCE` |
| `smc_expanded_backtests_2026-08-18_deltas.csv` | 25 | 0.42 | 60.00 | 0 | sí | NA | NA | 1292.00 | `INSUFFICIENT_EVIDENCE` |
| `smc_expanded_backtests_2026-08-18_results.csv` | 25 | 0.42 | 60.00 | 0 | sí | NA | NA | 1292.00 | `INSUFFICIENT_EVIDENCE` |
| `chart_pattern_backtests_2026-08-18_deltas.csv` | 55 | -0.12 | 49.09 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `chart_pattern_backtests_2026-08-18_results.csv` | 55 | -0.12 | 49.09 | 0 | sí | NA | NA | 1293.00 | `INSUFFICIENT_EVIDENCE` |
| `breakout_20_55_backtest_comparison_2026-08-19.csv` | 132 | -0.14 | 31.06 | 0 | no | -24.12 | NA | 861.00 | `INSUFFICIENT_EVIDENCE` |
| `breakout_20_55_backtests_2026-08-19.csv` | 138 | -0.14 | 30.43 | 0 | no | -24.12 | NA | 861.00 | `INSUFFICIENT_EVIDENCE` |
| `trend_pullback_backtests_2026-08-19.csv` | 798 | -0.19 | 13.66 | 0 | no | -9.80 | NA | 493.00 | `INSUFFICIENT_EVIDENCE` |
| `trend_pullback_backtest_comparison_2026-08-19.csv` | 792 | -0.19 | 13.64 | 0 | no | -9.80 | NA | 493.00 | `INSUFFICIENT_EVIDENCE` |
| `rsi_bounce_backtests_2026-08-19.csv` | 402 | -0.21 | 15.67 | 0 | no | -20.10 | NA | 707.00 | `INSUFFICIENT_EVIDENCE` |
| `rsi_bounce_backtest_comparison_2026-08-19.csv` | 396 | -0.21 | 15.66 | 0 | no | -20.10 | NA | 707.00 | `INSUFFICIENT_EVIDENCE` |
| `intraday_mean_reversion_backtests_2026-08-19.csv` | 204 | -0.24 | 8.82 | 0 | no | -21.60 | NA | 697.00 | `INSUFFICIENT_EVIDENCE` |
| `vwap_backtests_2026-08-19.csv` | 270 | -0.28 | 14.07 | 0 | no | -34.84 | NA | 995.00 | `INSUFFICIENT_EVIDENCE` |
| `vwap_backtest_comparison_2026-08-19.csv` | 264 | -0.28 | 14.02 | 0 | no | -34.84 | NA | 995.00 | `INSUFFICIENT_EVIDENCE` |
| `relative_strength_priority_backtests_2026-08-19.csv` | 102 | -0.37 | 14.71 | 0 | no | -10.79 | NA | 316.00 | `INSUFFICIENT_EVIDENCE` |
| `bearish_breakdown_retest_backtests_2026-08-19.csv` | 560 | -0.53 | 20.54 | 0 | no | -7.64 | NA | 23.00 | `INSUFFICIENT_EVIDENCE` |
| `orb_backtests_2026-08-19.csv` | 330 | -0.87 | 18.79 | 0 | no | -33.65 | NA | 1607.00 | `INSUFFICIENT_EVIDENCE` |
| `orb_backtest_comparison_2026-08-19.csv` | 324 | -0.90 | 18.83 | 0 | no | -33.65 | NA | 1607.00 | `INSUFFICIENT_EVIDENCE` |
| `online_strategy_backtests_2026-08-19_results.csv` | 360 | -4.49 | 3.06 | 0 | sí | -77.75 | 2558.00 | 65.00 | `RESEARCH_ONLY` |
| `wheel_backtests_1000_2026-08-18_results.csv` | 25 | 0.00 | 48.00 | 0 | sí | -1.56 | 44.00 | NA | `INSUFFICIENT_EVIDENCE` |
| `live_swing_setup_2026-08-18_results.csv` | 28 | 0.00 | 39.29 | 0 | sí | -1.06 | NA | 6.00 | `INSUFFICIENT_EVIDENCE` |
| `current_setup_integration_2026-08-18_results.csv` | 32 | 0.00 | 31.25 | 0 | sí | -2.39 | NA | 16.00 | `INSUFFICIENT_EVIDENCE` |
| `current_setup_integration_2026-08-18_comparison.csv` | 28 | 0.00 | 28.57 | 0 | sí | -1.42 | NA | 10.00 | `INSUFFICIENT_EVIDENCE` |
| `failure_retest_backtests_2026-08-19.csv` | 402 | 0.00 | 12.94 | 0 | no | -11.05 | NA | 380.00 | `INSUFFICIENT_EVIDENCE` |
| `structure_mtf_backtests_2026-08-19.csv` | 25 | 0.00 | 0.00 | 0 | no | -1.37 | NA | 9.00 | `INSUFFICIENT_EVIDENCE` |
| `structure_mtf_backtests_2026-08-19_summary.csv` | 20 | 0.00 | 0.00 | 0 | no | -0.65 | NA | 3.00 | `INSUFFICIENT_EVIDENCE` |
| `wheel_backtests_100_2026-08-18_results.csv` | 25 | 0.00 | 0.00 | 0 | sí | 0.00 | 0.00 | NA | `INSUFFICIENT_EVIDENCE` |
| `gamma_walls_backtests_2026-08-18_results.csv` | 10 | NA | NA | 0 | no | NA | NA | 0.00 | `INSUFFICIENT_EVIDENCE` |

## Próxima evaluación segura

La siguiente iteración debe fijar un dataset point-in-time y un baseline único, separar entrenamiento, purging/embargo y test final, aplicar costes y slippage pesimistas, y medir P&L por operación, drawdown, profit factor, exposición, concentración y sensibilidad. Después se hará un A/B en shadow con el mismo universo y las mismas barras, sin permitir que la señal candidata envíe órdenes. Solo una mejora repetida fuera de muestra podría pasar a `PROMOTION_CANDIDATE`; no existe todavía una base para prometer rentabilidad.

## Referencias internas

- `polaris_backtest_catalog_summary_2026-08-25.json` — resumen reproducible del catálogo.
- `AGENTS.md` — reglas operativas, guardarraíles y estado de producción.
- `docs/canary_post_execution_checklist.md` — procedimiento de verificación de broker, ledger y rollback.
