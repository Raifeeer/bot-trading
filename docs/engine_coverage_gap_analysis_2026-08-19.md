# Análisis de cobertura y huecos de motores — 2026-08-19

## Estado actual

Polaris ejecuta tres wrappers de opciones live: `opt_day_momentum` sobre 5 minutos, `opt_day_breakout` sobre 15 minutos y `opt_swing_trend` sobre diario. El motor bajista `put_choch` es una ruta especializada adicional que solo puede producir candidatos en condiciones CHoCH bear; no es un cuarto motor general. Las capas de setups, spreads definidos, VIX y estructura MTF están conectadas exclusivamente en shadow.

## Qué cubren los motores actuales

| Motor | Señal principal | Dirección | Hueco que deja |
|---|---|---|---|
| DayMomentum | Cruce EMA 9/21, volumen relativo, RSI y precio sobre EMA lenta | Larga | No detecta pullbacks limpios, VWAP/reversión ni señales cortas live |
| DayBreakout | Ruptura de Donchian de 10 barras | Larga | No distingue apertura/rango inicial, retest, continuación o fallo de ruptura |
| SwingTrend | SMA20/50, filtro SMA200, ATR y objetivo | Larga | No cubre rotación relativa, mean reversion ni cambios intradía |
| put_choch | Put spread tras CHoCH bajista | Bajista especializada | No cubre tendencia bajista temprana sin CHoCH confirmado ni rebotes alcistas durante selloffs |

## Huecos de oportunidad cuantificables

1. **Opening Range Breakout (ORB):** el motor Donchian empieza a evaluar desde las 10:00 ET y no conserva explícitamente el rango de apertura de 5/15/30 minutos. Puede perder rupturas tempranas confirmadas o confundirlas con cualquier ruptura posterior.
2. **VWAP pullback/mean reversion:** el bot observa VWAP en setups shadow, pero no tiene un motor live que evalúe distancia a VWAP, tendencia de VWAP, reclaim y volumen de confirmación.
3. **Pullback de continuación:** EMA crossover exige el cruce en la barra actual; no detecta retrocesos controlados a EMA/VWAP dentro de una tendencia ya establecida.
4. **Relative strength/cross-sectional rotation:** cada símbolo se evalúa de forma independiente; no existe ranking relativo contra SPY/QQQ ni selección de los líderes y rezagados del universo.
5. **Reversal/mean reversion con régimen:** RSI solo filtra DayMomentum y no existe un motor específico para rebotes desde extremos con confirmación de estructura y stop definido.
6. **Short intradía definido:** `RiskManager` mantiene cortas deshabilitadas como política general; no existe un motor live bear de 5m/15m, aunque sí una ruta put_choch especializada.
7. **Failure/retest de breakout:** DayBreakout solo requiere cierre por encima de Donchian y no modela de manera separada retest, aceptación o fallo.

## Criterio de selección

Los nuevos motores deben ser puros, deterministas y compatibles con `Strategy.scan()`. Deben usar velas cerradas, stops derivados de ATR o estructura, máximo de pérdida definido por la capa de opciones y no tener ruta directa al executor durante la investigación. Se priorizarán motores que cubran un hueco distinto en lugar de añadir variantes con la misma señal EMA/Donchian.

## Shortlist inicial

La primera ronda debe comparar cuatro familias: ORB, VWAP pullback/reclaim, trend pullback y relative-strength rotation. Mean reversion extrema y shorts intradía quedan para una segunda fase porque requieren gates adicionales de régimen y una revisión del contrato de cortas. Cada familia deberá tener skill, backtest multi-ventana y decisión independiente.

## Estado de seguridad

No se modifica la operación live por este documento. PAPER sigue siendo obligatorio; RiskManager, floor, circuit breakers y validación de cotizaciones son autoridades finales. Una mejora solo podrá conectarse inicialmente como shadow y podrá influir en órdenes únicamente después de evidencia fuera de muestra y revisión explícita.
