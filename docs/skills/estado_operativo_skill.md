# Skill: Estado operativo del sistema Polaris (para agentes nuevos)

Esta skill es el **punto de entrada obligatorio** para cualquier agente que continúe, diagnostique u opere el sistema Polaris desde una sesión nueva. Resume el estado exacto de la infraestructura, el problema activo y cómo reanudarlo sin perder horas de diagnóstico. Última actualización: 14 de agosto de 2026, ~22:50 UTC.

## 1. Mapa del sistema en una mirada

| Pieza | Dónde está | Referencia clave |
|---|---|---|
| Código del bot | `/home/ubuntu/bot-trading-sync` (repo local; push a GitHub `Raifeeer/Polaris-Web-Studio` — el bot vive como carpeta `bot-trading-sync` dentro de ese repo) | `bot.py`, `AGENTS.md`, `docs/skills/` |
| Bot en producción | Cloud Run `polaris-bot`, us-central1, proyecto `gen-lang-client-0746441136` | SA `173223792589-compute@developer.gserviceaccount.com` |
| Imagen Docker | Artifact Registry `us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:latest` | Tag `latest` se actualiza en cada build |
| Dashboard (código) | Proyecto Manus webdev `/home/ubuntu/polaris-options-dashboard` | Checkpoint más reciente: `52f4cb52` |
| Dashboard (producción) | Vercel, https://polaris-options-dashboard.vercel.app | Deploy vía `vercel deploy --prebuilt` (pnpm build falla en el entorno; subir bundle pre-compilado) |
| Firestore | DB Native `polaris` (NO la default del proyecto, que es Datastore) | Keyfile: `/home/ubuntu/upload/gen-lang-client-0746441136-8353da1d9f65.json` |
| Broker | Alpaca **PAPER**: `https://paper-api.alpaca.markets/v2` | Key `PK6NXQZR54PK7DKCFEM7U3ULNE` (también en Secret Manager como `alpaca-key`) |
| Telegram | Bot @Raifeeer, chat id `1779931930` | Token en Secret Manager (`TELEGRAM_BOT_TOKEN`) y en sesión como `8790081999:AAFaJQdQhd7VCvStpd8M2HHpi2JsoP_JyRc` |
| LLM (Telegram) | DeepSeek V4 Flash (`deepseek-chat`), timeout 45 s | Secret Manager `deepseek-api-key`; fallbacks `gemini-api-key` y `grok-api-key` |
| Backtests | `/home/ubuntu/backtests/` + `backtest_retos.py` | Resultados S1–S89 documentados en `hallazgo*.md` |

**Advertencia de entorno:** en sesiones nuevas de la sandbox, `gcloud` no está en el PATH de inmediato. Restaurarlo con `export PATH=/home/ubuntu/.google/google-cloud-sdk/bin:$PATH` (también existe en `/home/ubuntu/google-cloud-sdk/bin`). No editar los archivos `.env` de la sesión con shell commands (restricción del entorno); usar la ruta completa al binario es suficiente.

## 2. El problema activo: el bot no escribe a Firestore

El dashboard mostraba equity congelado porque el bot completaba ticks cada 10–15 min pero **nunca publicaba snapshots**. Todo el diagnóstico (cronología completa en AGENTS.md sección 13) converge en esto:

1. La imagen vieja (revisión 00046) tenía un `NameError: cfg` en `_regime_snapshot` y además el import de `state.firestore_state` fallaba **antes** de `logging.basicConfig`, dejando `FIRESTORE_ENABLED=False` de forma silenciosa. Corregido en commits `ffe5943` y `6e70bab`.
2. Tras los fixes, los logs confirman `FIRESTORE_ENABLED=True`, el bloque de escritura se ejecuta, el tick termina (`Tick OK`), pero el doc del día **no se actualiza** y ningún warning de `state.firestore` llega jamás a Cloud Logging.
3. La misma service account **sí puede escribir**: el endpoint `/diag/fs` (dentro del mismo contenedor) escribe y lista docs correctamente, y una escritura idéntica con `firebase-admin` desde la sandbox también funciona.
4. **Probe instalado (commit `fee6a09a`, revisión activa `polaris-bot-00052-lbz`)**: antes de `write_state_snapshot`, `bot.py` intenta un `set({"probe": True}, merge=True)` mínimo; loguea `DIAG_FS: probe escrito` si funciona o imprime el traceback completo (`DIAG_FS ERROR:`) si falla.

**Hipótesis dominante:** el payload completo contiene un tipo no serializable (`Decimal`, `datetime` o un objeto de alpaca-py dentro de `_enriched_positions()` u `orders_executed`) y el error se pierde porque los warnings del módulo no llegan a Cloud Logging. El probe con payload mínimo lo confirmará o descartará.

**Pasos inmediatos para continuar:**
1. Esperar el siguiente `Tick OK` de la 00052 (los ticks tardan ~10 min) y leer logs: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=polaris-bot" --limit 100 --format="value(textPayload)"`.
2. Si `DIAG_FS: probe escrito` → limpiar tipos en el payload (`_enriched_positions`, `orders_executed`: convertir `Decimal`→`float`, `datetime`→`str`, objetos de alpaca-py a dicts) y esperar el snapshot real.
3. Si `DIAG_FS ERROR:` → seguir el traceback.
4. Tras validar: `gcloud run services update polaris-bot --region us-central1 --min-instances 1 --max-instances 1` (las 2 instancias actuales causan `HTTP 409` en el polling de Telegram).
5. Quitar el probe, redesplegar revisión limpia, y comprobar que `polaris/2026-08-14` queda con payload real (el `updated_at` dejará de decir "test-local").

**Estado del puente temporal:** existe un doc `polaris/2026-08-14` creado manualmente con un script local (equity 99689.5, `updated_at: "test-local"`, campo `probe: true`). Por eso el dashboard de Vercel ya muestra datos reales en vivo. Es un marcador de diagnóstico: será sobrescrito por el bot en cuanto la escritura funcione. Si el agente decide regenerar este puente, la escritura con `firebase-admin` desde la sandbox funciona de forma demostrada.

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

**Despliegue del bot.** El build local con `gcloud builds submit --config cloudbuild.yaml .` falla si el contexto incluye `__pycache__` o archivos whiteout de overlay (`.wh..wh..opq`): deben eliminarse antes. Tras `gcloud run deploy`, Cloud Run puede seguir enrutando a la **instancia vieja** (minScale=1 la satisface heredando instancia); siempre verificar con `gcloud run revisions list --format="table(metadata.name,status.active)"` que la nueva revisión esté activa y que una instancia de ella arrancó (`Bot iniciado` con timestamp reciente). Para forzar una instancia nueva: `--min-instances 2 --max-instances 2` y luego volver a 1/1.

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
