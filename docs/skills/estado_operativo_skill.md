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
