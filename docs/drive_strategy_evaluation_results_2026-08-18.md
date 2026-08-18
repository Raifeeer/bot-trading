# Evaluación consolidada de estrategias de Drive para Polaris

**Autor:** Manus AI
**Fecha de corte:** 2026-08-18
**Estado de producción:** PAPER, revisión `polaris-bot-00086-n4n`; ninguna estrategia nueva de esta ronda está habilitada para influir en entradas.

## Resumen

Se auditó la carpeta ABACUS de Google Drive y se evaluaron, en orden, las familias que no estaban completamente contempladas por Polaris: Volume Profile, SMC ampliado, Williams %R, filtro VIX, patrones chartistas objetivos, filtros fundamentales swing y gamma walls. Para cada familia se creó o validó una skill, se investigaron sus definiciones y límites, se implementó una versión reproducible cuando los datos lo permitían y se ejecutaron backtests con ventanas históricas y controles comunes.

La conclusión no es que ninguna idea tenga utilidad, sino que **ninguna demostró todavía una mejora suficientemente robusta de profit ajustado a riesgo como para activar nuevas entradas**. VIX queda como candidato shadow preliminar; el flag chartista y MSS quedan como hipótesis de segunda ronda, pero no están conectados al loop live. Gamma walls fue rechazado por falta de datos históricos point-in-time esenciales.

## Matriz de decisión

| Familia | Skill | Backtest | Resultado principal | Decisión |
|---|---|---|---|---|
| Volume Profile | `volume-profile` | 675 combinaciones, 5 ventanas | Menor drawdown en verano/reciente, menor retorno en conjunto | `RESEARCH_ONLY` |
| SMC ampliado | `smc-expanded` | FVG, MSS, OB+sweep y confluencia, 5 ventanas | MSS redujo drawdown; FVG fue inconsistente; OB+sweep tuvo baja cobertura | `RESEARCH_ONLY`; MSS candidato de observación |
| Williams %R | `williams-r` | 90 combinaciones contra RSI y baseline | No superó consistentemente a RSI ni baseline | `RESEARCH_ONLY` |
| VIX filter | `vix-filter` | 13 gates, 5 ventanas, VIX anterior a sesión | Percentil 70 y shock 10% mejoraron retorno medio, con coste/sensibilidad | `SHADOW_CANDIDATE`, sin conexión live |
| Patrones chartistas | `chart-patterns` | 55 celdas, filtros y standalone | Flag mejoró retorno, pero aumentó drawdown ~4.8 pp | `RESEARCH_ONLY`; flag de segunda ronda |
| Fundamental swing | `fundamental-swing` | 25 celdas, snapshots SEC as-of | Todos los filtros redujeron retorno y trades | `RESEARCH_ONLY` |
| Gamma walls | `gamma-walls` | Gate de 5 variantes | Sin OI/gamma/spot/multiplier históricos | `REJECT_DATA` |

## Resultados por familia

### Volume Profile

Usando perfiles RTH de la sesión anterior sobre DayBreakout, el baseline fue superior en primavera, recuperación y periodo completo. Algunos filtros redujeron la pérdida del verano y mejoraron los últimos 30 días, pero los deltas medios fueron negativos: aproximadamente −1.50 pp para POC, −1.52 pp para VAH y −2.50 pp para aceptación VAH+volumen. El perfil se construyó asignando el volumen de cada vela al precio típico, no con transacciones individuales ni agresor comprador/vendedor. No se promueve.

### SMC ampliado

FVG superó al baseline en primavera y recuperación, pero perdió en verano y periodo completo. MSS redujo drawdown y evitó parte de la caída de verano, aunque sacrificó retorno y tuvo cobertura limitada. OB+sweep produjo aproximadamente 3.2 operaciones medias por ventana, insuficiente para inferir ventaja. La confluencia redujo drawdown, pero no superó retorno de forma consistente. No se promueve; MSS puede observarse más adelante con datos MTF reales.

### Williams %R

El cruce de −50 quedó cerca del baseline, pero no mostró información incremental robusta frente a RSI. Los filtros pullback y overbought redujeron mucho la actividad y sacrificaron retorno. Ninguna variante cumplió el criterio de superar al baseline en 8 de 15 celdas y no empeorar drawdown más de 0.25 pp. No se promueve.

### VIX

El VIX se alineó estrictamente con el cierre anterior de VIXCLS de FRED, evitando look-ahead. El percentil 70 tuvo un delta medio de retorno de +2.12 pp y el shock diario 10% +1.69 pp; ambos superaron retorno en 3 de 5 ventanas. El percentil 70 tuvo un coste medio de drawdown de +2.46 pp. Los niveles fijos 15, 20, 25 y 30 no fueron universales; el nivel 15 bloqueó demasiado y los niveles altos casi no cambiaron la exposición.

VIX queda como `SHADOW_CANDIDATE`, no como filtro que pueda bloquear entradas. Antes de promoverlo se necesita walk-forward no solapado, medir oportunidades perdidas y confirmar que la mejora no proviene solo de estar en efectivo. No se obtuvo term structure VIX3M point-in-time fiable.

### Patrones chartistas

Se formalizaron double top/bottom, triangle, flag y head-and-shoulders con pivots confirmados, neckline/valle y breakout con buffer ATR. `flag_standalone` mejoró retorno en 5/5 ventanas con delta medio de +4.32 pp, pero aumentó drawdown medio 4.81 pp. `flag_filter` mejoró 4/5 con delta +2.26 pp y coste de drawdown 4.59 pp. La mejora no es gratuita y la definición es sensible. No se promueve; flag solo merece segunda ronda con walk-forward y stops específicos.

### Filtros fundamentales swing

Se reconstruyeron snapshots de SEC Company Facts por fecha de presentación. Se excluyeron NOK por ausencia de facts us-gaap utilizables y TQQQ por no ser una empresa operativa. Sobre cinco símbolos, el baseline SwingTrend promedió +4.83%; value quality +3.20%, growth quality +1.27%, fundamental rank +2.75% y quality combo +3.20%. Ningún filtro superó al baseline en las cinco ventanas. El menor drawdown se consiguió operando menos, no por una ventaja demostrada. No se promueve.

### Gamma walls

Se creó un módulo con puerta estricta para OI, gamma, spot y multiplicador. Los caches históricos de opciones disponibles solo tienen OHLCV, trade_count y vwap: 73,119 filas del cache defined-risk y 9,799 del cache Wheel. Faltan OI, gamma, spot y multiplier. El gate devolvió `REJECT_DATA` en cinco variantes; no se calculó retorno ni drawdown y no se inventaron valores. La familia queda fuera hasta conseguir snapshots históricos completos.

## Reglas comunes y calidad

Los backtests utilizaron datos reales disponibles, timestamps cerrados, costes y slippage, y separaron retorno del subyacente de P&L exacto de opciones. Se registraron faltantes y se corrigió una inflación contable detectada en Volume Profile antes de interpretar resultados. Se evitó activar estrategias por ganar una sola ventana y se trató como limitación la superposición de `full_recent` con otras ventanas.

Las cifras no son comparables como si todas fueran la misma estrategia: Volume Profile, SMC, Williams, VIX y chart patterns usan proxy de DayBreakout sobre subyacente; fundamentales usa SwingTrend diario; gamma no tuvo datos para estimar rendimiento. No se debe sumar sus retornos ni elegir el mayor ganador sin una segunda ronda común de walk-forward.

## Estado de producción

No se modificó el flujo live para ninguna de estas familias. Las capas previas de setups y spreads definidos siguen en `shadow`, con `influence_entries=false` y `orders_allowed=false`. La revisión `polaris-bot-00086-n4n` permanece en PAPER. No se habilitó VIX, flag, MSS, fundamentales ni gamma para abrir órdenes.

## Próximo orden prudente

La prioridad de investigación posterior sería VIX en shadow controlado, porque fue el único filtro nuevo con mejora preliminar de retorno y cobertura razonable. En segundo lugar, una segunda ronda aislada de flag y MSS con ventanas no solapadas, parámetros congelados en entrenamiento y evaluación posterior. Volume Profile, Williams y fundamentales deberían quedar documentados sin activación. Gamma walls requiere primero un nuevo proveedor de datos, no un nuevo ajuste de parámetros.

**Basis:** backtests sobre subyacente y gates de cobertura; no P&L exacto para opciones salvo los backtests de cadenas separados. **Time:** datos hasta 2026-08-18. **Assumptions:** declarados en cada informe individual. **Sources & confidence:** Alpaca IEX, FRED, SEC, OCC/OIC, Fidelity, StockCharts, Investopedia y literatura académica; confianza media-baja por muestras parciales, proxy de opciones y pocas operaciones en varias familias. **Compliance:** This is research and analysis only, not personalized financial advice.
