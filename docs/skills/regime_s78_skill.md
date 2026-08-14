# Skill: Régimen S78 (regime-aware hold/cash) y defensas de crash

**Archivos de referencia:** `risk/regime.py`, `risk/floor.py`, y la integración en `bot.py` (paso 0 del tick principal).
**Origen:** backtest S78 (regime-aware: bull→hold, bear→cash), ganador de la ventana real abr–ago 2026 (+26.7%, drawdown -7.3%), más los hallazgos de estrés 17 y 18.

## 1. Por qué existe

Los backtests S1–S89 mostraron que **ningún motor único sobrevive a todos los regímenes**: S51 (hold semanal) ganó en bull (+92% en 90 días) pero sufrió en selloffs; S63 (puts CHoCH) fue el único positivo del selloff de ene–abr 2026; S36 (rebote) explotó los rebotes con RSI<25; y en lateral el hold destruyó -96% con rebalanceo diario. La estrategia S78 unifica todo en un **disyuntor de régimen**: el bot primero clasifica el estado global del universo y solo después decide si puede entrar.

| Régimen | Condición técnica | Acción | Evidencia |
|---|---|---|---|
| **Bull** | RSI14>50 + precio sobre SMA200 en ≥50% del universo | Entradas permitidas (call spreads debit 0.25/0.10) | S51: +92% en 90 días |
| **CHoCH bear** | Cierre bajo swing LOW con HI dominante <60 días, en ≥30% del universo | Defensivo: puts 0.30/0.10 DTE 21 (solo si RV lo permite); máx 2 posiciones | S63: +20.8% en selloff ene–abr 2026 |
| **Bear suave HTF** | Precio bajo SMA200 sin CHoCH estructural | **Cash** + hold solo si el régimen local es bull. NO puts (RV alta encarece spreads) | S78: +26.7% vs S75 -32.9% |
| **Lateral** | Ni bull ni bear | Cash, no operar | S55: S36 0 trades, capital intacto vs hold -96% |
| **Rebote en selloff** | RSI14<25 + precio sobre SMA100 | Call spread 0.30/0.10 DTE 21, budget 15% del equity | S36: +53–60%, win 71–75% |
| **Crash event** | ≥30% del universo cae ≥3% en 2 sesiones de cierre | Corte inmediato a cash, cool-down de 5 días | Hallazgo 17 |

## 2. Implementación en producción (`risk/regime.py`)

`classify_regime(data_1d, tickers, cfg)` se ejecuta en cada tick del bot sobre datos diarios del universo (el feed pide 400 días para cubrir el SMA200 con margen). Los parámetros por defecto de `DEFAULT_REGIME_CFG`:

```python
"crash_event_pct": 0.03,      # umbral de caída crash_event (3%)
"crash_cooldown_days": 5,     # días de cool-down tras activar crash_event
"intraday_stop_pct": 0.04,    # umbral stop intradiario (4%) — hallazgo 18
```

La salida del clasificador es un dict con `regime` (bull/bear), `summary`, `crash_event` (bool), `crash_active` (bool), `intraday_cuts` (lista de tickers cuyo low intradiario rompió el umbral) y `floor` (resultado de la guarda de piso de equity).

**Persistencia del crash_lock.** `apply_crash_cooldown(regime, bot_state)` persiste la fecha de activación en el estado del bot: si el crash_event se disparó, escribe la fecha en el state; mientras `(today - lock_date).days < 5`, el régimen permanece forzado a cash aunque los datos ya no lo marquen. Esto evita re-entradas prematuras tras pánicos en fases y sobrevive a reinicios del contenedor.

**Stop intradiario del 4% (hallazgo 18).** La validación se hizo con `stress_intraday.py` probando umbrales 4/6/8/10% sobre `(1 - ith) × close_prev` del subyacente:

| Escenario | Base | Stop 4% | Stop 6% | Stop 8% | Stop 10% |
|---|---|---|---|---|---|
| E1 Flash -20% 1 día | $96.1 (dd -4.3%) | **$97.9 (dd -2.8%)** | $96.5 | $96.3 | $96.1 |
| E2 Severo -35% 5d + rebote +50% | $138.3 (+38.3%) | **$141.6 (+41.6%)** | igual | $132.3 | $129.7 |
| E3c Rebalance día 1 + shock gradual | $97.3 (dd -2.7%) | **$100.5 (+0.5%)** | $98.6 | $97.6 | $97.4 |
| Real abr–ago 2026 | $128.9 (+28.9%, dd -7.3%) | **$132.5 (+32.5%, dd -4.8%)** | $130.6 | $129.0 | $128.9 |

Conclusiones adoptadas: el umbral 4% es el óptimo — mejora el flash crash, el catastrófico y el peor caso de timing sin degradar nunca; umbrales ≥6% se disparan tarde y en selloffs con rebote destruyen hasta +15 puntos de equity. En producción, cuando un ticker aparece en `intraday_cuts`, el bot cierra la posición de ese subyacente en la fase de gestión de posiciones (ver `bot.py`, paso de gestión).

## 3. Integración en el tick principal (`bot.py`)

El paso 0 del loop se ejecuta **antes** de descargar los datos de timeframe por estrategia:

```python
regime = _regime_snapshot(feed, tickers, state, equity, cfg.get("risk", {}))
state["regime"] = regime
if regime["regime"] != "bull":
    state["regime_lock"] = regime["regime"]   # bloquea entradas nuevas
else:
    state.pop("regime_lock", None)            # reactiva
```

Dos efectos en cascada: (1) si `regime["floor"]["crossed"]`, se notifica el halt por Telegram (`notify_risk_halt`) y no se abren posiciones hasta recuperar el piso de $99,900; (2) si el régimen no es bull, el lock impide todas las entradas hasta que el siguiente tick clasifique bull. El análisis de régimen se tolera a fallos: si la clasificación explota, el bot usa el último régimen conocido (`state.get("regime")`) en lugar de permitirse todo.

## 4. La guarda de piso de equity (`risk/floor.py`)

El usuario definió (14-ago-2026): la cuenta no debe bajar de **$99,900** y el objetivo es subir a **$100,100+**. `check_floor(equity, state, cfg)` compara el equity contra el piso y devuelve `{"crossed": bool, "reason": str}`. Cuando cruza, el bot deja de abrir posiciones (solo gestiona las existentes y publica el aviso en Firestore y Telegram); cuando el equity recupera ≥$99,900, se reactiva. El piso es una defensa adicional al `max_drawdown_total_pct: 30%` del RiskManager (que solo actúa si el capital cae a $70).

## 5. Límites físicos reconocidos

El crash_event protege en selloffs negociables (2–4 semanas) pero **no en flash crashes de ≤3 días**: la estructura de swings que requiere el detector no existe durante un pánico repentino y la reacción llega 2–5 días tarde. El stop intradiario acorta el daño pero no detiene el gap de apertura (ya consumado antes del stream de equity). El caso E3 sintético (-50% en 72 horas) queda por debajo de cualquier defensa: la única mitigación real es reducir la exposición antes (régimen cash) y operar con riesgo por trade bajo (5%).

## 6. Criterios de uso por el agente

No modificar los umbrales `crash_event_pct`/`intraday_stop_pct`/`crash_cooldown_days` sin volver a pasar `stress_test.py` + `stress_intraday.py` sobre el marco sintético (E1–E4) y la ventana real más reciente. El régimen se publica a Firestore en `payload.regime` como string ("bull"/"bear"), y el dashboard lo consume directamente; si se añade un nuevo valor de régimen, hay que actualizar el frontend simultáneamente. El order recomendado antes de cualquier cambio de lógica de régimen: pruebas con `tests/test_regime_s78.py` (datos reales de yfinance del universo reto), luego dry-run en Cloud Run, luego redeploy con ventana de observación de 30 minutos.
