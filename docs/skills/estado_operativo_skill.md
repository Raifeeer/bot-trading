# Skill: Estado operativo del sistema Polaris (para agentes nuevos)

Esta skill es el **punto de entrada obligatorio** para cualquier agente que continúe, diagnostique u opere el sistema Polaris desde una sesión nueva. Resume el estado exacto de la infraestructura, los incidentes operativos y cómo reanudar el trabajo sin perder horas de diagnóstico. Última actualización: 15 de agosto de 2026, 06:50 UTC.

## 1. Mapa del sistema en una mirada

| Pieza | Dónde está | Referencia clave |
|---|---|---|
| Código del bot | `/home/ubuntu/bot-trading` (repo GitHub `Raifeeer/bot-trading`, branch `main`) | `bot.py`, `AGENTS.md`, `docs/skills/` |
| Bot en producción | Cloud Run `polaris-bot`, us-central1, proyecto `gen-lang-client-0746441136` | SA `173223792589-compute@developer.gserviceaccount.com` |
| Imagen Docker | Artifact Registry `us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:latest` | Tag `latest` se actualiza en cada build |
| Dashboard (código) | Proyecto Manus webdev `/home/ubuntu/polaris-options-dashboard` | Checkpoint más reciente: `52f4cb52` |
| Dashboard (producción) | Vercel, https://polaris-options-dashboard.vercel.app | Deploy vía `vercel deploy --prebuilt` (pnpm build falla en el entorno; subir bundle pre-compilado) |
| Firestore | DB Native `polaris` (NO la default del proyecto, que es Datastore) | ADC de Cloud Run, Firebase Admin o REST autenticado; no guardar keyfiles en el repo |
| Broker | Alpaca **PAPER**: `https://paper-api.alpaca.markets/v2` | Credenciales exclusivamente desde Secret Manager: `alpaca-key` |
| Telegram | Bot @Raifeeer, chat id `1779931930` | Token exclusivamente desde Secret Manager (`TELEGRAM_BOT_TOKEN`); rotar cualquier token histórico expuesto |
| LLM (Telegram) | DeepSeek V4 Flash (`deepseek-chat`), timeout 45 s | Secret Manager `deepseek-api-key`; fallbacks `gemini-api-key` y `grok-api-key` |
| Backtests | `/home/ubuntu/backtests/` + `loop_backtests.py` / `stress_*.py` | Los resultados históricos S1–S89 están documentados, pero `/home/ubuntu/backtests/` está vacío en esta sandbox; deben regenerarse antes de usarse como evidencia. |

**Advertencia de entorno:** en sesiones nuevas de la sandbox, `gcloud` no está en el PATH de inmediato. Restaurarlo con `export PATH=/home/ubuntu/.google/google-cloud-sdk/bin:$PATH` (también existe en `/home/ubuntu/google-cloud-sdk/bin`). No editar los archivos `.env` de la sesión con shell commands (restricción del entorno); usar la ruta completa al binario es suficiente.

## 2. Incidente de Firestore: resuelto, pendiente de limpieza y redeploy

El dashboard había mostrado equity congelado porque el bot completaba ticks cada 10–15 minutos sin materializar snapshots. La investigación quedó documentada en `AGENTS.md`, sección 13. La revisión 00052 confirmó permisos/serialización; la revisión 00055 reveló además que `DocumentReference.set()` podía quedar bloqueado sin timeout. La corrección quedó desplegada en `polaris-bot-00056-f48`.

**Evidencia verificada:**

- Cloud Run `polaris-bot-00052-lbz` está `Ready` y recibe el 100% del tráfico.
- Los logs muestran `FIRESTORE_ENABLED=True`, `DIAG_FS: probe escrito` y `Tick OK` con equity `99689.50`.
- Firestore `polaris/2026-08-15` tiene `updated_at=2026-08-15T04:42:24.592357+00:00`, `trading_mode=PAPER`, régimen `bull`, guarda de piso activa y 30 puntos de curva.
- El `payload` contiene campos reales: `alpaca_positions`, `orders_executed`, `positions`, `risk`, `strategies`, `universe` y `decisions_today`.

El probe confirmó permisos/ADC y el snapshot completo posterior confirmó que no hay fallo de serialización reproducible. El probe ya fue retirado de `bot.py`, la revisión 00054 completó la escritura limpia, el documento se limpió de `probe`/`diag` mediante Firestore y el servicio quedó en `min-instances=1 / max-instances=1`. La caché de feeds se añadió en `fc9962f`; su primer ciclo en 00055 quedó bloqueado al escribir Firestore. El timeout de 30 s y el log `Estado escrito en Firestore` se añadieron en `a27ad4b`, se desplegaron en `polaris-bot-00056-f48` y se verificaron: `FIRESTORE_ENABLED=True` 06:42:28, escritura 06:45:48, `Tick OK` 06:46:27, Firestore `updated_at=2026-08-15T06:45:26.813506+00:00`, curva de 34 puntos y sin `probe`/`diag`.

El incidente anterior tuvo tres causas operativas: un `NameError` en la imagen vieja, logging inicial posterior al import condicional de Firestore y reutilización de una instancia antigua cuando `min-instances=1`. Los fixes de logging/import y el despliegue forzado a dos instancias permitieron aislar y resolver el problema. No modificar el perfil de riesgo S78 como parte de esta limpieza.

## 3. Esquema Firestore (contrato bot ↔ dashboard)

El bot escribe cada tick con `set(merge=True)` en `polaris/{YYYY-MM-DD}` (fecha del **contenedor**, que corre en UTC):

```json
{"updated_at": "<iso>", "payload": {
  "equity": 99689.50, "cash": ..., "buying_power": ...,
  "positions": [], "alpaca_positions": [{"symbol": "O:TQQQ...", "structure": "debit_call_spread", ...}],
  "orders_executed": [], "trade_history": [], "signals": [],
  "risk": {"risk_per_trade_pct": 5.0, "risk_per_trade_fraction": 0.05,
           "max_risk_per_trade_pct": 5.0, "max_positions": 2,
           "max_open_positions": 2, "halted": false, "regime": "bull",
           "regime_summary": "...", "crash_active": false, "floor": {...}},
  "trading_mode": "PAPER", "strategies": ["smc", "s78", "regime_aware"],
  "universe": ["SOFI","PLTR","F","TSLA","AMD","NOK","BB","TQQQ"],
  "decisions_today": []}}
```

El dashboard (React 19 + Tailwind 4, **cero mock**: sin doc muestra "—" y estados explícitos) lee con `onSnapshot` desde `client/src/lib/firestore.ts` el documento `polaris/{fecha-local-del-navegador}`. Las reglas de Firestore permiten lectura pública con la API key embebida. Para cambios en el dashboard: editar en el proyecto webdev, guardar checkpoint, y re-desplegar en Vercel con el bundle pre-compilado (`vercel deploy --prebuilt`; la CLI ya está autenticada).

## 4. Reglas operativas comprobadas en esta sesión

**Despliegue del bot.** El build local con `gcloud builds submit --config cloudbuild.yaml .` falla si el contexto incluye `__pycache__` o archivos whiteout de overlay (`.wh..wh..opq`): deben eliminarse antes. Tras `gcloud run deploy`, Cloud Run puede seguir enrutando a la **instancia vieja** (minScale=1 la satisface heredando instancia); siempre verificar con `gcloud run revisions list --format="table(metadata.name,status.active)"` que la nueva revisión esté activa y que una instancia de ella arrancó (`Bot iniciado` con timestamp reciente). Para forzar una instancia nueva: `--min-instances 2 --max-instances 2` y luego volver a 1/1. Nunca usar `--set-env-vars` o `--set-secrets` aislados; conservar el spec completo. La caché de feeds está desplegada en `polaris-bot-00055-7cd` (commit `fc9962f`) y debe medirse antes de cambiar sus TTL.

**Permisos GCP.** El usuario autorizó que el agente se autoasigne el rol mínimo necesario dentro de `gen-lang-client-0746441136` cuando una operación de Polaris devuelva `PERMISSION_DENIED`, siempre que primero verifique los roles existentes y documente en `AGENTS.md` el rol, el motivo, el recurso y si procede retirarlo. No solicitar otra credencial si la cuenta de servicio ya tiene `roles/resourcemanager.projectIamAdmin`.

**Advertencia de envs:** nunca usar `gcloud run services update --set-env-vars` aislado (en el pasado borró `APCA_API_BASE_URL` y `DATA_PROVIDER`); editar el spec completo y aplicar con `services replace`.

**Diagnóstico.** Los errores `yfinance "possibly delisted"`, `APIError subscription does not permit querying recent SIP data` y `Telegram poll falla` (409 cuando hay 2 instancias, timeouts el resto) son **ruido normal**; filtrarlos al leer logs. El log del proceso solo llega a Cloud Logging si `basicConfig` corrió antes; cualquier import condicional de arranque debe ir después. No confiar en los warnings del logger `state.firestore` (nunca aparecen en Cloud Logging): loguear contra el logger root de bot o con `print(..., flush=True)`.

**Ciclo de tick.** Poll 5 min, watchdog 25 min (sin tick completo → `sys.exit(1)` y Cloud Run recrea la instancia). El tick completo tarda 10–15 min por timeouts de yfinance (socket timeout 45 s por ticker). Orden: snapshot Alpaca → circuit breakers → feed 5m/15m/1d → señales → risk → ejecución → gestión de posiciones (TP/SL prima, DTE) → escritura Firestore con timeout 30 s → Telegram. 00056 completó un ciclo en unos 17 min desde arranque; la caché está activa pero el fallback de datos sigue dominando la latencia.

## 5. Estado del trading al pausar (14 ago 2026)

Modo PAPER. Estrategias: SMC, S78 Regime-aware y régimen-aware (3). Régimen actual: **bull** (5/8 tickers). Posiciones abiertas: 0 (el spread TQQQ se cerró; equity Alpaca $99,689.50). El equity está **por debajo del piso $99,900**, por lo que el bot haltea entradas nuevas (regla correcta del reto: piso $99,900, meta $100,100). La calibración vigente es la del reto $100→$200 (universo barato SOFI/PLTR/F/TSLA/AMD/NOK/BB/TQQQ, spread debit deltas 0.25/0.10, DTE 10–45, prima máx $12, TP +40%/SL 25% de prima, riesgo 20%/trade, máx 2 posiciones, dd diario 15%/total 30%). Mecanismos de defensa activos: `crash_event` 3% (cierre, cool-down 5d) e `intraday_stop` 4%.

## 6. Pendientes de mayor orden

1. **Auditoría de backtests:** corregir el benchmark `S51`/`hold`, validar anti-look-ahead, sustituir el proxy retrospectivo de earnings y regenerar todos los resultados en una carpeta persistente.
2. **Matriz de escenarios:** ampliar rupturas, gaps, selloffs, laterales, rebotes, IV crush y ventanas recientes con slippage, comisiones y walk-forward.
3. **Stream de equity en tiempo real** de Alpaca para el stop intradiario 4% y actualizaciones del dashboard entre ticks.
4. **Dashboard:** recuperar la fuente correcta `client/src/pages/Home.tsx`; el bundle de producción mostró que el antiguo payload 0.01/5 confundía porcentaje y límite. El bot ya publica el contrato corregido; falta confirmar el frontend y desplegar solo la fuente correcta.
5. **Telegram:** las respuestas libres dependen del LLM (45 s timeout); evaluar respuestas asíncronas por chat action sin bloquear el polling.
6. **Contexto de mercado:** investigar fuentes fechadas y anotar qué hechos son observados versus hipótesis; nunca usar noticias posteriores a la decisión en un backtest histórico.


## 7. Auditoría profunda y backtesting reproducible — 15 de agosto de 2026

La auditoría profunda está documentada en `docs/hallazgo20_auditoria_y_robustez_2026-08-15.md`. Se corrigieron una fuga de look-ahead en SMA200/volumen, la normalización UTC y la rama de feed de ventanas recientes. La validación actual pasa `compileall`, Ruff F/B y los tests deterministas de feed, riesgo, ejecución y asistente; el test de asistente puede mostrar que `gpt-4o-mini` ya no está soportado por el proxy, pero no falla el proceso.

Los artefactos de investigación ya no están vacíos: `/home/ubuntu/backtests/` contiene la matriz de 73 configuraciones, sensibilidad de 156 combinaciones, walk-forward simple y rodante, ensembles fijos y ensemble walk-forward, además de gráficos en `backtests/charts/`. La fuente real es yfinance a través de `MarketDataFeed`, con 520 días, ventanas explícitas, anti-look-ahead, slippage parametrizado para opciones y coste equity de 0.2% round-trip en benchmarks.

Los motores `breakout20` y `breakout55` son de investigación únicamente. `regime_hold_cash` es el candidato más consistente por ventanas, pero el walk-forward más reciente termina negativo. El ensemble 70% régimen/30% breakout55 mejora la mediana y el drawdown, pero no elimina la ventana negativa; no hay cambio autorizado a producción.

**Pendientes actualizados:** obtener datos point-in-time de cadenas de opciones y earnings; modelar fills bid/ask, liquidez, assignment y gaps; repetir walk-forward con más años y fuentes verificables; implementar el stream de equity de Alpaca antes de depender del stop intradiario; y corregir/confirmar la fuente del dashboard antes de cualquier redeploy. No cambiar la estrategia PAPER solo por resultados de una ventana.


## 8. Capa de setups shadow — 18 de agosto de 2026

El repositorio ahora incluye `strategies/setup_confluence.py`, un motor puro que formaliza los doce setups del PDF: Key Level, break-and-retest, order block, BOS, CHoCH, liquidity sweep, EMA cross, EMA cloud, VWAP, volumen proxy, Fibonacci/OTE y trendline/channel. Está conectado a `bot.py` mediante `_setup_shadow_snapshot()` y publica `state.setup_observations`, conteos por setup y timing `setups_s`.

La configuración efectiva es `setups.enabled=true`, `mode=shadow` e `influence_entries=false`. Esta capa no puede decidir sizing, strikes, precio límite, circuit breaker ni endpoint de broker. `RiskManager`, floor, validación de cotizaciones y límites de posiciones siguen siendo la autoridad final. Si alguien modifica la bandera de influencia, el loop registra una advertencia y conserva el bloqueo de promoción.

La validación local del cambio pasó 102 tests del repositorio, compilación y Ruff F/B/E9. El backtest direccional de la capa está en `docs/setup_confluence_backtest_2026-08-18.md`; el resultado se clasifica `RESEARCH_ONLY`. En cuatro ventanas, los setups redujeron drawdown frente a buy-and-hold, pero solo superaron retorno en los últimos 30 días, donde todos los escenarios fueron negativos. La corrida final utilizó siete símbolos; `SOFI` quedó faltante por inestabilidad/rate limiting del proveedor y el manifiesto lo declara. No promover, no activar `paper_filter` y no cambiar el perfil de riesgo por estos resultados.

Para repetir la investigación:

```bash
cd /home/ubuntu/bot-trading
export PYTHONPATH="$PWD"
python3 scripts/run_setup_backtests.py
python3 scripts/analyze_setup_backtests.py
```

Antes de desplegar una revisión con esta capa se debe confirmar que los artefactos de backtest están disponibles, revisar el diff, construir una imagen inmutable, preservar secretos/envs, verificar modo PAPER y observar al menos dos ciclos. Después del deploy, comprobar que Firestore contiene `setup_observations`, que Cloud Logging muestra `setups_s` y que `orders_executed` no aumenta por la capa shadow.


## 9. Capa shadow de spreads de riesgo definido — 18 de agosto de 2026

Polaris evalúa ahora `bear_call_credit`, `bull_put_credit` e `iron_condor` como observaciones shadow sobre las cadenas de Alpaca. La información se guarda en Firestore bajo `defined_risk_shadow_observations` y aparece en `tick_diagnostics` junto con `defined_risk_shadow_s`.

Esta capa no abre ni modifica posiciones. `orders_allowed=false`, `influence_entries=false` y `mode=shadow` son invariantes; no se deben cambiar sin walk-forward, revisión humana y un contrato explícito de promoción. Si falla la cadena de opciones o una cotización, el candidato queda `unavailable` o `error` por símbolo y el tick continúa.


## 10. VIX shadow — 18 de agosto de 2026

La capa `vix_shadow` consulta `^VIX` mediante el feed real y usa exclusivamente el último cierre estrictamente anterior a la fecha de mercado. Registra `shock_10`, `percentile_70` y `level_25` como señales `would_block`, sin bloquear entradas reales. `mode=shadow`, `influence_entries=false` y `orders_allowed=false` se fuerzan en código, incluso si una configuración antigua intenta cambiar esas banderas. El resultado se guarda como `vix_shadow_observations`, se resume en `tick_diagnostics.vix_shadow` y mide `vix_shadow_s` en `CYCLE TIMING`.


## 11. Verificación final de VIX shadow — 18 de agosto de 2026

La revisión activa es `polaris-bot-vixshadow3`, basada en `379dc84`, con 100% del tráfico y CPU always-on. La conexión a Alpaca PAPER se completó y los ciclos posteriores escribieron Firestore correctamente. Se observó `vix_shadow_s` de aproximadamente 0.006–0.009 s después del primer ciclo, junto con `Tick OK` y cero órdenes.

Firestore confirma `vix_shadow_observations` disponible, `mode=shadow`, `influence_entries=false`, `orders_allowed=false`, ocho símbolos, alineación al último cierre anterior y variantes `shock_10`, `percentile_70` y `level_25`. La consulta `^VIX` usa Alpaca como primer intento y yfinance real como fallback cuando Alpaca devuelve símbolo inválido. No se imputan barras ni se usa el valor para bloquear entradas.


## 12. Estructura MTF shadow — 19 de agosto de 2026

La capa `structure_mtf_shadow` está configurada y conectada al loop, pero no es una estrategia live. Analiza `1d`, `15min` y `5min` con swings fractales confirmados, registra dirección, score, máximos/mínimos confirmados y conteos bull/bear. Firestore recibe el snapshot bajo `structure_mtf_shadow_observations` y `CYCLE TIMING` expone `structure_mtf`.

Los invariantes son obligatorios: `mode=shadow`, `influence_entries=false`, `orders_allowed=false` y autoridad final del RiskManager. El backtest inicial sobre siete símbolos y 38 días disponibles no mostró mejora de retorno frente a DayBreakout + S78; no promover sin una segunda validación walk-forward más larga.


## 13. Motor bearish breakdown/retest — integración shadow 19 de agosto de 2026

El repositorio ahora incluye `strategies/bearish_breakdown_retest.py`, `tests/test_bearish_breakdown_retest.py` y el wrapper de bot `bearish_breakdown_shadow`. La configuración usa 15 minutos, soporte rolling de 20 barras, volumen mínimo 1.2x y retest máximo de 3 barras. El wrapper fuerza `mode=shadow`, `influence_entries=false` y `orders_allowed=false`; guarda el resultado bajo `bearish_breakdown_shadow_observations`, resume estados en `tick_diagnostics` y mide `breakdown_shadow` en el timing.

La evidencia histórica de cinco ventanas sobre siete símbolos disponibles clasifica el motor como `RESEARCH_ONLY` para promoción: la mejor variante gana 2/5 ventanas sin gate y 3/5 con gate bear/crash, pero el periodo reciente de 20 días es negativo y las variantes 5m son peores. La skill y el informe reproducible están en `/home/ubuntu/skills/bearish-breakdown-retest/SKILL.md` y `docs/bearish_breakdown_retest_backtest_2026-08-19.md`.

Antes de declarar la integración productiva completa, ejecutar:

```bash
cd /home/ubuntu/bot-trading
export GCLOUD=/home/ubuntu/tools/google-cloud-sdk/bin/gcloud
export PROJECT=gen-lang-client-0746441136
$GCLOUD run services describe polaris-bot --region us-central1 --project "$PROJECT" --format='value(status.traffic)'
$GCLOUD logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="polaris-bot"' --limit 100 --format='value(textPayload)' | grep -E 'Bot iniciado|CYCLE TIMING|Tick OK|BREAKDOWN SHADOW'
```

Confirmar la revisión nueva, dos ciclos completos, `bearish_breakdown_shadow_observations` en Firestore, `mode=shadow`, `orders_allowed=false`, `influence_entries=false` y ausencia de órdenes nuevas. Si la nueva revisión no arranca o se bloquea, revertir a la revisión PAPER anterior y documentar el incidente.


## 14. Verificación productiva de bearish shadow — 19 de agosto de 2026

La revisión activa final es `polaris-bot-brshadow0724650`, con 100% del tráfico PAPER. Usa el digest inmutable `sha256:fedf44ffe0725ed3db53c1f1f9fbc208adbcfc0928e3c3439b542956464f5fca`; `polaris-bot-floor217e0b2` queda como rollback. Cloud Run confirmó `Ready`, `Active`, `ContainerHealthy`, minScale=1, maxScale=1, CPU always-on, `DATA_PROVIDER=alpaca`, `APCA_API_BASE_URL=paper` y secretos Alpaca conservados.

Se observaron tres ciclos consecutivos con `Tick OK` y sin tracebacks: 16:02:20, 16:03:21 y 16:04:23 UTC. `CYCLE TIMING` incluyó `breakdown_shadow` de 0.160 s, 0.175 s y 0.168 s. Firestore `polaris/2026-08-19` confirmó `updated_at=2026-08-19T16:04:22.766280+00:00`, equity `$99,288.27`, `trading_mode=PAPER`, posiciones 0, órdenes ejecutadas 0, `mode=shadow`, `influence_entries=false`, `orders_allowed=false`, ocho símbolos y cinco confirmaciones bearish frente a tres `no_setup`. La capa es `HEALTHY_NO_SIGNAL` para ejecución live y `SHADOW_CANDIDATE` para observación; la estrategia sigue `RESEARCH_ONLY` para promoción.


## 15. Opening Range Breakout — investigación 19 de agosto de 2026

Se creó y validó `/home/ubuntu/skills/opening-range-breakout/SKILL.md`, con referencias en `references/research.md`. La skill formaliza rangos de 5/15/30 minutos desde las 09:30 ET, barras cerradas, entrada en la apertura siguiente, ATR/volumen desplazados, slippage y estados shadow. El detector puro vive en `strategies/opening_range_breakout.py` y sus cuatro tests están en `tests/test_opening_range_breakout.py`.

La matriz ORB usa caches reales Alpaca IEX de 5m/15m y diario, ocho símbolos disponibles y cinco/seis ventanas según timeframe. Se probaron 60 variantes con 5 bps de slippage por lado, sin overnight y sin P&L de opciones. El informe es `docs/orb_backtest_2026-08-19.md`; los artefactos se encuentran bajo `/home/ubuntu/backtests/orb_backtests_2026-08-19*`, `orb_backtest_comparison_2026-08-19.csv` y `orb_backtest_variant_summary_2026-08-19.csv`.

Decisión: `RESEARCH_ONLY`. `orb_5min_r5_short_vol12_none` y `orb_5min_r5_short_novol_directional` ganaron en varias ventanas recientes, pero perdieron en la cobertura completa 5m y mostraron drawdown material; las variantes 15m quedaron por debajo del baseline medio. No integrar ORB en `bot.py`, no crear configuración live, no publicar en Firestore y no desplegarlo. Antes de reconsiderar: ampliar el histórico 5m, ejecutar folds walk-forward no solapados y reconstruir un filtro `Stocks in Play` point-in-time.

Reproducción:

```bash
cd /home/ubuntu/bot-trading
export PYTHONPATH="$PWD"
python3 scripts/run_orb_backtests.py
python3 scripts/analyze_orb_backtests.py
pytest -q tests/test_opening_range_breakout.py
```

La revisión PAPER activa sigue siendo `polaris-bot-brshadow0724650`; el motor bearish continúa shadow y las capas ORB no forman parte del runtime productivo.


## 16. VWAP reclaim/pullback — investigación 19 de agosto de 2026

Se creó `/home/ubuntu/skills/vwap-reclaim-pullback/SKILL.md` y su referencia `references/research.md`. El detector puro está en `strategies/vwap_reclaim_pullback.py`; sus tests están en `tests/test_vwap_reclaim_pullback.py`. Formaliza VWAP RTH por sesión, displacement → retracement → resumption, volumen as-of, stop/target teórico y estados fail-closed. No está conectado a `bot.py` ni al executor.

El backtest completo utiliza 48 variantes, caches reales Alpaca IEX, siete símbolos porque SOFI falta, cinco/seis ventanas, 5 bps por lado, fills en la apertura siguiente y salida antes del cierre. El informe es `docs/vwap_reclaim_pullback_backtest_2026-08-19.md`, con resultados en `/home/ubuntu/backtests/vwap_backtests_2026-08-19.csv`, `vwap_backtest_comparison_2026-08-19.csv`, `vwap_backtest_variant_summary_2026-08-19.csv`, `vwap_backtest_symbol_summary_2026-08-19.csv` y el manifiesto JSON.

Decisión: `RESEARCH_ONLY`. Las variantes recientes con volumen/gate direccional son pequeñas y no superan el periodo completo comparable frente a DayBreakout. No añadir `vwap_shadow_observations`, no cambiar configuración live y no desplegar. La observación VWAP existente de `setup_confluence` no se modificó.

Validación completa posterior: **140 passed, 1 skipped, 2 xfailed**, Ruff focalizado limpio. La revisión PAPER sigue siendo `polaris-bot-brshadow0724650`; no se creó una revisión Cloud Run para VWAP.


## 17. Relative strength rotation — investigación 19 de agosto de 2026

La skill está en `/home/ubuntu/skills/relative-strength-rotation/SKILL.md`. El detector puro es `strategies/relative_strength_rotation.py`; tests: `tests/test_relative_strength_rotation.py`. Usa ranking cross-sectional as-of, benchmark equal-weight, excess return, percentil, horizonte y contrato shadow fail-closed. No hay SPY/QQQ point-in-time en los caches revisados; SOFI falta en el histórico diario.

El backtest probó 192 variantes y produjo `relative_strength_backtests_2026-08-19.csv`, `relative_strength_backtest_comparison_2026-08-19.csv`, `relative_strength_backtest_variant_summary_2026-08-19.csv`, `relative_strength_backtest_sensitivity_2026-08-19.csv` y el manifiesto JSON. El walk-forward no solapado está en `relative_strength_walkforward_2026-08-19.csv` y tiene cuatro folds consecutivos de 60 sesiones.

Decisión: `RESEARCH_ONLY`. Aunque algunas variantes h60/top-2/gate bull mejoran dos folds recientes, en full_available quedan debajo de `baseline_regime_s78`, y el gate deja el sistema en cash durante varios folds. No crear configuración live, no publicar observaciones shadow y no desplegar. Cloud Run sigue en `polaris-bot-brshadow0724650` al 100% PAPER.


## 18. Trend pullback / continuación EMA-VWAP — 19 de agosto de 2026

La skill reusable está en `/home/ubuntu/skills/trend-pullback-continuation/SKILL.md`. El detector puro está en `strategies/trend_pullback_continuation.py`; el wrapper shadow está en `bot.py`; tests: `tests/test_trend_pullback_continuation.py` y `tests/test_trend_pullback_shadow.py`.

El backtest `scripts/run_trend_pullback_backtests.py` produjo `trend_pullback_backtests_2026-08-19.csv`, trades, comparación y resumen de variantes. Se evaluaron 144 variantes 5m/15m con EMA 9/21, 12/26, 20/50, VWAP, volumen, gates none/bull/directional y long/both. La variante seleccionada para shadow es 15m EMA9/21 + VWAP alineado + volumen 1.2x + long-only. En full_available: +8.390% y DD −2.148% contra DayBreakout +8.485% y DD −3.097%. Walk-forward de cinco folds de 20 sesiones: retorno mejor en 3/5 y drawdown mejor en 4/5.

Se añadió `trend_pullback_shadow` a `config/config.yaml`. La capa no influye en entradas, no crea órdenes y fuerza las banderas shadow. Publica `trend_pullback_shadow_observations`, `signal_stats.trend_pullback_shadow` y `CYCLE TIMING.trend_pullback_shadow_s`. La configuración es long-only y no habilita cortas.

**Pendiente inmediato:** ejecutar suite completa, crear commit, desplegar una revisión PAPER separada, mover el 100% del tráfico solo después de comprobar que la nueva revisión está lista y verificar Firestore, timing y cero órdenes. La revisión anterior sigue siendo `polaris-bot-brshadow0724650` hasta completar esos pasos.


## 19. Verificación trend pullback en producción PAPER

La revisión activa es `polaris-bot-tpshadowf6eb11b`, con 100% del tráfico. Fue construida desde el commit `f6eb11b` y el digest `sha256:ce0715bbf3cf5919a8844e997c2da94bb98477d4d1ad21b581cce28710079486`. El arranque confirmó la configuración shadow y el primer ciclo completo no presentó traceback del motor.

Firestore `polaris/2026-08-19` se actualizó a `2026-08-19T19:37:50.311583+00:00`: equity `$99,288.27`, modo `PAPER`, posiciones `0`, órdenes ejecutadas `0`. `trend_pullback_shadow_observations` está persistido con 8 símbolos: 4 `confirmed`, 4 `no_setup`, 0 `missing_data`, 0 `insufficient_data`, 0 `error`. `tick_diagnostics.trend_pullback_shadow` contiene las mismas counts y `mode=shadow`, `influence_entries=false`, `orders_allowed=false`.

La telemetría `CYCLE TIMING` incluye `trend_pullback_shadow=...s`. Se observó únicamente el conflicto Telegram HTTP 409 entre instancias; no afectó la ejecución del tick ni habilitó órdenes.


## 20. RSI bounce sobre SMA200 — 19 de agosto de 2026

La skill está en `/home/ubuntu/skills/rsi-bounce-sma200/SKILL.md`. El detector y arneses están en `strategies/rsi_bounce_sma200.py`, `scripts/run_rsi_bounce_backtests.py`, `scripts/analyze_rsi_bounce_backtests.py` y `scripts/run_rsi_bounce_walkforward.py`; tests en `tests/test_rsi_bounce_sma200.py`.

Se evaluaron 72 variantes y 402 filas sobre 7 símbolos con caches reales 5m/15m, 5 bps por lado, RSI 2/5/14, umbrales 20/25/30, SMA200/SMA50 y gates none/bull. Baseline DayBreakout S78 15m: +8.485%, DD −3.097% full_available. Mejor variante 15m RSI2<30 + gate bull: +6.292%, DD −3.266%, 130 trades. Las variantes 5m con mejores promedios tienen solo 4–12 trades y no tienen baseline full comparable.

Walk-forward de cinco folds no solapados: la variante RSI2<30 bull quedó por debajo del baseline en los tres folds con actividad; RSI5<20 bull solo mejoró un fold. Decisión: `RESEARCH_ONLY`; no se añadió a bot.py/config.yaml y no se desplegó. Cloud Run continúa en `polaris-bot-tpshadowf6eb11b` PAPER, con trend pullback y breakdown shadow activos.


## 21. Breakout20/55 con volumen — 19 de agosto de 2026

Skill reusable: `/home/ubuntu/skills/breakout-20-55-volume/SKILL.md`. Detector: `strategies/breakout_20_55_volume.py`. Wrapper y telemetría: `bot.py`. Tests: `tests/test_breakout_20_55_volume.py` y `tests/test_breakout_20_55_shadow.py`.

La matriz ejecutó 24 variantes y 138 filas sobre 7 símbolos intradía. Mejor variante: `breakout_15min_lb55_vol10_bull`, con canal Donchian previo de 55 barras, volumen 1.0x, gate bull y long-only. Full_available: +9.542%, DD −2.945%, 93 trades; baseline S78: +8.485%, DD −3.097%, 156 trades. Walk-forward de cinco folds: dos sin señales; en los tres con actividad, mejora retorno y DD en dos y pierde en uno.

La capa se añadió a `config/config.yaml` como `breakout_20_55_shadow`, pero aún está pendiente de commit/deploy en esta entrada. Invariantes: `mode=shadow`, `influence_entries=false`, `orders_allowed=false`, `allow_shorts=false`, 15m, lookback 55, volumen 1.0x, gate bull. Al desplegar, verificar `breakout_20_55_shadow_observations`, `signal_stats.breakout_20_55_shadow`, `CYCLE TIMING.breakout_20_55_shadow` y cero órdenes. Producción actual sigue en `polaris-bot-tpshadowf6eb11b` PAPER.


### Verificación final Breakout20/55 — revisión `polaris-bot-br5520c4f3`

La revisión activa contiene el commit `c4f3ff4` y recibe 100% del tráfico. BOOT confirmó la configuración 15m/55/volumen 1.0x/gate bull en modo shadow. Se verificaron tres ciclos `Tick OK`; timing total: 145.050 s en el primer ciclo, 1.661 s y 3.238 s posteriormente. `breakout_20_55_shadow_s`: 0.136–0.156 s.

Firestore real `polaris/2026-08-19` confirmó a las 20:10:26Z: `PAPER`, equity `$99,288.27`, 0 posiciones, 0 órdenes; Breakout20/55 con 8 símbolos, 7 confirmadas, 1 no_setup y 0 errores. `gate_allowed=0` en la observación porque el régimen actual no era bull. `CYCLE TIMING` incluye la nueva fase.

La revisión se considera HEALTHY_SHADOW. El primer ciclo largo es de arranque/reconciliación heredado; los ciclos posteriores son sub-4 segundos. Mantener observación hasta acumular más sesiones y validar solapamiento contra DayBreakout antes de cualquier promoción.
