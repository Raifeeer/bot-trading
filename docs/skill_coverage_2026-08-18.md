# Cobertura de skills de Polaris — 2026-08-18

## Criterio

La presencia de un `*.md` no significa que la skill esté implementada. Se distinguen cinco estados: documentada; módulo existente; conectada al loop; activa en PAPER; y validada fuera de muestra.

## Matriz

| Skill | Documento | Módulos encontrados | Conectada al loop live | Activa en PAPER | Estado real |
|---|---|---|---|---|---|
| `backtest_skill.md` | Sí | `loop_backtests.py`, `scripts/run_*` | No | No | Investigación reproducible; no es lógica operativa. |
| `dashboard_telegram_skill.md` | Sí | `state/telegram_bot.py`, `state/firestore_state.py` | Telegram/Firestore sí; dashboard fuente ausente | Contrato de datos sí | Parcial: backend del contrato activo; frontend no versionado en este repo. |
| `datos_skill.md` | Sí | `data/feed.py`, `data/earnings.py` | Sí | Sí | Feed, caché, fallback y earnings participan en el loop. Alpaca SIP limitado provoca fallback a yfinance. |
| `estado_operativo_skill.md` | Sí | Ninguno: es documentación | No | No | Manual de operación y handoff, no motor de señales. |
| `infra_skill.md` | Sí | `Dockerfile`, `cloudbuild.yaml`, `entrypoint.sh`, configuración GCP | Proceso de despliegue | Sí indirectamente | Procedimiento operativo; no una estrategia. |
| `regime_s78_skill.md` | Sí | `risk/regime.py`, `bot.py` | Sí, `_regime_snapshot()` | Sí | Clasifica `bull/bear/cash`, crash cooldown y `put_choch` de régimen. |
| `riesgo_skill.md` | Sí | `risk/manager.py`, `risk/floor.py`, `bot.py` | Sí | Sí | RiskManager, floor, breakers, sizing y límites son autoridad final. |
| `smc_skill.md` | Sí | `strategies/smc.py`, `risk/regime.py` | Parcial | Parcial | CHoCH/put_choch está conectado vía régimen; `SMCStrategy` completa no se instancia en `build_strategies()`. |
| `wheel_skill.md` | Sí | `strategies/options_income.py` | No | No | `WheelStrategy` existe como módulo, pero no aparece en `build_strategies()` live. |
| `trading-setups` | Skill reusable en `/home/ubuntu/skills` | `strategies/setup_confluence.py`, `tests/test_setup_confluence.py` | Sí, `_setup_shadow_snapshot()` | Shadow sí; filtro no | Los 12 setups están implementados como observaciones puras; no autorizan órdenes y no tienen validación fuera de muestra de opciones. |

## Qué instancia actualmente `bot.py`

`build_strategies()` instancia `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend` según `config.yaml`. `OptionsStrategy` envuelve esos motores para construir spreads. El clasificador de régimen se ejecuta en `_regime_snapshot()` y su resultado puede activar el motor bajista `put_choch`, pero no equivale a tener la `SMCStrategy` completa conectada.

Además, `_setup_shadow_snapshot()` evalúa todos los setups sobre los DataFrames disponibles, guarda `setup_observations`, publica conteos resumidos y mide `setups_s`. La bandera efectiva es `mode=shadow` e `influence_entries=false`; el RiskManager y las puertas de ejecución no se modifican.

## Setups del PDF y cobertura

El PDF `TRADING_SETUP.pdf` aporta HTF/LTF order blocks, liquidity sweep, EMA cross, VWAP, OB/breaker, EMA Cloud, Fibonacci, BSL/SSL, buying/selling volume y etiquetas KL. El motor de setups formaliza los doce nombres siguientes como observaciones direccionales o contextuales:

| Setup | Implementación actual | Estado de validación |
|---|---|---|
| Key Level | Niveles previos/rolling, ruptura cerrada o sweep/reclaim | Test determinista; backtest proxy, no promoción |
| Break-and-retest | Ruptura, retest, hold/fallo/expiración | Backtest proxy; requiere walk-forward |
| Order block | Desplazamiento OHLCV y mitigación aproximada | Backtest proxy; no cadena de opciones |
| BOS / CHoCH | Pivots confirmados y cambio estructural | Backtest proxy; no es el motor `put_choch` de riesgo |
| Liquidity sweep | Sweep SSL/BSL y reclaim | Proxy OHLCV; no observa stops individuales |
| EMA cross / EMA cloud | Relación y pendiente de EMAs | Shadow; posible correlación entre features |
| VWAP | VWAP contextual según timeframe/feed | Shadow; requiere revisar sesiones y volumen |
| Volume proxy | Proxy CLV × volumen | Shadow; no es order flow L2 |
| Fibonacci/OTE | Anchors recientes y zona premium/discount | Shadow; sensible a anchors |
| Trendline/channel | Contexto de canal y pendiente | Shadow contextual, no confirmación de entrada |
| Confluencia MTF | Agregador estructural con conflicto neutral | Shadow; no validación de opciones |

La nueva skill `trading-setups` formaliza esos patrones como features `bull/bear/neutral`, pero no los convierte en órdenes. Solo el `RiskManager`, el floor, los circuit breakers y la validación de ejecución pueden autorizar órdenes.

## Backtest y decisión

El script `scripts/run_setup_backtests.py` usa cuatro ventanas, warmup histórico, anti-look-ahead y slippage de 5 bps por cambio de posición. La corrida final utilizó siete de ocho símbolos porque `SOFI` no pudo recuperarse de los proveedores disponibles; el manifiesto registra el faltante. Los setups redujeron drawdown frente a buy-and-hold en las cuatro ventanas, pero solo superaron el retorno en los últimos 30 días, donde todos los escenarios fueron negativos. La decisión es `RESEARCH_ONLY`: no habilitar `influence_entries` ni `paper_filter`.

Los detalles están en `docs/setup_confluence_backtest_2026-08-18.md` y los CSV/JSON bajo `/home/ubuntu/backtests/`. El A/B futuro requiere un adaptador porque `run_ab_comparison.py` entiende `run_scenario`, no el motor puro `analyze_setup_confluence`.

## Decisión operativa

No se deben presentar las skills como conocimiento automáticamente activo ni como evidencia de rentabilidad. La capa de setups puede permanecer en shadow para medir cobertura, latencia, conflictos y frecuencia de neutralidad. Antes de probarla como filtro PAPER se exige recuperar o declarar el universo de datos, ejecutar un A/B emparejado con el baseline regime-aware, walk-forward, sensibilidad a costes y revisión humana. PAPER permanece obligatorio; REAL requiere confirmación explícita independiente.


## Spreads de riesgo definido — actualización 18 de agosto de 2026

| Capacidad | Documento | Módulo | Conectada al loop | Activa para órdenes |
|---|---|---|---|---|
| Bear call credit shadow | Sí | `options/defined_risk_shadow.py` | Sí | No |
| Bull put credit shadow | Sí | `options/defined_risk_shadow.py` | Sí | No |
| Iron condor shadow | Sí | `options/defined_risk_shadow.py` | Sí | No |
| Debit spreads nuevos | Sí, backtest | No live | No | No |
| Calendars/diagonales | Sí, backtest | No live | No | No |

La integración publica `defined_risk_shadow_observations`, `orders_allowed=false` e `influence_entries=false`. El módulo no tiene acceso al executor y no puede saltarse RiskManager, floor, circuit breakers ni validación de cotizaciones.
