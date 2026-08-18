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
| `trading-setups` nueva | Skill reusable en `/home/ubuntu/skills` | Ninguno aún en Polaris | No | No | Especificación investigada; pendiente de implementar como shadow feature. |

## Qué instancia actualmente `bot.py`

`build_strategies()` instancia `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend` según `config.yaml`. `OptionsStrategy` envuelve esos motores para construir spreads. El clasificador de régimen se ejecuta en `_regime_snapshot()` y su resultado puede activar el motor bajista `put_choch`, pero no equivale a tener la `SMCStrategy` completa conectada.

## Setups del PDF y cobertura

El PDF `TRADING_SETUP.pdf` aporta HTF/LTF order blocks, liquidity sweep, EMA cross, VWAP, OB/breaker, EMA Cloud, Fibonacci, BSL/SSL, buying/selling volume y etiquetas KL. Los módulos actuales cubren parcialmente estructura/CHoCH, EMA/SMA, breakout y volumen de barras, pero no existe una implementación live equivalente y completa para VWAP+EMA Cloud+Fibonacci+liquidity sweep+KL+order-flow.

La nueva skill `trading-setups` formaliza esos patrones como features `bull/bear/neutral`, pero no los conecta ni los convierte en órdenes. La integración debe comenzar con funciones puras, fixtures deterministas, shadow/PAPER, telemetría por símbolo/setup y A/B reproducible. Solo el `RiskManager`, el floor, los circuit breakers y la validación de ejecución pueden autorizar órdenes.

## Decisión

No se deben presentar las skills como conocimiento automáticamente activo. El siguiente trabajo es implementar una feature de setups en shadow, comenzando por un subconjunto objetivo: `BOS/CHoCH + order block`, `liquidity sweep + reclaim` y `premium/discount`. VWAP, EMA Cloud, volumen proxy, Fibonacci y KL se incorporarán como filtros con parámetros explícitos, no como predictores independientes.
