# The Wheel: investigación profunda y backtest histórico

**Fecha de corte:** 18 de agosto de 2026.  
**Clasificación:** `RESEARCH_ONLY`; no activa en PAPER ni REAL.  
**Capital principal del experimento:** $100,000.  
**Sensibilidades:** $100 y $1,000.

## Conclusión ejecutiva

The Wheel combina cash-secured puts con covered calls después de una eventual asignación de 100 acciones. El cash-secured put no es ingreso pasivo sin riesgo: OIC lo describe principalmente como una estrategia de adquisición de acciones, neutral a moderadamente alcista, con ganancia máxima limitada a la prima y pérdida potencial sustancial si la acción cae fuertemente.[1] El covered call genera prima pero limita el upside y conserva la exposición a la caída de las acciones.[2] [3]

La ronda usó **barras históricas reales de opciones de Alpaca**, no datos sintéticos: siete subyacentes, 467 contratos seleccionados y 451 con barras, con 9,799 barras diarias entre abril y agosto de 2026. Se probaron cinco escenarios y cinco ventanas recientes. El escenario base terminó positivo en las cinco ventanas, con retorno medio de **+5.33%** y drawdown medio de **−0.35%**, pero solo superó a buy-and-hold en dos de cinco ventanas. En la ventana completa abril–agosto, The Wheel base obtuvo **+12.84%** frente a **+57.99%** de buy-and-hold; en verano, cuando buy-and-hold perdió 14.08%, la Wheel base ganó 6.24%.

El resultado sugiere que The Wheel puede funcionar como una estrategia de recolección de prima y reducción de participación en caídas, pero no demuestra que aumente el profit de forma consistente frente a mantener el subyacente. Con $100, la Wheel no pudo abrir ninguna operación porque un contrato requiere 100 acciones y el colateral mínimo de los símbolos disponibles supera ampliamente ese capital. No se recomienda integrarla todavía en el bot.

## Investigación de la estrategia

### Mecánica

El ciclo correcto es CSP → posible assignment de 100 acciones → CC → posible venta de las acciones → nuevo CSP. El CSP se debe abrir únicamente sobre un activo que el operador aceptaría comprar al strike. El precio neto de adquisición tras assignment es `strike − prima recibida`; esa prima reduce el coste, pero no elimina el riesgo de que el activo continúe cayendo.[1]

El CC debe estar cubierto por 100 acciones libres por contrato. Si la call se asigna, el escritor entrega las acciones al strike; por ello la prima no debe evaluarse separada del P&L de las acciones y del upside perdido.[2] [3]

### Assignment y ejercicio

Las opciones estandarizadas de acciones y ETF son americanas y pueden ejercerse antes del vencimiento. La asignación puede suceder antes de expiration y debe reconciliarse con el broker; no basta con observar si una opción terminó ITM.[7] Las calls ITM cerca de un dividendo importante tienen mayor riesgo de ejercicio temprano; el escritor asignado puede tener que entregar acciones y dividendo.[7] [8]

Alpaca documenta que su nivel 1 incluye venta de covered calls y cash-secured puts. También indica que las asignaciones no llegan por websocket y deben vigilarse mediante polling de actividades no comerciales; si falta buying power para un contrato ITM al vencimiento, el broker puede vender la posición antes de expiry.[9] [10]

### Roll

Un roll no es una extensión gratuita. Es cerrar la opción existente y abrir otra. El backtest registra cada roll como dos patas y aplica costes, pero no convierte una pérdida en ganancia por acumular primas. En producción se necesitarían estados persistentes, idempotencia, cursor de actividades, control de lotes y cálculo de crédito/débito neto.

## Método del backtest

### Datos

| Elemento | Base usada |
|---|---|
| Fuente de subyacentes | OHLCV diario real cacheado de MarketDataFeed/Alpaca-yfinance |
| Fuente de opciones | Barras históricas reales de Alpaca Options API |
| Símbolos | AMD, BB, F, NOK, PLTR, TQQQ y TSLA |
| Periodo | 1 abril–14 agosto de 2026; contratos 21–45 DTE |
| Contratos seleccionados | 467 |
| Contratos con barras | 451 |
| Barras de opciones | 9,799 |
| Capital principal | $100,000 |
| Comisión | $0.65 por contrato y lado |
| Slippage | 2% conservador, 5% base, 10% stress sobre el premium |
| Entrada | Venta al open de la primera barra posterior a la decisión semanal |
| Mark | Close diario de la opción; intrinsic si falta barra, contabilizando `data_gaps` |
| Asignación | ITM al vencimiento; early assignment no observable en las barras y queda como limitación |

La selección busca el contrato disponible más cercano a 21–45 DTE y 5% o 10% OTM. El delta histórico point-in-time no estaba disponible en el inventario usado; por tanto, moneyness es un **proxy declarado**, no delta. El inventario de contratos tampoco entrega una fecha histórica de listing, por lo que el resultado no puede considerarse una reconstrucción perfecta de la cadena disponible en cada fecha de decisión.

### Ventanas y escenarios

| Escenario | Put | Call | Gestión | Capital comprometido |
|---|---:|---:|---|---:|
| Conservador | 10% OTM | 10% OTM | TP 50%, sin roll | 25% máximo |
| Base | 5% OTM | 5% OTM | TP 50%, sin roll | 50% máximo |
| Early profit | 10% OTM | 10% OTM | TP 75%, sin roll | 50% máximo |
| Roll defense | 10% OTM | 10% OTM | TP 50%, roll si prima se duplica | 50% máximo |
| Stress | 5% OTM | 5% OTM | Sin TP, slippage 10% | 75% máximo |

Las ventanas fueron selloff de primavera, recuperación temprana, tendencia de verano, últimos 30 días disponibles y periodo completo abril–agosto. Buy-and-hold representa una referencia equal-weight de los siete subyacentes disponibles; no es la estrategia live de Polaris.

## Resultados con $100,000

| Ventana | Escenario | Retorno | P&L | Max drawdown | Buy-and-hold | Asignaciones | Data gaps |
|---|---|---:|---:|---:|---:|---:|---:|
| Spring selloff | Base | +0.69% | +$694 | −0.62% | +32.99% | 0 | 0 |
| Early recovery | Base | +0.62% | +$617 | −0.06% | +31.03% | 0 | 2 |
| Summer trend | Base | +6.24% | +$6,240 | −0.27% | −14.08% | 1 | 1 |
| Últimos 30 días | Base | +6.27% | +$6,271 | −0.18% | −7.90% | 1 | 6 |
| Full recent | Base | +12.84% | +$12,843 | −0.62% | +57.99% | 1 | 3 |

El escenario base fue positivo en las cinco ventanas y tuvo tres asignaciones de puts agregadas en toda la matriz. Sin embargo, solo superó a buy-and-hold en verano y en los últimos 30 días, periodos donde buy-and-hold fue negativo. Cuando el subyacente subió fuertemente, la Wheel cobró primas, pero dejó mucho upside sobre la mesa.

| Escenario | Retorno medio | Peor retorno | Drawdown medio | Peor drawdown | Ventanas positivas | Supera buy-and-hold |
|---|---:|---:|---:|---:|---:|---:|
| Base | +5.33% | +0.62% | −0.35% | −0.62% | 5/5 | 2/5 |
| Conservador | +0.23% | −0.15% | −0.32% | −0.46% | 3/5 | 2/5 |
| Early profit | +4.70% | +0.35% | −0.28% | −0.38% | 5/5 | 2/5 |
| Roll defense | +2.09% | −0.12% | −0.29% | −0.42% | 4/5 | 2/5 |
| Stress | +0.71% | −0.09% | −5.17% | −8.71% | 4/5 | 2/5 |

El escenario stress tiene 71 `data_gaps`, porque algunas posiciones carecieron de barra de opción y se marcaron con intrinsic. Sus métricas no deben utilizarse para seleccionar parámetros; sirve como alerta de que una política de gestión sin TP puede sufrir caminos de drawdown mucho mayores.

## Sensibilidad de capital

Con **$100**, ningún escenario abrió contratos en ninguna ventana. El resultado fue 0% con cero operaciones. No es un fallo del motor: un CSP requiere poder comprar 100 acciones y el colateral más barato de este universo supera $100.

Con **$1,000**, la actividad fue muy limitada y se concentró en los símbolos de menor precio. En el periodo completo, el mejor resultado fue aproximadamente **+1.68%**, con tres contratos cerrados y sin asignaciones; el buy-and-hold de referencia fue +57.99%. Esto muestra que la Wheel no es compatible con el reto ficticio $100→$200 sobre este universo sin usar margen, spreads de riesgo definido o una estructura distinta a la Wheel clásica. Usar margin cambiaría radicalmente el riesgo y no debe asumirse.

## Decisión de integración en Polaris

La decisión es **mantener The Wheel fuera del loop live**. La skill reutilizable quedó creada y validada en `/home/ubuntu/skills/the-wheel/SKILL.md`, con referencias OCC/OIC, Cboe y Alpaca. La documentación `docs/skills/wheel_skill.md` y `AGENTS.md` deben reflejar que el módulo de código existente no equivale a una Wheel operativa.

Antes de una posible fase PAPER se necesitaría: cadenas y quotes point-in-time con bid/ask, filtro histórico de earnings/dividendos, early assignment, reconciliación idempotente de NTA Alpaca, lotes de 100 acciones, colateral real, covered calls solo contra acciones libres, roll como dos órdenes, persistencia tras reinicios y pruebas walk-forward. No se cambia `wheel.enabled`, no se modifica `influence_entries`, no se relaja el piso ni el RiskManager y no se despliega a Cloud Run.

## Limitaciones y nivel de confianza

La cobertura de opciones es real y mejor que un proxy basado solo en subyacentes, pero no es un backtest institucional de Wheel. Faltan bid/ask históricos, delta histórico, timestamp de listing, early assignment observado, dividendos/earnings point-in-time y una reconstrucción completa del broker. Los fills usan OHLC y slippage paramétrico. La confianza es **media para la mecánica de riesgo y baja-media para el retorno numérico exacto**. La conclusión de que $100 no puede cubrir un contrato del universo tiene confianza alta bajo la regla cash-secured de 100 acciones.

## Referencias

[1] [Options Industry Council / OCC — Cash-Secured Put](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put)

[2] [Options Industry Council / OCC — Covered Call Risks](https://www.optionseducation.org/videolibrary/covered-call-risks)

[3] [Options Industry Council / OCC — Obligations of a Covered Call Writer](https://www.optionseducation.org/videolibrary/obligations-of-a-covered-call-writer)

[4] [Questrade — Wheel Strategy](https://www.questrade.com/learning/wheel-strategy-options)

[5] [Cboe — S&P 500 Volatility Managed PutWrite Index Methodology](https://cdn.cboe.com/api/global/us_indices/governance/PUTVM_Methodology.pdf)

[6] [Feldman y Roy — The Cash-secured PutWrite Strategy and Performance of Related Benchmark Indexes](https://www.researchgate.net/publication/247906423_The_Cash-secured_PutWrite_Strategy_and_Performance_of_Related_Benchmark_Indexes)

[7] [Options Industry Council / OCC — Exercising Options](https://www.optionseducation.org/optionsoverview/exercising-options)

[8] [Options Industry Council / OCC — Options Exercise FAQ](https://www.optionseducation.org/referencelibrary/faq/options-exercise)

[9] [Alpaca — Options Trading](https://docs.alpaca.markets/us/docs/options-trading)

[10] [Alpaca — Options Trading Overview](https://docs.alpaca.markets/us/docs/options-trading-overview)

**Disclosure:** este documento es investigación y análisis únicamente, no asesoría financiera personalizada. Los resultados son experimentales y no garantizan rentabilidad.
