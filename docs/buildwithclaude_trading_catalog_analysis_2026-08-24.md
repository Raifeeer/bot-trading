# Análisis del catálogo de plugins de trading de BuildWithClaude

**Fecha de consulta:** 2026-08-24 UTC  
**Catálogo:** [BuildWithClaude — búsqueda Trading][1]  
**Autor:** Manus AI  
**Alcance:** evaluar utilidad potencial para Polaris, no instalar ni conceder acceso a broker.

## Resumen ejecutivo

El catálogo es útil como índice de ideas y herramientas, pero no constituye una validación de calidad, seguridad ni rentabilidad. Los candidatos con mejor encaje para Polaris son componentes de validación temporal, backtesting, análisis de riesgo, calidad de datos y documentación. Los plugins de ejecución, brokers, DEX, wallets, transferencias y MCP con capacidad de trading deben quedar fuera del runtime del bot.

La recomendación es **no instalar un marketplace completo dentro de Polaris**. Si se toma algo, debe copiarse o adaptarse de forma selectiva, con revisión de código, dependencias fijadas, sandbox sin secretos, datos point-in-time y tests reproducibles. La arquitectura de Polaris ya tiene RiskManager, floor, circuit breakers, validación de cotizaciones y un executor PAPER; sustituirlos por componentes externos aumentaría el riesgo y dificultaría la auditoría.

## Candidatos revisados

| Candidato | Qué ofrece | Encaje | Decisión |
|---|---|---|---|
| [AGIPro claude-trading-skills][2] | 67 skills de trading, DeFi y finanzas cuantitativas; incluye walk-forward, riesgo, microestructura, slippage, opciones y también ejecución DEX/servicios crypto. | Alto para investigación si se seleccionan solo skills offline. | Auditar skill por skill; no instalar ejecución. |
| [Trading Experiment][3] | Genera estrategias crypto, ejecuta backtests con split 70/30, detecta sobreajuste y muta estrategias usando un servidor MCP. | Medio para laboratorio aislado; bajo para Polaris por orientación crypto y generación dinámica de código. | Usarlo como referencia o sandbox independiente. |
| [Finance Skills][4] | Skills de matemática, riesgo, datos, compliance y trading operations. `trading-operations` contiene 9 skills de lifecycle, pre/post-trade, conectividad, margen y riesgo operacional. | Medio-alto como documentación y checklist; no es un executor. | Extraer conceptos útiles, revisar licencia y no asumir compatibilidad regulatoria automática. |
| [Trading Indicator Plugins][5] | Indicadores Pine, NinjaScript y Tradovate; contexto declarado de futuros /ES y /NQ a 5 minutos. | Bajo para el runtime Python/Alpaca de Polaris; puede servir para traducir ideas. | Solo referencia de indicadores. |
| [Kisune][6] | 4 skills de análisis, investigación, patrones y traducción de estrategias. | Medio para análisis conceptual; muestra muy pequeña y poca evidencia cuantitativa. | No prioritario. |
| [Trading broker integration de Daodan][7] | Patrones y plugins para Interactive Brokers y MetaTrader 5. | Bajo para Alpaca; conceptos de lifecycle sí son aprovechables. | No conectar ni reemplazar el executor. |
| [Skills Registry][8] | Incluye un plugin descrito como filtros/gates de trading. | Potencial medio, pero la página concreta no pudo extraerse y tiene poca popularidad. | Revisar archivos exactos antes de usarlo. |

## Verificación técnica y riesgos

### AGIPro

El manifest declara un único plugin `trading-skills`, versión 1.0.0, con 67 skills. La parte más reutilizable para Polaris es `walk-forward-validation`, que describe rolling/expanding windows, purging, embargo, CPCV, Deflated Sharpe y PBO. La skill de `risk-management` contiene jerarquías de supervivencia, límites de drawdown, exposición, correlación y circuit breakers.

El mismo repositorio contiene `dex-execution`, `rl-execution`, APIs crypto y componentes de transacciones. Por tanto, no es seguro copiarlo completo: debe hacerse una allowlist explícita de skills de investigación y excluir todo lo que pueda crear órdenes, firmar transacciones, mover fondos o acceder a wallets.

### Trading Experiment

El plugin es deliberadamente autónomo: permite que un agente genere clases `backtesting.py`, las ejecute con `exec(strategy_code, namespace)`, las optimice y las persista. El servidor depende de `mcp`, `backtesting`, pandas, pandas-ta, numpy, SQLModel, yfinance y ccxt. El código de datos puede consultar exchanges mediante ccxt y el backtester ejecuta código generado dinámicamente.

Eso no lo convierte en un bot de ejecución, pero sí en una superficie de riesgo de supply-chain y código dinámico. No debe recibir variables de entorno de Alpaca, Secret Manager, Firestore ni acceso al repo de producción. En Polaris podría servir como laboratorio externo, con repositorio separado, imagen sin credenciales, límites de tiempo/iteraciones, revisión de cada estrategia generada y validación point-in-time propia.

### Finance Skills

El plugin `trading-operations` está marcado con `scripts=false`, por lo que su valor principal es guidance sobre lifecycle, best execution, pre-trade/post-trade, settlement, margin, exchange connectivity y operational risk. Es compatible conceptualmente con la documentación de Polaris, pero no debe interpretarse como implementación de controles. Además, mezclar guidance regulatorio estadounidense con una cuenta PAPER no sustituye revisión legal ni técnica.

## Comparación con Polaris

| Necesidad de Polaris | Ya existe en Polaris | Qué podría aportar el catálogo | Riesgo de duplicación |
|---|---|---|---|
| Anti-look-ahead y walk-forward | Skills y scripts propios, múltiples folds y decisiones documentadas. | CPCV, purging, embargo y DSR/PBO como ampliación metodológica. | Bajo si se usa como checklist; alto si se copian scripts sin adaptar datos. |
| Riesgo y circuit breakers | RiskManager, floor, límites y watchdog propios. | Taxonomía de riesgo, CVaR, correlación y lifecycle. | Alto si se introducen límites crypto que no corresponden a opciones/equities. |
| Market data | Alpaca/yfinance y caches reales con validación. | Referencias de ccxt, market-data lineage y quality checks. | Alto si se mezclan fuentes, timezone o datos posteriores. |
| Estrategias | Motores propios y capas shadow/promovidas ya auditadas. | Nuevas ideas y plantillas de laboratorio. | Alto: generar más variantes aumenta multiple testing y sobreajuste. |
| Ejecución | Executor Alpaca y aprobación centralizada. | Vocabulario de order lifecycle. | Crítico si se conecta cualquier broker/DEX externo. |
| Opciones | Cadenas y RiskManager propios; defined-risk sigue bloqueado por atomicidad multi-leg. | Skills de pricing y riesgo de opciones. | Alto si se asumen fills o liquidez que no existen. |

## Ranking recomendado

| Prioridad | Acción | Condición |
|---:|---|---|
| 1 | Adoptar ideas de `walk-forward-validation` y `risk-management` de AGIPro como checklist interno. | Copiar solo documentación y fórmulas revisadas; añadir tests contra casos Polaris. |
| 2 | Auditar de forma aislada `market-microstructure`, `slippage-modeling`, `options-pricing` y `portfolio-analytics` de AGIPro. | Sin ejecución, sin secrets, con licencia y dependencias verificadas. |
| 3 | Usar `finance_skills/trading-operations` para revisar order lifecycle, idempotencia, reconciliación y operational risk. | Guidance solamente; no desplazar RiskManager. |
| 4 | Mantener Trading Experiment en sandbox independiente para comparar metodología de generación. | Sin acceso a producción; toda estrategia generada requiere revisión y backtest propio. |
| 5 | Ignorar por ahora plugins de broker, DEX, wallet, escrow, copy-trading y MCP de órdenes. | Solo reconsiderar con executor aislado, permisos mínimos y confirmación separada. |

## Revisión específica de MCP Servers

La vista filtrada del catálogo mostró **55 MCP Servers** relacionados con Trading. La mayoría se orienta a crypto/DeFi, brokers externos, futuros o servicios de señales; ninguno de los candidatos revisados demostró compatibilidad directa con Alpaca PAPER.

| MCP | Capacidad declarada | Encaje con Polaris | Clasificación |
|---|---|---|---|
| `VARRD` | Event studies, backtesting y validación estadística en acciones, futuros y crypto; endpoint HTTP remoto | Potencial para research-only, sujeto a revisar herramientas y datos point-in-time | **Investigar aislado** |
| `TradingCalc` | PnL, liquidación, sizing y carry de futuros crypto; 19 herramientas | Útil como calculadora conceptual, no para opciones/equities de Alpaca | **Baja prioridad** |
| `IncomeBot` | Régimen, momentum, income options y simulación de riesgo | Es el más cercano al dominio de opciones, pero no demuestra compatibilidad con Alpaca ni fills reales | **Auditar antes de conectar** |
| `Finlab AI` | Más de 900 columnas, backtesting y ejemplos de estrategias | Potencial como laboratorio externo, no como fuente de verdad de Polaris | **Investigar aislado** |
| `Datasignals Lab` | Form 4, 13F, 8-K, FDA, Congreso y señales crypto | Puede aportar contexto event-driven si se verifican fechas y read-only | **Investigar aislado** |
| `Curistat` / `Lattiq` | Volatilidad, régimen y señales para ES/NQ | Mercado distinto al universo de Polaris | **No prioritario** |
| `Trading`, `Trading212`, `Kite`, `AlgoVesta`, `Sentinel`, `FINOPTIMA`, `Openmm`, `HashLock OTC` | Órdenes, brokers, exchanges, DEX, escrow o custodia | No son necesarios y amplían críticamente el perímetro de ejecución | **No conectar** |

Las fichas muestran endpoints HTTP remotos o comandos stdio/npx y, en algunos casos, fechas de última prueba antiguas o instrucciones ausentes. Antes de añadir cualquier MCP hay que consultar el registry, listar herramientas, identificar operaciones de mutación, autenticación y scopes, política de retención, rate limits y existencia de sandbox. Ningún MCP debe recibir claves de Alpaca, tokens de Secret Manager, acceso a Firestore ni acceso directo al executor.

## Conclusión

El catálogo no ofrece un plugin que deba conectarse directamente a Polaris. Su mayor valor es servir como fuente de patrones para investigación, validación y controles operacionales. La integración segura sería selectiva y documental, no una instalación masiva.

El siguiente experimento de mayor valor sería comparar la validación actual de Polaris con una implementación interna de **purging + embargo + Deflated Sharpe/PBO** sobre los backtests ya existentes. Eso probaría si la mejora aparente de una estrategia sobrevive al ajuste por múltiples pruebas, sin añadir riesgo operativo ni nuevas credenciales.

> Esto es una evaluación técnica y experimental en PAPER; no constituye asesoramiento financiero ni garantiza rentabilidad futura.

## Referencias

[1]: https://buildwithclaude.com/search?q=Trading&type=plugin "BuildWithClaude — catálogo de plugins de Trading"  
[2]: https://github.com/agiprolabs/claude-trading-skills "AGIPro Claude Trading Skills"  
[3]: https://github.com/leCheeseRoyale/trading-experiment "Trading Experiment"  
[4]: https://github.com/JoelLewis/finance_skills "Finance Skills for Claude Code"  
[5]: https://github.com/lgbarn/trading-indicator-plugins "Trading Indicator Plugins"  
[6]: https://github.com/xbklairith/kisune "Kisune Claude Code Plugins"  
[7]: https://github.com/acaprino/claude-code-daodan "Claude Code Daodan"  
[8]: https://github.com/smith6jt-cop/Skills_Registry "Skills Registry"
