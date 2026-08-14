# PolarIS Trading Bot — Guía de Operación para Agentes

> Documento de referencia para cualquier agente de IA que opere, diagnostique o extienda el sistema Polaris (bot de trading de opciones sobre Alpaca, desplegado en Google Cloud Run). Última actualización: 14 de agosto de 2026.

## 1. Qué es el sistema

PolarIS es un bot de trading automático de opciones sobre el universo Nasdaq/S&P 500. Analiza 15 tickers en múltiples timeframes, construye vertical spreads de opciones, ejecuta en Alpaca y publica su estado en tiempo real a Firestore, desde donde el dashboard en Vercel lo muestra. Está conectado a Telegram tanto para alertas salientes como para comandos interactivos con un asistente conversacional con IA.

**Arquitectura de alto nivel:**

| Capa | Componente | Dónde vive |
|---|---|---|
| Ejecución | Bot Python (bot.py) | Cloud Run, región us-central1, proyecto `gen-lang-client-0746441136` |
| Datos de mercado | yfinance (principal), Alpaca data API (respaldo) | Integrado en el contenedor |
| Ejecución de órdenes | Alpaca Paper Trading API | API externa |
| Estado en tiempo real | Firestore Native, base de datos `polaris` | GCP, mismo proyecto |
| Dashboard | React 19 + Tailwind 4 | Vercel (proyecto `polaris-options-dashboard`) |
| Telegram | Polling en hilo interno + alerts salientes | Dentro del mismo contenedor |
| Asistente IA (Telegram) | Módulo `state/ai_assistant.py` vía DeepSeek | Dentro del mismo contenedor |

## 2. Estructura del código

```
bot-trading/
├── bot.py                  # Loop principal: ticks cada 5 min, watchdog, snapshot a Firestore/Telegram
├── config/config.yaml      # Universo de tickers, riesgo, umbrales de señales
├── data/
│   └── feed.py             # Feed de datos: yfinance con socket timeout (45s), respaldo Alpaca
├── strategies/             # Estrategias de subyacente (swing/day)
│   └── strategy.py         # Strategy base + DayMomentum, DayBreakout, SwingTrend
├── options/
│   ├── chains.py           # SpreadBuilder: construcción de vertical spreads (deltas/DTE configurables)
│   ├── strategy.py         # OptionsStrategy: escaneo de señales → estructuras de opciones
│   └── feed.py             # OptionFeed: cadenas de opciones (live o simulado)
├── risk/
│   └── manager.py          # RiskManager: circuit breakers, drawdown, aprobación de posiciones
├── execution/
│   └── executor.py         # AlpacaExecutor: órdenes, snapshot de cuenta, dry-run
├── state/
│   ├── firestore_state.py  # Publicación del estado a Firestore (DB 'polaris')
│   ├── telegram_bot.py     # Comandos interactivos de Telegram (polling en hilo)
│   ├── telegram_notify.py  # Alertas salientes (apertura/cierre/riesgo)
│   └── ai_assistant.py     # Asistente conversacional IA (fallback de mensajes no-comando)
├── tests/                  # Tests locales (pytest)
├── Dockerfile              # Imagen: Python 3.12 + dependencias
├── entrypoint.sh           # Arranque: health HTTP en 8080 + exec bot.py
└── cloudbuild.yaml         # Pipeline opcional de build remoto
```

## 3. Cómo funciona un tick (loop principal)

Cada ciclo de `main()` en `bot.py` ejecuta, en orden:

1. **Snapshot de cuenta** en Alpaca → equity actual. Los circuit breakers de `RiskManager` evalúan drawdown diario/total; si se activan, el bot entra en HALT (solo monitorea, 10 min de pausa).
2. **Descarga de datos** por estrategia: Swing usa 1d (210 días para SMA200/ATR), Day usa 15m (10 días) y 5m (5 días). El proveedor principal es yfinance (el plan free de datos de Alpaca rechaza el SIP reciente); Alpaca se usa para órdenes y cuenta.
3. **Escaneo de señales**: cada estrategia evalúa su timeframe; `OptionsStrategy` traduce las señales a estructuras de opciones (call/put spreads) con deltas y DTE configurados en `config.yaml`.
4. **Aprobación de riesgo**: el risk manager valida tamaño, drawdown y número de posiciones.
5. **Ejecución**: `AlpacaExecutor` envía las órdenes (o las simula en dry-run).
6. **Gestión de posiciones**: evalúa TP/SL de prima y DTE. Los umbrales son configurables en `config.yaml` (`universo.options_reto` + `risk.prem_tp_mult`/`prem_sl_mult`) y se inyectan con `premium_exit_cfg` en `bot.py`; `evaluate_exit` en `options/strategy.py` admite `tp_mult`, `sl_mult`, `close_dte`, `hold_days`.
7. **Publicación de estado**: snapshot a Firestore (`polaris/YYYY-MM-DD`, merge) + curva de equity + actualización del estado del bot de Telegram.
8. **Heartbeat del watchdog** y sleep de 5 minutos (o 300 s en modo skip).

**Watchdog:** un hilo interno llama `sys.exit(1)` si no hay un tick completo en 12 minutos. Cloud Run recrea la instancia automáticamente al morir el proceso (minScale=1). Este mecanismo existe porque el feed de yfinance puede colgarse sin lanzar excepción.

**Timeout anti-freeze:** `fetch_yfinance` fuerza `socket.setdefaulttimeout(45)` por ticker y lo restaura después.

## 4. Credenciales y secretos

El service Cloud Run `polaris-bot` referencia estos secretos de Secret Manager como variables de entorno del contenedor:

| Env var | Secret / Origen | Uso |
|---|---|---|
| `APCA_API_KEY_ID` | alpaca-key (Secret Manager) | Clave de la API de Alpaca |
| `APCA_API_SECRET_KEY` | alpaca-key (Secret Manager) | Secreto de la API de Alpaca |
| `APCA_API_BASE_URL` | env var (valor) | `https://paper-api.alpaca.markets` — **PAPER; cambiar a `https://api.alpaca.markets` para REAL** |
| `DEEPSEEK_API_KEY` | deepseek-api-key (Secret Manager) | Asistente IA de Telegram (modelo `deepseek-chat`, sobrescribible con `DEEPSEEK_MODEL`) |
| `TELEGRAM_BOT_TOKEN` | env var (valor) | Token del bot @Raifeeer (8790081999:AAFaJQdQ...) |
| `TELEGRAM_CHAT_ID` | env var (valor) | Chat autorizado del dueño (1779931930) |
| `DATA_PROVIDER` | env var (valor) | `yfinance` (principal) |
| `FIRESTORE_DATABASE` | env var (valor) | `polaris` (base de datos Firestore Native) |

El contenedor se autentica con Firestore y Secret Manager mediante la **service account del servicio Cloud Run** (Compute Engine default SA del proyecto con rol `Secret Manager Secret Accessor` y permisos de Firestore Datastore). Un agente con acceso `gcloud` al proyecto `gen-lang-client-0746441136` puede leer las credenciales así:

```bash
gcloud secrets versions access latest --secret=alpaca-key --project=gen-lang-client-0746441136
gcloud secrets versions access latest --secret=deepseek-api-key --project=gen-lang-client-0746441136
gcloud run services describe polaris-bot --region us-central1 --format=json
```

Las claves de Alpaca paper concretas usadas durante el desarrollo (validas para pruebas): key `PK6NXQZR54PK7DKCFEM7U3ULNE`, secret `8HqWabPkVeWgig67o9topXdo6y65scrVuvVyoPK4Jkj5`, endpoint `https://paper-api.alpaca.markets/v2`.

El asistente IA de Telegram (`ai_assistant.py`) ahora usa **DeepSeek V4 Flash** con fallbacks a Gemini y Grok (API keys en Secret Manager del proyecto: `deepseek-api-key`, `gemini-api-key`, `grok-api-key`). Cada llamada al LLM tiene timeout de 45 s para evitar congelar el hilo de polling.

## 5. Despliegue

El flujo operativo del agente es:

1. Clonar `Raifeeer/bot-trading` (branch `main`) y aplicar los cambios.
2. Construir la imagen localmente (requiere `docker` con sudo):
   ```bash
   sudo docker build -t us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:latest .
   ```
3. Autenticar y pushear:
   ```bash
   export PATH=/home/ubuntu/google-cloud-sdk/bin:$PATH   # SDK instalado en /home/ubuntu/google-cloud-sdk
   gcloud auth activate-service-account --key-file=<keyfile del proyecto>
   gcloud auth print-access-token | sudo docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev
   sudo docker push us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:latest
   ```
4. Redesplegar creando nueva revisión (mantiene envs y secretos existentes):
   ```bash
   gcloud run services update polaris-bot --region us-central1 \
     --image us-central1-docker.pkg.dev/gen-lang-client-0746441136/polaris-images/polaris-bot:latest
   ```
5. Verificar: buscar `Bot iniciado`, `Tick OK` y ausencia de tracebacks en Cloud Logging, y confirmar que `curl https://polaris-bot-173223792589.us-central1.run.app/diag/state` devuelve un `mtime` reciente.

**No usar** `--set-env-vars` / `--set-secrets` aislados sobre el servicio: en revisiones previas eso borró envs existentes (`APCA_API_BASE_URL`, `DATA_PROVIDER`). Si hay que tocar envs, descargar el spec completo (`gcloud run services describe ... --format=yaml > spec.yaml`), editar y aplicar con `gcloud run services replace spec.yaml`.

Endoints del contenedor (puerto 8080): `GET /` (health: equity del último snapshot), `/diag/state` (archivo local de estado), `/diag/fs` (prueba de acceso a Firestore).

## 6. Firestore (estado publicado)

Base de datos Native `polaris` en `gen-lang-client-0746441136`. El bot escribe cada tick el documento `polaris/YYYY-MM-DD` con merge:

```json
{
  "updated_at": "...",
  "payload": {
    "equity": 100000.0, "cash": 100000.0, "buying_power": 400000.0,
    "positions": [], "alpaca_positions": [], "orders_executed": [],
    "risk": {"risk_per_trade_pct": 0.2, "max_positions": 2, "halted": false},
    "trading_mode": "PAPER", "strategies": [...], "decisions_today": [...],
    "updated_at": "..."
  },
  "equity_curve": [{"t": "...", "value": 100000.0}, ...]
}
```

Las reglas de seguridad permiten lectura pública con la API key del dashboard (Firebase web config en `client/src/lib/firestore.ts` del repo `polaris-options-dashboard`). El dashboard tiene un fallback de datos demo que se muestra solo mientras no exista el documento del día.

## 7. Configuración del objetivo actual (reto $100 → $200)

### 7.1 Calibración definitiva (backtests S1–S71, 14 ago 2026)

Se ejecutaron **71 escenarios de backtest** (`loop_backtests.py`, ventana de 90 días + ventanas del selloff ene-abr 2026 y lateral sep-dic 2025) sobre el universo reto. Los hallazgos consolidados están en `/home/ubuntu/backtests/hallazgo10.md`..`hallazgo15.md`.

**Estrategia régimen-aware (la definitiva):** el bot debe actuar según el régimen del mercado, no con un solo motor:

| Régimen | Acción | Evidencia de backtest |
|---|---|---|
| **Bull** (RSI14>50 + precio>SMA200 en ≥50% del universo) | **Hold semanal** equally weighted del universo reto | S51: +92% en 90 días vs S36 +53% |
| **CHoCH bear** (cierre bajo swing LOW tras HI dominante <60 días, en ≥30% del universo) | **Put spread 0.30/0.10 DTE 21**, solo tickers baratos con net ≤30% equity, TP 1.5 / SL 0.5, máx 2 pos | S63: +20.8% en el selloff de ene-abr 2026 (única estrategia positiva); con comisiones queda en break-even (+2.6%) |
| **Lateral** (ni bull ni bear) | **CASH**: no operar | S55: S36 0 trades (capital intacto) vs hold -96% (rebalanceo diario, bug corregido) |
| **Rebote en selloff** (RSI<25 + precio>SMA100) | Call spread S36 0.30/0.10 DTE 21, budget 15% | S36: +53–60% con 71–75% win rate |

**Regla de oro descubierta:** con $100 de capital, un put spread delta 0.30/0.10 DTE 21 cuesta $25-45 en tickers baratos y $150-1700 en PLTR/TSLA/TQQQ/AMD; solo BB/NOK/F/SOFI son operables con el presupuesto. DTE corto OTM (7-10 días) es un error: theta lo destruye (S67: -48%).

| Parámetro | Valor | Racional |
|---|---|---|
| Universo reto | SOFI, PLTR, F, TSLA, AMD, NOK, BB, TQQQ | Tickers baratos y líquidos; **se excluyen LCID y MARA** (vol. histórica ~150%: primas impagables, spreads simulados degenerados) |
| `max_vol_pct` | 100% | Excluir automáticamente tickers con vol. anualizada > 100% |
| Estructura | Call spread debit (bull) | Riesgo definido; la pata corta reduce coste neto y theta |
| Deltas | long **0.25** / short **0.10** | Prima asequible con exposición razonable |
| DTE | **10–45** (`close_dte` 7) | Ni theta extremo (0-7 DTE) ni vega de más; cierre a 7 DTE |
| Prima neta máx | **$12** por spread (~12% del capital) | Presupuesto por contrato para $100 |
| Gestión TP/SL | TP **+40%** de prima / SL al **25%** de prima (-75%) | Evita decaer posiciones hasta -90%; el backtest B perdió 93% de la prima sin stop activo |
| Riesgo | 20% capital/trade, máx. 2 posiciones, drawdown diario 15%, total 30% (HALT a $70) | Válvulas de seguridad del capital pequeño |

El script de backtest es `backtest_retos.py` en la raíz (señales reales del motor + precios simulados Black-Scholes con vol. histórica de yfinance). Sirve para comparar calibraciones, no para estimar P&L real (las primas simuladas asumen BS con IV=vol. histórica y un margen del 20%).

### 7.2 Paso a real
Cuando el usuario fondee la cuenta real de Alpaca y quiera operar con dinero real, el cambio mínimo es `APCA_API_BASE_URL` → `https://api.alpaca.markets` (y re-evaluar el perfil de riesgo, que hoy es demasiado agresivo para capital real grande).

## 8. Telegram

El módulo `state/telegram_bot.py` corre un hilo de polling contra `api.telegram.org` y responde solo a mensajes del `TELEGRAM_CHAT_ID`. Comandos: `/estado` (equity, cash, buying power, P&L del día), `/posiciones` (detalle de spreads y de Alpaca), `/historial` (operaciones cerradas), `/señales` (decisiones recientes), `/riesgo` (circuit breakers y límites), `/ayuda`. Cualquier mensaje que no sea comando cae en el asistente IA (`state/ai_assistant.py`), que envía al LLM (DeepSeek) el estado real del bot como contexto y responde en español. Las notificaciones salientes (`telegram_notify.py`) avisan de apertura/cierre de posiciones y eventos de riesgo.

## 9. Dashboard (Vercel)

Proyecto `polaris-options-dashboard` desplegado en `polaris-options-dashboard.vercel.app`. Lee la DB `polaris` con suscripción `onSnapshot` y mapea el payload a las secciones Consola, Posiciones, Señales, Riesgo y Backtest. El estado EN VIVO y el modo PAPER/REAL vienen directamente de Firestore. Para redeployar el dashboard: `pnpm build` + `vercel deploy` (conectado vía MCP/Vercel CLI al proyecto del usuario).

> **REQUISITO PERMANENTE DEL USUARIO (agosto 2026): absolutamente TODA la información del dashboard debe ser REAL y provenir de una fuente identificable (Firestore publicado por el bot, Alpaca, o un backend propio). Está PROHIBIDO mostrar datos mock, demo o inventados.** La hoja de ruta para eliminar los restos de datos demo es:
> 1. `client/src/lib/mockData.ts`: reemplazar cada dataset por lectura real. Las métricas de backtest deben venir del pipeline de backtest (Firestore o API del bot, p. ej. `backtest_retos.py` publicando sus resultados), no de valores embebidos.
> 2. Panel `BT-04` (win rate 62%, Sharpe 1.42, 47 ops) y `SIG-01`/`RSK-01` con datos demo cuando el doc del día no existe: mostrar estado vacío con etiqueta "esperando primer tick" en lugar de cifras inventadas.
> 3. Página `Backtest`: ejecutar el backtest como paso del pipeline (Cloud Run job o endpoint) y servir el resultado desde Firestore.
> 4. Si una fuente real aún no existe para algún campo, NO inventarla: el frontend debe declararlo vacío u ocultar el panel.

**Estado actual (14 ago 2026):** equity, posiciones, modo y universo ya son 100% en vivo desde Firestore. Pendiente: curva de equity sin datos → mostrar estado vacío; métricas de backtest y señales/demo siguen embebidas en `mockData.ts` (hoja de ruta anterior).

## 10. Historial de incidentes conocidos (para diagnóstico)

| Síntoma | Causa raíz | Solución aplicada |
|---|---|---|
| El bot se congela cada ~50 min sin morir ni loguear | `yfinance` sin timeout se cuelga en descargas Yahoo | Socket timeout 45 s por ticker + watchdog de 12 min que reinicia el proceso |
| `AttributeError: 'DayMomentum' object has no attribute 'cfg'` | El loop accedía a `strat.base.cfg` inexistente | Usar `strat.timeframe` / `strat.base.timeframe` |
| `NameError: threading` al arrancar | Watchdog usa `threading.Thread` sin import | `import threading` en `bot.py` |
| `UnboundLocalError: skip_tick` | Variable usada fuera de scope tras reordenar el loop | Calcular `skip_tick` antes de usarla |
| Los envs `APCA_API_BASE_URL`/`DATA_PROVIDER` desaparecían tras updates | `gcloud run services update --set-env-vars` reemplaza todo el bloque | Editar el spec completo y aplicar con `services replace` |
| Dashboard muestra datos demo | El doc del día no existía aún en Firestore | Normal: aparece el estado real en el primer tick completo (~10-12 min tras arranque) |
| El bot no respondía en Telegram / tardaba mucho | LLM sin timeout congelaba el hilo; NameError en main loop | Timeouts de 45 s por llamada LLM + watchdog heartbeat; caso actual: Telegram en pausa para testing del dueño (14 ago) |
| Benchmark hold con rebalanceo diario daba -67%/-96% | Bug: recompraba el mismo día con el mismo precio | Rebalanceo semanal (S57/S58: -6.8% selloff, +9.7% lateral) |
| `put_choch_entry` nunca disparaba | `detect_choch` original demasiado estricto | CHoCH pragmático: cierre bajo swing LOW con HI dominante <60 días (S63 +20.8%) |
| `build_spread(put)` devolvía None | Swap de strikes invertía las patas | Put long = strike MAYOR (más ATM), short = menor; débito = px_l - px_s |
| Alpaca data API: "subscription does not permit querying recent SIP data" | Plan free de datos de Alpaca | Fallback automático a yfinance por ticker |
| El bot no abría trades para el reto $100 con la calibración original | Las primas de megacaps superaban el presupuesto ($0.50/$50 de prima neta) | Perfil reto en config: universo barato, delta 0.25/0.10, prima máx $12, DTE 10-45 |
| LCID devoró -93% de la prima en el backtest sin gestión | Sin stop de prima: posiciones DTE cortos dejadas a decaer | SL de prima al 25% + cierre a 7 DTE + cierre a mitad de vida sin ganancia |
| LCID/MARA producían spreads degenerados en el simulador | Vol. histórica ~150% empuja strikes muy OTM (46%) y el spread net cae a ~0 | `max_vol_pct: 100` y exclusión explícita de LCID/MARA del universo reto |
| Comisiones de $0.65/pata comen el edge en spreads baratos | $2.60 por spread (entr+sal × 2 patas) = 6-33% del capital | Modeladas en S50/S56/S69; puts con comisiones solo break-even (+2.6%) |

## 11. Cómo operar este sistema un nuevo agente

El orden recomendado para cualquier intervención: (1) leer esta guía y `bot.py` completo; (2) para cambios de lógica, editar, probar localmente con `python3 -m py_compile` + los tests en `tests/`, y ejecutar el bot en modo `--dry-run` con credenciales paper; (3) redeployar vía Docker + `services update` como en la sección 5; (4) verificar con Cloud Logging y `/diag/state` que los ticks corren al menos 2 ciclos seguidos (~25 min). El market data de Yahoo y el poll de Telegram son las fuentes de inestabilidad históricas; cualquier cambio en `data/feed.py` o `state/telegram_bot.py` merece una ventana de observación de 30 minutos.
