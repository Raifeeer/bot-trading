# Auditoría de documentos de trading en Google Drive — notas de trabajo

Fecha de consulta: 2026-08-18. Fuente principal: carpeta Drive `ABACUS`, ID `1kDsdHqhMTo1l0S0c8D5aCOZb-L2aTBt`.

## Inventario y fuentes

La carpeta contiene documentos educativos, planes y PDFs relacionados con trading. Se catalogaron 21,379 archivos accesibles en Drive mediante 47 páginas; la carpeta ABACUS contiene múltiples PDFs de formación, documentos de opciones y planes operativos. Los documentos clave y sus enlaces originales son:

| Documento | ID | Enlace |
|---|---|---|
| TRADING PLAN - ABACUS PRO.pdf | `1RLDiz5Agcv1v1onEF8-CqSIsHOEn9aLF` | https://drive.google.com/file/d/1RLDiz5Agcv1v1onEF8-CqSIsHOEn9aLF/view?usp=drivesdk |
| TRADING SETUP.pdf | `1XNteBDCflDubmxa1NVEnhnTR8Zdf5e5C` | https://drive.google.com/file/d/1XNteBDCflDubmxa1NVEnhnTR8Zdf5e5C/view?usp=drivesdk |
| The Wheel.pdf | `1mmBkMnY34t5dr0Y-kCR4awjHXuBskO3B` | https://drive.google.com/file/d/1mmBkMnY34t5dr0Y-kCR4awjHXuBskO3B/view?usp=drivesdk |
| Smart Money Concepts I by Jorge Valet.pdf | `1E54_IfdKBaRqW9LMlvXhqjDGeozuooFk` | https://drive.google.com/file/d/1E54_IfdKBaRqW9LMlvXhqjDGeozuooFk/view?usp=drivesdk |
| Supply & Demand III by Jorge Valet.pdf | `1N6ocz0Eo_f8arLhrGjMSEEtfyNFEpUT5` | https://drive.google.com/file/d/1N6ocz0Eo_f8arLhrGjMSEEtfyNFEpUT5/view?usp=drivesdk |
| Multitimeframe Market Structure by Jorge Valet.pdf | ID catalogado en Drive como documento duplicado; copia local OCR revisada | — |
| Plan de Juego 13/11/2024 | documento PDF catalogado en ABACUS | — |
| Plan de Trading Magnificent7/TQQQ 2025-05-22 | `1J5WeYUDzgvtkARqlDYl0B7YFEG7aW7UA` | https://drive.google.com/file/d/1J5WeYUDzgvtkARqlDYl0B7YFEG7aW7UA/view?usp=drivesdk |
| Carlos Amec — CSP & Covered Calls | PDF catalogado en ABACUS | — |
| Recurso educativo clase 5 — Soportes y Resistencias | PDF catalogado en ABACUS | — |
| Recurso educativo clase 8 — Volatilidad y Volumen | PDF catalogado en ABACUS | — |
| Recurso educativo clase 9 — Temporalidades | PDF catalogado en ABACUS | — |
| Recurso educativo clase 10 — Tendencias | PDF catalogado en ABACUS | — |
| Recurso educativo clase 11 y 12 — Risk Reward & Day Trading Strategies | PDF catalogado en ABACUS | — |

## Hallazgos del TRADING PLAN - ABACUS PRO

El plan describe una operativa de opciones intradía y swing con premarket, ventanas de operación 10:30–13:00 y 15:30–17:00, límites de operaciones diarias, riesgo por posición y una cascada de análisis D→4H/2H/1H→30M/15M→5M/1M. Exige supply/demand, order blocks, CHoCH/BOS, BSL/SSL, KL, gaps, Volume Profile/VPOC/HVN/LVN, VWAP, cruces de EMAs 10/50, retests y confirmación de order flow.

Reglas citadas en el documento: para day trading ATM/ITM con 5–15 DTE o 10–30 DTE para un perfil menos agresivo; 0–3 DTE para scalping agresivo; swing 30–90 DTE. Riesgo indicado: 10–20% de la posición, ratio 2:1, con una nota específica de pérdida máxima en 0DTE. Estas cifras son material educativo específico del plan y no deben copiarse automáticamente al RiskManager de Polaris.

Brechas evidentes frente al bot live actual: no existe una cascada live 4H/2H/1H/30M/1M; no hay premarket/gaps ni Volume Profile/VPOC/HVN/LVN; el bot usa EMA 9/21 en momentum y SMA 20/50 en swing, no EMA 10/50 como regla del plan; no hay confirmación explícita de order flow, breaker, Killer Block o FVG como motores operativos; el bot live no limita explícitamente a las ventanas horarias del plan salvo el breakout 10:00–15:30.

Fuente: https://drive.google.com/file/d/1RLDiz5Agcv1v1onEF8-CqSIsHOEn9aLF/view?usp=drivesdk

## Hallazgos de TRADING SETUP.pdf

El OCR contiene ejemplos de HTF OB + LTF OB, Liquidity Sweep/Manipulación, EMA Cross + HTF OB, VWAP + OB/Breaker, EMA Cloud, HTF OB + Fibonacci, Key Levels, buyingVsSelling y Bearish OB, además de BSL/SSL, micro-KL, Fibonacci, trendlines, VWAP y EMAs 9/50. Los doce nombres ya fueron formalizados previamente en `strategies/setup_confluence.py` como shadow; el PDF no proporciona reglas paramétricas completas para convertir las capturas en un backtest exacto, por lo que los resultados siguen siendo proxy.

Fuente: https://drive.google.com/file/d/1XNteBDCflDubmxa1NVEnhnTR8Zdf5e5C/view?usp=drivesdk

## Hallazgos de Smart Money Concepts I

El documento define bullish/bearish order blocks como la última vela contraria antes de un impulso, usa HTF/LTF, distingue CHoCH y BOS, exige para un OB confirmado ruptura de high/low, consolidación exterior, desequilibrio 1:2, zona fresca y alineación con la tendencia mayor. También incluye Drop→Base→Drop, Rally→Base→Drop, Rally→Base→Rally, Drop→Base→Rally, BSL/SSL, acumulación–manipulación–distribución y zonas de liquidez.

`strategies/smc.py` cubre solo una parte: swings fractales, CHoCH, zonas básicas supply/demand y una cascada MTF limitada; no cubre de forma completa la validación 1:2/fresh zone, Killer Block, FVG, ni las estructuras clásicas. Además, `SMCStrategy` no es una de las tres estrategias instanciadas por `bot.py` live.

Fuente: https://drive.google.com/file/d/1E54_IfdKBaRqW9LMlvXhqjDGeozuooFk/view?usp=drivesdk

## Hallazgos de Supply & Demand III

El documento define BSL/SSL como zonas alrededor de highs/lows, equal highs/lows y líneas de tendencia; describe manipulación como ruptura rápida de highs/lows seguida de reversal; distingue Order Block tradicional, Breaker y Killer Block; define Killer Block como la combinación de manipulación y Order Block; e introduce Fair Value Gaps/imbalances como vacíos de liquidez. Estas partes no están completas en el motor live actual. La capa de setups actual tiene proxies de liquidity sweep y order block, pero no una implementación parametrizada completa de Breaker, Killer Block ni FVG.

Fuente: https://drive.google.com/file/d/1N6ocz0Eo_f8arLhrGjMSEEtfyNFEpUT5/view?usp=drivesdk

## Hallazgos de análisis multi-timeframe

La secuencia descrita es mensual/semanal/diario/4H/1H/M15/M5/M1, con una cascada operativa concreta D para perspectiva, 4H para narrativa, M15 para sesgo inmediato y M1 para temporización. Se advierte que CHoCH puede ser un retroceso y no una reversión, y se recomienda confluencia con supply/demand, liquidez y premium/discount.

Polaris live usa 1D, 15M y 5M para sus tres motores, y el módulo SMC existente documenta una cascada más amplia pero no está instanciado en `build_strategies()`. Esto es una brecha de cobertura, no una orden de activar todos los marcos sin revisar latencia, datos y look-ahead.

## Hallazgos de Volatilidad y Volumen

El material introduce VIX como volatilidad esperada de mercado, ATR para stops/targets y sizing, volumen como liquidez/confirmación/divergencia y beta como sensibilidad al mercado. Polaris usa ATR, volumen relativo y filtros de volatilidad en motores existentes, pero no usa VIX, beta, divergencias de volumen ni Volume Profile/VPOC/HVN/LVN como entradas operativas.

## Hallazgos de Temporalidades, Tendencias y Soportes/Resistencias

Los documentos recomiendan usar al menos tres toques históricos para validar soportes/resistencias, tratar zonas y vigilar cambios de rol después de un rompimiento. También enumeran velas y patrones: martillo, morning/evening star, double top/bottom, head-and-shoulders, wedges, rectangles, pennants y triángulos ascendentes/descendentes/simétricos. El clasificador de Polaris reduce el régimen global a bull/bear/cash y el motor live no contiene una librería de patrones chartistas ni reglas de tres toques; el Key Level shadow cubre solo una parte del concepto.

## Hallazgos de Plan de Juego y planes de activos

`Plan de Juego 13/11/2024` usa gamma walls, put support, VIX, US10Y, niveles de índices y activos proxy; es una fotografía fechada, no una regla sistemática reusable sin datos point-in-time. `Plan de Trading Magnificent7/TQQQ 2025-05-22` contiene soportes/resistencias, breakouts/breakdowns, objetivos y stops para TQQQ, AMZN, NVDA, AMD, AAPL, MSFT, META y TSLA; puede convertirse en un test genérico de nivel+stop, pero sus cifras son fechadas y no deben extrapolarse directamente.

## Hallazgos de CSP/covered calls

`Carlos Amec — CSP & Covered Calls` añade detalles de valor intrínseco/extrínseco, theta, IV, roll, assignment temprano, sweet spot cercano al strike, aproximadamente 2% de prima, dos semanas de vencimiento e IV alto. La skill The Wheel ya recoge la mayoría de estos conceptos, pero `WheelStrategy` no está conectada al loop live y la asignación/roll persistente siguen incompletos.

## Evidencia de operación actual de Polaris

La configuración vigente (`config/config.yaml`) tiene `setups.enabled=true`, `mode=shadow`, `influence_entries=false`, con regime 1d, setup 15min y entry 5min. Los spreads definidos (`defined_risk_shadow`) tienen `enabled=true`, `mode=shadow`, `influence_entries=false` y `orders_allowed=false`. Las únicas estrategias live activadas son `day_momentum` (5min, EMA 9/21, ATR, volumen relativo y RSI), `day_breakout` (15min, Donchian y ATR, ventana 10:00–15:30) y `swing_trend` (1d, SMA 20/50, filtro SMA200 y ATR). No hay banderas live para SMCStrategy completa, The Wheel, Williams %R, VIX, gamma walls, Volume Profile ni patrones chartistas.

`bot.py` instancia únicamente `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend` en `build_strategies()`. La capa de régimen puede activar `put_choch` en condiciones bajistas, pero eso no equivale a instanciar el módulo SMC completo. Las capas `setups` y `defined_risk_shadow` son observabilidad y no tienen ruta al executor.

## Clasificación preliminar de documentos

| Familia documental | Estado en Polaris | Brecha principal |
|---|---|---|
| SMC / Supply & Demand / Market Structure | Parcial: `strategies/smc.py` y CHoCH de régimen | SMC completo no live; faltan Breaker/Killer Block/FVG, validación OB 1:2/fresh y cascada completa operacional |
| TRADING SETUP | Implementado como 12 observaciones shadow | No influye en entradas; reglas de capturas son proxies y no tienen cadena de opciones point-in-time |
| TRADING PLAN ABACUS PRO | Documentado; algunos indicadores dispersos | Falta premarket/gaps, 4H/2H/1H/30M/1M live, Volume Profile y confirmación order-flow |
| The Wheel / CSP-CC | Skill y módulo sin conexión live | Faltan assignment/roll/persistencia completa y la evidencia no superó al baseline |
| Risk-Reward / Break & Retest | Break-and-retest como setup shadow; RiskManager activo | No es filtro live; plan discrecional no se ha convertido en motor exacto |
| Volatilidad y Volumen | ATR y volumen relativo activos | VIX, beta, divergencia volumen y VPOC/HVN/LVN ausentes |
| Temporalidades | 5m/15m/1d live; SMC 1d/4h/15m/1m parcial | Falta cascada operativa completa y sincronización MTF live |
| Tendencias / patrones | Régimen bull/bear/cash; EMAs/SMAs | Faltan patrones de velas y chartistas: double top/bottom, H&S, wedges, flags, rectangles, pennants, triangles |
| Fundamentos / P-E / Price Target / Conference Calls | No usados como filtros live | Faltan pipeline de snapshots point-in-time y reglas cuantificables para evitar look-ahead |
| Plan de Juego / gamma walls / VIX / US10Y | Solo documento fechado | No es una estrategia reusable; requiere datos históricos point-in-time y no debe codificarse como niveles fijos |
| Plan Magnificent7/TQQQ | Solo documento fechado | Puede convertirse en una prueba genérica de soporte/resistencia + breakout/stop, no usar sus precios históricos directamente |

## Candidatos de investigación priorizados

1. **Confirmación de régimen y filtro de volatilidad de mercado**: VIX/volatilidad de índice como contexto, sin usarlo como predictor autónomo.
2. **Volume Profile/VPOC/HVN/LVN**: candidato útil para entradas y salidas intradía, pero requiere barras intradía y sesión RTH/ETH correctas.
3. **SMC completo con Breaker/Killer Block/FVG y validación OB**: segunda prioridad después de definir reglas deterministas, porque el material es visual y subjetivo.
4. **Williams %R 14 como filtro o confirmación**, comparado contra RSI ya existente, para evitar añadir un indicador redundante.
5. **Patrones chartistas** solo en una versión algorítmica objetiva; no codificar dibujos manuales como verdad.
6. **Fundamentales/PE/ventas/earnings** como filtro de selección swing, no como señal intradía; requiere datos point-in-time, fundamental history y control de revisiones.
7. **Gamma walls/put support/US10Y** únicamente si se consigue historial point-in-time de opciones, volatilidad y macro; el plan fechado no basta.

La prioridad no es “implementar todo”: primero se debe formalizar cada candidato en reglas sin ambigüedad, definir qué datos históricos existen y hacer backtest emparejado contra el baseline con costes y walk-forward.
