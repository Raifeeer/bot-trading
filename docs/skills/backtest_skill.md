# Skill: Backtesting y calibración de estrategias

**Archivos de referencia:** `loop_backtests.py` (motor S1–S89), `backtest_retos.py` (precios Black-Scholes), `stress_test.py` (crashes sintéticos, hallazgo 17), `stress_intraday.py` (stops intradiarios, hallazgo 18), y los informes `/home/ubuntu/backtests/hallazgo1.md..18.md`. En esta sandbox, `/home/ubuntu/backtests/` está vacío al iniciar una sesión nueva: los CSV deben regenerarse y conservarse como artefactos versionados o en almacenamiento persistente.

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
| **S51** (hold semanal equally weighted, universo reto) | Bull | Resultado histórico publicado +92%, pendiente de regenerar; el motor ahora usa explícitamente `hold_weekly` y ya no el benchmark legacy de una sola posición. |
| **S63** (put spread 0.30/0.10, DTE 21, trigger CHoCH pragmático) | CHoCH bear | +20.8% en selloff ene–abr 2026 (única positiva; con comisiones +2.6%) |
| **S36** (call spread 0.30/0.10, DTE 21, RSI<25 + precio>SMA100) | Rebote | +53–60%, win rate 71–75%, budget 15% |
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
