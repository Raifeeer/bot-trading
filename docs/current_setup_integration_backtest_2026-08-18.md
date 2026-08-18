# Backtest integrado: configuración actual de Polaris + setups

**Fecha de ejecución:** 18 de agosto de 2026.  
**Autor:** Manus AI.  
**Clasificación:** investigación experimental; no promoción a PAPER como filtro y no REAL.

## Resumen ejecutivo

Se ejecutaron dos pruebas complementarias. La primera mantuvo la política de régimen actual documentada para Polaris —bull implica exposición semanal, bear/cash implica efectivo y se conserva el detector de crash— y probó los setups como filtro auxiliar. La segunda utilizó el código real de `strategies.swing_trading.SwingTrend`, que es uno de los motores live activos y puede evaluarse con el histórico diario disponible, y volvió a probarlo con filtros daily, weekly y multi-timeframe.

La conclusión no es que los setups aumenten profits de forma consistente. En la política de régimen, el filtro diario moderado fue la única variante con una mejora media de retorno frente al baseline y también redujo drawdown; su mejora proviene principalmente de la ventana reciente y no aparece en el selloff. En el motor SwingTrend exacto, ninguna variante con setups aumentó el retorno frente al baseline en las ventanas con actividad: el filtro diario redujo ligeramente los beneficios y los filtros weekly/MTF fueron demasiado restrictivos. Por ello, los setups continúan en shadow y no se habilita `influence_entries`.

## Datos y diseño

Se usaron siete de los ocho símbolos del universo reto: AMD, BB, F, NOK, PLTR, TQQQ y TSLA. SOFI no pudo recuperarse del proveedor disponible y quedó declarado como faltante; no se inventaron barras para sustituirlo. Los históricos son OHLCV diarios reales cacheados, desde marzo de 2025 hasta agosto de 2026.

Las ventanas fueron lateralidad septiembre–diciembre de 2025, selloff enero–abril de 2026, periodo reciente abril–agosto de 2026 y los últimos 30 días disponibles hasta el 14 de agosto. Las variantes usaron temporalidad diaria, semanal con vela cerrada y MTF diaria+semanal. Los umbrales moderado/estricto fueron 0.35/1 confirmación y 0.55/2 confirmaciones, respectivamente.

Todas las señales se calcularon con información disponible hasta el día de decisión. Las posiciones se valoraron diariamente y se realizaron en el rebalance semanal. Se aplicó 0.2% de coste round-trip de equity y 5 bps de slippage por lado. El experimento no tiene cadenas históricas point-in-time, bid/ask ni fills de opciones; por tanto, sus retornos son una proxy de exposición al subyacente y no deben leerse como P&L real de spreads.

La configuración actual tomada del repositorio incluye `max_open_positions=2`, `max_risk_per_trade_pct=5`, DTE 10–45, deltas 0.25/0.10 y multiplicadores de prima 1.4/0.25. Los DTE y deltas quedan documentados como configuración, pero no se aplican a la proxy de equity porque no hay cadena histórica de opciones disponible.

## Prueba A: política actual de régimen + setups

El baseline `baseline_current` replica la política de régimen hold/cash con el límite actual de dos posiciones. Las variantes de setups solo permiten mantener exposición alcista si la confluencia cumple el filtro; nunca aumentan el número de posiciones ni el riesgo.

| Ventana | Baseline actual | Setup diario moderado | Setup semanal moderado | Setup MTF moderado |
|---|---:|---:|---:|---:|
| Lateral 2025 | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Selloff 2026 | **+0.91%**, DD −0.11% | −0.17%, DD −0.47% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Reciente 2026 | +4.20%, DD −2.39% | **+5.33%**, DD −0.92% | +1.79%, DD −1.42% | +3.09%, DD −0.70% |
| Últimos 30 días | −0.89%, DD −0.90% | **0.00%**, DD 0.00% | −0.66%, DD −0.67% | **0.00%**, DD 0.00% |

Con $100 iniciales, el caso más favorable del filtro diario moderado termina en aproximadamente $105.33 en la ventana reciente frente a $104.20 del baseline. En el selloff, en cambio, termina en aproximadamente $99.83 frente a $100.91 del baseline. En los últimos 30 días, evita la pérdida del baseline, pero no produce profit: termina en $100.00.

Agregado sobre las cuatro ventanas, el filtro diario moderado mejora el retorno frente al baseline en dos ventanas, empeora en una y queda igual en una sin operaciones. Mejora el drawdown en tres ventanas y no cambia una ventana sin exposición. Los filtros MTF reducen drawdown en las cuatro ventanas, pero mejoran el retorno solo en una; su retorno medio frente al baseline es negativo. Los filtros semanales también reducen drawdown, pero sacrifican retorno.

## Prueba B: SwingTrend live exacto + setups

Esta prueba usa `strategies.swing_trading.SwingTrend` sin reescribir sus reglas: SMA 20/50, filtro de precio sobre SMA 200, stop por ATR y objetivo por ATR. Se comparó con los mismos filtros de setups. Esta es la prueba más cercana a uno de los motores que realmente construye `bot.py` con el histórico disponible.

| Ventana | SwingTrend baseline | Setup diario moderado | Setup semanal moderado | Setup MTF moderado |
|---|---:|---:|---:|---:|
| Lateral 2025 | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Selloff 2026 | **+2.12%**, DD −1.06% | +2.03%, DD −0.74% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Reciente 2026 | **+4.45%**, DD −0.48% | +3.76%, DD −0.48% | +0.15%, DD −0.48% | +0.15%, DD −0.48% |
| Últimos 30 días | **+0.67%**, DD −0.13% | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |

El SwingTrend baseline fue mejor que todas sus variantes con setups en retorno. El filtro diario redujo la cantidad de operaciones de 5 a 4 en el selloff y de 6 a 4 en el periodo reciente. Aunque el win rate de algunas variantes fue alto, las muestras son pequeñas y un win rate alto con pocas operaciones no demuestra una ventaja estable.

## Interpretación

Los resultados sugieren que los setups pueden servir como **filtro defensivo**, porque en varias ventanas reducen la exposición y el drawdown. No muestran todavía capacidad consistente para aumentar profits cuando se añaden a la estrategia actual. El único resultado positivo claro de retorno fue el filtro diario moderado sobre la política de régimen durante el periodo reciente; queda contradicho por el selloff y por la prueba exacta de SwingTrend.

La decisión correcta es mantenerlos en shadow. No se habilita `influence_entries`, no se modifica el piso de equity, no se relajan los límites del RiskManager y no se despliega una variante como filtro PAPER basándose en esta ronda. La siguiente prueba, si se desea promocionar alguna hipótesis, debe usar datos intradía históricos para los motores DayMomentum y DayBreakout, además de cadenas de opciones point-in-time con bid/ask y fills realistas.

## Qué significa drawdown

El **drawdown** es la caída desde el punto más alto que había alcanzado una cuenta o estrategia hasta un punto posterior de menor valor. No mide solo si la estrategia terminó con profit; mide cuánto dolor o pérdida temporal tuvo que soportar en el camino.

Por ejemplo, si una cuenta sube de $100 a $110 y después baja a $104, su drawdown máximo es de $6 desde el máximo de $110, es decir, aproximadamente −5.45%. Aunque la cuenta todavía tenga profit frente a los $100 iniciales, el drawdown indica que en algún momento perdió parte importante de lo que había ganado.

| Concepto | Ejemplo con $100 |
|---|---:|
| Equity inicial | $100 |
| Máximo alcanzado | $110 |
| Caída posterior | $104 |
| Drawdown en dólares | −$6 desde el máximo |
| Drawdown porcentual | −5.45% desde el máximo |
| Profit final frente al inicio | +$4, o +4% |

Un drawdown menor suele significar una trayectoria más estable y menos riesgo de que la cuenta llegue al piso de protección. Sin embargo, **reducir drawdown no equivale automáticamente a ganar más**: una estrategia puede perder menos porque opera menos y, al mismo tiempo, ganar mucho menos. Eso es exactamente lo que aparece en varias variantes semanales y MTF de este experimento.

## Archivos reproducibles

El arnés de la primera prueba es `scripts/run_current_setup_integration_backtests.py`. El arnés del motor live exacto es `scripts/run_live_swing_setup_backtests.py`. Los resultados, curvas, trades y manifiestos se guardaron bajo `/home/ubuntu/backtests/` con los prefijos `current_setup_integration_2026-08-18` y `live_swing_setup_2026-08-18`.
