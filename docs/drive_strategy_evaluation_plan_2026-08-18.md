# Plan de evaluación secuencial de estrategias de Drive

**Fecha de corte:** 2026-08-18. **Objetivo:** probar de forma disciplinada las familias que aparecen en ABACUS y que hoy no son parte de la ruta live de Polaris, sin activar órdenes por resultados aislados.

## Criterio común para todas las familias

Cada familia seguirá la misma secuencia: investigar fuentes primarias y el documento de Drive; crear o actualizar una skill con reglas objetivas, limitaciones y contrato de datos; implementar un motor puro o adaptador shadow; comprobar anti-look-ahead y disponibilidad histórica; ejecutar escenarios alcista, bajista, lateral y reciente, con ventanas in-sample/out-of-sample cuando sea posible; comparar con el baseline actual; medir retorno, drawdown, volatilidad, win rate, profit factor, número de señales, costes, slippage y cobertura; realizar sensibilidad de parámetros; y decidir `PROMOTE_SHADOW`, `RESEARCH_ONLY` o `REJECT_DATA`.

Las estrategias descartadas quedan fuera del código operativo. Las candidatas positivas solo podrán entrar primero como shadow. La promoción a filtro PAPER requerirá walk-forward, revisión humana, evidencia de datos suficientes y preservación de RiskManager, floor, circuit breakers y validación de cotizaciones.

## Orden de familias

| Orden | Familia | Fuente Drive | Datos mínimos | Hipótesis | Riesgo de investigación |
|---:|---|---|---|---|---|
| 1 | Volume Profile: VPOC/HVN/LVN | TRADING PLAN, TRADING SETUP, Volatilidad y Volumen | OHLCV intradía con sesión RTH/ETH | Zonas de volumen pueden mejorar entradas, stops y objetivos | El perfil depende de la sesión y del feed; no confundir proxy con order flow |
| 2 | SMC ampliado: Breaker, Killer Block, FVG, OB fresco/1:2 | Smart Money Concepts, Supply & Demand, Market Structure | OHLCV MTF cerrado | La estructura/liquidez adicional puede filtrar falsos breakouts | Definiciones visuales ambiguas y riesgo de sobreajuste |
| 3 | Williams %R 14 | Williams %R, Introducción al Análisis Técnico | OHLCV | Puede aportar confirmación distinta a RSI | Alta correlación con osciladores existentes |
| 4 | Filtro VIX/volatilidad de índice | Volatilidad y Volumen, Plan de Juego | VIX histórico point-in-time y OHLCV | Evitar entradas cuando la volatilidad sistémica es extrema | VIX es contexto, no señal; riesgo de usar datos no disponibles al momento |
| 5 | Patrones chartistas objetivos | Tendencias, Soportes/Resistencias, Risk-Reward | OHLCV MTF | Double top/bottom o triángulos con reglas fijas pueden filtrar entradas | Reconocimiento subjetivo y múltiples grados de libertad |
| 6 | Filtro fundamental swing | Price Target, ventas, P/E, Conference Calls | Fundamentales point-in-time, filings y calendario | Filtrar activos con salud/crecimiento antes de SwingTrend | Revisiones históricas, rezago de reportes y look-ahead |
| 7 | Gamma walls y niveles de opciones | Plan de Juego 13/11/2024 | OI, gamma, IV y cadenas point-in-time | Los niveles de posicionamiento pueden actuar como contexto | Falta de histórico verificable; plan fechado, no estrategia completa |

## Baseline y decisiones

El baseline primario será la configuración actual `regime_hold_cash`/regime-aware y, cuando la temporalidad lo permita, el motor live `SwingTrend`, `DayMomentum` o `DayBreakout`. La comparación debe usar los mismos símbolos, datos, fechas, costes y reglas de ejecución. No se usará el objetivo ficticio $100→$200 como criterio de selección.

Si una fuente histórica no permite una prueba válida, se marcará `REJECT_DATA` o `RESEARCH_ONLY`; no se rellenarán faltantes con datos simulados ni se presentará una proxy como P&L real de opciones.

## Estado operativo

Todas las familias permanecen fuera del executor. La configuración de producción sigue en PAPER; `setups.influence_entries=false` y `defined_risk_shadow.orders_allowed=false`. Este plan no habilita filtros ni nuevas órdenes.
