# Skill: Estado operativo del sistema Polaris (para agentes nuevos)

Esta skill es el **punto de entrada obligatorio** para cualquier agente que continúe, diagnostique u opere el sistema Polaris desde una sesión nueva. Resume el estado exacto de la infraestructura, los incidentes operativos y cómo reanudar el trabajo sin perder horas de diagnóstico. Última actualización: 15 de agosto de 2026, ~05:00 UTC.

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
| Backtests | `/home/ubuntu/backtests/` + `backtest_retos.py` | Resultados S1–S89 documentados en `hallazgo*.md` |

**Advertencia de entorno:** en sesiones nuevas de la sandbox, `gcloud` no está en el PATH de inmediato. Restaurarlo con `export PATH=/home/ubuntu/.google/google-cloud-sdk/bin:$PATH` (también existe en `/home/ubuntu/google-cloud-sdk/bin`). No editar los archivos `.env` de la sesión con shell commands (restricción del entorno); usar la ruta completa al binario es suficiente.

## 2. Incidente de Firestore: resuelto, pendiente de limpieza y redeploy

El dashboard había mostrado equity congelado porque el bot completaba ticks cada 10–15 minutos sin materializar snapshots. La investigación quedó documentada en `AGENTS.md`, sección 13. La revisión 00052 confirmó que el contenedor puede escribir y que el snapshot completo se publica correctamente.

**Evidencia verificada:**

- Cloud Run `polaris-bot-00052-lbz` está `Ready` y recibe el 100% del tráfico.
- Los logs muestran `FIRESTORE_ENABLED=True`, `DIAG_FS: probe escrito` y `Tick OK` con equity `99689.50`.
- Firestore `polaris/2026-08-15` tiene `updated_at=2026-08-15T04:42:24.592357+00:00`, `trading_mode=PAPER`, régimen `bull`, guarda de piso activa y 30 puntos de curva.
- El `payload` contiene campos reales: `alpaca_positions`, `orders_executed`, `positions`, `risk`, `strategies`, `universe` y `decisions_today`.

El probe confirmó permisos/ADC y el snapshot completo posterior confirmó que no hay fallo de serialización reproducible. El probe ya fue retirado de `bot.py`, la versión limpia quedó desplegada y el servicio está en `min-instances=1 / max-instances=1`; la revisión 00054 completó la escritura limpia, el documento se limpió de `probe`/`diag` mediante Firestore y el conflicto de polling quedó mitigado. La caché de feeds se añadió en el commit `fc9962f` y está desplegada en la revisión `polaris-bot-00055-7cd`; falta medir su primer ciclo completo en producción.

El incidente anterior tuvo tres causas operativas: un `NameError` en la imagen vieja, logging inicial posterior al import condicional de Firestore y reutilización de una instancia antigua cuando `min-instances=1`. Los fixes de logging/import y el despliegue forzado a dos instancias permitieron aislar y resolver el problema. No modificar el perfil de riesgo S78 como parte de esta limpieza.

## 3. Esquema Firestore (contrato bot ↔ dashboard)

El bot escribe cada tick con `set(merge=True)` en `polaris/{YYYY-MM-DD}` (fecha del **contenedor**, que corre en UTC):

```json
{"updated_at": "<iso>", "payload": {
  "equity": 99689.50, "cash": ..., "buying_power": ...,
  "positions": [], "alpaca_positions": [{"symbol": "O:TQQQ...", "structure": "debit_call_spread", ...}],
  "orders_executed": [], "trade_history": [], "signals": [],
  "risk": {"risk_per_trade_pct": 0.01, "max_positions": 5, "halted": false,
           "regime": "bull", "regime_summary": "...", "crash_active": false, "floor": {...}},
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

**Ciclo de tick.** Poll 5 min, watchdog 25 min (sin tick completo → `sys.exit(1)` y Cloud Run recrea la instancia). El tick completo tarda 10–15 min por timeouts de yfinance (socket timeout 45 s por ticker). Orden: snapshot Alpaca → circuit breakers → feed 5m/15m/1d → señales → risk → ejecución → gestión de posiciones (TP/SL prima, DTE) → escritura Firestore → Telegram.

## 5. Estado del trading al pausar (14 ago 2026)

Modo PAPER. Estrategias: SMC, S78 Regime-aware y régimen-aware (3). Régimen actual: **bull** (5/8 tickers). Posiciones abiertas: 0 (el spread TQQQ se cerró; equity Alpaca $99,689.50). El equity está **por debajo del piso $99,900**, por lo que el bot haltea entradas nuevas (regla correcta del reto: piso $99,900, meta $100,100). La calibración vigente es la del reto $100→$200 (universo barato SOFI/PLTR/F/TSLA/AMD/NOK/BB/TQQQ, spread debit deltas 0.25/0.10, DTE 10–45, prima máx $12, TP +40%/SL 25% de prima, riesgo 20%/trade, máx 2 posiciones, dd diario 15%/total 30%). Mecanismos de defensa activos: `crash_event` 3% (cierre, cool-down 5d) e `intraday_stop` 4%.

## 6. Pendientes de mayor orden (después de arreglar Firestore)

1. **Validar backtests con estrategia régimen-aware S78 en modo régimen-aware** (el backtest ganador S78/S51 aún no está portado al motor de producción 1:1; el motor de producción usa SMC + S78 + régimen-aware con otra parametrización).
2. **Caché de feeds** para acortar el tick de 10–15 min a ~2 min (los reintentos de yfinance dominan el ciclo).
3. **Stream de equity en tiempo real** de Alpaca (websocket gratuito del plan Basic) para el stop intradiario 4% y para actualizar el dashboard entre ticks.
4. **Telegram**: las respuestas a mensajes libres dependen del LLM (45 s timeout) y el usuario reportó latencia alta; evaluar respuestas asíncronas por chat action.
5. **Integración de contexto de mercado externo** (Unusual Whales descartada por ahora; Fear & Greed y proyecciones de analistas como filtro de calidad para el LLM de Telegram — anotado en AGENTS.md del usuario).
