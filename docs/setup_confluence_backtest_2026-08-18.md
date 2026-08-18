# Informe de backtest de la capa completa de setups

**Fecha de ejecución:** 18 de agosto de 2026 UTC. **Autor:** Manus AI. **Estado:** investigación experimental; no constituye asesoría financiera ni una validación de rentabilidad real. La cuenta de Polaris permanece en **PAPER** y la capa de setups permanece en `shadow`, sin autoridad para enviar órdenes.

## Resumen ejecutivo

Se ejecutó una matriz reproducible de los doce setups extraídos del PDF `TRADING SETUP.pdf`: `key_level`, `break_and_retest`, `order_block`, `bos`, `choch`, `liquidity_sweep`, `ema_cross`, `ema_cloud`, `vwap`, `volume_proxy`, `fibonacci_ote` y `trendline_channel`. El motor utiliza exclusivamente barras disponibles hasta la barra cerrada de decisión, aplica la posición a la siguiente variación de cierre y descuenta 5 puntos básicos por unidad de cambio de posición en los escenarios de setups. El experimento es un **proxy direccional del subyacente**, no un backtest de spreads de opciones, fills bid/ask, asignación, latencia ni disponibilidad histórica de cadenas.

El resultado no respalda promover la capa como estrategia autónoma ni habilitar `influence_entries`. Frente al benchmark de mantener exposición alcista, `setup_moderate` y `setup_strict` redujeron el drawdown en las cuatro ventanas, pero solo superaron el retorno del benchmark en la ventana `latest_30d`; el benchmark tuvo mayor retorno en las otras tres ventanas. La reducción de drawdown es informativa, pero no basta para cambiar la lógica de entradas de opciones: la capa debe continuar como observabilidad shadow y, como máximo, pasar a un filtro PAPER después de walk-forward, sensibilidad, A/B emparejado con el motor real y revisión humana.

## Datos y cobertura

La matriz usa el universo reto documentado de ocho símbolos. En la ejecución final se utilizaron siete históricos cacheados (`PLTR`, `F`, `TSLA`, `AMD`, `NOK`, `BB`, `TQQQ`); `SOFI` quedó fuera porque los proveedores disponibles devolvieron una respuesta vacía o fueron bloqueados por rate limiting. No se sustituyó con datos sintéticos. Este faltante está registrado en el manifiesto, por lo que los resultados finales no deben presentarse como cobertura completa de los ocho tickers.

| Elemento | Especificación |
|---|---|
| Fuente | Histórico real descargado por `MarketDataFeed`; cache local en `backtests/setup_history/*.pkl` |
| Universo esperado | `SOFI`, `PLTR`, `F`, `TSLA`, `AMD`, `NOK`, `BB`, `TQQQ` |
| Universo utilizado en la corrida final | 7 símbolos; `SOFI` faltante y explícitamente reportado |
| Ventanas | lateral sep–dic 2025; selloff ene–abr 2026; reciente abr–ago 2026; últimos 30 días de la ventana disponible |
| Escenarios | `buy_hold`, `setup_moderate`, `setup_strict` |
| Decisión | Solo barras hasta `t`; retorno aplicado a `t+1` |
| Coste | 5 bps por unidad de cambio de posición en los escenarios de setups |
| Persistencia | CSV de métricas, CSV de dirección, CSV de actividad por componente y manifiesto JSON |

## Resultados agregados

Los resultados son retornos porcentuales del proxy de subyacente y drawdown peak-to-trough. Los valores no representan P&L de opciones ni una expectativa de rentabilidad futura.

| Ventana | Escenario | Retorno | Delta vs. buy-and-hold | Drawdown | Profit factor | Señales | Cambios de posición |
|---|---|---:|---:|---:|---:|---:|---:|
| Lateral 2025 | buy_hold | 25.9695% | — | −17.2397% | 1.4916 | 588 | 0 |
| Lateral 2025 | setup_moderate | 0.3597% | −25.6098 pp | −10.5601% | 1.0272 | 259 | 204 |
| Lateral 2025 | setup_strict | −3.1216% | −29.0911 pp | −11.9175% | 0.9070 | 221 | 181 |
| Selloff 2026 | buy_hold | 22.9870% | — | −16.0482% | 1.4116 | 567 | 0 |
| Selloff 2026 | setup_moderate | 5.1687% | −17.8183 pp | −7.0323% | 1.1956 | 273 | 169 |
| Selloff 2026 | setup_strict | 4.4494% | −18.5376 pp | −7.3239% | 1.1861 | 243 | 147 |
| Reciente 2026 | buy_hold | 61.1543% | — | −25.4978% | 1.6352 | 651 | 0 |
| Reciente 2026 | setup_moderate | 15.1953% | −45.9590 pp | −14.3550% | 1.3683 | 290 | 217 |
| Reciente 2026 | setup_strict | 18.1615% | −42.9928 pp | −10.4369% | 1.4968 | 254 | 188 |
| Últimos 30 días | buy_hold | −4.7056% | — | −20.1163% | 0.9144 | 217 | 0 |
| Últimos 30 días | setup_moderate | −2.8449% | +1.8607 pp | −8.6640% | 0.8350 | 78 | 65 |
| Últimos 30 días | setup_strict | −1.4434% | +3.2622 pp | −7.5748% | 0.9186 | 66 | 50 |

La lectura principal es consistente con la política de no sobreajuste: **la capa sacrifica retorno en tres ventanas a cambio de menor drawdown y solo mejora al benchmark en la última ventana**, donde ambos resultados son negativos. Esto es una hipótesis de control de exposición, no evidencia suficiente de alfa. El escenario estricto tampoco domina al moderado: mejora el retorno en la ventana reciente y en los últimos 30 días, pero empeora el retorno en la lateral y en el selloff frente al moderado.

## Cobertura de los doce componentes

La actividad siguiente agrega las cuatro ventanas en `setup_moderate`. `directional_rate_pct` es la fracción de evaluaciones con dirección bull o bear; `active_rate_pct` cuenta estados que el arnés considera candidatos o confirmaciones. `trendline_channel` puede tener dirección contextual, pero no se contabiliza como activo porque su estado actual es `context`; esto evita presentarlo como una señal de entrada confirmada.

| Setup | Evaluaciones | Bull | Bear | Neutral | Activo | Tasa direccional |
|---|---:|---:|---:|---:|---:|---:|
| `vwap` | 8,344 | 3,808 | 2,733 | 1,803 | 6,541 | 78.39% |
| `ema_cross` | 8,344 | 3,285 | 1,964 | 3,095 | 5,249 | 62.91% |
| `volume_proxy` | 8,344 | 2,106 | 1,960 | 4,278 | 4,066 | 48.73% |
| `ema_cloud` | 8,344 | 2,846 | 1,047 | 4,451 | 3,893 | 46.66% |
| `bos` | 8,344 | 1,935 | 889 | 5,520 | 2,824 | 33.84% |
| `fibonacci_ote` | 8,344 | 1,813 | 966 | 5,565 | 2,779 | 33.31% |
| `break_and_retest` | 8,344 | 940 | 401 | 7,003 | 1,341 | 16.07% |
| `key_level` | 8,344 | 764 | 508 | 7,072 | 1,272 | 15.24% |
| `order_block` | 8,344 | 582 | 686 | 7,076 | 1,268 | 15.20% |
| `choch` | 8,344 | 456 | 377 | 7,511 | 833 | 9.98% |
| `liquidity_sweep` | 8,344 | 163 | 399 | 7,782 | 562 | 6.74% |
| `trendline_channel` | 8,344 | 2,847 | 1,642 | 3,855 | 0 | 53.80% |

El componente `key_level` fue corregido durante esta ronda. La versión anterior exigía simultáneamente proximidad al nivel y una distancia superior al umbral, por lo que en la práctica tendía a devolver neutral. La versión actual congela niveles previos y rolling, y reconoce ruptura cerrada o sweep/reclaim con dirección; la regresión determinista confirma una ruptura alcista. El cambio no convierte Key Level en autoridad de ejecución.

## Decisión operativa

La clasificación del resultado es **`RESEARCH_ONLY`**. La capa queda conectada al loop en `bot.py` como `setup_observations`, con timing `setups_s`, conteos por setup y observaciones por símbolo publicables a Firestore. La configuración mantiene `mode: shadow` e `influence_entries: false`. Aunque se haya configurado accidentalmente `influence_entries: true`, el loop registra una advertencia y continúa bloqueando la promoción; el `RiskManager`, el piso de equity, los circuit breakers y las validaciones de opciones siguen siendo la autoridad final.

No se recomienda ejecutar todavía `run_ab_comparison.py` como si la capa de setups fuera compatible con el motor genérico de opciones: ese arnés conoce `run_scenario` y no evalúa directamente `analyze_setup_confluence`. El siguiente A/B debe añadir un puente explícito que use el mismo dataset y las mismas ventanas, compare el baseline regime-aware contra una variante filtrada por setups, y mida primero el subyacente antes de trasladar cualquier conclusión a spreads. Ninguna mejora de retorno de una ventana ni la meta ficticia `$100 → $200` justifica habilitar entradas.

## Reproducción

```bash
cd /home/ubuntu/bot-trading
export PYTHONPATH="$PWD"
python3 scripts/run_setup_backtests.py
python3 scripts/analyze_setup_backtests.py
python3 -m unittest discover -s tests -v
ruff check . --select F,B,E9
```

Los artefactos producidos son el [CSV de métricas](../backtests/setup_confluence_backtests_2026-08-18.csv), el [CSV de dirección](../backtests/setup_confluence_direction_counts_2026-08-18.csv), el [CSV de actividad por componente](../backtests/setup_confluence_component_activity_2026-08-18.csv), el [análisis comparativo](../backtests/setup_confluence_analysis_2026-08-18_comparison.csv), el [resumen de componentes](../backtests/setup_confluence_analysis_2026-08-18_component_summary.csv) y el [manifiesto](../backtests/setup_confluence_backtests_2026-08-18.json). El manifiesto registra el universo esperado, el universo utilizado y el ticker faltante.

## Referencias

[1]: ../backtests/setup_confluence_backtests_2026-08-18.csv "Matriz de resultados de setup confluence"
[2]: ../backtests/setup_confluence_direction_counts_2026-08-18.csv "Conteos direccionales por ventana"
[3]: ../backtests/setup_confluence_component_activity_2026-08-18.csv "Actividad de cada componente"
[4]: ../backtests/setup_confluence_backtests_2026-08-18.json "Manifiesto de datos y supuestos"
[5]: ../strategies/setup_confluence.py "Motor puro de confluencia de setups"
[6]: ../docs/skills/backtest_skill.md "Metodología de backtesting de Polaris"
[7]: /home/ubuntu/skills/trading-setups/SKILL.md "Skill local de formalización de setups"


## Verificación final de producción

La primera revisión `polaris-bot-00081-6ns` evaluó y guardó las observaciones localmente, pero una comprobación directa de Firestore detectó que el payload no incluía `setup_observations`. El defecto se corrigió con el commit `0308314`, añadiendo explícitamente el campo al snapshot; no se modificaron las puertas de riesgo ni el modo PAPER.

La revisión final `polaris-bot-00083-f7s` quedó activa al 100% del tráfico en Cloud Run. Se observaron tres ciclos consecutivos con `Tick OK`, escritura confirmada en Firestore y el nuevo campo visible en `CYCLE TIMING`:

| Ciclo | Total | `setups_s` | Resultado |
|---:|---:|---:|---|
| 1 | 4.207 s | 0.236 s | Firestore escrito; equity 99,288.65; 0 posiciones |
| 2 | 0.722 s | 0.233 s | Firestore escrito; 0 órdenes; `same_bar_context` |
| 3 | 0.663 s | 0.235 s | Firestore escrito; 0 órdenes; `same_bar_context` |

La lectura autenticada de `polaris/2026-08-18` confirmó `trading_mode=PAPER`, `setup_observations` presente, `mode=shadow`, `influence_entries=false`, ocho símbolos, cero posiciones y cero órdenes. El bot está operativo y monitoreando, pero las entradas permanecen bloqueadas correctamente porque equity 99,288.65 está por debajo del floor 99,900; por eso la ausencia de operaciones debe clasificarse como `HEALTHY_BLOCKED`, no como fallo del motor shadow.
