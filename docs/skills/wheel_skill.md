# Skill: The Wheel (cash-secured puts → covered calls)

**Referencias:** `options/strategy.py`, `options/chains.py` (`SpreadBuilder`), y la investigación de opciones avanzadas de la carpeta Abacus del Google Drive del dueño.

## 1. Concepto y ciclo

The Wheel es el ciclo sistemático de recolección de primas sobre acciones que el operador está dispuesto a poseer. Su ventaja estructural es que **nunca se queda sin dirección**: si el put expira worthless, se repite; si es asignado, el operador pasa a vender calls sobre las acciones. Cada paso genera ingreso y la estrategia solo pierde si el subyacente cae más que la prima recolectada acumula.

El ciclo completo: (1) vender un **cash-secured put** OTM sobre un activo de buena calidad; (2) si expira worthless, volver a (1); (3) si es asignado, vender un **covered call** OTM sobre las acciones; (4) si el call es asignado, volver a (1) con el capital recuperado más la diferencia.

## 2. Parámetros calibrados en los backtests

La calibración provino de la serie de backtests S1–S89 (ver `docs/skills/backtest_skill.md`). Los valores que siguen siendo referencia:

| Parámetro | Valor | Racional |
|---|---|---|
| Delta del strike vendido | **0.30** (long 0.30 / short 0.10 en spreads) | Balance entre prima recolectable y probabilidad de asignación |
| DTE del contrato | **21 días** (puts defensivos CHoCH) | Suficiente para decaimiento de theta sin exponerse a gamma de vencimiento |
| DTE operativo general | 10–45, con cierre a 7 DTE (`close_dte`) | Ni theta extremo de los últimos días ni vega de más |
| Presupuesto por prima neta | **$12** (reto $100) / ~30% del capital (CHoCH puts, S63) | Solo BB, NOK, F, SOFI son operables dentro del presupuesto con capital pequeño |
| Gestión TP/SL de prima | TP **+40%** (`prem_tp_mult: 1.4`) / SL **−75%** (`prem_sl_mult: 0.25`) | El backtest B perdió 93% de la prima en LCID por no tener stop de prima |
| Riesgo por trade | 5% del capital (`max_risk_per_trade_pct`) | Reducido desde 20% tras la integración S78 |

## 3. Reglas de gestión aprendidas (hallazgos 16–18)

**DTE corto OTM es un error.** La estrategia S67 (DTE 7–10 días OTM) destruyó -48% en backtest: el theta de los últimos días consume la prima antes de que la dirección se materialice. La ventana óptima para spreads defensivos es DTE 21.

**Las comisiones importan.** Alpaca cobra ~$0.65 por pata; un spread completo (entrada + salida, 2 patas cada una) cuesta $2.60. En spreads baratos del reto ($12 de prima), las comisiones representan el 6–33% del capital desplegado. Por eso los **puts defensivos con comisiones solo quedaron en break-even (+2.6% en S63)**: se operan solo como defensa en régimen CHoCH bear, no como motor de ingreso con capital de $100.

**El RV alto encarece las defensivas.** En mercado bear suave sin CHoCH (ej. abr–ago 2026), la volatilidad realizada infla el precio de los put spreads. S76 (-6.6%) y S75 (-32.9%) operaban defensivas en ese régimen; S78 (+26.7%) ganó simplemente **quedándose en cash**. Regla: **no vender puts defensivos en bear suave HTF** — cash + hold solo si el régimen local es bull.

**El gap de apertura no se puede cortar.** El peor caso real (entrar el día del rebalance con caída -17% intradiaria tras un rally falso de +2%) pasa de -2.7% de drawdown a break-even positivo (+0.5%) con el stop intradiario del 4%, pero ningún stop detiene el salto de apertura. Única defensa estructural: reducir exposición en regímenes no-bull.

## 4. Integración con SMC

El flujo de decisión combinado es: las señales SMC (sección 3 de `docs/skills/smc_skill.md`) definen la **dirección**; The Wheel define la **estructura** que la expresa.

| Régimen | Estructura | Referencia |
|---|---|---|
| Bull (RSI>50, precio>SMA200, universo) | Call debit spread 0.25/0.10, DTE 10–45, cierre 7 DTE | S51 (+92% en 90 días) |
| CHoCH bear (≥30% del universo) | Put spread 0.30/0.10, DTE 21, budget 30% equity, máx 2 pos, TP 1.5/SL 0.5 | S63 (+20.8% en selloff ene–abr 2026) |
| Lateral | Cash — no operar | S55 (S36: 0 trades, capital intacto) |
| Rebote en selloff | **ATRIBUCIÓN CORREGIDA — ver aviso abajo** | S36 mide `smc_daily`, no rebote |
| Bear suave HTF (bajo SMA200 sin CHoCH) | Cash + hold solo si bull local | S78 (+26.7%, ganador reciente) |

> **AVISO (17 ago 2026): la fila de "rebote en selloff" era incorrecta.** Esta
> tabla atribuía a S36 la condición «RSI<25 y precio>SMA100» con +53–60% y win
> 71–75%. Dos problemas comprobados: (1) en el código **S36 es
> `motor="smc_daily"`**, no un motor de rebote, así que esas cifras pertenecen a
> otra estrategia; (2) la condición documentada **no puede dispararse**: se
> implementó como motor `rebote_doc` y dio **0 operaciones en 4.928 días-ticker**
> (2024-02 → 2026-08, universo reto). La causa es estructural, no de muestra —
> cuando el RSI cae por debajo de 25 (mínimos históricos 13,9–24,7) el precio ya
> está **por debajo** de su SMA100; las dos cláusulas se excluyen entre sí.
> Incluso relajando a RSI<30 salen 0 ocurrencias; hacen falta RSI<35 para 5 y
> RSI<40 para 53. Por eso el repo tiene `rebote_rsi40`: alguien ya había
> descubierto que el umbral debía relajarse, pero la documentación siguió
> citando la condición original. **No usar esta fila para calibrar nada.**

## 5. Errores conocidos

| Error | Consecuencia | Corrección |
|---|---|---|
| Sin stop de prima | Posición LCID decayó a -93% de la prima | SL de prima al 25% + cierre a 7 DTE + cierre a mitad de vida sin ganancia |
| Spreads degenerados en simulador | Vol. ~150% empujaba strikes 46% OTM y el net caía a ~0 | `max_vol_pct: 100`, exclusión de LCID/MARA |
| Rebalanceo diario del benchmark | El mismo precio se recompraba el mismo día (-67%/-96%) | Rebalanceo semanal (S57/S58: -6.8% selloff, +9.7% lateral) |

## 6. Criterios de uso por el agente

Antes de montar cualquier estructura Wheel verificar: (1) el régimen global permite operar (solo bull/CHoCH-rebote tienen luz verde para entradas nuevas); (2) el subyacente está fuera de `earnings_horizon_days` (2 días antes de earnings no se entra — el material advierte de la volatilidad de earnings y el filtro lo bloquea automáticamente); (3) la prima neta cabe en el presupuesto del perfil activo; (4) el delta del strike no excede 0.30 para la pata vendida salvo spreads de rebote; (5) existe TP/SL de prima configurado. Nunca vender premium en cash-secured puts sobre tickers con vol. anualizada >100%.


## 7. Auditoría del PDF fuente y estado de integración — 18 ago 2026

La fuente primaria del material revisado es `The Wheel.pdf` en Google Drive, archivo de 9 páginas. El documento describe el ciclo CSP → asignación de 100 acciones → covered call → acciones llamadas → reinicio; menciona selección según capital, análisis técnico/fundamental, evitar earnings/noticias de alto impacto, ROC aproximado de 1–2% mensual sobre colateral, deltas de 0.20 o menores y roll/recompra como defensa.

Esta skill cubre esas reglas y añade parámetros de Polaris y resultados de investigación. La existencia de esta skill no significa que el bot opere The Wheel. El módulo relacionado `strategies/options_income.py` contiene `WheelStrategy`, estados CSP/CC, filtros de earnings/SMA200, DTE 21–45, delta máximo 0.20 y ROC mínimo 1%, pero no está instanciado por `bot.py::build_strategies()`.

Estado real: **documentada = sí; módulo = sí; conectada al loop = no; activa en PAPER = no**. La configuración live instancia `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend`, además del motor bajista separado; no existe `wheel.enabled`. Antes de activar Wheel se necesita persistencia y reconciliación de acciones asignadas, control de colateral por lotes de 100 acciones, gestión de exercise/assignment, roll como operación de dos patas, filtros point-in-time de earnings/noticias y pruebas PAPER específicas. No cablear el módulo automáticamente ni tratar sus reglas educativas como una autorización de órdenes.


## 8. Skill reutilizable y backtest con opciones históricas — 18 ago 2026

La skill reutilizable para futuras tareas está en `/home/ubuntu/skills/the-wheel/SKILL.md`, validada con `quick_validate.py`. Incluye las referencias `research.md` y `polaris-alpaca.md`, con fuentes OCC/OIC, Cboe, Alpaca y límites de datos.

El backtest de esta ronda utilizó barras históricas reales de opciones Alpaca: 467 contratos seleccionados, 451 con barras y 9,799 barras diarias sobre AMD, BB, F, NOK, PLTR, TQQQ y TSLA entre abril y agosto 2026. Se probaron cinco escenarios y cinco ventanas. El escenario base con capital $100,000 obtuvo +5.33% medio en 5/5 ventanas positivas, pero superó buy-and-hold solo 2/5; en full recent hizo +12.84% frente a +57.99% de buy-and-hold. En summer trend hizo +6.24% frente a −14.08% del buy-and-hold. Con $100 no hubo operaciones: el colateral de 100 acciones hace inviable la Wheel clásica para ese tamaño.

La selección por moneyness 5%/10% sustituye delta histórica ausente; faltan bid/ask point-in-time, listing timestamp y early assignment observado. Clasificación: `RESEARCH_ONLY`. No activar Wheel en Polaris sin reconciliación persistente de NTA/assignment, lotes de 100 acciones, colateral real, dividendos/earnings as-of, roll idempotente y pruebas PAPER.
