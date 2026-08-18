# Backtests de estrategias de opciones de riesgo definido

**Fecha de corte:** 18 de agosto de 2026.  
**Estado:** `RESEARCH_ONLY`; ninguna estrategia fue activada en Polaris PAPER.  
**Capital principal:** $100,000.  
**Universo:** AMD, BB, F, NOK, PLTR, TQQQ y TSLA.

## Conclusión

Se ejecutó una matriz de **1,800 combinaciones** sobre diez familias de estructuras, tres objetivos de DTE, dos anchos de moneyness, tres políticas de gestión, dos modos de régimen y cinco ventanas históricas. La matriz incluyó bull call debit spreads, bear put debit spreads, bull put credit spreads, bear call credit spreads, iron condors, call butterflies, call calendars, put calendars, call diagonals y put diagonals.

La configuración con el mayor retorno en el periodo completo abril–agosto fue un **bull call debit spread de 45 DTE, 5% de ancho, gestión conservadora y régimen gated**, con +4.62% y drawdown −0.77%. Sin embargo, tuvo 37 `data_gaps`, por lo que no es candidata de promoción. El candidato más estable con los filtros aplicados fue un **bear call credit spread de 30 DTE, 10% de moneyness, gestión conservadora y régimen gated**: retorno medio +0.46% en cinco ventanas, cuatro ventanas positivas, peor ventana 0.00%, drawdown medio −0.10% y 12 data gaps. Tampoco supera buy-and-hold en el periodo completo y no se considera listo para PAPER.

La conclusión operativa es que los spreads de riesgo definido son más adecuados que The Wheel para el tamaño de capital ficticio, porque limitan el riesgo por contrato y no exigen comprar 100 acciones. Pero en esta muestra no aparece un ganador que aumente profits de forma consistente frente al baseline o buy-and-hold. Se requiere una segunda ronda con datos de bid/ask point-in-time y walk-forward antes de decidir.

## Metodología

### Datos y cobertura

| Elemento | Valor |
|---|---|
| Fuente de opciones | Alpaca Historical Options API, barras OHLC diarias |
| Contratos seleccionados | 3,626 |
| Contratos con barras | 3,448 |
| Barras de opciones | 73,119 |
| Periodo | 1 abril–7 agosto de 2026 |
| Decisiones | Viernes, con precio del subyacente cerrado |
| Fill de entrada | Open de la primera barra de opción posterior a la decisión, máximo cinco días calendario |
| Mark de salida | Close diario; intrinsic cuando falta barra, contabilizando `data_gaps` |
| Comisión | $0.65 por contrato y lado |
| Slippage | 2% conservador, 5% base, 10% agresivo |
| Riesgo por operación | 0.5%, 1% o 2% del equity |

El histórico de contratos no expone timestamp de listing ni pertenencia de la cadena as-of; por eso la selección de strikes es un proxy de moneyness, no delta histórico point-in-time. No se usaron datos sintéticos, pero el P&L no debe interpretarse como una reconstrucción institucional exacta.

### Estrategias y parámetros

| Familia | Estructura probada | Riesgo teórico |
|---|---|---|
| Debit spread alcista | Compra call y vende call superior | Débito pagado |
| Debit spread bajista | Compra put y vende put inferior | Débito pagado |
| Credit spread alcista | Vende put y compra put inferior | Ancho menos crédito |
| Credit spread bajista | Vende call y compra call superior | Ancho menos crédito |
| Iron condor | Bull put spread + bear call spread | Ancho del ala menos crédito |
| Butterfly | Call butterfly de débito | Débito pagado; zona rentable estrecha |
| Calendar | Compra vencimiento lejano y vende vencimiento cercano | Débito; valoración proxy |
| Diagonal | Calendar con strike distinto | Débito; valoración proxy |

Se probaron objetivos de 14, 30 y 45 DTE; anchos de 5% y 10%; gestión conservadora, base y agresiva; y régimen `gated` o `neutral_ok`. `gated` exige bull para estructuras alcistas, bear para bajistas y neutral para condors/butterflies. `neutral_ok` permite estructuras direccionales también en régimen neutral.

## Resultados principales

### Ranking del periodo completo

| Estrategia | DTE | Moneyness | Gestión | Régimen | Retorno | Drawdown | Operaciones cerradas | Data gaps |
|---|---:|---:|---|---|---:|---:|---:|---:|
| Bull call debit | 45 | 5% | Conservadora | Gated | +4.62% | −0.77% | 18 | 37 |
| Bull put credit | 45 | 5% | Base | Neutral OK | +2.19% | −2.26% | 24 | 130 |
| Bear call credit | 45 | 10% | Conservadora | Neutral OK | +2.11% | −1.13% | 17 | 26 |
| Bear call credit | 14 | 10% | Conservadora | Neutral OK | +1.02% | −0.44% | 26 | 8 |
| Put diagonal | 14 | 10% | Base | Gated | +0.64% | −0.28% | 17 | 1 |
| Iron condor | 45 | 5% | Conservadora | Gated | +0.59% | −0.08% | 6 | 14 |

El buy-and-hold equal-weight de los siete subyacentes obtuvo +57.99% en la ventana completa. Ninguna de las configuraciones principales superó ese resultado. La comparación no significa que buy-and-hold sea preferible para todos los objetivos: una estrategia de opciones puede buscar reducir drawdown o limitar riesgo, pero el retorno debe analizarse junto con esas características.

### Candidato más estable

El **bear call credit 30 DTE, 10%, conservadora, gated** tuvo estos resultados por ventana:

| Ventana | Retorno | Drawdown | Operaciones | Resultado |
|---|---:|---:|---:|---|
| Spring selloff | 0.00% | 0.00% | 0 | Sin señal bear válida |
| Early recovery | +0.01% | 0.00% | 1 | Casi neutral |
| Summer trend | +0.88% | −0.16% | 9 | Positivo |
| Últimos 30 días | +0.50% | −0.16% | 5 | Positivo |
| Full recent | +0.89% | −0.16% | 10 | Positivo |

Fue positivo o neutral en las cinco ventanas, pero su rendimiento es pequeño. La ausencia de pérdidas en esta muestra no demuestra que no pueda perder; refleja también una muestra corta y un filtro de régimen que abrió pocas operaciones.

### Rendimiento por familia

| Familia | Retorno medio de todas las variantes | Peor retorno | Drawdown medio | Ventanas positivas agregadas |
|---|---:|---:|---:|---:|
| Bull put credit | −0.46% | −7.15% | −1.45% | 92 de 180 |
| Iron condor | −0.49% | −3.86% | −0.61% | 42 de 180 |
| Put diagonal | −0.49% | −6.55% | −1.01% | 66 de 180 |
| Bear call credit | −1.58% | −21.40% | −2.41% | 55 de 180 |
| Call diagonal | −1.64% | −12.66% | −1.71% | 22 de 180 |
| Bear put debit | −2.55% | −21.64% | −2.78% | 13 de 180 |
| Bull call debit | −2.60% | −24.08% | −2.95% | 32 de 180 |
| Put calendar | −2.62% | −13.32% | −3.38% | 8 de 180 |
| Call calendar | −4.45% | −24.59% | −4.39% | 0 de 180 |
| Call butterfly | −5.91% | −33.90% | −6.26% | 2 de 180 |

Esta tabla mezcla políticas y ventanas; no se debe usar para seleccionar automáticamente. Sirve para observar que las estructuras de crédito, especialmente bear calls y bull puts, fueron más resistentes que las butterflies y calendars bajo este proxy de datos.

## Lectura sencilla

El mayor profit puntual provino de un bull call spread de 45 DTE, pero apareció con muchos faltantes de barras y no fue estable en todas las ventanas. El mejor candidato defensivo fue un bear call spread conservador, pero produjo menos de 1% en la ventana completa y no superó a buy-and-hold.

Los iron condors mostraron drawdown bajo en algunas configuraciones, pero pocas operaciones y retornos modestos. Las butterflies y calendars no funcionaron bien con estos datos y reglas; además son muy sensibles a la volatilidad implícita y a la calidad del mark, por lo que no se deben descartar de manera definitiva usando solo esta ronda.

## Decisión para Polaris

No se activa ninguna estrategia en `bot.py`, `config.yaml`, Cloud Run ni PAPER. La matriz queda como investigación. Los siguientes candidatos para una segunda ronda serían:

1. `bear_call_credit`, 30 DTE, 10% OTM, gestión conservadora, régimen gated.
2. `iron_condor`, 45 DTE, 5% OTM, gestión conservadora, únicamente como prueba de régimen neutral.
3. `put_diagonal`, 14 DTE, 10% OTM, gestión conservadora o base, solo después de validar la valoración temporal.
4. `bull_call_debit`, 45 DTE, 5% OTM, gestión conservadora, excluido provisionalmente hasta resolver los `data_gaps`.

La segunda ronda debe utilizar bid/ask históricos, delta/IV point-in-time, cadenas completas, earnings/dividendos as-of y un walk-forward con un periodo de entrenamiento separado del periodo de evaluación. No se debe promover por ganar el periodo full_recent.

## Fuentes y límites

Las definiciones de riesgo de spreads se alinean con las descripciones educativas de OIC/OCC para bull call, bear put, bull put, bear call e iron condor.[1] [2] [3] [4] [5] La mecánica de opciones y assignment se contrasta con OCC y Alpaca.[6] [7]

La confianza es **media-baja para los retornos numéricos exactos** por ausencia de bid/ask y delta point-in-time, y **media para la comparación relativa de capital y riesgo máximo**. Los calendarios y diagonales tienen una valoración especialmente aproximada.

## Referencias

[1] [OIC — Bull Call Spread](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread)

[2] [OIC — Bear Put Spread](https://www.optionseducation.org/strategies/all-strategies/bear-put-spread)

[3] [OIC — Bull Put Spread](https://www.optionseducation.org/strategies/all-strategies/bull-put-spread)

[4] [OIC — Bear Call Spread](https://www.optionseducation.org/strategies/all-strategies/bear-call-spread)

[5] [OIC — Iron Condor](https://www.optionseducation.org/strategies/all-strategies/iron-condor)

[6] [OIC — Exercising Options](https://www.optionseducation.org/optionsoverview/exercising-options)

[7] [Alpaca — Options Trading](https://docs.alpaca.markets/us/docs/options-trading)

**Disclosure:** Este documento es investigación y análisis únicamente, no asesoría financiera personalizada. Las cifras son experimentales y no garantizan rentabilidad.
