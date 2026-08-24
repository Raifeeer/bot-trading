# Readiness de promoción de capas shadow — Polaris

**Fecha:** 2026-08-24 UTC  
**Alcance:** setup_confluence, vix_shadow, structure_mtf_shadow y defined_risk_shadow.  
**Estado:** no se cambia producción con este informe.

## Criterio pre-registrado

Una capa shadow solo puede pasar a una promoción controlada en PAPER si cumple simultáneamente: (1) evidencia fuera de muestra con al menos tres folds/ventanas comparables; (2) mejora de retorno neto o reducción de drawdown frente al baseline en la mediana; (3) ausencia de deterioro material de drawdown; (4) costes, slippage y datos point-in-time razonables; (5) valor incremental frente a los motores ya activos, no solo señales coincidentes; (6) muestra suficiente y estabilidad por régimen; y (7) ruta de ejecución reversible que no salte RiskManager, floor, circuit breakers ni validación de cotizaciones.

## Evaluación

| Capa | Evidencia histórica | Evidencia PAPER | Riesgo/ruta | Decisión |
|---|---|---|---|---|
| `setup_confluence` | Con política de régimen mejora retorno solo en la ventana reciente; empeora en selloff y queda igual en lateral. Con `SwingTrend` exacto no supera al baseline en retorno en ninguna ventana. Los filtros reducen drawdown principalmente porque reducen exposición. | Solo observaciones contextuales —1 break-and-retest y 2 BOS en el snapshot auditado—, sin prueba de P&L marginal ni independencia. | Podría actuar como filtro de entradas, pero todavía no tiene evidencia suficiente ni datos intradía/options point-in-time para demostrar valor incremental. | **No promover; mantener shadow.** |
| `vix_shadow` | `shock_10` fue elegido en 4/4 folds; superó retorno en 2/4, empató 1/4 y perdió 1/4. Delta compuesto +0.43 pp frente a baseline, con drawdown medio 0.06 pp peor. El criterio mínimo exigía al menos 3 tests mejores, 2 mejoras de drawdown y delta de drawdown no positivo. | `would_block=0`; usa fallback real a yfinance porque Alpaca no acepta `^VIX`. No se observa bloqueo ni mejora marginal en PAPER. | Es una capa de veto/gate, no un generador de órdenes. Un fallo de proveedor puede cambiar la disponibilidad del índice; debe fallar cerrado para datos inválidos y no inventar VIX. | **No promover a filtro; mantener `SHADOW_CANDIDATE`.** |
| `structure_mtf_shadow` | MSS/estructura no superó al baseline; el walk-forward mostró retorno compuesto −1.75% frente a +8.58% y fue seleccionado como baseline en folds posteriores. | Aporta etiquetas bull/bear/mixed, pero las confirmaciones se solapan con otros motores y no demuestran calidad marginal. | Puede reducir o habilitar exposición, por lo que requiere validación fuerte para no filtrar oportunidades útiles. | **No promover; mantener shadow/contexto.** |
| `defined_risk_shadow` | Matriz de 1,800 combinaciones: el bear call 30DTE fue el candidato más estable, pero no cumplió promoción robusta ni superó claramente el benchmark ajustado a riesgo. | Cinco candidatos bear-call disponibles; bull-put/iron-condor sin estructuras líquidas en el snapshot. | El executor actual envía patas secuencialmente; no hay atomicidad multi-leg garantizada. | **No promover; mantener shadow hasta tener executor atómico y nueva validación.** |

## Hallazgo conjunto

En el snapshot PAPER auditado, las capas intradía confirmadas presentaron solapamiento completo: 16 confirmaciones agregadas correspondieron a 8 símbolos y cada símbolo confirmado perteneció a dos capas. `setup_confluence` aporta contexto, pero no evidencia de una señal independiente. Por tanto, sumar confirmaciones no debe interpretarse como mayor probabilidad de éxito.

## Decisión final

**Ninguna de las capas evaluadas cumple hoy el criterio completo de promoción.** VIX es la más cercana, pero su ventaja es pequeña, no mejora el drawdown y no produjo bloqueos en PAPER. `setup_confluence` puede tener valor defensivo, pero no ha demostrado mejora de retorno frente al motor live exacto y su muestra contextual es demasiado pequeña.

La siguiente prueba adecuada no es activar más capas, sino construir un ledger diario de shadow que registre por símbolo y timestamp: señal de cada capa, régimen, señal live equivalente, si habría pasado RiskManager, resultado forward neto con costes y solapamiento. Para VIX se necesita además una serie point-in-time reproducible y un manejo explícito de fallback. Para defined-risk es obligatorio resolver primero la atomicidad multi-leg.

## Referencias internas

[1]: `current_setup_integration_backtest_2026-08-18.md` — setup_confluence contra política actual y SwingTrend.  
[2]: `walk_forward_vix_smc_flags_2026-08-18.md` — walk-forward VIX, MSS y flags.  
[3]: `shadow_layers_audit_2026-08-19.md` — telemetría y solapamiento PAPER.  
[4]: `defined_risk_options_backtest_2026-08-18.md` — matriz de spreads definidos.  

> Este análisis es investigación experimental en PAPER; no constituye asesoramiento financiero ni garantiza rentabilidad futura.
