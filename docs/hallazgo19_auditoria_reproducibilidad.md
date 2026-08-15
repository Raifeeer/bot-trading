# Hallazgo 19 — Auditoría de reproducibilidad del motor de backtesting

**Fecha:** 15 de agosto de 2026  
**Repositorio:** `Raifeeer/bot-trading`  
**Estado:** corregido parcialmente y pendiente de regenerar la matriz completa; no desplegar cambios de backtesting en producción.

## Resumen

El artefacto histórico publicado en Firestore (`polaris/backtest`) declara que S51 alcanzó 92.5% con 61 trades. Al reproducir S51 en el motor actual, se encontró que el escenario estaba definido como `motor="hold"`, pero el código genérico abría una sola posición y no coincidía con el benchmark semanal equally weighted descrito en la documentación. S51 fue corregido para usar `hold_weekly`.

La primera ejecución reproducible tras la corrección produjo **$103.60 (+3.6%)**, 105 trades, 47% de aciertos y drawdown máximo de -10.2% en una ventana móvil de 90 días descargada desde yfinance el 15 de agosto de 2026. Por tanto, el resultado histórico de +92.5% no es reproducible con el motor corregido y no debe usarse para seleccionar una estrategia.

## Cambios auditados

| Hallazgo | Corrección |
|---|---|
| S51 usaba `hold` pese a documentarse como hold semanal equally weighted. | S51 ahora usa `hold_weekly`. |
| S75/S76 declaraban `cheap_min_net`, pero `run_scenario` solo consumía `min_net`. | El motor consume `min_net` y, si no existe, `cheap_min_net`. La unidad es USD por contrato. |
| `stress_test.py` tenía Ruff B023 en la lambda que capturaba `real_hour`. | La lambda ahora fija el valor mediante argumento por defecto. |
| El directorio local `/home/ubuntu/backtests/` no contiene resultados persistentes al iniciar la sesión. | Los resultados deben regenerarse, guardarse como artefactos y versionarse o persistirse fuera de la sandbox. |

## Smoke tests reproducibles

Comando base:

```bash
export DATA_PROVIDER=yfinance
export PYTHONPATH=/home/ubuntu/bot-trading
python3 loop_backtests.py --scenario S51
python3 loop_backtests.py --scenario S75
python3 loop_backtests.py --scenario S76
```

| Escenario | Motor | Equity final | Retorno | Trades | Win rate | Max DD |
|---|---|---:|---:|---:|---:|---:|
| S51 | `hold_weekly` | $103.60 | +3.6% | 105 | 47% | -10.2% |
| S75 | `regime_aware` | $67.12 | -32.9% | 10 | 0% | -32.9% |
| S76 | `regime_aware` | $93.43 | -6.6% | 2 | 0% | -4.0% |

## Límites de interpretación

La descarga usa yfinance y el motor valora opciones con Black–Scholes, volatilidad realizada histórica y margen `MARGIN_MULT=1.2`; no son cadenas de opciones point-in-time. La ventana móvil actual tampoco es comparable automáticamente con una ventana histórica fija. Todavía deben incorporarse slippage, comisiones de entrada/salida, disponibilidad real de strikes, filtros anti-look-ahead y validación walk-forward.

El filtro anti-earnings de producción consulta un calendario actual y no es point-in-time. No se debe tratar como información histórica válida sin una fuente archivada por fecha.

## Siguiente paso obligatorio

Regenerar S1–S89 en una ejecución fechada, producir CSV de equity y trades, comparar resultados out-of-sample y ejecutar estrés E1–E5. No ajustar la estrategia para perseguir $100→$200 a partir de esta única muestra.
