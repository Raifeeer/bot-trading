# Skill: Infraestructura y despliegue (GCP, Cloud Run, Firestore, Vercel, Telegram)

**Cubre:** el ciclo completo de vida del sistema Polaris: build, deploy, secretos, monitoreo, y los traps operativos conocidos.

## 1. Mapa de la infraestructura

| Componente | Ubicación | Nota crítica |
|---|---|---|
| Bot (`bot.py`) | Cloud Run, servicio `polaris-bot`, región `us-central1`, proyecto `gen-lang-client-0746441136` | minScale=1 (siempre activo) |
| Imagen Docker | Artifact Registry `us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot` | Tags descriptivos (ej. `s78-fix`); `latest` = última estable |
| Firestore | Base Native `polaris` (mismo proyecto) | Docs `polaris/YYYY-MM-DD` con merge por tick |
| Secretos | Secret Manager: `alpaca-key`, `alpaca-secret`, `deepseek-api-key`, `telegram-bot-token` | Cloud Run usa `valueFrom.secretKeyRef`; la SA tiene `roles/secretmanager.secretAccessor` solo en estos secretos |
| Dashboard | Vercel, proyecto `polaris-options-dashboard`, dominio `polaris-options-dashboard.vercel.app` | Estático precompilado (ver sección 5) |
| Telegram | Bot `@Raifeeer`, chat autorizado `1779931930` | Token en Secret Manager; polling en hilo + watchdog del hilo |
| Repo bot | GitHub `Raifeeer/bot-trading`, branch `main` | Código vigente desplegado desde `8c5f1dc`; handoff en `744814d` |
| Repo dashboard | GitHub `Raifeeer/Polaris-Web-Studio` | React 19 + Tailwind 4 |

## 2. Flujo de despliegue del bot (probado y documentado)

1. Clonar `Raifeeer/bot-trading` (main), aplicar cambios, compilar con `python3 -m py_compile` y pasar `tests/`.
2. Build de la imagen (docker con sudo):
   ```bash
   sudo docker build -t us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:s78-fix .
   ```
3. Autenticar y pushear. **Ojo:** `gcloud` vive en `/home/ubuntu/google-cloud-sdk/bin` (añadir al PATH). El login de docker requiere pasar el token de `gcloud` a la sesión de sudo:
   ```bash
   export PATH=/home/ubuntu/google-cloud-sdk/bin:$PATH
   gcloud auth print-access-token | sudo sh -c 'docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev'
   sudo docker push us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:s78-fix
   ```
4. Construir la imagen con Cloud Build y guardar el digest; desplegarla por digest, no por `latest`:
   ```bash
   gcloud builds submit --project=gen-lang-client-0746441136 --config=cloudbuild.yaml .
   gcloud run deploy polaris-bot --region us-central1 \
     --image us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot@sha256:... \
     --no-traffic --revision-suffix=<commit>
   ```
5. Verificar la revisión sin tráfico y después mover tráfico explícitamente. En cambios de configuración, exportar el spec completo y usar `services replace`; preservar `minScale=1`, `maxScale=1`, `cpu-throttling=false`, `PAPER`, secretos, Firestore y el rollback anterior.
6. Verificar: Cloud Logging con `Bot iniciado`, restauración del ledger, `Tick OK`, ausencia de tracebacks; Firestore y Alpaca deben coincidir en posiciones/órdenes. Antes de reanudar entradas, observar al menos dos ciclos y mantener una revisión de rollback identificada.

## 3. Traps operativos del servicio Cloud Run

**Envs y secretos.** NUNCA usar `gcloud run services update --set-env-vars` o `--set-secrets` aislados: reemplazan el bloque completo y pueden borrar variables existentes. Si hay que tocar envs, descargar el spec completo, editarlo y aplicar con `gcloud run services replace spec.yaml`. Si una variable pasa de literal a secreto, primero eliminar el literal y después usar `valueFrom.secretKeyRef`; si el spec contiene una anotación `run.googleapis.com/secrets` con rutas inválidas, reemplazarla declarativamente con nombres reales de Secret Manager. Verificar IAM de la SA con `roles/secretmanager.secretAccessor` antes de mover tráfico.

**Variables efectivas verificadas en la revisión vigente:** `APCA_API_BASE_URL=paper`, `DATA_PROVIDER=alpaca`, `POLL_SECONDS=60`, `BOT_POLL_MINUTES=5` (compatibilidad), `GCP_PROJECT_ID=gen-lang-client-0746441136`, `TELEGRAM_CHAT_ID=1779931930`; `FIRESTORE_DATABASE` usa por defecto `polaris` si no está definido. `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `DEEPSEEK_API_KEY` y `TELEGRAM_BOT_TOKEN` llegan desde Secret Manager. No cambiar `paper` a REAL sin confirmación explícita nueva.

**Ledger de salidas.** La colección dedicada es `polaris_exit_ledger/{ledger_id}`. La primera pata requiere claim idempotente con `create()`, las actualizaciones son versionadas y una salida solo se marca `completed` después de confirmar broker y Firestore. Un fallo de lectura/escritura mantiene el halt y no reintenta.

**Arranque.** `entrypoint.sh` levanta el health HTTP en 8080 y ejecuta `bot.py`. Endpoints del contenedor: `GET /` (health con equity), `/diag/state`, `/diag/fs` (prueba Firestore), `/diag/feed`.

## 4. Watchdogs y resiliencia del contenedor

El tick dura 10–12 minutos (yfinance es lento; el plan free de datos de Alpaca rechaza el SIP reciente con `"subscription does not permit querying recent SIP data"` y el bot hace fallback a yfinance por ticker). Mecanismos de defensa:

| Mecanismo | Ubicación | Comportamiento |
|---|---|---|
| Watchdog de tick | hilo en `bot.py` | Usa `os._exit(1)` si no hay tick completo en 12 min; Cloud Run recrea el contenedor (minScale=1) |
| Watchdog de Telegram | hilo en `bot.py` | Si el hilo de polling no hace heartbeat en `TG_HB_TIMEOUT_S` → `os._exit(1)` |
| Socket timeout | `data/feed.py` | `socket.setdefaulttimeout(45)` por ticker de yfinance, restaurado después |
| Tolerancia a régimen | paso 0 del tick | Si `classify_regime` falla, usa el último régimen conocido en lugar de bloquear |
| Tolerancia a timeframe | bucle de datos | Si un timeframe no descarga, el tick continúa con los demás y reintenta en el siguiente ciclo |

## 5. Despliegue del dashboard (Vercel)

El entorno de build de Vercel (Node 24 + wrapper de pnpm) falla de forma reproducible con `ERR_PNPM_META_FETCH_FAIL` / `ERR_INVALID_THIS` al hacer fetch del registry con plugins internos del template. La solución permanente: **construir el bundle localmente** (`pnpm install` + `pnpm build` en el sandbox) y desplegar **solo los artefactos estáticos precompilados** vía el MCP de Vercel (`deploy_to_vercel` con `framework: null`, outputDirectory apuntando al `dist` ya compilado, y `vercel.json` SPA en la raíz). El dashboard lee la DB `polaris` con `onSnapshot` en tiempo real: las reglas de Firestore permiten lectura pública con la API key configurada (`client/src/lib/firestore.ts`), así que el contenido se actualiza solo con cada tick del bot.

**Dato clave del frontend:** el bot publica las posiciones crudas en `payload.alpaca_positions` (piernas separadas, ej. `TQQQ260918C00085000` long + `TQQQ260918C00100000` short) y `payload.positions` queda vacío. El dashboard prioriza `alpaca_positions` cuando `positions` está vacío (`toPosRaw` en `client/src/lib/firestore.ts`). No revertir ese orden.

**Regla permanente del dueño:** absolutamente toda la información del dashboard debe ser real y provenir de una fuente identificable (Firestore publicado por el bot, Alpaca o backend propio). Prohibido mostrar datos mock/demo. Si no hay fuente para un campo, el panel se muestra vacío con su estado explícito.

## 6. Credenciales de acceso (para un agente orquestador)

Un agente con acceso `gcloud` al proyecto puede diagnosticar de forma segura así; no imprimir ni copiar valores de secretos:

```bash
gcloud run services describe polaris-bot --region us-central1 --format=export > spec.yaml
# Inspeccionar solo nombres de variables y referencias secretKeyRef.
# Para comparar un valor sensible, usar hashes en memoria; nunca imprimirlo.
```

Las credenciales de Alpaca PAPER se consumen exclusivamente desde `alpaca-key`/`alpaca-secret`; Telegram usa `telegram-bot-token`; nunca deben copiarse a esta skill ni a commits. El endpoint PAPER se resuelve desde `APCA_API_BASE_URL=paper` en la revisión vigente y no debe apuntar a REAL. Firestore se accede con la identidad de Cloud Run o, para diagnóstico REST, con `gcloud auth print-access-token` contra la base `polaris`. Si aparecen credenciales históricas en documentación, deben rotarse.

## 7. Historial de incidentes de infraestructura

| Síntoma | Causa raíz | Solución |
|---|---|---|
| Bot se congela ~50 min sin morir | yfinance sin timeout se cuelga en descargas Yahoo | Socket timeout 45s + watchdog 12 min |
| Envs `APCA_API_BASE_URL`/`DATA_PROVIDER` desaparecían | `--set-env-vars` reemplaza todo el bloque | Editar spec completo + `services replace` |
| `ERR_PNPM_META_FETCH_FAIL` en Vercel | pnpm/Corepack/Node 24 en el build de Vercel | Bundle estático precompilado |
| Alpaca data: "subscription does not permit querying recent SIP data" | Plan free de datos | Fallback automático a yfinance |
| Telegram tarda o no responde | LLM sin timeout congelaba el hilo de polling | Timeout 45s por llamada + watchdog del hilo |

## 8. Criterios de uso por el agente

Orden de intervención recomendado: (1) leer `AGENTS.md` y este documento; (2) para cambios de lógica, editar, compilar, probar con tests y modo `--dry-run`; (3) construir por Cloud Build y desplegar por digest con tráfico controlado; (4) verificar al menos 2 ciclos completos de tick en Cloud Logging, Firestore y Alpaca. Las fuentes de inestabilidad históricas son el market data de Yahoo y el polling de Telegram: cualquier cambio en `data/feed.py` o `state/telegram_bot.py` merece una ventana de observación prolongada antes de darse por bueno. Nunca crear posiciones solo para probar el executor sin autorización específica.
