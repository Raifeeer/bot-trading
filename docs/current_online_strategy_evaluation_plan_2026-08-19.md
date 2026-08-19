# Evaluación de estrategias online actuales — plan de selección

## Objetivo

Investigar estrategias que están recibiendo atención reciente, convertir solo las que tengan reglas objetivas en skills reutilizables y someterlas a backtests reproducibles. Ninguna estrategia se activará automáticamente por ser popular o por ganar una ventana.

## Selección principal

| Estrategia | Motivo de selección | Estado de datos esperado |
|---|---|---|
| Broken-wing butterfly | Estructura definida, asimétrica y direccional; ha recibido atención reciente y puede ser compatible con spreads. | Potencialmente backtesteable con cuatro patas de la cadena histórica existente. |
| 0DTE/1DTE credit spreads | Alto interés actual, riesgo máximo definido y menor colateral; se estudia como familia, no como promesa de rentabilidad. | Se debe verificar cobertura de expiraciones intradía y bid/ask; si falta, solo gate de datos. |
| Earnings-event debit spread / long straddle proxy | La volatilidad implícita alrededor de resultados y su crush posterior son temas actuales y medibles si hay fechas y cadenas point-in-time. | Requiere earnings dates, IV y bid/ask históricos; puede acabar en REJECT_DATA. |

## Familias no seleccionadas para implementación

| Familia | Motivo |
|---|---|
| Straddles/strangles vendidos sin protección | Riesgo no definido o muy elevado; incompatibles con la autoridad actual de RiskManager. |
| Put ratio spreads y jade lizards sin protección adicional | Exposición de cola que no debe entrar en Polaris sin cobertura definida. |
| Short calendars | Pueden convertirse en naked call/put al vencer la pata corta; no son adecuadas para la primera ronda. |
| 0DTE sin spreads definidos | Gamma, ejecución y riesgo de expiración demasiado altos para una primera implementación. |

## Protocolo común

Para cada familia se creará una skill con fuentes, reglas, riesgos y contrato de datos. El backtest usará solo contratos y barras históricas point-in-time disponibles, comisiones y slippage explícitos, sizing por riesgo máximo, ventanas recientes y periodos separados de selección/prueba. La decisión será `PROMOTE_SHADOW`, `RESEARCH_ONLY` o `REJECT_DATA/REJECT_RISK`.

El modo live se mantiene PAPER, sin cambios de órdenes, hasta que exista evidencia fuera de muestra y una revisión humana de la implementación.
