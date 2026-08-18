# Segunda validación walk-forward: VIX, MSS y flags

**Fecha de corte:** 2026-08-18.
**Estado:** `RESEARCH_ONLY`; ninguna variante puede enviar órdenes.

## Objetivo

La primera ronda encontró tres hipótesis interesantes: filtro VIX, MSS de SMC ampliado y flags chartistas. Esta segunda ronda debía comprobar si la mejora sobrevivía cuando los parámetros se elegían únicamente con datos anteriores y se evaluaban en periodos posteriores no solapados.

## Diseño

Se utilizaron las mismas barras reales de 15 minutos Alpaca IEX y los ocho símbolos del universo Polaris. El baseline mantuvo Donchian 10, entradas 10:00–15:30 ET, stop 2.5 ATR, máximo 20 barras y 5 bps de slippage.

| Fold | Entrenamiento | Test |
|---|---|---|
| 1 | 2025-08-18 → 2026-03-01 | 2026-03-01 → 2026-05-01 |
| 2 | 2025-08-18 → 2026-05-01 | 2026-05-01 → 2026-06-01 |
| 3 | 2025-08-18 → 2026-06-01 | 2026-06-01 → 2026-07-16 |
| 4 | 2025-08-18 → 2026-07-16 | 2026-07-16 → 2026-08-19 |

En cada fold se seleccionó la variante con mejor puntuación de entrenamiento: `retorno + 0.50 × drawdown`. Como el drawdown es negativo, la fórmula penaliza las caídas. El intervalo de test no participó en la selección.

## Resultados agregados de test

| Familia | Variantes elegidas en los folds | Tests con mayor retorno | Deltas medios de retorno | Deltas medios de drawdown | Retorno compuesto elegido | Retorno compuesto baseline |
|---|---|---:|---:|---:|---:|---:|
| VIX | shock_10 en 4/4 | 2/4 | +0.13 pp | +0.06 pp | +9.01% | +8.58% |
| MSS | mss_filter en 2/4; baseline en 2/4 | 0/4 | −2.61 pp | +1.12 pp | −1.75% | +8.58% |
| Flags | flag_filter en fold 1; flag_standalone en 3/4 | 3/4 | +1.39 pp | +2.83 pp | +14.81% | +8.58% |

Los deltas de drawdown positivos indican que la estrategia elegida tuvo una caída máxima peor que el baseline. Por tanto, aunque flags superó el retorno en tres de cuatro tests, empeoró el drawdown en los cuatro. VIX tuvo una mejora de retorno pequeña y prácticamente neutra en drawdown. MSS no superó el retorno en ningún test y fue seleccionado como baseline en los dos folds finales.

## Lectura por familia

### VIX

El `shock_10` fue elegido en los cuatro entrenamientos. En test superó al baseline en los folds 1 y 4, fue idéntico en el fold 2 y quedó por debajo en el fold 3. El retorno compuesto fue solo 0.43 puntos porcentuales superior al baseline, mientras que el drawdown medio empeoró 0.06 puntos.

Esto no es suficiente para activar el filtro. El resultado sí justifica conservarlo como observación shadow, porque no colapsó fuera de muestra y el impacto medio fue pequeño. Todavía hay que medir si la mejora procede de evitar malas entradas o simplemente de operar menos; el ratio medio de operaciones fue 0.89 frente al baseline.

### MSS

MSS fue elegido por entrenamiento en los dos primeros folds, pero falló en ambos tests: −5.93 pp y −4.53 pp frente al baseline. En los folds 3 y 4 el propio baseline obtuvo mejor puntuación de entrenamiento, por lo que el proceso walk-forward eligió no utilizar MSS. El retorno compuesto de la selección fue −1.75% frente a +8.58% del baseline.

MSS queda descartado como filtro de entradas en esta forma. Puede ser útil como feature diagnóstica, pero no hay evidencia para darle autoridad operativa.

### Flags

El proceso eligió `flag_filter` en el primer fold y `flag_standalone` en los tres siguientes. Superó retorno en tres de cuatro tests y alcanzó 14.81% compuesto frente a 8.58% del baseline. Sin embargo, el drawdown empeoró en los cuatro folds y el promedio de operaciones cayó a 61.9% del baseline.

La ganancia no es una mejora ajustada al riesgo: proviene de una exposición más agresiva y de una selección de operaciones que deja pasar otras entradas. Flags no debe promoverse a filtro live. Puede permanecer como hipótesis de investigación, pero requeriría un stop específico de la bandera, análisis MAE/MFE y más datos no solapados.

## Decisión

| Familia | Decisión |
|---|---|
| VIX | Mantener como `SHADOW_CANDIDATE`; no puede bloquear entradas todavía. |
| MSS | `RESEARCH_ONLY`; no promover. |
| Flags | `RESEARCH_ONLY`; no promover por coste en drawdown. |

Ninguna familia cumplió simultáneamente un criterio mínimo de al menos tres tests con mayor retorno, al menos dos mejoras de drawdown y delta medio de drawdown no positivo. Por ello, **no se cambió `bot.py`, no se modificó `influence_entries`, no se desplegó una nueva revisión y no se autorizaron órdenes**.

## Reproducibilidad

- Motor: `scripts/run_walk_forward_vix_smc_flags.py`
- Analizador: `scripts/analyze_walk_forward_vix_smc_flags.py`
- Resultados por fold: `/home/ubuntu/backtests/walk_forward_vix_smc_flags_2026-08-18.csv`
- Resumen: `/home/ubuntu/backtests/walk_forward_vix_smc_flags_2026-08-18_family_summary.csv`
- Manifiesto: `/home/ubuntu/backtests/walk_forward_vix_smc_flags_2026-08-18_manifest.json`

**Basis:** retorno sobre subyacente, no P&L exacto de opciones. **Time:** 2025-08-18 a 2026-08-19 según fold. **Assumptions:** datos Alpaca IEX 15m, VIXCLS anterior a sesión, 5 bps, sin comisiones, Donchian 10, stop 2.5 ATR. **Sources & confidence:** datos reales y motores previamente auditados; confianza media-baja por proxy de opciones, ocho símbolos y cuatro folds. **Compliance:** This is research and analysis only, not personalized financial advice.
