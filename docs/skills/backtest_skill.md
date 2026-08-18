# Skill: Backtesting y calibración de estrategias

**Archivos de referencia:** `loop_backtests.py` (motor S1–S89), `backtest_retos.py` (precios Black-Scholes), `stress_test.py` (crashes sintéticos, hallazgo 17), `stress_intraday.py` (stops intradiarios, hallazgo 18), y los informes `/home/ubuntu/backtests/hallazgo1.md..18.md`. En esta sandbox, `/home/ubuntu/backtests/` está vacío al iniciar una sesión nueva: los CSV deben regenerarse y conservarse como artefactos versionados o en almacenamiento persistente.

> **Matriz reproducible disponible desde el 15 ago 2026 en `docs/backtests/2026-08-15/`** (151 CSV: resumen + trades/equity por escenario), con informe en `docs/hallazgo21_regeneracion_backtests_2026-08-15.md`. Siete de los ocho escenarios titulares reproducen dentro de ±3 puntos; el único que no era reproducible, S51, quedó corregido (ver §3).

> **Nota de datos (sandbox de Claude Code):** yfinance no funciona aquí — `curl_cffi` choca con la intercepción TLS del proxy (`Recv failure` en todos los tickers) y sin imitación de navegador Yahoo responde 429. Usar la cascada `_segmented` de `data/feed.py` con credenciales de Alpaca desde Secret Manager (`alpaca-key` / `alpaca-secret`). Coste: falta el tramo reciente que solo Yahoo cubre, así que las ventanas terminan ~2 sesiones antes de hoy; declararlo en cada informe.

## 1. Herramientas y qué mide cada una

| Script | Qué hace | Para qué sirve |
|---|---|---|
| `loop_backtests.py` | Ejecuta la serie S1–S89 sobre datos reales de yfinance del universo reto | Comparar motores de decisión: hold, cash, put CHoCH, rebote, régimen-aware |
| `backtest_retos.py` | Señales reales del motor + precios simulados Black-Scholes con vol. histórica de yfinance (margen 20%) | Calibrar deltas, DTE, TP/SL de primas con comisiones modeladas |
| `stress_test.py` | Inyecta crashes sintéticos (E1–E4) reemplazando barras reales del feed | Validar defensas de crash event ante escenarios no vistos en historia |
| `stress_intraday.py` | Mismo marco sintético con stops intradiarios 4/6/8/10% | Elegir el umbral óptimo de stop intradiario |

> Advertencia permanente: las primas de `backtest_retos.py` son simuladas (BS con IV = vol. histórica + margen 20%) y las comisiones están modeladas, no reales. Sirven para comparar calibraciones, **no para estimar P&L real**.

## 2. Metodología de ventanas (crítica)

Los backtests usan cuatro ventanas con comportamientos de régimen distintos, y la conclusión cambia según la ventana — por eso se exige evaluar **todas**:

| Ventana | Régimen dominante | Comportamiento del motor |
|---|---|---|
| 90 días estándar | Mixto | Comparador base |
| Selloff ene–abr 2026 | Bajada sostenida con rebotes | Solo defensas (puts CHoCH) positivas |
| Lateral sep–dic 2025 | Sin tendencia | Hold destruye; cash gana |
| Reciente abr–ago 2026 | Bear suave HTF (bajo SMA200 sin CHoCH) | El ganador es cash + hold selectivo (S78) |

## 3. Resultados consolidados S1–S89 (la calibración definitiva)

| Estrategia | Perfil | Resultado clave |
|---|---|---|
| **S51** (hold semanal equally weighted, universo reto) | Bull | **Regenerado 15 ago 2026: +3.6%, 105 trades, dd −10.2%.** El +92% histórico era un artefacto del motor legacy `hold`, que concentraba el capital en una sola posición (+92.5% con dd −63.5%); con `hold_weekly` explícito el benchmark real es +3.6%. No volver a citar el +92%. |
| **S63** (put spread 0.30/0.10, DTE 21, trigger CHoCH pragmático) | CHoCH bear | +20.8% en selloff ene–abr 2026 (única positiva; con comisiones +2.6%) |
| **S36** | Rebote (atribución errónea) | En el código S36 es `motor="smc_daily"`, NO un motor de rebote. La condición «RSI<25 + precio>SMA100» que se le atribuía da **0 operaciones** en 4.928 días-ticker: al caer el RSI bajo 25 el precio ya está bajo su SMA100, así que las cláusulas se excluyen. Ver aviso en `wheel_skill.md` §4. |
| **S55** (cash en lateral) | Lateral | S36: 0 trades, capital intacto vs hold -96% |
| **S67** (DTE 7–10 OTM) | — | -48%: el theta de los últimos días destruye |
| **S75/S76** (defensivas en bear suave HTF) | Bear suave | El filtro `cheap_min_net=28` estaba declarado pero ignorado; ya está conectado al motor y los resultados deben regenerarse. |
| **S78** (bull→hold, bear→cash) | Régimen-aware | **+26.7% en ventana reciente (ganador)**; dd -28.0% con crash_event 3% |

La regla de oro histórica debe tratarse como hipótesis hasta regenerar los escenarios con el motor corregido. Las primas del backtest siguen siendo proxies Black–Scholes con IV histórica, no cadenas point-in-time. Con $100 de capital, slippage, comisiones y disponibilidad real de contratos pueden cambiar completamente la operabilidad; no asumir que un ticker es operable solo por su prima simulada.

## 4. Prueba de estrés de crash (hallazgo 17, `stress_test.py`)

Escenarios sintéticos inyectados sobre el feed real del universo reto (las barras sintéticas **reemplazan** las reales de las mismas fechas, con alineación fila a fila y hora igual al histórico — el bug antiguo que concatenaba con tz desalineada corrompía la cronología y está corregido):

| Escenario | Perfil | S78 base | S78 mitigado (crash_event 3% + cooldown 5d) |
|---|---|---|---|
| E1 Flash | -20% en 1 día | $90.0 (dd -24.4%) | $96.1 (dd -4.3%) |
| E2 Severo | -35% en 5 días + rebote +50% | $116.6 (+16.6%) | $138.3 (+38.3%, dd 0%) |
| E3 Catastrófico | -50% en 3 días sin rebote | $54.6 (-45.4%) | límite físico (cae antes de cortar) |
| E4 Realista | -30% en 20 días + rebote débil | $116.8 | $116.6 (dd 0%) |

Conclusión: el CHoCH protege en selloffs negociables (2–4 semanas) pero **no en flash crashes de ≤3 días** — la estructura HI/LO no existe durante un pánico repentino y la reacción llega 2–5 días tarde. Validado en ventana real abr–ago 2026: drawdown mejora de -40.3% a -28.0% con equity superior ($128.9 vs $126.7). E3 es el límite físico de cualquier estrategia de cierre diario.

## 5. Stops intradiarios (hallazgo 18, `stress_intraday.py`)

Umbrales probados sobre `(1-ith)×close_prev` del subyacente, medibles en producción con el stream de equity de Alpaca (gratuito en el plan Basic):

| Escenario | Base | **4%** | 6% | 8% | 10% |
|---|---|---|---|---|---|
| E1 Flash | $96.1 (dd -4.3%) | **$97.9 (dd -2.8%)** | $96.5 | $96.3 | $96.1 |
| E2 Severo +rebote | $138.3 | **$141.6 (+41.6%, dd 0%)** | igual | $132.3 | $129.7 |
| E3c rebal día 1 + shock | $97.3 (dd -2.7%) | **$100.5 (+0.5%, dd 0%)** | $98.6 | $97.6 | $97.4 |
| Real abr–ago 2026 | $128.9 (dd -7.3%) | **$132.5 (+32.5%, dd -4.8%)** | $130.6 | $129.0 | $128.9 |

Conclusión histórica: **4% fue el umbral óptimo en esos escenarios sintéticos**, no una garantía fuera de muestra. El gap de apertura no se detiene (ya consumado antes del stream): el stop solo acorta el resto del día. Defensa adoptada para PAPER: `crash_event` 3% (cierre) + `intraday_stop` 4% + trailing de prima 30–40%, sujeto a nueva validación tras corregir el motor.

## 6. Contexto de mercado fechado

El contexto de noticias para la ronda del 15 de agosto de 2026 está en `docs/market_context_2026-08-15.md`. Reuters y CNBC describen un selloff tecnológico con rebote incompleto el 9 de junio y un máximo concentrado en AI/chips el 13 de agosto. Estas notas sirven para etiquetar ventanas de momentum unwind, rebote, concentración y riesgo geopolítico; no son variables de entrada automáticas.

En cada backtest, guardar la fecha de decisión y usar únicamente información disponible hasta esa fecha. La noticia posterior se puede citar en el informe de resultado, pero no en la lógica que decide la operación histórica. Los datos de earnings actuales de yfinance no son point-in-time y deben excluirse de las corridas primarias o marcarse como proxy retrospectivo.

## 7. Breakout y ensembles de investigación

`breakout20` y `breakout55` son motores de investigación, no de producción. Una entrada exige que el cierre de la fecha de decisión supere el máximo de las `lookback` barras anteriores y que el volumen sea al menos 1.2x la referencia; ambos cálculos deben usar solo filas `<= d`. La salida de investigación usa pérdida de SMA20. Toda corrida debe reportar slippage, riesgo y número de operaciones.

Los ensembles fijos de `regime_hold_cash` con breakout20/55 se evalúan como investigación separada. Los pesos no se pueden elegir sobre el test. La selección se realiza en train/validation, con mínimo de operaciones por split, y el peso elegido se mide en test fuera de muestra. Un retorno positivo en una sola ventana o una meta $100→$200 no es evidencia suficiente.

## 8. Reglas para el agente orquestador

Ningún cambio de parámetro de estrategia entra en producción sin: (1) pasar por las cuatro ventanas de backtest; (2) pasar por E1–E4 y E3c si toca los stops; (3) validarse en la ventana más reciente; (4) documentar el informe con resultados reproducibles. Cada ronda debe incluir anti-look-ahead, fecha de decisión, comisiones, slippage y sensibilidad. El filtro anti-earnings de producción usa un calendario actual de yfinance y no es point-in-time; no inyectarlo sin más en historia. Los cierres o lambdas dentro de barridos deben evitar capturas tardías de variables (B023). La estrategia puede cambiar con los datos, pero no se debe perseguir $100→$200 mediante sobreajuste ni presentar una meta como rentabilidad esperada.


## 9. Comparación A/B reproducible

Usar `scripts/run_ab_comparison.py` para comparar un baseline y un candidato sin tocar Cloud Run ni enviar órdenes. El script descarga el dataset una sola vez, exige que ambos brazos tengan las mismas ventanas, conserva el commit, proveedor, universo y hash de los datos, y genera un CSV emparejado más un manifiesto JSON.

Ejemplo:

```bash
cd /home/ubuntu/bot-trading
export PYTHONPATH="$PWD"
python3 scripts/run_ab_comparison.py \
  --baseline-key regime_hold_cash_recent_2026 \
  --candidate-key breakout55_recent_2026_r15 \
  --output-prefix ab_recent_2026
```

Para un ajuste propio, pasar `--baseline-json` y `--candidate-json` con el mismo número y orden de ventanas. Cada brazo debe declarar motor, universo, fechas, riesgo, DTE, deltas, TP/SL, comisión, slippage y coste equity. No se permite elegir el ganador mirando solo la ventana de test.

El resultado debe evaluarse por retorno neto, drawdown peak-to-trough, número de operaciones, win rate, profit factor, sensibilidad a slippage y estabilidad fuera de muestra. El candidato no se promueve por tener mayor retorno aislado: debe mejorar o no degradar materialmente el drawdown, sobrevivir a costes, mantener suficiente muestra y superar una validación walk-forward. Todo ajuste que llegue a PAPER debe conservar una feature flag y permitir volver al baseline sin cambiar el `RiskManager`.

El smoke A/B del 17 de agosto de 2026 comparó `regime_hold_cash_recent_2026` frente a `breakout55_recent_2026_r15` sobre `2026-04-01..2026-08-14`, con un único dataset y sin órdenes. El baseline terminó en `129.186` (+29.186%, 152 trades, drawdown -25.0933%); el candidato en `127.4964` (+27.4964%, 14 trades, drawdown -25.4729%). Es una comprobación del arnés, no evidencia para promover breakout. El artefacto está en `/home/ubuntu/backtests/ab_smoke_recent_2026_20260817T184708Z.csv` y su manifiesto JSON homónimo.


## 10. Backtest de la capa completa de setups — 18 ago 2026

El script `scripts/run_setup_backtests.py` evalúa los doce componentes de `strategies/setup_confluence.py`: `key_level`, `break_and_retest`, `order_block`, `bos`, `choch`, `liquidity_sweep`, `ema_cross`, `ema_cloud`, `vwap`, `volume_proxy`, `fibonacci_ote` y `trendline_channel`. La corrida es research-only y trabaja sobre el subyacente; no modela fills de opciones, bid/ask, assignment, latencia ni disponibilidad point-in-time de cadenas.

### Procedimiento

1. Cachear históricos reales en `/home/ubuntu/backtests/setup_history/*.pkl`; nunca crear barras sintéticas para completar un símbolo.
2. Registrar en el manifiesto el universo esperado, el universo utilizado y cualquier ticker faltante.
3. Para cada símbolo y ventana, mantener warmup anterior al inicio de la ventana para EMA/ATR/estructura, pero publicar retornos solo desde la fecha de inicio.
4. Calcular la observación con filas `<= t` y aplicar la posición a la variación de cierre `t → t+1`.
5. Descontar 5 bps por unidad de cambio de posición en `setup_moderate` y `setup_strict`; declarar que `buy_hold` es el control de exposición alcista, no un benchmark de opciones.
6. Exportar métricas, dirección agregada, actividad por componente y un manifiesto JSON. Ejecutar después `scripts/analyze_setup_backtests.py`.
7. Rechazar promoción si solo existe mejora en una ventana, si el drawdown no mejora materialmente, si el universo es incompleto sin declararlo, o si el resultado no sobrevive sensibilidad y walk-forward.

### Resultado reproducible de la primera matriz

La ejecución final usó siete de ocho símbolos porque `SOFI` no se pudo recuperar del proveedor disponible; el faltante se registra en `setup_confluence_backtests_2026-08-18.json`. Los resultados fueron:

| Ventana | Buy-and-hold | Setup moderate | Setup strict |
|---|---:|---:|---:|
| Lateral 2025 | +25.9695%, DD −17.2397% | +0.3597%, DD −10.5601% | −3.1216%, DD −11.9175% |
| Selloff 2026 | +22.9870%, DD −16.0482% | +5.1687%, DD −7.0323% | +4.4494%, DD −7.3239% |
| Reciente 2026 | +61.1543%, DD −25.4978% | +15.1953%, DD −14.3550% | +18.1615%, DD −10.4369% |
| Últimos 30 días | −4.7056%, DD −20.1163% | −2.8449%, DD −8.6640% | −1.4434%, DD −7.5748% |

La conclusión es `RESEARCH_ONLY`: los setups redujeron drawdown en las cuatro ventanas, pero solo superaron retorno en la última ventana y ambos resultados fueron negativos. No habilitar `influence_entries`, no llamar a esto alfa y no usar la meta `$100 → $200` como criterio de promoción.

El informe está en `docs/setup_confluence_backtest_2026-08-18.md`. Los artefactos son `setup_confluence_backtests_2026-08-18.csv`, `setup_confluence_direction_counts_2026-08-18.csv`, `setup_confluence_component_activity_2026-08-18.csv`, `setup_confluence_analysis_2026-08-18_comparison.csv`, `setup_confluence_analysis_2026-08-18_component_summary.csv` y `setup_confluence_backtests_2026-08-18.json` bajo `/home/ubuntu/backtests/`.

El A/B de setups no debe ejecutarse todavía con `run_ab_comparison.py` sin un adaptador: ese arnés entiende motores de `run_scenario`, mientras que `analyze_setup_confluence` es un motor puro de observaciones. El adaptador futuro debe conservar un dataset compartido, commit, hash, ventanas, costes, slippage, train/validation/test y una bandera PAPER reversible.


## 11. Integración de setups sobre la estrategia actual — 18 ago 2026

Cuando el usuario pida saber si los setups ayudan al bot actual, no basta con ejecutar una estrategia de setups aislada. El experimento debe incluir al menos un baseline que conserve la política de Polaris y un candidato que solo añada el filtro de setups, sin cambiar riesgo, número máximo de posiciones, sizing ni lógica de ejecución.

En la ronda del 18 de agosto se probaron dos referencias. `scripts/run_current_setup_integration_backtests.py` conserva `regime_hold_cash`: bull → exposición semanal; bear/cash → efectivo; detector de crash y máximo de dos posiciones. `scripts/run_live_swing_setup_backtests.py` utiliza el código real `SwingTrend` de `strategies/swing_trading.py`: SMA20/50, filtro SMA200, stop y objetivo por ATR.

Las variantes cubren setups diarios, semanales con velas cerradas y MTF diaria+semanal. Se comparan umbrales moderate/strict y se registran retorno neto, máximo drawdown, trades, win rate, profit factor, señales y tiempo en mercado. El resultado debe leerse en dos dimensiones: retorno incremental frente al baseline y drawdown incremental. Una variante que termina con más dinero pero con drawdown mucho mayor no es automáticamente mejor; una que reduce drawdown pero gana menos tampoco prueba que aumente profits.

Resultado de esta ronda: sobre la política regime-hold/cash, el filtro diario moderado dio +5.33% frente a +4.20% en la ventana reciente y redujo drawdown de −2.39% a −0.92%, pero perdió −0.17% frente a +0.91% en el selloff. Sobre el SwingTrend live exacto, el baseline superó a todas las variantes con setups en retorno: +2.12% vs +2.03% en el selloff, +4.45% vs +3.76% en la ventana reciente y +0.67% vs 0.00% en los últimos 30 días. La clasificación es `RESEARCH_ONLY`; no promover.

Debido a la ausencia de opciones históricas point-in-time, estos resultados usan proxy de exposición al subyacente. No presentar el resultado como P&L de spreads. La siguiente etapa, antes de una feature `paper_filter`, debe conseguir históricos intradía para los motores 5m/15m, cadenas point-in-time con bid/ask/fills, o declarar explícitamente que el test sigue siendo un proxy.


## 12. Backtest de The Wheel con barras históricas de opciones — 18 ago 2026

Para The Wheel no es suficiente un backtest de subyacente o un cálculo de ROC de prima. La ronda reproducible debe descargar contratos y barras históricas point-in-time cuando sea posible, seleccionar vencimiento/moneyness con información as-of, vender CSP, modelar assignment y crear lotes de 100 acciones, vender CC cubiertas, modelar call assignment/retención de stock, roll como cierre+apertura y aplicar comisiones y slippage.

Se ejecutó `scripts/cache_wheel_option_history.py` con Alpaca en solo lectura y `scripts/run_wheel_backtests.py` sobre siete símbolos y cinco ventanas recientes. La API entregó 467 contratos seleccionados, 451 con barras y 9,799 barras diarias. La delta histórica no estaba disponible as-of; se usó moneyness 5%/10% como proxy declarado. Faltan bid/ask históricos, timestamp de listing y early assignment observable; el resultado es `RESEARCH_ONLY`, no P&L institucional ni aprobación live.

El escenario `wheel_base` con $100,000 obtuvo +5.33% de retorno medio en 5 ventanas, 5/5 ventanas positivas y drawdown medio −0.35%, pero superó buy-and-hold solo en 2/5. En la ventana full recent hizo +12.84% frente a +57.99% de buy-and-hold; en summer trend hizo +6.24% mientras buy-and-hold perdió −14.08%. El escenario stress llegó a −8.71% de peor drawdown y acumuló 71 data gaps; no seleccionar parámetros por ese resultado.

La sensibilidad con $100 produjo cero operaciones, porque la Wheel cash-secured exige colateral para comprar 100 acciones. Con $1,000 la actividad fue muy limitada. Para comparar contra el bot, informar siempre cash, buy-and-hold, retorno total, drawdown, asignaciones, stock P&L, primas, rolles, data gaps, capital comprometido y tiempo en cada fase. No promover por retorno de una sola ventana.


## 13. Matriz de spreads y estructuras de riesgo definido — 18 ago 2026

Para comparar alternativas a The Wheel se debe probar una matriz que cruce familia, DTE, ancho, régimen y gestión de salidas. La ronda actual usó 10 familias —debit spreads, credit spreads, iron condor, butterfly, calendar y diagonal—, DTE 14/30/45, moneyness 5%/10%, gestión conservadora/base/agresiva y regímenes gated/neutral_ok, en cinco ventanas. Se ejecutaron 1,800 combinaciones con 3,626 contratos seleccionados y 73,119 barras Alpaca.

La selección principal de full_recent fue bull call debit 45 DTE/5%/conservadora/gated con +4.62% y drawdown −0.77%, pero tuvo 37 data gaps y no debe promoverse. La variante más consistente fue bear call credit 30 DTE/10%/conservadora/gated: +0.46% medio en cinco ventanas, 4/5 positivas, peor retorno 0.00%, drawdown medio −0.10% y 12 data gaps; full_recent +0.89% frente a buy-and-hold +57.99%. Es defensiva, no una mejora de profits.

Iron condor 45 DTE/5% conservador y put diagonal 14 DTE/10% conservador son candidatos secundarios. Calendars y butterflies fueron débiles en la muestra. No seleccionar por max retorno en una ventana: exigir retorno positivo o no negativo en la mayoría de ventanas, data gaps bajos, drawdown acotado, profit factor no dependiente de cero pérdidas y prueba walk-forward con bid/ask, IV/delta point-in-time, listing timestamp y eventos corporativos as-of.
