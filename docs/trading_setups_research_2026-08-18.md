# Investigación preliminar de setups — fase BOS/CHoCH/Order Blocks

## Fuentes consultadas

1. Daily Price Action, “SMC Market Structure: BoS and CHoCH Made Simple”, actualizado el 10 de diciembre de 2025: https://dailypriceaction.com/blog/smc-market-structure/
2. Trading Wyckoff / Rubén Villahermosa, “Smart Money Concepts (SMC): Complete Guide to Order Blocks, FVG and Liquidity”, actualizado en abril de 2026: https://tradingwyckoff.com/en/smart-money-concepts/

## Hallazgos

- Daily Price Action presenta BOS y CHoCH como lectura de estructura para continuidad o posible reversión, y afirma que puede expresarse mediante reglas mecánicas; es una fuente educativa basada en el método del autor, no evidencia estadística independiente.
- Trading Wyckoff define un order block válido con tres condiciones simultáneas: última vela contraria al impulso, desplazamiento impulsivo y ruptura confirmada de estructura. Una vela previa a un rally sin desplazamiento y BOS no basta.
- Para formalizar el OB, la fuente marca la zona desde open hasta low en bullish OB y desde open hasta high en bearish OB; propone esperar mitigación/retorno a la zona.
- La entrada puede ser agresiva en la línea proximal, conservadora tras una vela de confirmación o mediante cambio de estructura en un timeframe inferior. Para un bot conviene empezar por confirmación, no por límite agresivo.
- El stop se ubica fuera de la línea distal con buffer dependiente de volatilidad; cierre más allá del umbral medio puede tratarse como mitigación/invalidez adicional.
- Los objetivos se relacionan con swing highs/lows, FVG y liquidez externa. La idea de “draw on liquidity” es direccional, pero necesita una definición algorítmica explícita de niveles, distancia y prioridad.
- Estas definiciones son de la literatura educativa SMC/ICT y contienen ambigüedades subjetivas; no deben convertirse directamente en órdenes. Requieren parámetros, timestamp de confirmación, reglas anti-look-ahead, datos OHLCV point-in-time, costes y validación fuera de muestra.

## Comparación con Polaris

`strategies/smc.py` ya contiene swings fractales, CHoCH y zonas supply/demand; `risk/regime.py` consume una versión pragmática de CHoCH bajista para clasificar bear y el motor `put_choch`. Sin embargo, el constructor live de `bot.py` instancia `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend`; `SMCStrategy` no está conectado como motor principal de entradas.

El order block del código actual es parcial: `detect_sw_zone` busca una vela base contraria seguida de un salto sobre high/low, pero no formaliza displacement con ATR, BOS multi-timeframe, mitigación, invalidación, target de liquidez ni fill. El nuevo setup skill debe especificar estas partes antes de implementarlas.

## Reglas de investigación

No afirmar que estos patrones predicen el mercado sin evidencia propia. Usarlos primero como features de dirección (`bull`, `bear`, `neutral`) en shadow/PAPER y comparar contra el baseline. Guardar la fuente, fecha de consulta y cualquier dato histórico de contexto; no usar explicaciones o niveles conocidos después de la fecha de decisión.

## Fase liquidity sweeps / BSL / SSL

3. Flux Charts, “Liquidity Sweeps Explained”: https://www.fluxcharts.com/articles/liquidity-sweeps-explained-how-to-identify-and-trade-them
4. ATAS, “What Is Liquidity Sweep? How to Trade It?”, 13 de marzo de 2025: https://atas.net/blog/what-is-liquidity-sweep-how-to-trade-it/

- Flux Charts describe un sweep como una penetración de un nivel de liquidez seguida de recuperación/reversión. Un barrido de SSL se interpreta como sesgo bullish; uno de BSL, como sesgo bearish. Para automatizarlo hay que exigir que el precio cruce el nivel y cierre/reclame al otro lado, no llamar sweep a cualquier ruptura.
- ATAS explica que arriba del precio existen sell limits y buy stops; abajo, buy limits y sell stops. BSL/SSL son zonas inferidas, no una lectura directa de stops individuales.
- ATAS advierte que no es posible identificar la ubicación exacta de todos los stop orders en mercados públicos solo desde OHLCV; la narrativa de “smart money ve todos los stops” es una simplificación.
- Un algoritmo debe construir niveles observables: máximos/mínimos relevantes, equal highs/lows con tolerancia basada en ATR, extremos de sesión/día/semana y niveles psicológicos. Debe registrar si hubo wick-through, cierre de regreso, volumen relativo y confirmación estructural posterior.
- Un sweep no garantiza reversión. Puede ser breakout genuino, absorción o continuación. La dirección debe ser provisional hasta una confirmación como CHoCH/BOS en timeframe inferior, rechazo de zona y riesgo definido.
- Para Polaris, un módulo de sweep debería producir `bull`, `bear` o `neutral` con confianza y evidencia, nunca ordenar directamente. Debe evitar usar máximos/mínimos futuros y separar nivel identificado en t de la reacción posterior.
- La fuente ATAS es educativa y comercial; aporta definiciones y limitaciones, no una validación estadística independiente de rentabilidad.

## Fase EMA / VWAP / EMA Cloud / volumen

5. TrendSpider, “Understanding Volume”: https://trendspider.com/learning-center/understanding-volume-indicator-a-comprehensive-guide/
6. AlgoTest, “VWAP EMA Combined Strategy”: https://docs.algotest.in/signals/pinescripts/volume_vwap_ema_combined_strategy/
7. arXiv, “Order Book Filtration and Directional Signal Extraction at High Frequency”: https://arxiv.org/html/2507.22712v1

- Un cruce EMA es un indicador rezagado de tendencia/momentum; el periodo y el timeframe determinan la velocidad y el ruido. No debe tratarse como predicción independiente.
- VWAP es un precio medio ponderado por volumen de la sesión y puede usarse como filtro de contexto: precio y EMA por encima de VWAP sugieren sesgo bullish; por debajo, bearish. La definición debe fijar sesión, timezone, reinicios y tratamiento de premarket.
- EMA Cloud es una visualización de dos o más medias, no una señal única. Para automatizarla hay que especificar qué medias, si se exige separación mínima, pendiente y cierre fuera de la nube.
- Volumen total no contiene dirección por sí mismo. Un volumen alto confirma participación/liquidez, pero no revela con certeza quién compra o vende. Un proxy buy/sell basado en OHLCV necesita documentar su fórmula y no debe llamarse order-flow real.
- Un estudio sobre desequilibrio del libro de órdenes sugiere que señales persistentes de imbalance pueden tener información direccional, pero eso requiere datos L2/order book; el feed OHLCV de Polaris no lo proporciona.
- Para una skill reusable, EMA/VWAP/volumen deben tratarse como filtros de confluencia y features separadas, no como setups independientes sin validación. Cada feature debe registrar valor, timestamp y umbral usado.
- Estas fuentes son educativas o trabajos preliminares; no demuestran que una combinación EMA/VWAP genere alfa robusto después de costes.

## Fuentes web verificadas de EMA/VWAP/volumen

8. AlgoTest, “VWAP EMA Combined Strategy”: https://docs.algotest.in/signals/pinescripts/volume_vwap_ema_combined_strategy/
9. TrendSpider, “Volume Indicator Guide: Understanding Trading Volume & Market Activity”: https://trendspider.com/learning-center/understanding-volume-indicator-a-comprehensive-guide/

- La combinación VWAP+EMA debe formalizar qué significa cruce, dónde ocurre el cierre de confirmación, qué periodo de EMA se usa y qué reglas de salida/stop se aplican. Una receta de PineScript o una guía de plataforma no es prueba de generalización.
- TrendSpider afirma explícitamente que el volumen mide participación, no dirección; el volumen alto puede dar credibilidad a rupturas o reversiones, pero funciona mejor como confirmación junto con otros elementos.
- Las diferencias entre volumen real de acciones/futuros y tick volume de forex muestran que la skill debe registrar el tipo de volumen y no transferir fórmulas sin adaptación.
- En Polaris, VWAP/EMA Cloud aún no forman un motor live equivalente al setup del PDF. Se pueden añadir inicialmente como features de dirección y filtros de calidad, no como órdenes autónomas.

## Fase Fibonacci / premium-discount / OTE

10. Daily Price Action, “Premium and Discount Trading Strategy (How Smart Money Uses OTE)”, actualizado el 17 de diciembre de 2025: https://dailypriceaction.com/blog/premium-and-discount-trading-strategy/
11. Zerodha Varsity, “The Fibonacci Retracements”: https://zerodha.com/varsity/chapter/fibonacci-retracements/

- OTE/premium-discount usa un swing definido para dividir el rango: por encima del 50% se trata como premium y por debajo como discount. La guía SMC consultada usa la banda 62%-79% como OTE; esto es una convención metodológica, no una ley del mercado.
- Zerodha explica que los niveles 23.6%, 38.2% y 61.8% se calculan sobre un movimiento peak-trough identificado y que los retrocesos son niveles potenciales, no certezas.
- Zerodha recomienda utilizar Fibonacci como confirmación junto con estructura, patrón de vela, soporte/resistencia y volumen; esto respalda no usar Fibonacci como señal única.
- El principal riesgo algorítmico es la selección retrospectiva de los extremos: si el peak/trough se elige con información futura, el backtest queda contaminado. La skill debe fijar una ventana de swing, un algoritmo de pivots confirmado y un retraso de confirmación.
- La confluencia multi-timeframe debe ser explícita: timeframe de régimen, timeframe de setup y timeframe de ejecución; cada uno solo puede usar datos cerrados y disponibles en el momento de decisión.
- Para Polaris, Fibonacci debe ser un filtro de ubicación (`discount_long`, `premium_short`, `neutral`) y no una predicción autónoma. El módulo debe registrar anchors, ratios, timestamp y si el anchor quedó confirmado antes de la entrada.

## Aclaración de KL

12. Resultados de búsqueda sobre “key levels (KL)”: https://fr.tradingview.com/scripts/keylevels/ y https://es.tradingview.com/scripts/keylevels/

- En el OCR del PDF, KL aparece como etiquetas numéricas asociadas a `PREV LOW - KL`, `KL - low`, `Micro KL`, niveles próximos a OB y a máximos/mínimos. No aparece como nombre de un oscilador o estrategia autónoma.
- La evidencia disponible sugiere que KL significa `key level`/nivel clave, probablemente un máximo o mínimo previo usado como soporte, resistencia o liquidez. El significado exacto del indicador que generó la etiqueta no está especificado en el PDF.
- La skill debe tratar KL como un nivel estructural configurable, no como señal independiente: definir si proviene de high/low previo, sesión/día/semana, tolerancia, expiración y reacción requerida.
- Antes de implementarlo en Polaris hay que confirmar con el usuario o con el autor del setup qué representa exactamente cada KL, porque el OCR no permite distinguir todos los casos.

## Evidencia y límites metodológicos

13. Psaradellis et al., “Technical analysis, spread trading, and data snooping control”: https://eprints.gla.ac.uk/253683/2/253683.pdf
14. Sullivan, Timmermann y White, “Data-Snooping, Technical Trading Rule Performance, and the Bootstrap”: https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf
15. Federal Reserve, “Order Flow Imbalances and Amplification of Price Movements”: https://www.federalreserve.gov/econres/notes/feds-notes/order-flow-imbalances-and-amplification-of-price-movements-evidence-from-u-s-treasury-markets-20251103.html
16. “Can Returns Breed Like Rabbits? Econometric Tests for Fibonacci Retracements”: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4212430

- La literatura de reglas técnicas insiste en controlar data snooping, selección ex post y costes de transacción. La skill debe separar descubrimiento, validación y test final, y no seleccionar parámetros mirando el test.
- La evidencia de order-flow es distinta de un indicador de volumen OHLCV: la microestructura puede aportar información direccional, pero requiere datos de órdenes/trades y no puede inferirse completamente desde las barras del bot.
- La investigación sobre Fibonacci debe tratarse como hipótesis empírica a probar, no como una propiedad causal del mercado. La implementación debe comparar contra niveles aleatorios/control y contra baseline.
- Ninguna de estas fuentes valida por sí sola los setups del PDF para opciones sobre acciones; la validación de Polaris requiere datos y fills específicos del instrumento.
