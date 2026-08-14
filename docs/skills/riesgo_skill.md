# Skill: Gestión de Riesgo (RiskManager + reglas del reto)

**Archivos de referencia:** `risk/manager.py`, `risk/regime.py`, `risk/floor.py`, `config/config.yaml` (sección `risk`), y la integración en `bot.py`.

## 1. Filosofía de las tres capas

El riesgo se gestiona en tres capas que actúan en orden dentro del tick: primero el **régimen global** (¿se puede operar?), luego las **válvulas de capital** del RiskManager (¿cuánto se puede arriesgar?), y finalmente las **defensas tácticas** de cada posición (stop de prima, DTE, stop intradiario, anti-earnings). Si una capa bloquea, las capas posteriores ni se consultan.

## 2. Válvulas de capital (`config.yaml`, sección `risk`)

| Parámetro | Valor | Qué hace |
|---|---|---|
| `mode` | `aggressive` | Perfil activo del reto (conservative/moderate también existen) |
| `max_risk_per_trade_pct` | **5.0%** | Riesgo máximo por operación (~$5,000 sobre el equity paper; sobre la base de $100 serían $5) |
| `max_open_positions` | **2** | Poca simultaneidad por capital reducido |
| `max_sector_weight_pct` | 60.0% | Concentración máxima por sector |
| `max_drawdown_daily_pct` | 15.0% | Pierde 15% en el día → detiene el trading del día |
| `max_drawdown_total_pct` | 30.0% | El capital cae a $70 → el bot se detiene (HALT) |
| `prem_tp_mult` / `prem_sl_mult` | 1.4 / 0.25 | TP al +40% de prima; SL al -75% de prima |
| `allow_pyramiding` / `allow_averaging_down` | false | Prohibido añadir a posiciones en pérdida ni en ganancia |
| `earnings_horizon_days` | 2 | Bloquea entradas 2 días antes de reportes de ganancias |

## 3. Circuit breakers (`risk/manager.py`)

`RiskManager` mantiene el drawdown diario (máx. observado del día vs equity de apertura) y el drawdown total (vs el máximo histórico de equity). `check_circuit_breakers(equity)` los evalúa en cada tick y, si alguno activa, `is_halted()` devuelve true: el bot solo monitorea y vuelve a intentar tras 600 segundos. El riesgo diario **no** se resetea por sí solo a mitad del día — solo con la renovación diaria del máximo. El nivel de HALT de drawdown total de 30% ($70) es la red final; la guarda de piso (`risk/floor.py`) actúa mucho antes.

## 4. Guarda del piso de equity (`risk/floor.py`)

> Regla del usuario (14-ago-2026): la cuenta no debe bajar de **$99,900**; el objetivo es subir hacia **$100,100+**.

`check_floor(equity, state, cfg)` compara el equity contra el piso y devuelve `{"crossed": bool, "reason": str}`. Cruzado: sin entradas nuevas, notificación de halt por Telegram, solo gestión de posiciones existentes. Recuperación del equity ≥ piso: reactivación automática en el siguiente tick. Está integrada en el paso 0 del tick junto al régimen (ver `docs/skills/regime_s78_skill.md`); el piso se publica a Firestore y aparece como aviso en el dashboard (KPI EQ-01).

## 5. Defensas tácticas de posición

**Stop de prima.** La prima neta de cada spread se mide contra la entrada: cierre parcial o total con TP al +40% o SL al -75%. El hallazgo más caro de todo el proyecto: en el backtest B, una posición de LCID decayó **-93%** de su prima por no tener stop activo. También se cierra a **7 DTE** (evitar la gamma de la última semana) y a mitad de vida si no hay ganancia.

**Trailing stop de prima.** Complemento adoptado para spreads de opciones: trailing sobre la prima del 30–40% para proteger ganancias ya capturadas.

**Stop intradiario del subyacente (hallazgo 18).** Precio intradiario ≤ `(1 - 0.04) × close_prev` → cierre inmediato de la posición de ese ticker (evaluado en la fase de gestión de posiciones; los tickers afectados salen en `intraday_cuts` del clasificador de régimen). Validado: mejora el peor caso real de -2.7% a +0.5% de drawdown sin degradar ningún escenario.

**Anti-earnings.** `earnings_horizon_days: 2` bloquea entradas en la ventana de reportes; el material de opciones advierte que la volatilidad de earnings destruye spreads por ambas direcciones.

## 6. Dimensionamiento del sizing

El tamaño por trade se calcula como `max_risk_per_trade_pct × equity` contra el riesgo definido de la estructura (débito neto del spread × contratos). El flujo: (1) presupuesto de riesgo; (2) prima neta máxima del perfil (reto: $12 por spread); (3) número de contratos = floor(presupuesto / prima neta) dentro del riesgo definido; (4) validar contra `max_open_positions` y `max_sector_weight_pct`. Nunca promediar a la baja (`allow_averaging_down: false`): cada spread es independiente.

## 7. Errores históricos y su lección

| Error | Costo | Corrección permanente |
|---|---|---|
| Sin stop de prima (LCID) | -93% de la prima | SL 25% + cierre 7 DTE + cierre a mitad de vida |
| Riesgo 20% por trade (calibración original) | $1,970 de exposición en un solo spread = 2% del equity | `max_risk_per_trade_pct` bajado a 5.0 |
| Drawdown diario sin medición | El selloff erosionaba la cuenta sin freno intradiario | `max_drawdown_daily_pct: 15` + piso $99,900 |
| Pyramiding en ganancia | Concentración súbita en un trade | Prohibido |
| Entradas pre-earnings | Swings de ±15% en horas | `earnings_horizon_days: 2` |

## 8. Criterios de uso por el agente

Cualquier propuesta de modificación de riesgo debe pasar primero por los backtests de estrés (`stress_test.py` + `stress_intraday.py`) y por una validación en la ventana real más reciente con `backtest_retos.py`/`loop_backtests.py`. Umbrales aprobados por evidencia, nunca por intuición. Si el usuario cambia los niveles del piso/techo, actualizar `risk/floor.py` y comunicar el cambio en el checkpoint del repo.
