# Comparación de proveedores para OOS de opciones

**Fecha de corte:** 25 de agosto de 2026  
**Objetivo:** seleccionar una fuente realista para evaluar estrategias de Polaris con datos históricos de ejecución, sin contratarla ni conectarla todavía.

## Resumen ejecutivo

El bloqueo sí tiene solución técnica. Los candidatos que mejor encajan son **Databento OPRA** y **algoseek Options**. Databento es la opción más razonable para un piloto inicial porque ofrece acceso por API y archivos históricos, publica OPRA consolidado con last sale y National BBO desde 2013 y muestra precio histórico desde `$0.04/GB` [1]. algoseek es la opción de mayor fidelidad para ejecución porque declara captura lossless del feed OPRA desde 2014, trades y quotes tick-level, NBBO, referencias del subyacente y seguimiento listing-to-expiry, pero su precio es empresarial: la página muestra un paquete histórico desde `$3,000/mes` y el dataset individual de trade+NBBO desde `$7,200/mes` indicativos [2] [3].

Cboe DataShop puede ser un tercer camino si basta con resolución de un minuto. Su producto Option Quote Intervals ofrece snapshots de 1 minuto o N-minuto con NBBO, tamaños, OHLC y volumen, cubre opciones de acciones, ETFs e índices distribuidas por OPRA y tiene historia publicada desde enero de 2012 [4]. ThetaData también parece viable por sus operaciones históricas de quotes/trades y flat files, pero exige confirmar precio, licencias, cobertura de contratos y comportamiento de gaps antes de incorporarlo [5] [6].

Ningún proveedor queda conectado ni contratado con esta investigación. La recomendación es pedir o comprar primero una **muestra pequeña** a Databento o algoseek y ejecutar un data gate automatizado sobre AMD, F, BB, NOK, PLTR, TQQQ y TSLA antes de descargar años completos.

## Qué necesita Polaris

Polaris necesita timestamp UTC, símbolo OCC, expiración, strike y tipo, bid/ask y tamaño NBBO, trades y condiciones, estado del contrato por fecha, underlying sincronizado, open interest cuando corresponda, paginación completa, huecos detectables, costes de transacción y una licencia que permita investigación/backtesting. Para 0DTE/1DTE se requiere al menos resolución de un minuto y preferiblemente tick/NBBO; OHLC diario o una cadena actual aplicada retrospectivamente no es aceptable.

## Matriz de comparación

| Proveedor | Evidencia de mercado | Cadena/lifecycle | Resolución e integración | Precio publicado o indicativo | Ajuste preliminar |
|---|---|---|---|---|---|
| **Databento OPRA** | Last sale, exchange BBO y National BBO de todas las bolsas de opciones estadounidenses; más de 1.4 millones de contratos declarados | Ofrece instrument definitions y estadísticas/open interest; hay que verificar en la muestra la reconstrucción listing/expiry por contrato | API, Python/C++/Rust, histórico y bulk; symbology raw/instrument/parent | Histórico desde `$0.04/GB`; el coste final depende de dataset/consulta [1] | **Mejor primer piloto API/coste** |
| **algoseek Options** | Feed OPRA lossless desde 2014, trades/quotes tick-level, NBBO, condiciones e información del subyacente | Declara full lifecycle listing-to-expiry, security master y open interest | CSV/SQL y paquetes históricos; muy apto para fills y 0DTE | Dataset individual desde `$7,200/mes` indicativo; paquete histórico desde `$3,000/mes` [2] [3] | **Mejor fidelidad; caro** |
| **Cboe DataShop Option Quote Intervals** | NBBO, bid/ask size, OHLC, volumen y underlying bid/ask | Campos de símbolo, root, expiry, strike y type; verificar cobertura histórica de contratos inactivos | Archivos de intervalos de 1 o N minutos; historia desde enero de 2012 | Precio no encontrado públicamente; requiere cotización/checkout y puede haber licencias SIP/índices [4] | **Buena alternativa 1-min; menos detalle tick** |
| **ThetaData** | Declara quotes/trades sin filtrar, históricos y Greeks; documentación enumera quotes, trade-quote y OHLC | Expone listados de raíces, expiraciones, strikes y contratos; validar lifecycle y continuidad | REST local/Terminal, streaming y flat files; requiere validar operación bulk | Precio final no confirmado en la página consultada [5] [6] | **Candidato técnico; precio/licencia pendientes** |
| **Alpaca actual** | Barras y trades históricos, última cotización, snapshots y cadena actual | El cache local no tiene cadena point-in-time ni bid/ask intradía; el SDK instalado no expone histórico `get_option_quotes` | Fácil integración actual, pero insuficiente para ejecución histórica | Incluido en la infraestructura existente, pero no supera el data gate | **No suficiente para OOS de ejecución** |

## Puntuación de ajuste a Polaris

La puntuación siguiente es una evaluación de ingeniería, no una métrica publicada por los proveedores. Premia la capacidad demostrada en las fuentes y penaliza los campos que aún necesitan validación en una muestra.

| Proveedor | NBBO/fills | 0DTE/1DTE | Lifecycle | Integración | Coste piloto | Total orientativo |
|---|---:|---:|---:|---:|---:|---:|
| Databento | 5/5 | 5/5 | 3/5 | 5/5 | 4/5 | **22/25** |
| algoseek | 5/5 | 5/5 | 5/5 | 4/5 | 1/5 | **20/25** |
| Cboe DataShop | 4/5 | 4/5 | 3/5 | 3/5 | 2/5 | **16/25** |
| ThetaData | 4/5 | 4/5 | 3/5 | 4/5 | 2/5 | **17/25** |

Databento obtiene la mejor puntuación para **un piloto acotado y autocontrolado**: el precio de entrada está publicado, existe API/bulk y la fuente declara OPRA/NBBO desde 2013 [1]. algoseek sería preferible si el objetivo es máxima fidelidad de ejecución y se dispone de presupuesto empresarial; sus propios productos declaran el lifecycle completo y el contexto NBBO al trade [2] [3].

## Piloto recomendado

El piloto no debe descargar el universo completo. Debe solicitar una semana de mercado y un subconjunto de contratos near-ATM de AMD, F, BB, NOK, PLTR, TQQQ y TSLA, incluyendo al menos una sesión de alta volatilidad y una expiración corta. Para cada contrato se debe comprobar que haya timestamp, bid, ask, tamaño si existe, trade, underlying sincronizado, expiración y símbolo estable. El pipeline debe contar duplicados, huecos, quotes cruzadas, bid/ask cero, timestamps fuera de RTH, contratos que aparecen retrospectivamente y páginas incompletas.

La salida del piloto debe ser un `manifest` con proveedor, dataset, feed, fechas, consulta, símbolos, número de filas, hash de archivos, costes, huecos, porcentaje de filas con NBBO y licencia. Solo si supera el data gate se puede ampliar a meses y después a un walk-forward separado por entrenamiento, embargo y test. La fuente debe alimentar un adaptador de lectura; no debe cambiar `config/config.yaml`, habilitar entradas ni tocar el executor multi-pata.

## Qué queda pendiente antes de elegir

| Verificación | Databento | algoseek | Cboe | ThetaData |
|---|---|---|---|---|
| Muestra real de los siete símbolos | Pendiente | Pendiente | Pendiente | Pendiente |
| Point-in-time de contratos inactivos | Confirmar | Declarado, verificar | Riesgo: ciertos productos no soportan inactivos | Confirmar |
| Precio de una semana | Consultar checkout/API | Solicitar cotización | Solicitar cotización | Solicitar cotización |
| Licencia backtesting | Leer términos de la cuenta | Confirmar licencia de investigación | Confirmar uso no-display | Confirmar uso y redistribución |
| Integración definitiva | No iniciar | No iniciar | No iniciar | No iniciar |

## Recomendación

**Recomiendo empezar por Databento con un piloto de una semana y alcance limitado**, sin comprometer una suscripción anual ni modificar el bot. Si la muestra falla el lifecycle o la resolución de fills, el segundo paso debe ser algoseek, cuyo producto parece más completo para ejecución, sujeto a una cotización que haga viable el presupuesto. Cboe DataShop puede ser suficiente para setups de entrada/salida a minuto, pero no es la primera opción para estudiar fills tick-level. ThetaData merece una prueba si su precio/licencia y el acceso a quotes históricos son mejores que los de Databento.

## Referencias

[1]: https://databento.com/options "Databento Options Data"
[2]: https://algoseek.com/options "algoseek US Equity Options Data"
[3]: https://algoseek.com/dataset/us-options-trade-and-nbbo-quote/ "algoseek US Options Trade and NBBO Quote"
[4]: https://datashop.cboe.com/option-quote-intervals "Cboe DataShop Option Quote Intervals"
[5]: https://thetadata.us/pricing/ "ThetaData Options Data and Pricing"
[6]: https://http-docs.thetadata.us/operations/get-hist-option-trade.html "ThetaData Historical Options Operations"
