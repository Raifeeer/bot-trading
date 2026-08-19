# Relative strength rotation — investigación y backtest 2026-08-19

## Decisión ejecutiva

**Resultado: `RESEARCH_ONLY`; no integrar en `bot.py`, no crear una capa shadow live y no desplegar.** El ranking cross-sectional puede producir mejoras muy grandes en algunas fases del histórico, pero no resiste la validación temporal completa: las configuraciones líderes quedan por debajo del baseline de régimen S78 en `full_available` y no muestran una ventaja uniforme en los cuatro folds no solapados. Además, la mejor lectura utiliza un gate bull que deja el sistema en efectivo durante parte importante del periodo; eso reduce el riesgo, pero también significa que el resultado no es una prueba de selección de líderes operativa continua.

El código queda como detector puro y arnés reproducible. No tiene acceso al executor, no cambia sizing, no modifica el floor de recuperación de $99,000 y no autoriza cortas. Cloud Run no cambia.

## Qué se investigó

Relative strength rotation clasifica los símbolos disponibles por retorno reciente y compara cada uno con el retorno medio del universo. La idea conceptual es comprar ganadores y vender perdedores recientes [1]. La literatura de factores también formaliza momentum como carteras long/short cross-sectional, con un benchmark y una construcción explícita de cartera [2]. Sin embargo, la evidencia externa suele referirse a horizontes mensuales o de activos amplios; no constituye evidencia de una señal diaria para el universo pequeño de Polaris.

El estudio de momentum crash es especialmente relevante: reporta asimetría negativa y episodios de pérdidas fuertes después de caídas y durante rebotes/pánico de mercado [3]. Por eso el detector se probó con un gate bull, se mantuvo long-only como variante principal y se dejó `long_short` solo como investigación. La fuente reciente sobre múltiples periodos de formación se trató como contraste metodológico, no como una fuente de parámetros [4].

## Datos y metodología

Se utilizaron caches diarios reales de `setup_history`. El universo solicitado era SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI no tenía cache diario utilizable, por lo que se usaron **7 símbolos**. No se inventó un benchmark SPY/QQQ: los caches revisados no contienen esos símbolos. El benchmark principal fue el retorno equal-weight de los símbolos disponibles en cada fecha.

Se evaluaron **192 variantes** con horizontes de formación de 20 y 60 sesiones, top-1/top-2, rebalanceo diario o cada 5 sesiones, gate sin régimen o solo bull, `long_only`/`long_short`, retorno absoluto positivo o no y costes de 5/10/20 bps por cambio de peso. Se generaron 1,164 filas de métricas con ventanas recientes, previas, completas y un benchmark `regime_s78` que mantiene exposición larga solamente cuando el régimen es bull.

El ranking de cada fecha usa únicamente cierres disponibles hasta ese día y aplica el retorno siguiente. El benchmark usa el mismo universo disponible. El régimen utiliza barras diarias previas. Las posiciones se ponderan por igual dentro del top-k y se aplican costes por turnover. Las métricas son retorno, max drawdown, exposición absoluta media, número de rebalanceos y turnover one-way.

## Benchmarks

| Benchmark | Full available | Max drawdown | Función |
|---|---:|---:|---|
| Equal-weight de los 7 símbolos | **+138.1104%** | −25.8822% | Referencia de mantener el universo completo; está fuertemente afectada por la composición del periodo y no es una promesa operativa |
| `regime_s78` | **+14.6189%** | −14.8852% | Referencia principal de exposición larga condicionada al régimen bull |

El equal-weight presenta un retorno histórico extraordinario, por lo que es un control severo y también una advertencia de concentración/periodo: no se usa para afirmar que buy-and-hold sea replicable con opciones. La referencia operativa más prudente para el detector es `regime_s78`.

## Walk-forward no solapado

Para evitar que las ventanas superpuestas ocultaran una ruptura temporal, se probaron cuatro folds consecutivos de 60 sesiones. La tabla muestra las cuatro configuraciones que parecían más prometedoras en la matriz y su comparación directa contra `regime_s78`.

| Variante | Fold 1 reciente | Fold 2 | Fold 3 | Fold 4 | Full available |
|---|---:|---:|---:|---:|---:|
| `h60 k2 r5 bull long_only c5` | +42.88% vs −5.37% | +38.61% vs +24.18% | 0.00% vs −2.46% | 0.00% vs 0.00% | **+7.27% vs +14.62%** |
| `h60 k2 r5 bull long_only c20` | +41.81% vs −5.37% | +38.20% vs +24.18% | 0.00% vs −2.46% | 0.00% vs 0.00% | **+5.98% vs +14.62%** |
| `h20 k1 r5 bull long_only c5` | +48.66% vs −5.37% | +45.16% vs +24.18% | 0.00% vs −2.46% | 0.00% vs 0.00% | **−9.32% vs +14.62%** |
| `h60 k2 r5 bull long_short c5` | +34.53% vs −5.37% | +25.13% vs +24.18% | 0.00% vs −2.46% | 0.00% vs 0.00% | **+3.37% vs +14.62%** |

Los resultados altos de los dos folds recientes no son suficientes. En los folds 3 y 4 el gate bull deja la estrategia en efectivo; el resultado es defensivo, no evidencia de rotación rentable. En la ventana completa, todas las configuraciones quedan por debajo de `regime_s78`, y las variantes short además contradicen la política actual de cortas bloqueadas.

## Robustez y sensibilidad

La matriz original marca varias configuraciones con 4–5 ventanas mejores que `regime_s78`, pero esa cuenta mezcla ventanas superpuestas y no penaliza suficientemente que las ventanas con ventaja coincidan con un mismo tramo alcista. El walk-forward no solapado reduce la evidencia a 2 folds claramente favorables, 1 fold defensivo y 1 fold sin exposición.

| Control | Hallazgo | Decisión |
|---|---|---|
| Horizonte 20 vs 60 | 60d top-2 es menos frágil que 20d top-1; aun así, full queda por debajo de S78 | No seleccionar horizonte para producción |
| Top-1 vs top-2 | Top-1 concentra más y puede terminar negativo en full; top-2 es menos extremo | No promover sin análisis de concentración por símbolo |
| Rebalanceo diario vs 5 sesiones | Diario incrementa turnover y no resuelve la caída full | Mantener 5 sesiones solo como hipótesis de investigación |
| Coste 5 vs 20 bps | La ventaja reciente se reduce con costes; full continúa por debajo de S78 | El edge no depende solo del coste, pero tampoco lo supera |
| Gate bull | Reduce exposición y evita partes del selloff, pero genera muchos días en cash | Es un control de riesgo, no una prueba de selección de líderes |
| Long-only vs long-short | Long-short no mejora full y las cortas están prohibidas | No considerar integración de cortas |

La exposición absoluta media del candidato `h60 k2 r5 bull long_only c5` fue aproximadamente 0.18 en el fold reciente, 0.40 en el fold anterior y 0.08 en la ventana completa. Por tanto, su retorno no se puede comparar con una estrategia permanentemente invertida sin reportar también el tiempo en efectivo.

## Limitaciones

El universo tiene solo siete símbolos y no contiene SPY/QQQ en los caches disponibles. El ranking equal-weight puede cambiar mucho si se añade o elimina un ticker. No se dispone aquí de una historia point-in-time de opciones, IV, bid/ask, fills de patas o costes de spread; el estudio es sobre el subyacente diario y no sobre P&L de opciones. La evidencia de la literatura es principalmente de horizontes más largos y mercados amplios.

El detector aún no reporta un ledger de exposición por símbolo en cada fold; solo reporta exposición media, turnover y métricas de cartera. Antes de cualquier nueva evaluación habría que añadir ese ledger, excluir el mejor símbolo como análisis de sensibilidad y probar un benchmark externo cuando exista cache sincronizado.

## Decisión para Polaris

No añadir `relative_strength_shadow_observations`, no crear configuración live y no desplegar. La estrategia puede volver a evaluarse cuando exista una historia más amplia y uniforme, un benchmark SPY/QQQ point-in-time, un ledger de concentración por símbolo y una validación específica sobre entradas de opciones. Si alguna variante llega a shadow en el futuro, deberá forzar `mode=shadow`, `influence_entries=false` y `orders_allowed=false`, y las cortas seguirán bloqueadas.

Polaris continúa en PAPER con la revisión `polaris-bot-brshadow0724650`; el único motor auxiliar desplegado recientemente es breakdown/retest bearish en shadow.

## Artefactos

- `strategies/relative_strength_rotation.py`
- `tests/test_relative_strength_rotation.py`
- `scripts/run_relative_strength_backtests.py`
- `scripts/analyze_relative_strength_backtests.py`
- `scripts/run_relative_strength_walkforward.py`
- `docs/relative_strength_research_sources_2026-08-19.md`
- `/home/ubuntu/backtests/relative_strength_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_backtest_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_backtest_variant_summary_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_backtest_sensitivity_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_walkforward_2026-08-19.csv`
- `/home/ubuntu/backtests/relative_strength_walkforward_manifest_2026-08-19.json`

## Referencias

[1] [Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency — Jegadeesh and Titman](https://doi.org/10.2307/2328882).

[2] [Value and Momentum Everywhere: Factors, Monthly — AQR](https://www.aqr.com/Insights/Datasets/Value-and-Momentum-Everywhere-Factors-Monthly).

[3] [Momentum Crashes — Daniel and Moskowitz](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2371227).

[4] [Cross-sectional factor momentum: evidence from multiple formation periods](https://www.tandfonline.com/doi/full/10.1080/13504851.2025.2472032).
