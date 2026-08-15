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
| `TELEGRAM_BOT_TOKEN` | Secret Manager (`TELEGRAM_BOT_TOKEN`) | Token del bot @Raifeeer; no documentar el valor |
| `TELEGRAM_CHAT_ID` | env var (valor) | Chat autorizado del dueño (1779931930) |
| `DATA_PROVIDER` | env var (valor) | `yfinance` (principal) |
| `FIRESTORE_DATABASE` | env var (valor) | `polaris` (base de datos Firestore Native) |

El contenedor se autentica con Firestore y Secret Manager mediante la **service account del servicio Cloud Run** (Compute Engine default SA del proyecto con rol `Secret Manager Secret Accessor` y permisos de Firestore Datastore). Un agente con acceso `gcloud` al proyecto `gen-lang-client-0746441136` puede leer las credenciales así:

```bash
gcloud secrets versions access latest --secret=alpaca-key --project=gen-lang-client-0746441136
gcloud secrets versions access latest --secret=deepseek-api-key --project=gen-lang-client-0746441136
gcloud run services describe polaris-bot --region us-central1 --format=json
```

Las credenciales de Alpaca PAPER no deben aparecer en documentación ni commits. Se consumen desde Secret Manager mediante `alpaca-key`; el endpoint es `https://paper-api.alpaca.markets/v2`. Las credenciales que aparecieron en documentación histórica deben rotarse.

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

Las reglas de seguridad permiten lectura pública con la API key del dashboard (Firebase web config en `client/src/lib/firestore.ts` del repo `polaris-options-dashboard`). Si no existe el documento del día, el dashboard debe mostrar estado vacío explícito (`—`) y nunca datos demo o inventados.

## 7. Configuración del objetivo actual (reto $100 → $200)

### 7.1 Calibración definitiva (backtests S1–S89, 14 ago 2026)

Se ejecutaron **89 escenarios de backtest** (`loop_backtests.py`, ventana de 90 días + ventanas del selloff ene-abr 2026, lateral sep-dic 2025 y ventana reciente abr-ago 2026) sobre el universo reto. Los hallazgos consolidados están en `/home/ubuntu/backtests/hallazgo10.md`..`hallazgo16.md`.

**Estrategia régimen-aware (la definitiva):** el bot debe actuar según el régimen del mercado, no con un solo motor:

| Régimen | Acción | Evidencia de backtest |
|---|---|---|
| **Bull** (RSI14>50 + precio>SMA200 en ≥50% del universo) | **Hold semanal** equally weighted del universo reto | S51: +92% en 90 días vs S36 +53% |
| **CHoCH bear** (cierre bajo swing LOW tras HI dominante <60 días, en ≥30% del universo) | **Put spread 0.30/0.10 DTE 21**, solo tickers baratos con net ≤30% equity, TP 1.5 / SL 0.5, máx 2 pos | S63: +20.8% en el selloff de ene-abr 2026 (única estrategia positiva); con comisiones queda en break-even (+2.6%) |
| **Lateral** (ni bull ni bear) | **CASH**: no operar | S55: S36 0 trades (capital intacto) vs hold -96% (rebalanceo diario, bug corregido) |
| **Rebote en selloff** (RSI<25 + precio>SMA100) | Call spread S36 0.30/0.10 DTE 21, budget 15% | S36: +53–60% con 71–75% win rate |
| **Bear suave HTF** (bajo SMA200 pero sin CHoCH, ej. abr-ago 2026) | **Cash + hold solo si bull local**; NO puts (RV alta encarece los spreads) | S78: +26.7% (bull→hold, bear→cash) fue el GANADOR de la ventana reciente; S75 -32.9%, S76 -6.6% |

**Regla de oro descubierta:** con $100 de capital, un put spread delta 0.30/0.10 DTE 21 cuesta $25-45 en tickers baratos y $150-1700 en PLTR/TSLA/TQQQ/AMD; solo BB/NOK/F/SOFI son operables con el presupuesto. DTE corto OTM (7-10 días) es un error: theta lo destruye (S67: -48%).

### 7.1.1 Prueba de estrés ante crash abrupto (hallazgo17)

Se construyó `stress_test.py` que inyecta crashes sintéticos en el feed real de yfinance (universo reto) y evalúa S78. El CHoCH protege en selloffs negociables (2-4 semanas) pero **no protege en flash crashes de ≤3 días**: la estructura HI/LO que requiere el detector no existe durante un pánico repentino, y la reacción llega 2-5 días tarde, vendiendo en el fondo.

| Escenario | Perfil | S78 mitigado | S78 base |
|---|---|---|---|
| E1 Flash | -20% en 1 día | $96.1 (dd -4.3%) | $90.0 (dd -24.4%) |
| E2 Severo | -35% en 5 días + rebote +50% | $138.3 (+38.3%, dd 0%) | $116.6 (+16.6%) |
| E3 Catastrófico | -50% en 3 días sin rebote | límite físico (cae antes de cortar) | $54.6 (-45.4%) |
| E4 Realista | -30% en 20 días + débil | $116.6 (dd 0%) | $116.8 |

**Mitigación implementada** en el motor `regime_hold_cash` de `loop_backtests.py`: parámetro `crash_event=0.03` — si ≥30% del universo pierde ≥3% en 2 sesiones de cierre, se corta el hold a cash de inmediato, con cool-down de 5 días tras la activación (evita cortes falsos en pánicos en fases). Validado en la ventana real abr-ago 2026: dd mejora de -40.3% a -28.0% con equity superior ($128.9 vs $126.7). El caso E3 es un límite físico de cualquier estrategia de cierre diario: para un -50% en 72h la defensa requiere stops intradiarios o reducción de exposición fija.

### 7.1.2 Defensa intradiaria: stop del 4% (hallazgo18)

Se construyó `stress_intraday.py` sobre el mismo marco sintético para evaluar stops intradiarios (umbrales 4/6/8/10% sobre `(1-ith)×close_prev` del subyacente, medibles en producción con el stream de equity de Alpaca, gratuito en el plan Basic). Resultados:

| Escenario | Base | Stop 4% | Stop 6% | Stop 8% | Stop 10% |
|---|---|---|---|---|---|
| E1 Flash -20% 1d | $96.1 (dd -4.3%) | **$97.9 (dd -2.8%)** | $96.5 | $96.3 | $96.1 |
| E2 Severo -35% 5d +rebote | **$141.6 (+41.6%, dd 0%)** | igual (neutro) | $132.3 | $129.7 | $126.7 |
| E3 Catastrófico -50% 3d | $96.1 (dd -4.3%) | **$97.9 (dd -2.8%)** | $96.5 | $96.3 | $96.1 |
| E3c Rebal mismo día + shock gradual | $97.3 (dd -2.7%) | **$100.5 (+0.5%, dd 0%)** | $98.6 | $97.6 | $97.4 |
| Real abr–ago 2026 | $128.9 (+28.9%, dd -7.3%) | **$132.5 (+32.5%, dd -4.8%)** | $130.6 | $129.0 | $128.9 |

**Conclusiones:** (1) el umbral óptimo es **4%**: mejora el flash crash, el catastrófico y el peor caso de timing (E3c) sin degradar nunca; umbrales ≥6% se disparan tarde y en selloffs con rebote destruyen hasta +15 puntos de equity. (2) El peor caso real (entrar el rebalance el día 1 del crash con caída -17% intradiaria tras un rally falso del +2%) pasa de -2.7% de drawdown a **break-even positivo** con stop 4%. (3) El gap de apertura no se evita (límite físico: ya consumado antes del stream); el stop solo acorta el resto del día. **Defensa adoptada para producción:** `crash_event` 3% (cierre) + `intraday_stop` 4% (stream equity websocket de Alpaca + orden stop/stop-limit nativa de opciones con límite ajustado 1–2% para no aceptar fills ruinosos; en gap extremo el stop-limit puede quedar pendiente). Complemento para spreads de opciones: trailing stop sobre la prima del 30–40%.

**Nota de infraestructura:** el antiguo `inject_crash` concatenaba barras sintéticas con tz/hora desalineada (corrompía la cronología: el motor veía el precio real en lugar del shock). Se corrigió para que las sintéticas **REEMPLACEN** las reales de las mismas fechas, con fechas alineadas fila a fila (salto de fines de semana consistente) y hora igual al histórico real.

Implementación en el motor: parámetros `intraday_stop` (precio de quiebre `(1-ith)×close_prev` en rebalance y cierre bear) y `force_bull_until` (solo para stress testing).


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

**Estado actual auditado (15 ago 2026):** equity, posiciones, modo, universo, curva y BT-04 se observan en producción desde Firestore. El documento `polaris/backtest` es real y publica `source=loop_backtests.py (89 escenarios S1-S89)`, mejor escenario `S51`, retorno `92.5%`, win rate `44.3%` y 61 trades; los valores visibles `44% win` y `S51 · 92.5%` son redondeos legítimos. Las señales no publicadas se muestran como estado vacío explícito.

El bundle de producción conserva la ruta de fuente `client/src/pages/Home.tsx`, pero esa fuente no está disponible en la sandbox y el repo local `Raifeeer/Polaris-Web-Studio` es el sitio comercial principal, no el dashboard de trading. No modificar ese repo como dashboard sin recuperar la fuente correcta del proyecto Vercel/Manus.

Se detectó una posible corrección de presentación: el bundle formatea `riskPerTradePct.toFixed(1)` directamente, mientras el bot publica `payload.risk.risk_per_trade_pct=0.01` como fracción decimal. Por eso la interfaz muestra `0.0% del capital` aunque el valor real equivale a 1%. Recuperar `Home.tsx`, confirmar el contrato, corregir la conversión a porcentaje y añadir una prueba antes de desplegar. El texto `Gestión: esperando reglas publicadas por el bot` indica que el payload actual no publica reglas de gestión suficientes para ese panel; no inventar esos valores.

## 10. Historial de incidentes conocidos (para diagnóstico)

| Síntoma | Causa raíz | Solución aplicada |
|---|---|---|
| El bot se congela cada ~50 min sin morir ni loguear | `yfinance` sin timeout se cuelga en descargas Yahoo | Socket timeout 45 s por ticker + watchdog de 25 min que reinicia el proceso |
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

### 10.1 Mejora de feeds preparada el 15 ago 2026

`data/feed.py` incorpora una caché en memoria por símbolo/timeframe con TTL por defecto de 900 s para `1d`, 600 s para `15min`, 240 s para `5min` y 45 s para `1min`. Un histórico superset de 400 días reutiliza la misma descarga para el régimen y la consulta de 100 días de swing; una prueba aislada confirmó una sola descarga y un recorte correcto. La caché se pierde al reiniciar el contenedor, no modifica señales ni riesgo. Quedó desplegada en Cloud Run en el commit `fc9962f`, revisión `polaris-bot-00055-7cd`, el 15 de agosto de 2026 a las 05:54 UTC; falta medir el primer ciclo completo en producción y comparar su duración con la revisión 00054.

## 11. Skills detalladas (para orquestación por otro agente)

El directorio **`docs/skills/`** contiene la documentación exhaustiva de cada criterio, estrategia y mecanismo del sistema, pensada para que un agente futuro pueda operar, diagnosticar o extender el bot sin perder contexto:

| Skill | Qué documenta |
|---|---|
| `docs/skills/smc_skill.md` | SMC multi-timeframe (1D/4H/M15/M1), CHoCH pragmático, zonas S&D, errores corregidos |
| `docs/skills/wheel_skill.md` | The Wheel (cash-secured puts → covered calls), parámetros calibrados, integración con SMC |
| `docs/skills/regime_s78_skill.md` | Régimen S78, crash_event 3% + cool-down 5d, stop intradiario 4%, guarda de piso $99,900 |
| `docs/skills/riesgo_skill.md` | RiskManager: circuit breakers, sizing 5%, TP/SL de prima, anti-earnings |
| `docs/skills/backtest_skill.md` | Metodología de ventanas, resultados S1–S89, estrés E1–E4, umbrales 4/6/8/10% |
| `docs/skills/datos_skill.md` | Feed yfinance/Alpaca, caché TTL por timeframe, timeouts, watchdog, decisiones deliberadas (sin TradingView) |
| `docs/skills/infra_skill.md` | Build/deploy Cloud Run, traps de envs, deploy estático de Vercel, credenciales |
| `docs/skills/dashboard_telegram_skill.md` | Contrato Firestore ↔ dashboard, comandos Telegram, asistente IA con fallbacks |
| `docs/skills/estado_operativo_skill.md` | **PUNTO DE ENTRADA para agentes nuevos**: mapa del sistema, incidente Firestore resuelto (14–15 ago 2026), limpieza pendiente y plan de reanudación |

## 12. Cómo operar este sistema un nuevo agente

El orden recomendado para cualquier intervención: (1) leer primero `docs/skills/estado_operativo_skill.md` (estado operativo al momento de pausar, 14 ago 2026) y esta guía; (2) leer `bot.py` completo; (3) para cambios de lógica, editar, probar localmente con `python3 -m py_compile` + los tests en `tests/`, y ejecutar el bot en modo `--dry-run` con credenciales paper; (4) redeployar vía Docker + `services update` como en la sección 5; (5) verificar con Cloud Logging y `/diag/state` que los ticks corren al menos 2 ciclos seguidos (~25 min). El market data de Yahoo y el poll de Telegram son las fuentes de inestabilidad históricas; cualquier cambio en `data/feed.py` o `state/telegram_bot.py` merece una ventana de observación de 30 minutos.

## 13. INCIDENTE RESUELTO: publicación de snapshots a Firestore (14–15 ago 2026)

**Síntoma original:** el dashboard en Vercel mostraba equity congelado ($99,669.50) y sin posiciones. El bot completaba ticks cada 10–15 minutos, pero el snapshot diario no se materializaba en Firestore.

**Estado actual (verificado el 15 de agosto de 2026):** la revisión `polaris-bot-00052-lbz` escribe correctamente el snapshot completo a la DB Native `polaris`. La resolución se confirmó con `FIRESTORE_ENABLED=True`, el probe mínimo `DIAG_FS: probe escrito`, `Tick OK` posterior y un documento `polaris/2026-08-15` con `updated_at` real, `payload` completo y curva de equity. El probe era diagnóstico y debe retirarse antes del redeploy limpio; no forma parte del comportamiento permanente.

### 13.1 Cronología y hallazgos del diagnóstico

El incidente se rastreó el 14 de agosto de 2026 (tarde, hora AST; la revisión activa al inicio era `polaris-bot-00046`). Los hallazgos, en orden, fueron los siguientes.

1. **Imagen desactualizada con NameError.** La revisión 00046 en producción tenía un `NameError: name 'cfg' is not defined` en `_regime_snapshot` (firma cambiada en local pero la imagen llevaba código viejo). Se construyó y desplegó la imagen actual vía `gcloud builds submit --config cloudbuild.yaml .` + `gcloud run deploy`.
2. **El import de Firestore fallaba antes de configurar el logging.** El bloque `try: from state.firestore_state import ...` de `bot.py` ocurre antes de `logging.basicConfig`, por lo que cualquier fallo de import quedaba completamente silencioso: `FIRESTORE_ENABLED` permanecía en `False` y ningún log lo delataba. Corregido en commits `ffe5943` (loguear excepción del import) y `6e70bab` (mover `basicConfig` antes del try).
3. **El watchdog mataba instancias antes de que el tick terminara.** Los ticks tardan 10–15 min por timeouts repetidos de yfinance (SOFI, PLTR, F y AMD dan "possibly delisted" en ventanas intradiarias y el plan free de Alpaca rechaza el SIP reciente: `subscription does not permit querying recent SIP data`). El watchdog de 25 min reiniciaba la instancia cuando el feed se alargaba.
4. **Confusión entre rutas de Firestore.** El doc real y antiguo era `polaris/2026-08-13` (escrito el 13 de agosto por la versión anterior, equity 100000 fijo); **no existía ningún doc del día 14**, por lo que el dashboard mostraba el estado congelado de ayer. El dashboard lee `polaris/{fecha-local-del-navegador}`, así que la ruta coincide en horario normal pero el doc no se actualizaba.
5. **El contenedor SÍ puede escribir a Firestore.** El endpoint `/diag/fs` del health server (mismo contenedor, misma service account `173223792589-compute@developer.gserviceaccount.com`, mismas ADC) escribe correctamente: listó `["2026-08-13", "2026-08-14", "backtest"]`. Una escritura idéntica desde la sandbox con `firebase_admin` + keyfile (`/home/ubuntu/upload/gen-lang-client-0746441136-8353da1d9f65.json`, DB `polaris`) también funciona. Las credenciales no son el problema.
6. **Tras el fix de import, FIRESTORE_ENABLED=True pero la escritura sigue sin materializarse.** Logs del 14/08 22:21 confirman `FIRESTORE_ENABLED=True (antes de write_state_snapshot)` y el tick se completó (`Tick OK`), pero el doc `polaris/2026-08-14` no se creó/actualizó. Curiosidad clave: el warning `logger.warning("Fallo al escribir estado en Firestore: %s", e)` del módulo `state/firestore_state.py` **nunca aparece en Cloud Logging** (cero apariciones en ~5000 líneas revisadas), ni siquiera el `logger.exception("Error publicando estado a Firestore")` del except de `bot.py` (línea ~558). Esto sugiere que los mensajes del logger `state.firestore` no llegan al stdout capturado por Cloud Run, o que el bloque de escritura no se ejecuta por otra ruta.
7. **min-instances=1 reutilizaba la instancia vieja.** Cloud Run satisfacía minScale=1 con la instancia heredada de la revisión anterior, por lo que los fixes no se aplicaban aunque la revisión nueva tuviera 100% del tráfico. Solución operativa: desplegar con `--min-instances 2 --max-instances 2` para forzar una instancia de la última revisión y verificar con `gcloud run revisions list --format="table(metadata.name,status.active)"`.

### 13.2 Evidencia de resolución

La revisión `polaris-bot-00052-lbz` quedó activa el 14 de agosto con `min-instances=2 / max-instances=2` para forzar una instancia de la revisión nueva y evitar que Cloud Run reutilizara la instancia vieja. En los logs de esa revisión se verificó:

- `FIRESTORE_ENABLED=True (antes de write_state_snapshot)`.
- `DIAG_FS: probe escrito en polaris/2026-08-15`.
- `Tick OK — equity=99689.50 posiciones=0`.
- El documento `polaris/2026-08-15` tiene `updated_at=2026-08-15T04:42:24.592357+00:00`, `trading_mode=PAPER`, régimen `bull`, guarda de piso activa y 30 puntos de curva de equity.
- El documento contiene campos reales de `payload`, incluyendo `alpaca_positions`, `orders_executed`, `positions`, `risk`, `strategies`, `universe` y `decisions_today`.

La evidencia descarta tanto un problema de permisos/ADC como un fallo de serialización del payload en la revisión activa. El snapshot completo se escribió después del probe. El `probe: true` permanece temporalmente en el documento porque la escritura diagnóstica usó `merge=True`; debe eliminarse o quedar reemplazado al limpiar el documento.

El código del repositorio se actualizó al `origin/main` (`0cd0fd5`) y el probe ya fue retirado localmente de `bot.py`. Falta desplegar esa versión limpia, comprobar dos ticks y devolver el servicio a una sola instancia para eliminar el conflicto de polling de Telegram.

### 13.3 Diagnóstico final

1. **Permisos y ADC:** descartados. `/diag/fs` y el probe usaron la misma identidad de Cloud Run y escribieron en la DB `polaris`.
2. **Import silencioso:** corregido al mover `logging.basicConfig` antes de los imports condicionales y registrar cualquier excepción; la revisión activa confirma `FIRESTORE_ENABLED=True`.
3. **Serialización del payload:** no se reprodujo en la revisión 00052; el snapshot completo se publicó con posiciones, órdenes, riesgo y curva de equity.
4. **Instancia antigua:** mitigado forzando temporalmente `min/max-instances=2`. Debe revertirse a `1/1` después del redeploy limpio.
5. **Probe y documento puente:** son residuos de diagnóstico. El probe se elimina del código y el campo temporal del documento se limpia con una operación Firebase/Firestore explícita, sin borrar los datos reales del día.

### 13.4 Cierre y acciones pendientes inmediatas

1. Ejecutar `python3 -m py_compile bot.py state/firestore_state.py` y las pruebas locales disponibles.
2. Hacer commit y push del `bot.py` sin probe y de esta actualización documental.
3. Construir y publicar una imagen limpia desde el repositorio `Raifeeer/bot-trading`, sin `--set-env-vars` ni `--set-secrets` aislados.
4. Actualizar Cloud Run solo con la imagen, verificar que la revisión resultante esté `Ready` y que registre un `Bot iniciado` reciente.
5. Esperar y verificar **dos ticks completos** con `FIRESTORE_ENABLED=True`, `Tick OK` y `updated_at` avanzando en `polaris/2026-08-15`.
6. Ajustar `min-instances=1` y `max-instances=1`; confirmar que desaparece el `409 Conflict` de Telegram.
7. Limpiar únicamente los campos temporales `probe`/`diag` del documento del día mediante Firestore, conservando el payload real y la curva de equity.
8. Comprobar el dashboard `https://polaris-options-dashboard.vercel.app` y documentar el timestamp visible y la fuente Firestore.

No se debe modificar el perfil de riesgo, el régimen S78 ni las reglas del reto `$100 → $200` como parte de este incidente.

### 13.5 Comandos de diagnóstico rápidos (probados y funcionales)

```bash
# Logs del servicio (los errores de Telegram/reintentos de feed son ruido normal; filtrarlos)
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=polaris-bot" --limit 100 --format="value(textPayload)" | grep -viE "reintento|apierror|WARNING feed|Failed to get|TzCache|Conflict"

# Instancias activas por revisión (clave para saber qué código corre)
gcloud run revisions list --service polaris-bot --region us-central1 --format="table(metadata.name,status.active)"

# Probar escritura a Firestore desde cualquier máquina con el keyfile
# (firebase-admin, keyfile /home/ubuntu/upload/gen-lang-client-0746441136-8353da1d9f65.json,
#  initialize_app con {'databaseURL':'https://gen-lang-client-0746441136.firebaseio.com',
#  'firestoreOptions':{'databaseId':'polaris'}})

# Endpoints de diagnóstico del contenedor
curl https://polaris-bot-173223792589.us-central1.run.app/diag/state   # archivo local del estado
curl https://polaris-bot-173223792589.us-central1.run.app/diag/fs      # lista docs + prueba escritura Firestore
```

### 13.6 Reglas operativas aprendidas en esta sesión

No asumir que `gcloud run deploy` aplica el código nuevo de inmediato: verificar con `revisions list` que la nueva revisión está activa y que una instancia de ELLA arrancó (`Bot iniciado` con timestamp reciente). Si la instancia vieja sigue generando ticks, forzar min/max-instances=2. El pnpm build del dashboard falla en el entorno de desarrollo (problema de pnpm/wouter); el workaround validado es desplegar vía bundle pre-compilado con `vercel deploy --prebuilt`. El log del proceso del contenedor llega a Cloud Logging solo si `logging.basicConfig` corre antes; cualquier import condicional al arranque debe ir después. El logger `state.firestore` parece no llegar a Cloud Logging (sus warnings nunca aparecieron) — no confiar en ellos para diagnóstico; loguear siempre contra el logger root/bot o con print+flush.

El usuario autorizó que, si una operación de Polaris en GCP devuelve `PERMISSION_DENIED`, el agente pueda autoasignarse el rol mínimo necesario dentro del proyecto `gen-lang-client-0746441136`, documentando en `AGENTS.md` el permiso otorgado, el motivo, el recurso afectado y si debe retirarse después. No pedir otra credencial si la cuenta de servicio ya tiene `roles/resourcemanager.projectIamAdmin`; verificar primero los roles actuales y evitar privilegios permanentes más amplios de lo necesario.
