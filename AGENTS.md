# PolarIS Trading Bot — Guía de Operación para Agentes

> Documento de referencia para cualquier agente de IA que opere, diagnostique o extienda el sistema Polaris (bot de trading de opciones sobre Alpaca, desplegado en Google Cloud Run). Última actualización: 18 de agosto de 2026 UTC.

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

Se confirmó y corrigió un bug de contrato: el bot publicaba `risk_per_trade_pct=0.01` y `max_positions=5` por usar defaults que no coincidían con `config.yaml` (`max_risk_per_trade_pct=5.0`, `max_open_positions=2`). La rama de auditoría ahora publica `risk_per_trade_pct=5.0`, `risk_per_trade_fraction=0.05`, `max_risk_per_trade_pct=5.0`, `max_positions=2` y `max_open_positions=2`; Telegram admite contrato nuevo y snapshots legacy. El bundle de producción formatea `riskPerTradePct` directamente, así que la siguiente validación debe confirmar que muestra 5.0%. El panel de gestión sigue sin fuente suficiente: no inventar reglas.

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
8. **La revisión 00055 se bloqueó durante `write_state_snapshot`.** El primer ciclo llegó a `FIRESTORE_ENABLED=True` a las 06:15 UTC, pero `updated_at` no avanzó y no apareció `Tick OK`; `/diag/state` sí tenía el régimen actualizado. La causa fue compatible con una RPC `DocumentReference.set()` sin timeout. El timeout explícito de 30 s y el log root-visible de éxito se desplegaron en `polaris-bot-00056-f48` y se verificaron: `Estado escrito en Firestore` a las 06:45:48 y `Tick OK` a las 06:46:27.

### 13.2 Evidencia de resolución

La revisión `polaris-bot-00052-lbz` quedó activa el 14 de agosto con `min-instances=2 / max-instances=2` para forzar una instancia de la revisión nueva y evitar que Cloud Run reutilizara la instancia vieja. En los logs de esa revisión se verificó:

- `FIRESTORE_ENABLED=True (antes de write_state_snapshot)`.
- `DIAG_FS: probe escrito en polaris/2026-08-15`.
- `Tick OK — equity=99689.50 posiciones=0`.
- El documento `polaris/2026-08-15` tiene `updated_at=2026-08-15T04:42:24.592357+00:00`, `trading_mode=PAPER`, régimen `bull`, guarda de piso activa y 30 puntos de curva de equity.
- El documento contiene campos reales de `payload`, incluyendo `alpaca_positions`, `orders_executed`, `positions`, `risk`, `strategies`, `universe` y `decisions_today`.

La evidencia descarta tanto un problema de permisos/ADC como un fallo de serialización del payload en la revisión activa. El snapshot completo se escribió después del probe. El `probe: true` permanece temporalmente en el documento porque la escritura diagnóstica usó `merge=True`; debe eliminarse o quedar reemplazado al limpiar el documento.

El probe fue retirado de `bot.py` en el commit `689286d`; la caché de feeds se añadió en `fc9962f`; y la documentación del estado quedó publicada en `4ed2b61` y `ba9a89e`. La revisión limpia `00054` escribió Firestore y el documento fue limpiado de `probe`/`diag`; el servicio quedó en `1/1` y sin conflicto 409 observado después. La revisión `00055` añadió la caché, pero su primer tick llegó a la escritura de Firestore y quedó bloqueado antes de `Tick OK`; el timeout de 30 s está preparado localmente, aún no desplegado.

### 13.3 Diagnóstico final

1. **Permisos y ADC:** descartados. `/diag/fs`, la cuenta de servicio y la API REST escriben en la DB `polaris`.
2. **Import silencioso:** corregido; la revisión 00055 registra `FIRESTORE_ENABLED=True`.
3. **Serialización del payload:** descartada como causa principal; la revisión 00054 publicó el snapshot completo con posiciones, riesgo y curva.
4. **Probe:** retirado del código y eliminados `probe`/`diag` del documento del día sin borrar datos reales.
5. **Bloqueo de escritura:** la revisión 00055 demuestra que una llamada `set()` sin timeout puede detener el tick después de que los feeds terminan. La corrección es `timeout=30.0` más logs de éxito/fallo visibles; no cambiar el perfil de riesgo.
6. **Dashboard:** la producción muestra datos reales de Firestore y el documento `backtest` real; el bundle conserva `Home.tsx` como ruta de fuente, pero la fuente no está disponible localmente. La rama de auditoría corrigió el contrato publicado para que el bundle pueda mostrar 5.0% directamente; falta validar el frontend con la nueva escritura y recuperar la fuente antes de desplegar cambios de UI.

### 13.4 Cierre y acciones pendientes inmediatas

1. La revisión `00056-f48` ya verificó `FIRESTORE_ENABLED=True`, `Estado escrito en Firestore`, `Tick OK` y `updated_at` avanzando en `polaris/2026-08-15`.
2. La caché de feeds está desplegada en `00055`, pero su duración aún debe medirse con varios ciclos limpios; el fallback de yfinance sigue siendo el cuello de botella.
3. La rama local de auditoría contiene fixes de contrato de riesgo, circuito diario, régimen sin datos, órdenes de opciones y reconstrucción de posiciones. **No desplegarla todavía**: primero ejecutar la batería local y revisar el diff.
4. Recuperar la fuente real `client/src/pages/Home.tsx`, validar que consume el contrato de riesgo nuevo y añadir una prueba antes de cualquier deploy de Vercel.
5. Regenerar el backtest completo: los CSV locales no están disponibles en `/home/ubuntu/backtests/` y el documento `polaris/backtest` no debe considerarse evidencia suficiente sin reproducibilidad.

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

No asumir que `gcloud run deploy` aplica el código nuevo de inmediato: verificar con `revisions list` que la nueva revisión está activa y que una instancia de ELLA arrancó (`Bot iniciado` con timestamp reciente). Si la instancia vieja sigue generando ticks, forzar min/max-instances=2. El pnpm build del dashboard falla en el entorno de desarrollo; el workaround validado es desplegar vía bundle precompilado con `vercel deploy --prebuilt`. El log del proceso del contenedor llega a Cloud Logging solo si `logging.basicConfig` corre antes; cualquier import condicional al arranque debe ir después. Las llamadas Firestore deben tener timeout explícito y log de éxito/fallo visible en el logger root/bot; no asumir que una función que captura excepciones liberará el tick si la RPC queda bloqueada.

El usuario autorizó que, si una operación de Polaris en GCP devuelve `PERMISSION_DENIED`, el agente pueda autoasignarse el rol mínimo necesario dentro del proyecto `gen-lang-client-0746441136`, documentando en `AGENTS.md` el permiso otorgado, el motivo, el recurso afectado y si debe retirarse después. No pedir otra credencial si la cuenta de servicio ya tiene `roles/resourcemanager.projectIamAdmin`; verificar primero los roles actuales y evitar privilegios permanentes más amplios de lo necesario.

## 14. Auditoría profunda de código — 15 de agosto de 2026

**Estado:** revisión local en curso; los cambios de esta sección todavía no están desplegados en Cloud Run. La revisión productiva verificada sigue siendo `polaris-bot-00056-f48`, en modo PAPER.

### 14.1 Bugs confirmados y correcciones preparadas

1. **Contrato de riesgo incorrecto en Firestore.** `bot.py` publicaba `risk_per_trade_pct=0.01` y `max_positions=5` aunque `config.yaml` definía `max_risk_per_trade_pct=5.0` y `max_open_positions=2`. Se corrigió el payload para publicar `risk_per_trade_pct=5.0`, `risk_per_trade_fraction=0.05`, `max_risk_per_trade_pct=5.0`, `max_positions=2` y `max_open_positions=2`.
2. **Telegram convertía dos veces el porcentaje.** `state/telegram_bot.py` multiplicaba por 100 un campo que ahora es porcentaje; se corrigió y se dejó compatibilidad con snapshots legacy que usaban fracción decimal.
3. **Circuit breaker diario sin rollover.** `RiskManager` solo inicializaba `day_start_equity` al arrancar el proceso; ahora `ensure_day()` reinicia el límite diario al cambiar el día y conserva el límite total. El circuito sigue latched durante el día en que se dispara.
4. **Universo vacío clasificado como bear.** `risk/regime.py` evaluaba `0 >= 0` y devolvía `bear` sin datos. Ahora un universo sin datos devuelve `cash`, nunca una señal bajista fabricada.
5. **Órdenes de opciones con precio límite cero.** `bot.py` llamaba `submit_option_order()` sin precio y `execution/alpaca_executor.py` convertía `None` en `0.0`. Ahora el ejecutor rechaza límites inválidos y el bot prevalida todas las cotizaciones, usa ask para compras y bid para ventas, aplica el offset configurado y evita enviar la primera pata si falta la segunda.
6. **Polaridad invertida al abrir spreads.** El helper temporal asignaba `sell` a una pata long y `buy` a una short; se corrigió a long→buy y short→sell, con inversión solo al cerrar.
7. **Reconstrucción frágil de posiciones.** Las posiciones nuevas guardan símbolos y órdenes de sus patas; `vertical_spread_from()` intenta reconstruir por esos símbolos y ya no aplica el filtro `dte_min=14` al buscar posiciones envejecidas. `bot.py` usa un builder fallback si la estrategia original fue deshabilitada tras un reinicio.
8. **Caché negativa de earnings inefectiva.** `data/earnings.py` volvía a consultar cada 24 horas dentro del mismo tick cuando no había fecha de earnings; ahora cachea también el resultado negativo.
9. **Test de caché dependiente del directorio actual.** `tests/test_feed_cache.py` ahora añade la raíz del repositorio a `sys.path` y usa timestamps UTC con zona explícita.

### 14.2 Validación local completada

- `python3 -m compileall -q .`: PASS.
- `tests/test_risk_contract.py`: 3 pruebas, PASS.
- `tests/test_execution_contract.py`: 2 pruebas, PASS.
- `tests/test_feed_cache.py`: PASS.
- `tests/test_ai_assistant.py`: PASS con el proxy LLM disponible; el nombre legacy `gpt-4o-mini` no está permitido por el catálogo actual, pero el fallback real funciona.
- `tests/test_regime_s78.py`: termina con código 0 y obtiene 8/8 tickers con yfinance, pero sigue siendo un script manual sin asserts; no debe considerarse cobertura CI suficiente.

### 14.3 Riesgos y límites del motor de backtesting todavía abiertos

- `loop_backtests.py` declara `S51` como benchmark `motor="hold"`, pero el motor genérico abre solo una posición y el resultado publicado `S51=92.5% / 61 trades` no es reproducible en la sandbox actual. El documento Firestore `polaris/backtest` debe tratarse como artefacto histórico hasta regenerar CSV y trades.
- `cheap_min_net` aparece en S75/S76 pero el motor solo consume `min_net`; ese filtro puede estar inactivo y debe corregirse antes de comparar estrategias.
- Los datos de earnings usados por producción vienen de un calendario actual de yfinance y no son point-in-time; no deben inyectarse directamente en backtests históricos.
- `stress_test.py` conserva el hallazgo Ruff B023 sobre cierres que capturan una variable de bucle; debe corregirse antes de confiar en un barrido multi-ventana.
- Los precios de opciones del backtest son proxies Black–Scholes con IV histórica, no un histórico point-in-time de cadenas; toda conclusión debe incluir esa limitación, slippage, comisiones y sensibilidad.
- La fuente de `client/src/pages/Home.tsx` del dashboard no está disponible localmente; no modificar `Raifeeer/Polaris-Web-Studio` como sustituto porque es otro proyecto.

### 14.4 Orden obligatorio antes de desplegar esta rama

1. Completar tests unitarios del motor y corregir `S51/hold`, `cheap_min_net` y B023.
2. Ejecutar backtests reproducibles con datos fechados, sin look-ahead, comisiones y slippage.
3. Revisar el diff y hacer commit/push.
4. Construir y desplegar a una revisión aislada de Cloud Run conservando todos los envs/secrets; mantener PAPER.
5. Verificar en Cloud Logging órdenes simuladas/prevalidadas, `Estado escrito en Firestore`, `Tick OK`, Telegram y el contrato de riesgo nuevo durante al menos dos ciclos.
6. Solo después evaluar si el dashboard consume correctamente 5.0% y 2 posiciones, sin mostrar valores mock.

No convertir el backtest $100→$200 en una promesa de rentabilidad ni activar trading REAL como resultado de esta auditoría.

## 15. Contexto de mercado fechado para backtests — 15 de agosto de 2026

Las notas completas están en `docs/market_context_2026-08-15.md`. Se verificaron Reuters y CNBC sobre dos estados de mercado relevantes: el 9 de junio hubo venta de tecnología/semiconductores y rebote incompleto, con presión geopolítica, inflación, Fed, valoraciones AI y rotación de momentum; el 13 de agosto el S&P 500 y Nasdaq cerraron en máximos, con rally concentrado en AI/chips, inflación de productores más suave y riesgo geopolítico todavía activo.

Estas noticias son **contexto**, no señales. En una simulación histórica solo se pueden usar hechos publicados antes o en la fecha de decisión. La cobertura posterior se excluye de la información de entrada y solo puede usarse para explicar el resultado fuera de muestra. El intento de análisis de video de Gavin Baker no produjo salida utilizable; no se debe citar ni usar como evidencia hasta repetirlo y guardar el resultado.

### 14.5 Segunda ronda de auditoría — 15 de agosto de 2026

Se corrigió una fuga de información en `loop_backtests.py`: `above_sma200` y `volume_spark` usaban el último valor del DataFrame completo y podían leer barras posteriores a la fecha de decisión. Ambos filtros ahora calculan sobre `hist <= d`.

El motor ahora admite `slippage_pct` opcional. La entrada de un spread aumenta el costo por `1 + slippage_pct` y la salida reduce el valor por `1 - slippage_pct`; el valor por defecto es 0 para conservar comparabilidad legacy. Toda corrida relevante debe declarar el porcentaje usado, aplicar comisiones y etiquetar que sigue siendo un proxy de fills.

`data/feed.py` sustituyó `datetime.utcnow()` por timestamps UTC con zona explícita; el test de caché dejó de emitir deprecaciones. La próxima matriz debe regenerarse desde el commit que contiene estas correcciones y no mezclar resultados previos.

## 16. Auditoría profunda y robustez — 15 de agosto de 2026

El informe reproducible completo está en `docs/hallazgo20_auditoria_y_robustez_2026-08-15.md`.

La auditoría corrigió una fuga de look-ahead en SMA200/volumen, normalizó UTC y corrigió la rama de ventanas recientes del feed. El motor ahora acepta `slippage_pct` para opciones y `equity_cost_pct` para benchmarks equity. Se añadieron motores de investigación `breakout20` y `breakout55`, con ruptura de máximos previos y confirmación de volumen calculadas solo con el histórico hasta la fecha de decisión.

La matriz final tuvo 73 configuraciones; la sensibilidad tuvo 156. `regime_hold_cash` fue el motor más consistente por ventanas, mientras `smc_daily` fue negativo en la mayoría de configuraciones. Un ensemble fijo 70% `regime_hold_cash` + 30% `breakout55` tuvo mediana +13.493%, pero peor ventana -5.208%. El walk-forward del ensemble seleccionó pesos distintos por fold y terminó con +34.985% en un test y -2.232% en otro. La revisión concluye que no hay evidencia robusta para cambiar la estrategia PAPER en producción ni para presentar $100→$200 como objetivo alcanzable.

No desplegar nuevas estrategias sin datos point-in-time de opciones/earnings, fills bid/ask, más ventanas fuera de muestra y validación walk-forward. Los artefactos están en `/home/ubuntu/backtests/` y sus manifiestos deben acompañar cada commit de investigación.

## 17. Cierre de auditoría de esta sesión

El estado versionado de esta sesión queda en `origin/main` con commit **`649151c`** (`research: audit engine and add robust walk-forward studies`). El árbol local quedó limpio después del push.

El commit incluye la limpieza Ruff F/B completa, la corrección de timezone y ventana reciente del feed, el modelo opcional de slippage/coste equity, los motores de investigación breakout20/55, los scripts de matriz, sensibilidad, walk-forward rodante y ensembles, el informe `docs/hallazgo20_auditoria_y_robustez_2026-08-15.md` y los contextos de mercado fechados.

Resultado operativo: Firestore quedó confirmado en la revisión 00056 con escritura completa y `Tick OK`; no se desplegó ninguna estrategia nueva. La investigación terminó con dependencia de régimen y tests recientes negativos para los candidatos seleccionados. Mantener Cloud Run en PAPER y no cambiar parámetros productivos hasta disponer de cadenas de opciones y earnings point-in-time, modelo de fills bid/ask/liquidez/assignment/gaps y validación fuera de muestra adicional.

## 18. Permisos IAM de Claude-trading-bot — 15 de agosto de 2026

Por confirmación explícita del usuario, se copiaron a `claude-trading-bot@gen-lang-client-0746441136.iam.gserviceaccount.com` los 12 roles de proyecto que tenía la SA operativa `manus-39@gen-lang-client-0746441136.iam.gserviceaccount.com`.

La comparación posterior confirmó **12 roles en origen y 12 en destino, sin roles faltantes ni extras**:

`roles/artifactregistry.admin`, `roles/cloudbuild.builds.editor`, `roles/cloudscheduler.admin`, `roles/cloudscheduler.serviceAgent`, `roles/cloudtasks.admin`, `roles/datastore.owner`, `roles/editor`, `roles/logging.admin`, `roles/resourcemanager.projectIamAdmin`, `roles/run.admin`, `roles/secretmanager.admin` y `roles/storage.admin`.

Este es un acceso administrativo amplio y fue aplicado únicamente tras la confirmación del usuario. No se imprimieron claves ni tokens. Si en el futuro deja de ser necesario, debe revisarse y reducirse al principio de mínimo privilegio, especialmente `roles/editor`, `roles/resourcemanager.projectIamAdmin` y los roles administrativos de Secret Manager, Cloud Run y almacenamiento.


## 19. Regeneración reproducible de los 89 escenarios — 15 de agosto de 2026

Informe completo: `docs/hallazgo21_regeneracion_backtests_2026-08-15.md`.
Artefactos versionados: `docs/backtests/2026-08-15/` (151 CSV, 724 KB).

Cierra el punto 1 de §14.4 y el punto 5 de §13.4. Es la primera vez que la matriz de
backtests queda dentro del repositorio; antes vivía en `/home/ubuntu/backtests/`, que se
pierde entre sesiones y hacía imposible auditar las cifras publicadas.

**Fuente de datos: Alpaca, no yfinance.** En el sandbox de Claude Code yfinance es
inutilizable (`curl_cffi` choca con la intercepción TLS del proxy → `Recv failure` en el
100% de los tickers; sin imitación de navegador Yahoo responde 429). Se usó la cascada
`_segmented` de `data/feed.py` con credenciales de Secret Manager (`alpaca-key` /
`alpaca-secret`). Limitación a declarar siempre: falta el tramo reciente que solo Yahoo
cubre, así que **las ventanas terminan el 2026-08-12**, no el 15.

**Resultado central: el motor es reproducible; S51 no lo era.**

| Escenario | Publicado | Regenerado | Delta |
|---|---:|---:|---:|
| S36 | +56.5% | +59.3% | +2.8 |
| **S51** | **+92.5%** | **+3.6%** | **−88.9** |
| S63 | +20.8% | +19.7% | −1.1 |
| S67 | −48.0% | −48.3% | −0.3 |
| S75 | −32.9% | −32.9% | 0.0 |
| S76 | −6.6% | −6.6% | 0.0 |
| S78 | +26.7% | +26.7% | 0.0 |
| S55 | 0 trades | 0 trades | 0.0 |

Siete de ocho reproducen dentro de ±3 puntos y cuatro son idénticos. El único outlier es
S51, exactamente el que §14.3 marcaba como sospechoso: con el motor legacy `hold` el
"benchmark" concentraba todo el capital en una sola posición (+92.5% con dd −63.5%). Con
`hold_weekly` explícito —8 tickers equally weighted, rebalanceo semanal, que es lo que su
etiqueta siempre describió— rinde **+3.6% con dd −10.2% y 105 trades**. El backtest no
estaba mal calculado: medía otra cosa distinta de la que decía su nombre.

**Panorama global de los 89:** mediana de retorno **0.0%**, media +13.3%, **41 positivos
de 89**, y **28 escenarios con 0 trades**. El mejor por retorno (S16, +101.7%) tiene 3
trades: ruido, no estrategia. La lectura honesta del corpus es mucho más sobria que la
selección de titulares que circulaba.

**Impacto en producción: `polaris/backtest` republicado el 2026-08-15T14:07:29Z** con
autorización del dueño. El documento anterior publicaba `best = {S51, 92.5%, 61 trades}` y
el dashboard lo mostraba como titular: un artefacto del motor legacy que sobreestimaba el
benchmark real ~26x, en contra del requisito permanente de §9.

El documento nuevo lleva `best` = **S78** (+26.7%, 144 trades, wr 42%), la estrategia de
*producción* y no el máximo del corpus — promover el máximo sobre la misma muestra en que
se mide es sobreajuste, y aquí ese máximo es S16 (+101.7%) con **3 trades**. Se conservó la
clave `best` en vez de eliminarla porque la fuente del dashboard no es inspeccionable (§9
advierte de no adivinar su contrato). Se mantuvieron 30 elementos en `scenarios` para no
alterar el renderizado, y se añadieron dos campos nuevos: `corpus` (mediana 0.0%, media
+13.3%, 41/89 positivos, 28 sin operar) y `nota` con la advertencia de proxies
Black–Scholes. Respaldo del documento previo tomado antes de sobrescribir.

**Cautela cerrada (segunda pasada):** el republicado inicial dejaba S16 (+101.7%, 3 trades)
a la cabeza de `scenarios` — el ruido solo se había movido de `best` a la lista. Se añadió
un filtro `trades >= 10` antes de seleccionar el top; la lista bajó de 30 a 25 elementos y
su cabecera pasó a **S30 (+80.5%, 49 trades, dd −42.7%)**, con muestra real.

**Lo que este hallazgo NO levanta:** siguen vigentes todas las advertencias de §14.3 y §16
— primas Black–Scholes en vez de cadenas point-in-time, earnings no point-in-time, ausencia
de fills bid/ask y liquidez, y walk-forward con pesos inestables entre folds. Nada aquí
convierte el reto $100 → $200 en un objetivo con respaldo empírico; la caída del benchmark
de +92.5% a +3.6% y una mediana de corpus de 0.0% empujan en la dirección contraria.
Mantener Cloud Run en PAPER.

## 20. Fix: posiciones abiertas invisibles tras reinicio del contenedor — 15 de agosto de 2026

**Síntoma detectado en vivo:** el snapshot de `polaris/2026-08-15` mostraba `positions: []`
(estado interno del bot) mientras `alpaca_positions` sí tenía un call spread abierto en
TQQQ (long 85C / short 100C, vence 2026-09-18). El bot tenía una posición real abierta en
el broker de la que no sabía nada.

**Causa raíz:** `state["positions"]` se carga una sola vez al arrancar desde
`data/bot_state.json` (`load_state()` en `bot.py`), un archivo en el filesystem efímero del
contenedor de Cloud Run. Un redeploy, un reinicio de instancia o que Cloud Run levante una
instancia nueva resetean ese archivo a `{"positions": []}`, mientras la posición sigue
abierta en Alpaca (fuente de verdad real). Sin reconciliación al arrancar, el bot quedaba
ciego a esa posición: nunca evaluaba su TP/SL/DTE (`_manage_open_position` solo itera
`state["positions"]`) y no la contaba para `max_open_positions`, pudiendo abrir posiciones
adicionales por encima del límite de riesgo real.

**Fix aplicado:** `reconcile_positions_with_broker(executor, state)` en `bot.py`, llamada
una vez al arrancar `main()` justo después de `load_state()` (solo si hay credenciales
reales de Alpaca). Compara las patas de opciones que devuelve `executor.positions()` contra
los símbolos ya conocidos en `state["positions"]`; para las patas desconocidas, agrupa por
subyacente + vencimiento + tipo y reconstruye verticales de 2 patas (long+short) con
`net_premium` calculado desde el `avg_entry` real de Alpaca (no un precio de mercado
recalculado). Estructuras que no forman un par 2-patas claro (una sola pata suelta, más de
2 patas del mismo vencimiento) **no se reconstruyen automáticamente**: se registra un
`logger.warning` para revisión manual en vez de adivinar una estructura incorrecta. Las
posiciones reconstruidas llevan `"strategy": "reconciled_broker"` y `"reconciled": True`
para poder auditarlas después.

Tests en `tests/test_position_reconciliation.py` (4 casos: reconstrucción de un vertical
completo, no duplicar una posición ya conocida, no adivinar con una sola pata suelta, no-op
sin posiciones de opciones). Suite completa corrida: 10/10 (`test_regime_s78.py` excluido
por el `SyntaxError` preexistente en f-strings anidados, ya documentado en §14.2, no
relacionado con este cambio).

**No desplegado en esta sesión.** El cambio está en el árbol de `main` de este repo, listo
para el flujo de build/deploy de la sección 5. Antes de desplegar: confirmar en Cloud
Logging que el mensaje "Reconciliación al arrancar: N posición(es) reconstruida(s)" aparece
en el primer tick tras el despliegue, y que el spread de TQQQ ya detectado pasa a aparecer
en `state["positions"]` (verificable en `/diag/state` o en el próximo snapshot de
Firestore).
## 21. Pendiente prioritario: evaluar TradingAgents frente a Polaris — plan para otro agente

**Estado:** pendiente; no iniciar automáticamente el despliegue ni modificar la estrategia productiva. El objetivo es comprobar con datos reproducibles si TradingAgents aporta valor incremental sobre Polaris, no asumir que una arquitectura multiagente implica rentabilidad.

### 19.1 Qué se quiere probar

El repositorio externo [`TauricResearch/TradingAgents`](https://github.com/TauricResearch/TradingAgents) es un framework multiagente de investigación. Su README describe analistas de fundamentales, sentimiento, noticias y técnica; investigadores bull/bear; trader; equipo de riesgo y portfolio manager. La ejecución descrita por el proyecto es sobre un exchange simulado y el propio README advierte que el framework no es consejo financiero y que los resultados varían con el modelo, temperatura, periodo y calidad de datos. El paper original también presenta resultados frente a baselines, pero es evidencia de investigación histórica, no una garantía de rendimiento en Polaris ni en producción. [TA1] [TA2]

La pregunta experimental debe ser estricta: **¿TradingAgents mejora una decisión de Polaris con el mismo universo, datos, costes, ventanas y reglas de riesgo, fuera de muestra, después de contabilizar latencia y coste de LLM?** No se debe formular como “¿puede duplicar $100 a $200?” porque esa meta induce selección por retorno y sobreajuste.

### 19.2 Aislamiento obligatorio

No clonar el repositorio externo dentro de `bot-trading` ni copiar su código al loop de producción al comienzo. Usar un directorio y entorno separados, por ejemplo `/home/ubuntu/TradingAgents` y un virtualenv independiente, fijar un tag o commit concreto y registrar el hash con `git rev-parse HEAD`. En la fecha de esta documentación el repositorio mostraba la versión `v0.3.1` y el commit visible `a33fd4c`; el agente que ejecute la prueba debe volver a comprobarlo y registrar el hash real utilizado.

La primera integración debe ser **advisory/shadow**: TradingAgents genera un informe y una recomendación estructurada, pero no puede enviar órdenes, cambiar `RiskManager`, cambiar sizing, cambiar TP/SL, saltarse circuit breakers, escoger credenciales de Alpaca ni escribir directamente en `orders_executed`. La salida se guarda separada como `tradingagents_advisory` o en un documento de investigación distinto. El feature flag inicial debe ser `TRADINGAGENTS_ENABLED=false` y cualquier prueba PAPER debe tener un kill switch independiente.

Las claves de LLM, datos y proveedores se deben obtener de Secret Manager o del entorno seguro; nunca escribirlas en `AGENTS.md`, commits, prompts guardados, CSV ni logs. “Gratis” se debe interpretar únicamente como código abierto: las llamadas a LLM y proveedores de datos pueden tener coste, límites, latencia y cambios de disponibilidad.

### 19.3 Variantes A/B pre-registradas

Usar pares de decisiones con el mismo timestamp, ticker, snapshot de mercado y estado de Polaris. No comparar ejecuciones hechas con datos de mercado distintos.

| Variante | Descripción | Puede modificar órdenes | Propósito |
|---|---|---:|---|
| A — Polaris baseline | Polaris actual, sin salida TradingAgents. | Sí, solo dentro de PAPER y reglas existentes. | Control principal. |
| B0 — TradingAgents shadow | TradingAgents analiza el mismo snapshot; su recomendación se registra pero no afecta decisiones. | No. | Medir acuerdo, latencia, coste y estabilidad. |
| B1 — Filtro conservador | TradingAgents puede **suprimir** una señal existente si la evidencia estructurada contradice la señal; nunca puede aumentar riesgo, tamaño o número de posiciones. | Solo veto limitado en PAPER. | Medir si reduce falsos positivos y drawdown. |
| B2 — Score auxiliar | La salida se convierte en un score acotado y se usa como una característica adicional, con límites idénticos de `RiskManager`. | No cambia los límites. | Medir si aporta señal incremental frente al baseline. |

No ejecutar B1/B2 hasta que B0 demuestre que la salida está estructurada, llega dentro del timeout, tiene provenance de datos y puede repetirse. No usar TradingAgents para seleccionar strikes, primas, fills ni órdenes de opciones en la primera fase; la traducción a vertical spreads debe seguir siendo responsabilidad determinista de Polaris.

### 19.4 Datos y control anti-look-ahead

Para cada decisión guardar un manifiesto con commit de Polaris, commit de TradingAgents, proveedor, timestamp UTC, fecha `as_of`, ticker, ventana OHLCV, indicadores, snapshot de fundamentales, identificadores y timestamps de noticias, sentimiento, modelo, proveedor, configuración, temperatura, número de debates, prompt versionado, respuesta estructurada, latencia, tokens/coste y error/reintentos.

Las noticias, Reddit y StockTwits deben ser snapshots fechados disponibles **antes** de la decisión histórica. El README de TradingAgents advierte que las fuentes sociales y de noticias cambian aunque se fije la fecha del ticker; usar la web actual para explicar una operación histórica invalida el test. Si no existe un archivo point-in-time, marcar ese escenario como no reproducible y excluirlo del resultado principal.

Las ventanas mínimas deben conservar la disciplina ya usada en Polaris: lateralidad septiembre–diciembre de 2025, selloff enero–abril de 2026, ventana abril–agosto de 2026 y una ventana reciente cerrada al día de ejecución. Para un test más robusto, separar train 2024–2025, validation enero–junio de 2026 y test julio–agosto de 2026; el test nunca puede seleccionar modelo, prompt, peso o umbral.

Las opciones requieren una cautela adicional: si no hay cadenas históricas point-in-time, bid/ask, liquidez, assignment y fills, el experimento principal debe comparar **señales y decisiones de exposición**, no declarar P&L de opciones como si fuera real. El motor de opciones de Polaris debe mantener sus costes, slippage, comisiones, DTE, deltas y límites; no permitir que TradingAgents fabrique primas.

### 19.5 Métricas y criterios de decisión

Guardar resultados por ventana, ticker, variante y réplica. Las métricas mínimas son retorno neto después de costes, máximo drawdown, Sharpe/Sortino con advertencia de muestra, profit factor, win rate, número de operaciones, turnover, duración media, peor operación, pérdida acumulada, exposición media, tiempo en cash, señales vetadas, acuerdos/desacuerdos con Polaris, latencia p50/p95, tokens/coste por decisión, errores, timeouts y estabilidad entre réplicas.

Pre-registrar antes de mirar el test un criterio de promoción conservador: al menos tres ventanas fuera de muestra; mejora de retorno neto o reducción de drawdown frente a A en la mediana; ninguna ventana con deterioro material de drawdown; mejora que sobreviva a slippage/costes; y coste/latencia que no rompan el watchdog ni el presupuesto. Una configuración que gana únicamente en la ventana del objetivo `$100 → $200`, con pocas operaciones o tras probar muchos prompts, se clasifica como **sobreajuste** y no se promueve.

Repetir B0 con varias réplicas del mismo snapshot o con temperatura/configuración fijada. Si las recomendaciones cambian materialmente, reportar la dispersión y no convertir una salida aislada en regla. La decisión final debe separar señal de mercado, calidad de ejecución y calidad de la explicación LLM.

### 19.6 Secuencia de implementación para otro agente

1. Leer este `AGENTS.md`, `docs/skills/estado_operativo_skill.md`, `docs/skills/backtest_skill.md`, `config/config.yaml`, `risk/manager.py`, `bot.py` y el README oficial de TradingAgents.
2. Confirmar la revisión Cloud Run activa, modo PAPER, estado de Firestore y que no hay cambios productivos sin documentar.
3. Clonar TradingAgents en entorno separado, fijar commit/tag, instalar dependencias y ejecutar solo un smoke test con un ticker y fecha no productiva.
4. Crear `research/tradingagents_eval/` o `scripts/tradingagents_eval/` con adaptador de entrada/salida, esquema JSON, manifiesto y logger; no editar el loop de órdenes de Polaris.
5. Ejecutar A y B0 con exactamente el mismo snapshot de datos. Guardar JSON/CSV, coste, latencia y provenance.
6. Validar que no haya claves en artefactos, que los prompts no contengan secretos, que los resultados sean parseables y que los timeouts sean menores que el presupuesto del tick.
7. Repetir por ventanas históricas, incluyendo un test fuera de muestra reservado. Generar tablas y gráficos de retorno, drawdown, acuerdo, latencia y coste.
8. Solo si B0 muestra valor y reproducibilidad, implementar B1 como veto limitado en una rama PAPER separada; nunca cambiar el universo, sizing o circuit breakers al mismo tiempo.
9. Ejecutar una observación PAPER mínima de varios ciclos y comparar con A; cualquier deploy requiere revisión explícita, nueva revisión Cloud Run y rollback documentado.
10. Publicar `docs/hallazgo21_tradingagents_eval_YYYY-MM-DD.md`, `backtests/tradingagents_ab_*.csv`, manifiestos, gráficos, commit de código y decisión go/no-go en este `AGENTS.md`.

### 19.7 Criterio go/no-go

**GO experimental** solo si el valor incremental aparece fuera de muestra, en varias ventanas, con costes y slippage, sin aumentar drawdown de forma relevante, con latencia estable y sin incumplir las reglas de riesgo. **NO-GO** si el resultado depende de una sola ventana, de noticias posteriores, de pocas operaciones, de un prompt elegido después del test, de un modelo concreto no disponible, de datos sin timestamp o de P&L simulado sin fills realistas. Incluso con GO experimental, mantenerlo en shadow/PAPER hasta una revisión posterior; no pasar a real automáticamente.

### 19.8 Referencias oficiales para el experimento

[TA1]: https://github.com/TauricResearch/TradingAgents "Repositorio y README oficial de TradingAgents"
[TA2]: https://arxiv.org/abs/2412.20138 "Paper original: TradingAgents: Multi-Agents LLM Financial Trading Framework"
[TA3]: https://github.com/TauricResearch/TradingAgents/blob/main/CHANGELOG.md "Changelog y versiones del framework"

## 22. Fix desplegado y segundo bug descubierto en el primer tick real — 15 de agosto de 2026

La revisión `polaris-bot-00057-hgt` (fix de §20) se construyó vía `gcloud builds submit
--config cloudbuild.yaml .` (el build local con `docker build` falla en este sandbox: el
contenedor no confía en el certificado de la intercepción de red del entorno) y se desplegó
con `gcloud run services update`. Verificado en Cloud Logging: instancia nueva arrancada
por `min-instances`, Alpaca conectado, y el log esperado apareció:

```
Reconciliación al arrancar: 1 posición(es) reconstruida(s) desde Alpaca que no estaban en el estado local
Reconciliación: reconstruida posición TQQQ (call_spread_TQQQ_85.0_100.0) desde Alpaca
```

El fix de §20 funciona. Pero al gestionar por primera vez esa posición real, el tick se
cayó con un error nuevo, nunca antes visto en producción porque `state["positions"]` había
estado vacío desde siempre:

```
bot ERROR Error gestionando posición TQQQ: 'MarketDataFeed' object has no attribute 'snapshots'
```

**Causa:** `_manage_open_position(feed, builder, strat, pos)` en `bot.py` llamaba
`feed.snapshots(contracts, spot)` sobre `feed`, que es el `MarketDataFeed` (datos de
acciones, solo expone `history()`). `snapshots()` es un método de `OptionFeed` (cadenas de
opciones), accesible como `builder.feed` (`SpreadBuilder.__init__` guarda `self.feed =
feed` con el `OptionFeed`). Corregido a `builder.feed.snapshots(contracts, spot)`.

**Segundo bug encontrado al escribir el test de regresión, sin ejecutar ni desplegar
todavía cuando se detectó:** la línea siguiente, `net = abs(net) * (-1 if st.direction ==
"bear" and st.kind == "vertical" else 1)`, referencia `st.direction` y `st.kind`, atributos
que **no existen** en la dataclass `OptionStructure` (`options/chains.py`, campos reales:
`name, legs, underlying, rationale, max_risk, max_profit, breakevens`). Esta línea habría
lanzado `AttributeError` para *cualquier* posición gestionada, reconciliada o no — es
anterior al bug de §20 y nunca se había ejecutado en producción por la misma razón: nunca
hubo una posición real en `state["positions"]` para gestionar. El valor `net` que computaba
el bucle previo tampoco se usaba después: `evaluate_exit()` recalcula la prima actual
internamente desde `current_structure.net_premium` (property de `OptionStructure`, ya
actualizada por el `snapshots()` recién corregido). Se eliminó la línea rota y se conservó
solo la guarda útil del bucle (no evaluar salida si alguna pata no tiene cotización válida
— `OptionContract.mid` cae a `0.0` sin bid/ask/last, lo que dispararía un TP/SL falso).

**Conclusión: la gestión de TP/SL/DTE de posiciones de opciones nunca había funcionado en
producción**, para ninguna posición, desde que existe este código — no por el bug de estado
efímero (§20) sino porque el propio `_manage_open_position` crasheaba en la primera llamada
real. Los dos bugs se enmascaraban mutuamente: sin §20 nunca se llamaba a la función; con
§20 arreglado pero sin este segundo fix, se habría descubierto en cuanto hubiera una
posición gestionable, real o reconciliada.

Test de regresión en `tests/test_manage_open_position.py`: un doble de `MarketDataFeed` sin
método `snapshots()` (para que el primer bug reviente si reaparece) contra un doble de
`SpreadBuilder`/`OptionFeed` que sí lo tiene, verificando que la llamada completa sin
lanzar excepción. Suite completa: 11/11 (`test_regime_s78.py` sigue excluido por el
`SyntaxError` preexistente de §14.2, no relacionado).

**Pendiente inmediato:** desplegar este segundo fix (aún no construido ni desplegado al
cerrar esta sección) y verificar en Cloud Logging que la posición TQQQ reconciliada se
gestiona sin error en el próximo tick.

## 23. Auditoría de procedencia del dashboard Polaris — 15 de agosto de 2026

**Estado:** el código fuente original del dashboard no fue localizado en la sandbox, GitHub ni en la configuración del proyecto Vercel. No crear un falso repositorio a partir de un bundle minificado; conservar el bundle solo como evidencia temporal hasta recuperar la fuente real.

### 20.1 Resultado de la búsqueda

Se inspeccionaron los directorios de `/home/ubuntu`, los repositorios accesibles de la cuenta `Raifeeer`, el repositorio `Raifeeer/bot-trading`, las configuraciones locales de Vercel y los artefactos descargados del dominio de producción. No apareció una copia del proyecto que contenga la combinación esperada de `client/src`, `package.json`, archivos `.tsx/.jsx`, configuración Vite y código del dashboard. `Polaris-Web-Studio` contiene el sitio comercial de Polaris y componentes de otro producto; no debe tratarse como la fuente del dashboard de trading.

El repositorio `bot-trading` sigue siendo exclusivamente Python/infraestructura/documentación; no añadir el frontend allí como reconstrucción especulativa. La referencia `client/src/pages/Home.tsx` que aparece en el bundle es un metadato de desarrollo conservado por el build, no una ruta local recuperable.

### 20.2 Cómo se desplegó probablemente

El proyecto Vercel confirmado es `polaris-options-dashboard`, propietario `cristian2200299-8837's projects`, framework Vite, root `.`, comando `pnpm run build`, output `dist` y Node.js 24.x. La CLI de Vercel puede listar el proyecto y sus despliegues, pero el proyecto no muestra repositorio Git enlazado.

La deployment de producción inspeccionada fue `dpl_49qkt1wPuymjDDnL73w9NVjUKPHj`, alias `polaris-options-dashboard.vercel.app`, creada el 14 de agosto de 2026 a las 16:42 UTC. La API de Vercel devolvió `source=null`, `gitSource=null`, `meta={}` y `builds=[]`; la CLI mostró un build de 0 ms. Junto con el historial de despliegues de pocos segundos y el uso documentado de `vercel deploy --prebuilt`, la evidencia es consistente con un upload de artefacto precompilado desde una carpeta local, no con un despliegue conectado a Git. Esto explica por qué el proyecto se publicó pero su fuente nunca llegó a GitHub: Vercel recibió `dist/`, no un repositorio.

Esto es una inferencia basada en metadatos de despliegue, no una prueba de quién creó originalmente la carpeta local. La ruta `/home/ubuntu/polaris-options-dashboard/client/src/...` no existe actualmente en esta sandbox ni en los repositorios rastreados.

### 20.3 Hallazgo API-01 / Credenciales Alpaca

El bundle de producción contiene en `Config.tsx`, componente `API-01`, línea 152, el literal visible `••••••••••••••••••••••43UL` bajo la etiqueta `API Key`. No proviene de Firestore ni de una variable de datos en vivo: está embebido como texto en el bundle compilado.

Se comparó el sufijo `43UL` de forma segura con el secreto actual `alpaca-key` de Secret Manager, sin imprimir la credencial. El secreto actual tiene formato de una sola línea y su API key no termina en `43UL`. Por tanto, el sufijo del bundle **no coincide con la API key actualmente configurada**. No se puede determinar desde el bundle si fue un placeholder, una clave antigua o una demo; debe tratarse como un valor hardcodeado no verificable y retirarse.

No se debe mostrar ningún sufijo de API key en el dashboard. El panel debe mostrar únicamente un estado real y no sensible, por ejemplo `Configurado en Secret Manager` si existe una señal backend verificable, o `No disponible`/`—` si no existe. Nunca debe leer `APCA_API_KEY_ID` desde el frontend: las credenciales de Alpaca solo deben permanecer en Secret Manager y ser consumidas por Cloud Run.

### 20.4 Acción pendiente para el siguiente agente

1. Recuperar la carpeta original `/home/ubuntu/polaris-options-dashboard` desde el equipo o almacenamiento donde se ejecutó el `vercel deploy --prebuilt`, o pedir al usuario que la adjunte. No intentar reconstruir el proyecto completo desde el bundle salvo como último recurso.
2. Antes de versionar, ejecutar un escaneo de secretos y retirar el literal `43UL` y cualquier otro valor de credencial. Rotar la API key si existe cualquier posibilidad de que el valor visible corresponda a una clave histórica real.
3. Crear un repositorio separado, preferentemente `Raifeeer/polaris-options-dashboard`, salvo que el usuario prefiera una carpeta `dashboard/` dentro de `bot-trading`. Incluir `package.json`, lockfile, `src/`, configuración Vite, README, `.env.example` sin valores y reglas de despliegue.
4. Añadir una prueba que garantice que el panel de credenciales no contiene API keys, sufijos, secretos ni valores demo. Las pruebas deben confirmar que todos los paneles leen Firestore o muestran estado vacío explícito.
5. Configurar el proyecto Vercel para Git después de la revisión y hacer el primer despliegue desde el commit versionado. Mantener el dashboard en producción con datos reales y no desplegar una reconstrucción no auditada.
6. Documentar el hash del commit fuente, el hash de la deployment, el comando de build, el output, el alias de producción y la relación Git↔Vercel en este archivo.

### 20.5 Evidencia guardada localmente

La auditoría del bundle está en `/tmp/polaris-dashboard-audit/` durante esta sesión y contiene `index.html`, los assets JS descargados, fragmentos de `Home.tsx`, `Config.tsx`, Firestore y el análisis de riesgo. Es evidencia de producción, no fuente mantenible. Si se necesita conservarla entre sesiones, copiar solo una versión sanitizada a `docs/audits/` sin incluir tokens, datos personales ni credenciales.

## 24. El watchdog nunca funcionó: `sys.exit(1)` en hilo daemon no mata el proceso — 15 de agosto de 2026

Los fixes de §20/§22 se construyeron y desplegaron (`polaris-bot-00058-272`, vía `gcloud
builds submit` + `gcloud run services update`). Verificado en Cloud Logging: la posición
TQQQ reconciliada se gestionó **sin errores** hasta `FIRESTORE_ENABLED=True (antes de
write_state_snapshot)` — ambos bugs de §20/§22 confirmados resueltos en producción.

Pero ese mismo tick se colgó justo después: Alpaca rechazó el rango reciente de TQQQ por
SIP, cayó a yfinance para el spot price dentro de `_manage_open_position`, y yfinance se
quedó colgado sin lanzar excepción — el problema histórico ya documentado en §3/§10. A los
25 minutos el watchdog disparó:

```
bot CRITICAL Watchdog: sin ticks completos en 25 min; reiniciando el proceso
```

**37 segundos después**, sin embargo, apareció:

```
state.firestore INFO Estado escrito en Firestore: polaris/2026-08-15
```

Es decir, el tick colgado terminó solo, *después* de que el watchdog dijera que reiniciaba
el proceso. Eso reveló que **el watchdog nunca reinicia nada**: `_watchdog()` corre en un
`threading.Thread(daemon=True)` y llamaba `sys.exit(1)`. En CPython, `sys.exit()` lanza
`SystemExit`; el `threading.excepthook` por defecto **ignora silenciosamente** `SystemExit`
en cualquier hilo que no sea el principal — no termina el proceso ni los demás hilos, solo
el propio hilo watchdog muere en silencio. Confirmado con un repro aislado de 10 líneas
(`sys.exit(1)` en un hilo daemon; el hilo principal sigue vivo y termina normalmente).

**Consecuencia real:** toda la protección contra cuelgues descrita en `AGENTS.md` §3 desde
el principio de este documento — "Cloud Run recrea la instancia automáticamente al morir el
proceso" — depende de un mecanismo que jamás mató al proceso. Además, como el hilo watchdog
muere la primera vez que dispara (`sys.exit` termina su propio bucle `while True`), después
del primer disparo **deja de vigilar por completo** por el resto de la vida del proceso. La
única razón por la que el bot se recuperaba antes de yfinance colgado era pura suerte: que
la llamada bloqueada resolviera sola, no que el watchdog interviniera.

**Fix:** las dos llamadas del watchdog cambiaron de `sys.exit(1)` a `os._exit(1)`, que
termina el proceso completo a nivel de sistema operativo sin importar qué hilo lo invoque
(no ejecuta cleanup handlers, lo cual es exactamente lo que se quiere para un proceso
que se asume irrecuperablemente colgado). Se eliminó el `import sys as _sys` que quedó sin
uso.

Test de regresión en `tests/test_watchdog.py`: un test de control que reproduce el bug real
(`sys.exit(1)` en hilo daemon no mata el proceso — con el warning esperado de pytest sobre
la excepción no capturada) y un test que verifica por inspección de fuente
(`inspect.getsource`) que `_watchdog()` usa `os._exit(` y no `sys.exit(`/`_sys.exit(` — no
se invoca el watchdog real en el test porque `os._exit()` mataría el proceso de pytest.
Suite completa: 13/13.

**Pendiente inmediato:** construir y desplegar este tercer fix, y verificar en Cloud
Logging que un tick realmente colgado (o uno simulado) termina con la instancia
reiniciándose de verdad (nueva entrada "Starting new instance" en el log del servicio, no
solo el mensaje CRITICAL).

## 26. Cierre manual de la posición legacy de TQQQ — 15 de agosto de 2026

Con los tres fixes de §20/§22/§24 desplegados y verificados, el usuario preguntó por el
estado operativo real: equity $99,689.15, por debajo del **piso de $99,900** que
`risk/floor.py` ya protege correctamente (bloquea nuevas entradas mientras `equity <
floor`, verificado en `bot.py:540`). La causa era el spread de TQQQ (long 10x
`TQQQ260918C00085000` @2.32 / short 10x `TQQQ260918C00100000` @0.35, prima neta ~$1,970)
con -$310 no realizado.

**Diagnóstico: esa posición no puede haberla abierto el código actual.** `_option_order_specs`
en `bot.py` construye `qty: abs(int(leg.quantity))`, y `SpreadBuilder.vertical_spread` crea
`Leg(l, +1)` / `Leg(s, -1)` — cantidad fija ±1 por pata. El código de hoy nunca puede pedir
10 contratos. Es un resto de una versión anterior de `bot.py` (previa a la calibración del
perfil `options_reto`), que quedó abierta en la cuenta paper y que la reconciliación de §20
detectó y empezó a gestionar por primera vez.

**Acción, autorizada explícitamente por el usuario:** cerrar la posición para restablecer
el equity y liberar el piso. Con el mercado cerrado (próxima apertura 2026-08-17 09:30 ET),
se intentó primero con dos órdenes limit independientes (`sell_to_close` 85C, luego
`buy_to_close` 100C) — **ambas rechazadas por Alpaca con
`account not eligible to trade uncovered option contracts`**: cerrar una pata del spread
por separado deja la otra momentáneamente descubierta (naked), y el nivel de opciones de
esta cuenta paper no lo permite, incluso como orden de cierre. La solución fue una **orden
multi-pata** (`order_class=OrderClass.MLEG`, dos `OptionLegRequest` con `position_intent`
`sell_to_close`/`buy_to_close`), que cierra ambas patas atómicamente:

```
multi-leg close: 8777c641-b53e-47c3-ad1c-d884e9dee3b7 · ACCEPTED
  leg TQQQ260918C00085000 SELL qty=10
  leg TQQQ260918C00100000 BUY  qty=10
limit_price neto: $1.66/contrato (recupera ~$1,660 de los $2,010 comprometidos)
time_in_force: GTC (mercado cerrado; se ejecutará en la apertura del lunes si el precio
  se mantiene cerca del actual)
```

**Nota técnica para futuras órdenes manuales de cierre de spreads en esta cuenta:** nunca
enviar las dos patas como órdenes `simple` independientes — Alpaca las evalúa contra el
nivel de opciones aprobado de forma individual y rechaza la que, vista aislada, dejaría una
pata sin cobertura. Usar siempre `OrderClass.MLEG` con ambas patas en la misma request.

**Pendiente de verificar el lunes 17 de agosto tras la apertura:**
1. Que la orden `8777c641-...` se ejecute (o ajustar/cancelar si el precio se movió mucho
   durante el fin de semana).
2. Que el equity vuelva a estar por encima de $99,900 y el piso se libere
   (`regime.floor.below_floor = false`, notificación "PISO RECUPERADO" por Telegram).
3. **Posible duplicado a vigilar:** el estado local del bot (`state["positions"]`) sigue
   teniendo esta posición reconciliada desde §20. Si el tick del lunes evalúa su TP/SL
   antes de que el cierre manual se refleje, `_manage_open_position` podría intentar cerrar
   la misma posición otra vez. No es grave (Alpaca rechazaría una orden de cierre sin
   posición viva, y el except de `bot.py` ya captura y loguea sin tumbar el tick), pero
   conviene revisar los logs del primer tick del lunes para confirmarlo.
4. La notificación "PISO ROTADO" de `risk/floor.py` depende de `state["_floor_below"]`
   persistido en `data/bot_state.json` (filesystem efímero, mismo problema estructural que
   §20): cada redeploy con equity ya bajo el piso puede volver a disparar la notificación
   de "cruce" en falso. No se corrigió en esta sesión; queda como hallazgo menor para
   revisión futura.

## 27. Fix: Telegram tardaba minutos en responder (Secret Manager sin timeout) — 15 de agosto de 2026

**Síntoma reportado en vivo:** el usuario preguntó por Telegram algo que activa el asistente
IA ("Qué me dices de la acción de SpaceX?") y no obtuvo respuesta durante varios minutos.

**Diagnóstico confirmado en Cloud Logging:** el mensaje sí llegó (`TG update chat=...`
19:40:33), pero no hubo ni `TG response sent` ni `IA tardó más de 45s` durante más de 2
minutos. La causa: `state/ai_assistant.py::_sm_key()` se llama a **import time** del módulo
(líneas ~62-67, para resolver `GEMINI_KEY`/`GROK_KEY` de respaldo desde Secret Manager) en
el **hilo principal de Telegram**, antes de que `_ai_answer_with_timeout` lance el hilo con
el timeout de 45s que protege la llamada al LLM — ese timeout nunca cubre el import.

`access_secret_version()` se llamaba sin `timeout=`, y los dos secretos de respaldo
(`vercel-polaris-web-studio-GEMINI_API_KEY`, `polaris-GROK_API_KEY`) devuelven
`PERMISSION_DENIED` para la service account del bot (compute default SA, distinta del SA de
esta sesión). Sin timeout explícito, gRPC reintenta con backoff antes de rendirse: el log
confirmó el error de Gemini a los ~2m25s y el de Grok ~40s después — casi 3 minutos
bloqueando el hilo de Telegram, en el primer mensaje que usa el asistente de cada proceso
(los valores quedan cacheados en globals del módulo tras el primer import, así que solo pasa
una vez por arranque, pero se repite en cada redeploy).

**Fix:** `access_secret_version(request={"name": name}, timeout=5.0)`. Un secreto denegado
falla en ≤5s en vez de minutos. Test de regresión en
`tests/test_ai_assistant_secret_timeout.py` (mock del cliente de Secret Manager, verifica
que se pasa `timeout` y que sin `GCP_PROJECT_ID` nunca se llama a Secret Manager). Suite
completa: 15/15.

**Nota aparte, no corregida en esta sesión:** los fallbacks de Gemini/Grok seguirán sin
funcionar de verdad (fallan rápido en vez de colgarse, pero siguen fallando) hasta que se
le otorgue `roles/secretmanager.secretAccessor` a la service account del bot
(`173223792589-compute@developer.gserviceaccount.com`) sobre esos dos secretos específicos,
si el usuario quiere que esos fallbacks funcionen de verdad. DeepSeek (la clave primaria,
vía variable de entorno directa) no depende de Secret Manager y no se ve afectado.

## 28. Asistente de Telegram: análisis técnico real, no solo fundamentales — 15 de agosto de 2026

Tras diagnosticar el retraso de §27, el usuario preguntó honestamente qué usa hoy el bot
para contexto general/fundamentos/noticias al operar y al responder por Telegram. Respuesta
verificada en código, no supuesta: **para decidir operaciones reales, el motor es 100%
análisis técnico de precio** (SMC/CHoCH, cruces de medias, RSI, ATR, Donchian, volumen); el
único filtro no técnico es la *fecha* del próximo earnings (`data/earnings.py`, vía
yfinance), nunca su contenido. **No hay noticias, fundamentales de negocio ni sentimiento
en el loop de trading en ningún punto.**

El asistente de Telegram (`state/ai_assistant.py::answer()`) solo agregaba, si detectaba un
ticker en el mensaje, una consulta puntual a yfinance (precio, SMA200, P/E trailing, fecha
de earnings) vía `_fundamentals()`/`_fundamentals_slow()` — sin análisis técnico real ni
señal del motor.

**Ampliación pedida por el usuario (alcance elegido: "ampliar lo que ya hay", sin costo
extra — sigue siendo yfinance + DeepSeek, ningún proveedor nuevo):** nueva función
`_technical_snapshot(sym, hist)` que reutiliza literalmente el mismo código que decide
operaciones en producción — `SwingTrend.scan()` (`strategies/swing_trading.py`, la
estrategia `swing_trend` real) y `detect_choch()` (`strategies/smc.py`, el mismo usado por
`risk/regime.py` para clasificar el régimen) — sobre los datos OHLCV de 1 año que
`_fundamentals_slow` ya descarga (sin segunda descarga, sin costo de red adicional).
Devuelve la señal real (LONG/EXIT/NONE con su razón), el estado de CHoCH y el RSI14. El
prompt al LLM lo etiqueta explícitamente como "mismo código que usa el motor para decidir,
NO una opinión aparte del chat", para que el LLM no lo trate como un análisis
independiente inventado.

No se implementaron noticias reales ni búsqueda web (opciones descartadas por el usuario en
esta ronda por requerir suscripción externa y mayor riesgo de alucinación): siguen sin
existir en el bot. Si se quieren en el futuro, requieren una API de noticias de pago y
presupuesto de tokens adicional por resumen.

Test de regresión en `tests/test_technical_snapshot.py` (datos OHLCV sintéticos, ya que
yfinance no es alcanzable desde este sandbox): señal real devuelta, historial insuficiente
devuelve vacío sin fallar, y un DataFrame malformado nunca lanza excepción. Suite completa:
18/18.

## 29. Aviso inmediato en Telegram mientras responde el asistente — 15 de agosto de 2026

El usuario notó que el camino conversacional (fundamentales + análisis técnico + LLM, §28)
tarda 30-60s, y durante ese tiempo Telegram no da ninguna señal de que el mensaje llegó.
`_handle_message` ahora envía un aviso inmediato (`"🤖 Dame unos segundos, estoy
analizando…"`) justo antes de `_ai_answer_with_timeout`, solo en el camino lento (los
comandos fijos, que responden al instante, no lo necesitan y no lo envían).

Test de regresión en `tests/test_telegram_ack_message.py`: mockea `_send` y
`_ai_answer_with_timeout` para verificar el orden (aviso antes de la llamada lenta) y que
los comandos conocidos no disparan el aviso. Suite completa: 20/20.

Desplegado en `polaris-bot-00062-xcc`.

## 30. Avisos de progreso por etapa, no solo un mensaje genérico — 15 de agosto de 2026

A petición del usuario, el aviso único de §29 se amplió a avisos por etapa: `notify`
(callback que envuelve `_send`) ahora se propaga desde `telegram_bot._ai_answer_with_timeout`
hasta `ai_assistant.answer()` → `_fundamentals()` → `_fundamentals_slow()`, y cada punto lento
manda su propio mensaje según ocurre:

1. `telegram_bot._handle_message` (inmediato, sin cambios de §29): "🤖 Dame unos segundos,
   estoy analizando…"
2. `_fundamentals_slow`, al confirmar un ticker válido (precio real de yfinance, no una
   palabra falsa): "📈 Encontré {SYM}, revisando precio y fundamentales…"
3. `_fundamentals_slow`, antes de calcular la señal técnica: "📊 Calculando la señal técnica
   del motor para {SYM}…"
4. `answer()`, justo antes de llamar al LLM: "🧠 Generando la respuesta con la IA…"

Si el mensaje no menciona un ticker, solo se envían los avisos 1 y 4 (no hay etapa de
fundamentales/técnico que anunciar). `notify` es opcional en todas las firmas
(`answer(text, notify=None)`, etc.) para no romper las llamadas existentes sin callback.

Test de regresión en `tests/test_ai_assistant_progress_notify.py`: mockea `yfinance.Ticker`
(con un factory por símbolo — un mock que devuelve el mismo precio para cualquier ticker
producía un falso positivo con la palabra "de" en "qué opinas de AAPL", resuelto en el
primer intento del test), `data.earnings.get_earnings` y `_call_llm`; verifica que los
mensajes de progreso mencionan el ticker real y la etapa de "generando respuesta", y que
`answer()` sigue funcionando sin `notify`. Suite completa: 22/22.

Desplegado en `polaris-bot-00063-4b9`.

## 31. El watchdog reinició el proceso de verdad por primera vez — 15 de agosto de 2026

Primera prueba real en producción del fix de §25 (`os._exit` en vez de `sys.exit`). El tick
que arrancó a las 22:59:22 se colgó tras `FIRESTORE_ENABLED=True` (sin traceback: un
cuelgue silencioso, el tipo exacto de fallo para el que existe el watchdog — no relacionado
con los cambios de esta sesión). A los 25 minutos:

```
23:25:03  CRITICAL Watchdog: sin ticks completos en 25 min; reiniciando el proceso
23:25:09  Container called exit(1)
23:25:11  Starting new instance
23:25:12  STARTUP TCP probe succeeded
```

Antes del fix de §25, ese log CRITICAL no reiniciaba nada — confirmado en vivo el mismo día
(§25). Esta vez el contenedor murió de verdad (`Container called exit(1)`, evento propio de
Cloud Run) y una instancia nueva arrancó en segundos. Es la primera vez, en toda la historia
documentada de este bot, que el mecanismo de recuperación automática ante cuelgues funciona
como siempre se supuso que funcionaba.

## 32. Root-cause del cuelgue post-`FIRESTORE_ENABLED=True`: `feed.history()` sin timeout — 16 de agosto de 2026

El cuelgue de §31 se repitió dos veces seguidas en `polaris-bot-00063-4b9`, siempre en el
mismo punto exacto: justo después de `FIRESTORE_ENABLED=True (antes de write_state_snapshot)`
y antes de `Tick OK`. El watchdog (§25/§31) recuperaba el proceso correctamente las dos
veces, pero la causa del cuelgue en sí seguía sin arreglarse — iba a repetirse en cada tick
mientras hubiera una posición abierta.

Causa raíz: `_enriched_positions(executor)` (llamada **dos veces** por tick — una para el
snapshot de Firestore, otra para la actualización de Telegram) → `enrich_positions()` →
`spot_iv_from_feed(feed, "TQQQ")` (subyacente de la posición reconciliada de §20) →
`feed.history(["TQQQ"], "1d", days=60)`, una llamada de red respaldada por yfinance. Esta
llamada estaba envuelta en `try/except Exception`, que protege contra errores pero no contra
un **cuelgue** (una llamada que nunca retorna ni lanza excepción) — el modo de fallo
documentado de yfinance en todo este repo (p. ej. el watchdog de 25 min y el timeout de 45s
por ticker en el feed existen precisamente por esto).

Fix en `options/option_details.py::spot_iv_from_feed`: la llamada a `feed.history()` ahora
corre en un hilo daemon con `t.join(_SPOT_IV_TIMEOUT_S=20.0)`; si no vuelve a tiempo, se
abandona el hilo (puede seguir corriendo en segundo plano, pero ya no bloquea el tick) y se
retorna `(None, None)`, igual que ante cualquier otro fallo de datos. Mismo patrón ya usado
en `telegram_bot._ai_answer_with_timeout` y `ai_assistant._fundamentals`.

Además, `bot.py` calculaba `_enriched_positions(executor)` dos veces por tick (Firestore y
Telegram) — duplicando innecesariamente el costo/riesgo de esta llamada. Ahora se calcula
una sola vez (`enriched_positions = _enriched_positions(executor)`, justo después del log de
`FIRESTORE_ENABLED`) y se reutiliza en ambos bloques.

Test de regresión en `tests/test_spot_iv_timeout.py`: un feed falso cuyo `history()` duerme
1 hora confirma que `spot_iv_from_feed` retorna `(None, None)` en menos de 2s (con
`_SPOT_IV_TIMEOUT_S` parcheado a 0.2s para no alargar la suite), y un feed rápido confirma
que el valor real sigue devolviéndose cuando no hay cuelgue. Suite completa: 25/25 (excluyendo
`test_regime_s78.py`, con un `SyntaxError` preexistente y no relacionado).

Pendiente: build + deploy + monitoreo en producción de esta revisión, para confirmar que el
cuelgue post-`FIRESTORE_ENABLED` deja de repetirse en los próximos ticks con la posición TQQQ
abierta.

## 33. Credenciales GCP perdidas entre sesiones — causa raíz y procedimiento estándar — 16 de agosto de 2026

Cada sesión de Claude Code en este entorno corre en un contenedor **efímero**: se crea nuevo
al empezar la sesión y se destruye al terminarla. Todo lo que viva solo en el filesystem del
contenedor (una keyfile subida a mano, un `gcloud auth login` interactivo, config de shell no
persistida) desaparece entre sesiones. Lo que sí persiste: el código en GitHub, los secretos
en GCP Secret Manager, y la configuración propia del **Environment** de Claude Code (variables
de entorno / secrets / script de configuración), que se reaplica automáticamente en cada
contenedor nuevo.

Esto causó, el 16 de agosto de 2026, que una sesión nueva no tuviera credenciales para
`gcloud builds submit` pese a que la sesión anterior sí las tenía — la keyfile de
`claude-trading-bot@gen-lang-client-0746441136.iam.gserviceaccount.com` solo se había subido
al chat, nunca se guardó en un lugar persistente.

**Procedimiento estándar para que no se repita**: `docs/setup_environment.sh` (nuevo, en este
commit) es el script pensado para pegarse en el campo "Script de configuración" del Environment
en claude.ai/code. Lee una variable de entorno `GCP_SA_KEY_JSON` (que debe configurarse una
sola vez, como secret del Environment, con el JSON completo de la cuenta de servicio) y hace
`gcloud auth activate-service-account` automáticamente al arrancar cada contenedor nuevo —
también instala `requirements.txt`, evitando el otro problema visto ese mismo día
(`ModuleNotFoundError: No module named 'pandas'` en un contenedor limpio).

Importante: nótese `unset CLOUDSDK_AUTH_ACCESS_TOKEN` — el proxy de la sesión inyecta esa
variable con el valor `proxy-injected`, y si no se limpia, `gcloud` la usa en vez de las
credenciales de la cuenta de servicio recién activada, fallando con
`ACCESS_TOKEN_TYPE_UNSUPPORTED` incluso después de un `activate-service-account` exitoso.

Este archivo (`docs/setup_environment.sh`) queda versionado en el repo como referencia, pero
activarlo requiere que el usuario configure `GCP_SA_KEY_JSON` en la pantalla de configuración
del Environment — eso no lo puede hacer un agente desde dentro de una sesión.

## 34. Fix del cuelgue post-`FIRESTORE_ENABLED` confirmado en producción — 16 de agosto de 2026

Con la keyfile reactivada (§33), se compiló y desplegó §32 en `polaris-bot-00064-k5t`
(`gcloud builds submit` → build `1258fd45` → `gcloud run services update`). Log del primer
tick completo tras el deploy, con la posición TQQQ reconciliada abierta (la orden multi-leg
de cierre de §26 sigue pendiente de ejecutarse al abrir el mercado):

```
00:57:08  FIRESTORE_ENABLED=True (antes de write_state_snapshot)
00:57:12  feed WARNING TQQQ: APIError (subscription...) — reintento con yfinance
00:59:57  state.firestore INFO Estado escrito en Firestore: polaris/2026-08-16
00:59:58  bot INFO Tick OK — equity=99689.15 posiciones=1
```

Antes del fix, el tick se colgaba indefinidamente justo después de la primera línea, sin
avanzar nunca a `Estado escrito en Firestore` (solo lo destrababa el watchdog a los 25 min,
§31). Esta vez, con la posición TQQQ real todavía abierta (el escenario exacto que disparaba
el cuelgue), el tick completo — incluyendo el `spot_iv_from_feed` que antes se quedaba
colgado — tardó ~2.5 minutos y terminó en `Tick OK`. Root-cause confirmado y resuelto en
producción, no solo en el test unitario de `tests/test_spot_iv_timeout.py`.

## 35. Cierre de pendientes menores: fallbacks LLM, bandera de piso persistente, gate verificado — 17 de agosto de 2026

Tres de los cuatro pendientes que quedaban abiertos (todo salvo la ejecución de la orden de
cierre de TQQQ, que depende de que abra el mercado):

**Fallbacks Gemini/Grok reales.** La cuenta de servicio del propio bot en Cloud Run
(`173223792589-compute@developer.gserviceaccount.com`) no tenía `roles/secretmanager.secretAccessor`
sobre `vercel-polaris-web-studio-GEMINI_API_KEY` ni `polaris-GROK_API_KEY` — por eso, aunque
§27 evitó que el cuelgue de Secret Manager bloqueara Telegram, esas dos claves seguían sin
poder leerse nunca (fallo rápido en vez de cuelgue, pero fallo al fin). Se otorgó el rol con
`gcloud secrets add-iam-policy-binding` sobre ambos secretos — aplica en caliente, sin
necesidad de redeploy.

**Bandera "PISO ROTADO/RECUPERADO" espontánea en cada redeploy.** Causa raíz: `_floor_below`
en `risk/floor.py::check_floor()` vive en `state` (el JSON local efímero de `bot.py`), que se
resetea en cada redeploy/reinicio de instancia — así que tras un restart el bot "olvidaba" que
ya estaba bajo el piso y podía volver a notificar el cruce sin que el equity se hubiera movido
de verdad. Fix: nueva `state.firestore_state.read_last_equity()` (lee el último equity
publicado del día, con fallback a los 7 días previos si el tick de hoy aún no escribió nada);
`bot.py` la usa justo después de `load_state()` para reconstruir `state["_floor_below"]` antes
de la primera evaluación del piso, solo cuando el estado local no trae ya el flag (arranque en
frío). Documentado como fix, no solo detectado.

**Verificación de que el piso bloquea entradas nuevas de verdad.** El código en `bot.py`
(~línea 552) ya exigía `regime=='bull' and not below_floor` para abrir una posición — existía,
pero nunca se había probado. `tests/test_floor_gate.py` reproduce exactamente esa condición
booleana con `check_floor()` real (no mockeado) y confirma que con equity bajo el piso el gate
queda cerrado, y abierto cuando el equity está por encima. También cubre transiciones
below→above→below de `crossed` (solo dispara una vez por cruce) y `read_last_equity()` con
Firestore mockeado (día de hoy, fallback a días previos, fallo silencioso → None).

Suite completa: 31/31 (excluyendo `test_regime_s78.py`, `SyntaxError` preexistente y no
relacionado). Pendiente: build + deploy de este commit (los roles IAM ya aplican sin deploy;
la reconstrucción del piso desde Firestore sí requiere la nueva imagen).

## 36. Tres bugs del motor de backtest y por qué el corpus histórico no era fiable — 17 de agosto de 2026

Al intentar justificar con datos un cambio de TP/SL, el walk-forward destapó que el motor
(`loop_backtests.py`) tenía tres defectos que invalidaban los resultados:

**(a) El universo del escenario se ignoraba.** Los bucles de entrada de las rutas no-regime
iteran `sorted(data.items())` —todos los tickers que el llamador descargó— en vez de
`sc["tickers"]`. Dos escenarios con universos distintos devolvían resultados idénticos byte a
byte. Todas las conclusiones "por universo" del corpus S1–S89 (baratos vs ETF vs tech) estaban
midiendo lo mismo. Arreglado filtrando `data` al entrar en `run_scenario`, con fallo ruidoso si
el universo no intersecta los datos.

**(b) El equity podía acabar negativo** (−102% en 38 corridas; imposible, porque un spread de
débito no puede perder más que la prima). Causas acumuladas en **cuatro** contabilidades
duplicadas (`equity`, `equity2`, `equity3`, `equity3b`): el capital comprometido en posiciones
abiertas no se descontaba; la comisión de ida y vuelta se cobra al cerrar y no se reservaba al
entrar; y las tres rutas de *hold* repartían el equity ENTERO entre los símbolos sin descontar
los puts que seguían ocupando capital. Centralizado en `_safe_per_symbol()` + `_MIN_PER`.

**(c) Corrección de una conclusión propia.** Se afirmó que la config de producción
(tp 1.4 / sl 0.25) era "matemáticamente perdedora" porque su win rate de equilibrio nominal es
65.2%. Es una **cota pesimista**: las salidas se evalúan en velas diarias y los ganadores
rebasan el objetivo, así que el R:R **realizado** medido en los trades es 1.4 de mediana
(S41 2.80, S39 2.13, S78 2.04) frente al 0.53 nominal. El equilibrio real ronda el 42%.

**Hallazgo colateral:** con el universo ya aplicado, `solo_tech` y `solo_TQQQ` dan 0 trades. El
motor solo dispara en BB, F y NOK — no es la estrategia sobre el universo del reto que describe
la documentación, y explica que 52 de 89 escenarios tuvieran menos de 10 operaciones.

### Resultados con el motor corregido (3 rondas, dataset congelado 2024-02-29 → 2026-08-13)

Ronda 1 (walk-forward, ventanas disjuntas): TRAIN 0% de configs rentables, VALID 0%, TEST 41%
(mediana −4.6%). rho TRAIN→TEST +0.596 (con el motor roto daba +0.909: el bug inflaba la
aparente generalización).

Ronda 2 (consistencia, 14 ventanas independientes de ~2 meses): **ninguna** candidata supera el
36% de ventanas positivas. Producción (smc_daily tp1.4/sl0.25): 21% de ventanas positivas,
mediana −18.6%. `hold_weekly`: 0% de 14 ventanas con 430 trades.

Ronda 3 (costes) — **la ronda decisiva**. Producción, mediana y % de ventanas positivas:

| comisión | slip 0% | slip 5% |
|---|---|---|
| $0.00 | 50% / +0.1% | 50% / +0.7% |
| $0.65 | 21% / −18.6% | 7% / −17.2% |
| $1.30 | 7% / −34.9% | 7% / −30.8% |

Conclusión: **sin costes la estrategia es break-even; lo que la vuelve claramente perdedora es
la comisión.** Un spread vertical paga 4 comisiones por operación completa ($2.60 con $0.65 por
pata-lado), y sobre primas de $12 eso es el 21.7% del capital arriesgado — el win rate de
equilibrio se va al 84.1%. La comisión es un coste FIJO por operación, así que su peso es
inversamente proporcional al tamaño:

| prima | comisión/prima | WR de equilibrio |
|---|---|---|
| $12 | 21.7% | 84.1% |
| $100 | 2.6% | 67.5% |
| $289 | 0.9% | 66.0% |
| $777 | 0.3% | 65.5% |

Es decir: el tope de prima de $12 del perfil del reto era, él mismo, una de las causas
principales de que la estrategia no pudiera ganar. Operar más grande no mejora la señal, pero
elimina el lastre que la ronda 3 identifica como el killer.

## 37. Piso de equity en dos fases y dimensionamiento de recuperación — 17 de agosto de 2026

Con la cuenta en $99,689 y el piso del reto en $99,900, el bot quedaba en un **bloqueo
circular**: necesitaba ganar para poder operar y operar para poder ganar. No habría operado
nunca. Decisión del dueño: modo recuperación temporal.

`risk/floor.py` pasa a dos fases. **`recuperacion`** (equity < `challenge_target` $100,000):
rige `recovery_floor` ($99,400) y el bot puede operar. **`reto`**: al tocar los $100,000 la fase
queda **ARMADA de forma permanente** y rige `equity_floor` ($99,900).

El latch (`_challenge_armed`) es la pieza crítica: si la fase se recalculara comparando equity
con el objetivo, romper el piso del reto devolvería al bot a recuperación —piso más bajo— y el
piso de $99,900 no protegería nada. Como el JSON local es efímero, se reconstruye desde
Firestore al arrancar (`read_challenge_armed()`, busca el flag en los snapshots de 30 días).

`recovery_sizing()` + `contracts_for_target()`: en fase de recuperación se levanta el tope de
prima y se escalan contratos hacia `brecha / (tp_mult - 1)` (~$777 para una brecha de $311 con
TP +40%), acotado por la caja. Las dos patas escalan por igual: el spread mantiene su ratio 1:1
y sigue siendo de riesgo definido. Al armarse el reto vuelve solo al tope de config y 1
contrato, sin fecha que recordar.

**RIESGO ACEPTADO Y DOCUMENTADO:** $777 de prima supera los $289 de margen hasta el piso de
recuperación, así que una sola entrada perdedora puede dejar el equity en ~$98,912, bajo el
piso. El piso solo bloquea entradas NUEVAS; no limita la pérdida de una posición ya abierta
(así se llegó aquí: la posición TQQQ heredada eran $1,970 de prima). Registrado en
`logger.warning` por entrada y fijado en `test_target_premium_exceeds_margin_to_floor`.

## 38. Los circuit breakers estaban calibrados a la escala equivocada — 17 de agosto de 2026

La gestión de riesgo existía pero no protegía al tamaño del reto: `max_drawdown_daily_pct` 15%
se mide sobre la cuenta completa, o sea **$14,953**. Con entradas de $777 harían falta ~19
pérdidas totales para que saltara. Eran decorativos a esta escala.

Nuevo `max_daily_loss_usd` (400.0) en `risk/manager.py::check_circuit_breakers`: corta por
importe absoluto, de modo que **una única entrada perdedora grande detiene las entradas del
resto del día** en vez de encadenar otra igual. Sin la clave en config el comportamiento es
idéntico al histórico (cambio aditivo).

Pendiente conocido, no tocado: `max_risk_per_trade_pct` se calcula en `approve_position()` y se
descarta — el tamaño sale de la estructura, no del gestor de riesgo. Hoy lo gobierna
`recovery_sizing()` a propósito, pero la incoherencia sigue ahí.

Revisiones desplegadas hoy: `polaris-bot-00066-k9f` (piso en dos fases),
`00067-dk7` (dimensionamiento de recuperación), `00068-wtq` (breaker diario absoluto).
Suite: 66 tests en verde.

## 39. Cuarto bug del motor: el P&L de las patas de acciones se descartaba — 17 de agosto de 2026

El más silencioso de los cuatro. El bucle diario refrescaba `pos["last_spot"]` con el cierre de
cada día, y los cierres valoraban la posición contra ese mismo campo:

```python
pos["last_spot"] = exit_spot                       # bucle diario
val = entry_net * cierre_hoy / pos["last_spot"]    # cierre -> cociente 1 -> pnl 0.0
```

Las patas de acciones no podían registrar ganancia ni pérdida. `regime_aware` tenía **72 de 74
operaciones con pnl exactamente 0 y pnl MÁXIMO +0.0000**: parecía incapaz de ganar cuando en
realidad su P&L se tiraba a la basura. Se detectó porque la ronda 4 reportó win rate mediano 0%
con 4,728 operaciones, algo imposible.

Arreglado separando `entry_spot` (precio de entrada, inmutable, referencia de valoración) de
`last_spot` (último precio conocido, fallback si falta la barra de salida), con `_ref_spot()`
sembrado en las cuatro rutas que crean patas de acciones. Efecto en la ventana del drawdown
−19% (feb–jun 2025): `regime_aware` de 72/74 ceros a 0/74 y +5.04%; `hold_weekly` +16.61%.

Invalidó los resultados previos para `hold_weekly`, `hold`, `regime_aware` y `regime_hold_cash`,
y las cifras del corpus que dependen de ellos: **S51, S57, S58, S65, S77 y S78** (incluido el
"+26.7% de S78" y el benchmark S51). Con el motor limpio, la ronda 1 pasa de "41% de configs
rentables en TEST, mediana −4.6%" a **78% y +3.3%**, y `hold_weekly` de 0% a 100% de configs
positivas en TEST — la conclusión previa de "2 de 3 ventanas pierden para todo" queda retirada.

Van cuatro defectos independientes en este motor (universo ignorado, bancarrota en cuatro
contabilidades, P&L descartado). Regla práctica: **toda cifra del corpus histórico es sospechosa
hasta regenerarla con el motor actual**, y cada invariante tiene ya su test
(`test_backtest_universe.py`, `test_backtest_no_bankruptcy.py`, `test_backtest_equity_pnl.py`).

## 40. El único resultado con ventaja real: put_choch a tamaño suficiente — 17 de agosto de 2026

El bot en producción es **long-only** por cuatro puertas independientes: `direction: bull` fijo
en config (leído una vez al arrancar), la puerta de entrada exige `regime == "bull"`, el gestor
rechaza señales SHORT por política, y `put_choch_entry()` se calcula en `risk/regime.py` pero
ningún punto de `bot.py` lo consume. En régimen bear no hace nada.

**Ronda 4** (21 ventanas, 7 alineadas a los drawdowns reales de SPY; clasificación por caída
interna y no por retorno punta a punta, porque un put vive del camino: w6 cae −13.7% y cierra
+1.5%). En ventanas bajistas y sin comisión, `put_choch` es el único motor con mayoría de
ventanas positivas (64.1%, mediana +1.1%). **`regime_aware` —la forma en que el repo ya tiene
cableados los puts— es PEOR que quedarse en cash** (12.5% de ventanas positivas contra 37.5%):
encenderlo sin medirlo habría empeorado el bot.

**Ronda 5** (efecto del tamaño; el backtest opera primas de ~$15, así que se escala la comisión
a la baja en la misma proporción — equivalente, porque lo que importa es el cociente
comisión/prima, verificado: $15→17.33%, $777→0.33%).

Resultado en ventanas bajistas (% de ventanas positivas / mediana):

| motor | $15 | $100 | $777 |
|---|---|---|---|
| **put_choch tp1.5/sl0.5** | 31% / −5.2% | **75% / +4.7%** | **75% / +6.8%** |
| smc_daily | 25% / −14.0% | 44% / +0.0% | 44% / +0.0% |
| swing | 12% / −0.4% | 25% / +0.0% | 25% / +0.0% |
| regime_hold_cash (cash) | 0% / −18.8% | 38% / −2.8% | 38% / −1.3% |

Dos conclusiones, una de ellas contra la hipótesis de partida:

**(a) "El tamaño arregla la estrategia" es FALSO para los calls.** Subir el tamaño detiene la
sangría (de −14.7% a 0.0%) pero no crea ventaja: `smc_daily` y `swing` se estancan exactamente
en mediana 0.0% a cualquier tamaño. La comisión explicaba las pérdidas, no la ausencia de
ganancias.

**(b) Es CIERTO para los puts.** La comisión enmascaraba una señal real en `put_choch`: con
prima ≥$100 aparece 75% de ventanas bajistas positivas y mediana +6.8%, batiendo al cash
(−1.3%) de forma clara. Es lo único de todo el día con ventaja positiva, consistente y fuera de
muestra. Y solo funciona con `tp1.5/sl0.5`: con el `tp1.4/sl0.25` de producción nunca cruza el
umbral — el TP/SL sí importa, pero medido, no por la cota nominal.

Salvedades: 8 ventanas bajistas (ese 75% son 6 de 8, muestra pequeña) y primas Black-Scholes,
no cadenas point-in-time. Recomendación pendiente de decisión del dueño: cablear `put_choch`
con `tp1.5/sl0.5` y prima ≥$100 como motor bajista. **No** `regime_aware`.

## 41. Ronda 6: el playbook documentado, medido — y una atribución falsa — 17 de agosto de 2026

`docs/skills/wheel_skill.md` §4 define una tabla régimen→estructura que nunca se había medido
como conjunto. Se evaluaron sus 7 patas sobre 21 ventanas y 2 tamaños, puntuando cada pata en SU
régimen (no en promedio) y con el cash como pata de referencia.

**Hallazgo 1 — la pata de rebote no puede existir.** El skill atribuía a S36 la condición
«RSI<25 y precio>SMA100» con +53–60% y win 71–75%. En el código **S36 es `motor="smc_daily"`**,
así que esas cifras son de otra estrategia. Y la condición documentada, implementada como motor
`rebote_doc`, da **0 operaciones en 4.928 días-ticker**: cuando el RSI baja de 25 (mínimos
13,9–24,7) el precio ya está bajo su SMA100 — las dos cláusulas se excluyen estructuralmente.
RSI<30 también da 0; hacen falta RSI<35 para 5 ocurrencias y RSI<40 para 53. De ahí que el repo
tenga `rebote_rsi40`: el umbral ya se había relajado en el código, pero la documentación siguió
citando la condición original. Corregido en `wheel_skill.md` §4 y `backtest_skill.md` §3.

**Hallazgo 2 — la tabla por régimen sugiere que el playbook está invertido, pero NO es
accionable.** Con prima $289: en régimen «sube» ninguna pata bate al cash (+1.7%, 56%); en
«lateral» el call spread 0.30/0.10 TP1.5/SL0.5 da +4.9% y 75% frente a −2.7% del cash; en «baja»
`choch_put_S63` da +7.2% y 75%. Leído literalmente: el bot opera donde no aporta y está quieto
donde sí aportaría.

**Por qué no se actuó sobre eso.** Dos defectos de la medición, no del bot:
(a) la etiqueta de régimen se calcula sobre **SPY**, pero el motor solo dispara en BB, F y NOK,
cuya correlación diaria con SPY es de +0,41, +0,43 y +0,33 — la etiqueta no describe lo que
hicieron los tickers operados; (b) «lateral» son **4 ventanas**, así que ese 75% son 3 de 4.
Invertir la puerta de entrada con esa base sería el mismo error de sobreajuste que el propio
`backtest_skill.md` §8 prohíbe. Pendiente metodológico: clasificar el régimen por ticker (o por
el propio universo) en vez de por SPY antes de volver a evaluar el playbook.

Nota importante: el sesgo está solo en el etiquetado del backtest. La clasificación de régimen
**en producción** (`risk/regime.py`) ya se calcula sobre los propios tickers del universo.

**Lo que sí replica en tres pruebas independientes:** `put_choch` en mercado a la baja — ronda 5
(+6,8%, 75% de ventanas), ronda 6 (+7,2%, 75%) y el S63 histórico (+20,8% en el selloff). Es lo
único del corpus con ventaja confirmada por caminos distintos, y ya está en producción (§40).


## 42. Handoff Manus tras revisar los commits de Cloud — 17 de agosto de 2026

### 42.1 Sincronización confirmada

La rama local fue alineada con `origin/main` en el commit `4b39ee3` (`docs: corregir la atribucion falsa de S36 y registrar la ronda 6`). Desde el estado anterior conocido `642dc12` hasta `4b39ee3` hay **32 commits de Claude** entre el 15 y el 17 de agosto de 2026. El conjunto modifica 42 archivos, con aproximadamente 4.609 líneas añadidas y 140 eliminadas.

La secuencia completa está formada por:

| Bloque | Commits y resultado |
|---|---|
| Fiabilidad operativa | `ce44c78` corrige el watchdog para usar `os._exit(1)` desde el hilo daemon; `5cda8fd` añade timeout de 20 s a `spot_iv_from_feed`; `e68ddbc` hace persistente el latch del piso en Firestore y habilita fallbacks LLM; `db401fb` documenta el fix post-`FIRESTORE_ENABLED`. |
| Telegram y asistente | `e3bf0bb` añade timeout del acceso a Secret Manager; `303491d` añade snapshot técnico real; `925ea3d` añade acuse inmediato; `a265243` añade avisos de progreso por etapa y sus tests. |
| Motor de backtest | `be0db2e` añade herramientas reproducibles; `c3ffdb1` añade rondas de consistencia y costes; `d5eadca` corrige universo/equity y añade tests; `93d5060` corrige bancarrota; `42ac5e4` corrige el P&L de patas equity; `b4976a0` añade el guard-rail del win rate; `97293e3`, `452dc95` y `6f066b0` ejecutan rondas 4–6. |
| Piso y riesgo | `7e217cd` implementa piso de equity en dos fases; `9eeedde` elimina el tope de prima en recuperación; `cd20b99` añade `max_daily_loss_usd`; `6eb724f` documenta estos cambios y sus límites. |
| Motor bajista | `7a9416f` cablea `put_choch` para régimen `bear`; `b21ea62` evita que una barra malformada descarte el ticker completo; `bd300f4` restringe el motor bajista a `regime == bear`, nunca `cash`, y añade regresiones. |
| Documentación/metodología | `4d26352` documenta el cuarto bug y la ventaja medida de `put_choch`; `4b39ee3` corrige la atribución falsa de S36, registra la ronda 6 y actualiza las skills. Los commits intermedios incluyen actualizaciones de `bot.log` y documentación de cierres/producción. |

### 42.2 Estado local validado

Sobre `4b39ee3`, `python3 -m compileall -q .` termina correctamente. La suite ejecutada con `python3 -m unittest discover -s tests -p 'test_*.py' -v` termina con **90 tests OK**, 1 omitido y 2 expected failures. `pytest` no está instalado en la sandbox, por lo que no debe confundirse su ausencia con un fallo del código.

Ruff F/B todavía reporta cinco problemas estáticos no corregidos en el HEAD de Cloud: `round2_consistency.py` B007, `round5_size.py` F401, `tests/test_backtest_no_bankruptcy.py` B007, `tests/test_telegram_ack_message.py` F401 y `walkforward.py` F401. No son fallos de ejecución confirmados, pero deben limpiarse antes de afirmar que la auditoría estática está completamente verde.

### 42.3 Estado real de Cloud Run

La revisión activa es `polaris-bot-00071-8pz`, creada el 17 de agosto a las 13:54 UTC, lista y con 100% del tráfico. Cloud Logging confirma `FIRESTORE_ENABLED=True`, `Estado escrito en Firestore` y `Tick OK`. El último estado observado muestra equity `99,288.65`, cero posiciones, régimen `bull` y el proceso en fase `recuperación` porque el objetivo de `100,000` aún no se ha alcanzado.

El bot está emitiendo el warning de recuperación con una prima objetivo aproximada de `1,778.38` y caja `99,288.65`, mientras el piso de recuperación es `99,400.00`. En consecuencia, el piso bloquea nuevas entradas cuando el equity está por debajo de ese nivel. La lógica actual documenta explícitamente que el sizing de recuperación puede abrir una pérdida potencial mayor que el margen hasta el piso; no se debe tratar como un riesgo pequeño ni como una garantía de recuperación.

El último build de Cloud Build asociado temporalmente al despliegue activo fue generado alrededor de las 13:52 UTC, antes de `6f066b0` y `4b39ee3`. Los metadatos del build no contienen `COMMIT_SHA`, y la imagen solo está etiquetada como `latest`; por ello no se puede afirmar automáticamente que la revisión 00071 contenga los últimos commits de documentación/ronda 6. Antes de cualquier cambio posterior conviene publicar imágenes inmutables etiquetadas por commit.

### 42.4 Pendiente crítico detectado en revisión de código

`reconcile_positions_with_broker()` reconstruye una posición de spread desde Alpaca pero no añade `"kind": "put"` cuando la estructura es un put. En cambio, `bear_entry_candidates()` cuenta las posiciones bajistas con `p.get("kind") == "put"`. Tras un reinicio con un put reconstruido, el contador puede subestimar las posiciones bajistas y permitir más de `options_bear.max_positions`. La salida también detecta puts por el nombre de la estructura, pero el límite de entradas no.

Este punto está confirmado por lectura estática y todavía no tiene una prueba de regresión. Antes de desplegar el siguiente cambio hay que añadir `kind` derivado de `otype` en la reconstrucción y un test que simule un put reconstruido, compruebe el límite de posiciones y confirme que los calls no se etiquetan como puts.

### 42.5 Otras incoherencias que siguen abiertas

`RiskManager.approve_position()` sigue calculando `max_risk_per_trade_pct`, pero el tamaño real de spreads en el loop lo determina `recovery_sizing()` y `contracts_for_target()`. La propia documentación de Cloud lo marca como pendiente: el porcentaje de riesgo no gobierna efectivamente el tamaño durante recuperación.

La configuración mantiene `options_bear.enabled: true` y `min_premium_net: 100.0`, pero el motor bajista solo puede abrir cuando el régimen es exactamente `bear` y el piso no está bloqueando nuevas entradas. La evidencia que motivó `put_choch` sigue limitada a ocho ventanas bajistas y primas Black–Scholes, no a cadenas de opciones point-in-time con bid/ask y fills reales.

La medición de la ronda 6 clasifica ventanas usando SPY mientras el motor opera BB, F y NOK; Cloud documenta correctamente que esto no debe usarse para invertir el playbook. El siguiente estudio metodológico debe clasificar el régimen por ticker o por universo operado antes de modificar las puertas de producción.

### 42.6 Regla de continuación

No promocionar nuevas estrategias ni interpretar el objetivo `$100 → $200` como criterio de éxito. Primero corregir la reconciliación de puts, cerrar los cinco avisos F/B, etiquetar imágenes por commit y verificar la revisión resultante en PAPER. Después repetir los backtests con datos y costes documentados, especialmente con cadenas de opciones históricas point-in-time antes de tomar decisiones sobre `put_choch`.


## 43. Correcciones Manus: recuperación y operación PAPER — 17 de agosto de 2026

### 43.1 Diagnóstico de no operación

La revisión activa `polaris-bot-00071-8pz` estaba sana: Cloud Logging mostraba `FIRESTORE_ENABLED=True`, escritura de estado y `Tick OK`. El documento `polaris/2026-08-17` tenía equity `99,288.65`, cero posiciones, cero órdenes y cero señales. La ausencia de operaciones no era un fallo del loop: el régimen reciente era `bull`, pero el equity estaba por debajo del `recovery_floor` configurado en `99,400`, por lo que la condición `not regime.floor.below_floor` bloqueaba entradas alcistas y bajistas. El motor bajista, además, solo opera con régimen exactamente `bear`; no opera en `cash` por diseño.

### 43.2 Fixes aplicados y validados

1. `reconcile_positions_with_broker()` ahora persiste `kind: "put"` o `kind: "call"` al reconstruir un vertical desde Alpaca. `bear_entry_candidates()` cuenta tanto `kind == "put"` como estructuras legacy cuyo nombre contiene `put`, evitando superar `options_bear.max_positions` tras un reinicio.
2. `contracts_for_target()` ahora devuelve cero si ni un contrato cabe en el presupuesto seguro, en vez de forzar una entrada de prima cero o una entrada que no cabe. `recovery_risk_budget()` limita la prima total de una entrada al menor entre `max_risk_per_trade_pct` y `max_daily_loss_usd`; las entradas que exceden ese presupuesto se descartan antes de enviar la primera pata.
3. El `recovery_floor` se ajustó de `99,400` a `99,000` en `risk/floor.py` y `config/config.yaml`. La razón es desbloquear la recuperación desde el equity observado de `99,288.65`, conservando un guard-rail y los breakers de riesgo. El piso del reto sigue en `99,900` y el objetivo sigue en `100,000`.
4. Se cerraron los cinco avisos Ruff F/B pendientes en `round2_consistency.py`, `round5_size.py`, `tests/test_backtest_no_bankruptcy.py`, `tests/test_telegram_ack_message.py` y `walkforward.py`.

### 43.3 Validación local

Tras los cambios: `python3 -m compileall -q .` termina con éxito; `ruff check . --select F,B` termina con `All checks passed`; y `python3 -m unittest discover -s tests -p 'test_*.py' -q` termina con **94 tests OK**, 1 omitido y 2 expected failures. Se añadieron regresiones para puts reconstruidos, presupuesto de recuperación y equity de producción por encima del nuevo piso.

### 43.4 Estado de despliegue

Estos cambios están validados localmente pero todavía no deben considerarse activos en Cloud Run hasta publicar una imagen inmutable etiquetada con el commit, desplegarla en PAPER y observar varios ticks con señales, órdenes o un bloqueo explícito de datos/earnings. No se habilita `REAL` automáticamente. Antes del despliegue se debe revisar el diff, publicar GitHub y construir la imagen con tag de commit en vez de depender solo de `latest`.

### 43.5 Criterio operativo

El bot sí tiene cobertura conceptual para `bull`, `bear` y `cash`, pero no significa que opere en cualquier dirección en cada tick. En `bull` requiere señales alcistas válidas, cotizaciones completas, anti-earnings sin bloqueo, riesgo aprobado y piso abierto. En `bear` requiere CHoCH bajista, cadena de opciones válida, prima mínima de `100`, presupuesto seguro y piso abierto. En `cash` permanece fuera de mercado. El siguiente agente debe distinguir siempre entre proceso sano, señal disponible, orden enviada y posición confirmada por Alpaca.


## 44. Revisión Manus: bloqueo de arranque 00072 y recuperación operativa — 17 de agosto de 2026

La revisión `polaris-bot-00072-fpc` se desplegó desde `b22ec6d` con la configuración PAPER preservada. Cloud Run pasó el startup probe y Telegram inició, pero durante la ventana observada no apareció `Bot iniciado`, `FIRESTORE_ENABLED`, `Tick OK` ni un nuevo snapshot. El último documento Firestore seguía en equity `99,288.65`, cero posiciones, órdenes y señales. El orden de arranque coloca Telegram antes del log `Bot iniciado`; el hilo de Telegram tiene timeout y heartbeat, por lo que el punto probable estaba entre conexión/snapshot de Alpaca, lecturas persistentes y reconciliación inicial.

Se añadió `_positions_with_timeout()` en `bot.py`: la lectura de posiciones de Alpaca se ejecuta en un hilo daemon con límite de 30 segundos. Si el broker no responde, el bot registra el fallo y continúa el arranque sin reconstrucción; el enriquecimiento de posiciones reutiliza el mismo timeout. Esto evita que un endpoint colgado impida llegar al primer tick.

Se corrigió también el mensaje de recuperación, que todavía decía “sin tope de prima” y mostraba el piso antiguo de `99,400`. Ahora informa objetivo, prima objetivo, presupuesto seguro, caja y piso vigente. El sizing ya limita el número de contratos al menor entre `max_risk_per_trade_pct` y `max_daily_loss_usd`, y descarta antes de enviar órdenes si ni un contrato cabe.

El `recovery_floor` se cambió a `99,000` en código y configuración para que el equity observado de `99,288.65` no permanezca bloqueado por debajo de `99,400`. El piso del reto permanece `99,900`, el objetivo `100,000`, el `max_daily_loss_usd` permanece `400` y el modo de producción sigue siendo PAPER. Esta modificación permite nuevas entradas PAPER, pero no elimina el circuito diario ni el límite por operación.

Validación local posterior: `compileall` correcto, Ruff F/B en cero y **94 tests OK**, 1 omitido y 2 expected failures. Antes de declarar producción funcional hay que publicar este cambio, construir una imagen inmutable por commit, desplegar la revisión siguiente en PAPER y observar al menos un arranque completo y dos ticks. Deben distinguirse: señal detectada, entrada bloqueada por earnings/riesgo/piso, orden enviada y posición confirmada por Alpaca.


## 45. Timeout de conexión Alpaca antes del primer tick

La revisión `00073` pasó el startup probe y arrancó Telegram, pero no alcanzó `Bot iniciado` durante la ventana observada. La lectura de código confirmó que el proceso principal todavía podía quedar bloqueado en `executor.connect()` o `executor.account_snapshot()` antes de la reconciliación de posiciones. Se añadió `_call_with_timeout()` con hilo daemon: 45 s para conexión Alpaca, 30 s para snapshot de cuenta y 30 s para posiciones. En producción PAPER, un bloqueo ahora falla rápido y deja que Cloud Run reinicie la instancia en vez de mantenerla viva sin ticks.

La regresión de timeout de posiciones quedó cubierta por un test determinista. La validación local posterior terminó con **95 tests OK**, 1 omitido y 2 expected failures; `compileall` y Ruff F/B también pasaron. El siguiente despliegue debe confirmar que aparece `Bot iniciado` tras el timeout o que se registra un fallo controlado de Alpaca y una recreación limpia de la instancia.


## 46. Causa raíz de operación background y segundo ciclo — 17 de agosto de 2026

La causa raíz de que las revisiones `00072–00075` parecieran sanas pero no ejecutaran el loop de forma continua era la anotación de Cloud Run `run.googleapis.com/cpu-throttling: 'true'`. El servicio tenía `minScale=1`, pero Cloud Run estrangulaba la CPU cuando no había una solicitud HTTP activa; el servidor `/diag/*` podía responder mientras `bot.py` no avanzaba. Se corrigió con `gcloud run services update polaris-bot --no-cpu-throttling`, creando la revisión `polaris-bot-00076-zn6`, con `minScale=1`, `maxScale=1` y CPU siempre asignada.

La revisión `00076` quedó verificada con `Bot iniciado`, conexión Alpaca PAPER, `FIRESTORE_ENABLED=True`, régimen `bull`, equity `99,288.65`, `Estado escrito en Firestore` y `Tick OK`. No había posiciones ni órdenes porque antes del cambio el piso bloqueaba, y después el feed produjo datos pero no una señal ejecutable; esto es distinto de un proceso caído.

Se observó un `HTTP 409 Conflict` del polling Telegram durante el cambio de revisión, causado por revisiones antiguas con instancias/polling aún vivos. Se eliminaron las revisiones sin tráfico `00071` a `00075`, conservando `00076`, para dejar un único consumidor del bot de Telegram. El conflicto debe comprobarse de nuevo en el siguiente ciclo.

Aunque `00076` completó el primer tick, no apareció un segundo tick durante la ventana esperada. La revisión de código mostró que el loop llamaba directamente a `executor.account_snapshot()` al inicio y al final de cada ciclo, sin timeout. Se añadió `_call_with_timeout(..., 30s)` a ambas rutas; así una respuesta colgada del broker no bloquea el ciclo indefinidamente. El siguiente despliegue `00077` debe confirmar al menos dos `Tick OK` y una nueva escritura Firestore, o un timeout controlado claramente registrado.

El feed de Alpaca PAPER devuelve `APIError: subscription does not permit querying recent SIP data` para los ocho tickers y cae a yfinance. El fallback funciona y entrega 5min, 15min y 1d; no debe confundirse este warning de suscripción con un fallo total del bot. Para reducir latencia y dependencia de fallback, queda pendiente contratar un feed Alpaca compatible o seleccionar explícitamente un proveedor de datos autorizado.


## 47. Verificación de 00077 y telemetría de señales

La revisión `polaris-bot-00077-4jq` opera con CPU siempre asignada, `minScale=1`, `maxScale=1` y modo `PAPER`. Después de eliminar la revisión anterior `00076`, el bot completó dos ciclos con `Estado escrito en Firestore` y `Tick OK`; no se observó un nuevo `HTTP 409 Conflict` de Telegram después de la limpieza. El 409 observado a las `17:35:56Z` pertenecía al intervalo previo a eliminar `00076`, que era el segundo poller.

En ambos ticks el snapshot quedó con equity `99,288.65`, cero posiciones y cero órdenes. El régimen fue `bull` (`4/8` tickers bull, `0/8` bear) y los datos llegaron para 5min, 15min y 1d. Alpaca rechazó las consultas SIP recientes por la suscripción actual y el feed cayó a yfinance, pero el fallback entregó los datos y el tick finalizó correctamente.

Para distinguir ausencia de señales de bloqueos silenciosos se añadió `signal_stats` por tick y se publica en el snapshot: `scanned`, `tradable`, `bull_gate`, `approved`, `orders` y `bear_candidates`. También se registra `SEÑALES tick: {...}` en Cloud Logging. Esta telemetría se validó localmente con `compileall`, Ruff F/B y **95 tests OK**, 1 omitido y 2 expected failures. Debe desplegarse antes de concluir por qué no se abrió una posición.


## 48. Resultado final de operación 00078 — 17 de agosto de 2026

La revisión `polaris-bot-00078-xtj`, desplegada desde el commit `c40ce62`, conserva `PAPER`, `minScale=1`, `maxScale=1` y `cpu-throttling=false`. El bot arranca, conecta con Alpaca, reconstruye el piso desde Firestore y completa ticks con `Estado escrito en Firestore` y `Tick OK`. La revisión anterior `00077` queda reemplazada; las revisiones antiguas que podían mantener un polling Telegram paralelo fueron eliminadas.

El diagnóstico publicado en el último snapshot muestra:

```text
scanned=24
tradable=0
bull_gate=0
approved=0
bear_candidates=0
orders=0
```

Por tanto, el bot está ejecutándose y no está realizando operaciones porque **ninguna de las 24 evaluaciones de estrategia produjo una señal tradable** en los ticks observados. No hay evidencia de que el bloqueo actual sea el piso, `RiskManager`, earnings, prima mínima o falta de presupuesto: esas puertas no se alcanzaron porque `tradable=0`. Tampoco debe forzarse una orden solo para mostrar actividad; eso rompería la semántica de las estrategias y el control de riesgo.

El régimen actual es `bull` (`4/8` tickers bull, `0/8` bear), por lo que el motor bajista no tiene candidatos. Los tres motores alcistas están activos (`opt_day_momentum`, `opt_day_breakout`, `opt_swing_trend`), pero no han generado una señal ejecutable. El feed de Alpaca sigue devolviendo `subscription does not permit querying recent SIP data` y utiliza yfinance como fallback; el fallback entrega barras 5min, 15min y 1d y no impide completar el tick.

Estado confirmado: equity `99,288.65`, cero posiciones, cero órdenes, modo `PAPER`, Firestore actualizado. Antes de promover cualquier cambio de sensibilidad de las señales, el siguiente agente debe registrar la causa estadística de `tradable=0` por estrategia/símbolo y ejecutar un análisis A/B en PAPER; nunca relajar umbrales únicamente para fabricar operaciones.


## 49. Telemetría detallada y arnés A/B — 17 de agosto de 2026

Se amplió `bot.py` para guardar en `tick_diagnostics` el diagnóstico agregado y desglosado del loop. El snapshot conserva `scanned`, `tradable`, `bull_gate`, `approved`, `orders` y `bear_candidates`; además incluye `by_strategy` y `by_symbol`. Cada estrategia registra timeframe, barras escaneadas, señales tradables y razones como `not_tradable`, `insufficient_history`, `earnings_blocked`, `regime_not_bull`, `below_floor`, `no_structure`, `risk_rejected:<reason>`, `approved` y `orders_submitted`. Cada símbolo conserva el mismo desglose por estrategia.

La telemetría no modifica las puertas de entrada, el `RiskManager`, el sizing ni el motor bajista; solo hace observable el motivo de cada resultado. Antes de desplegar, se verificó `compileall`, Ruff F/B en cero y 95 tests OK (1 omitido y 2 expected failures).

Se añadió `scripts/run_ab_comparison.py`. Es research-only: descarga los datos una vez, ejecuta baseline y candidato sobre el mismo objeto de datos, exige ventanas idénticas, registra commit/proveedor/universo/hash y genera CSV emparejado más manifiesto JSON. No importa un executor, no toca Cloud Run, no escribe Firestore y no puede enviar órdenes.

Smoke reproducible ejecutado sobre `2026-04-01..2026-08-14`:

| Brazo | Equity final | Retorno | Trades | Win rate | Profit factor | Drawdown |
|---|---:|---:|---:|---:|---:|---:|
| `regime_hold_cash_recent_2026` | 129.1860 | 29.186% | 152 | 43.42% | 1.4888 | -25.0933% |
| `breakout55_recent_2026_r15` | 127.4964 | 27.4964% | 14 | 57.14% | 1.4177 | -25.4729% |

El smoke valida el arnés, no promueve breakout. Artefactos: `/home/ubuntu/backtests/ab_smoke_recent_2026_20260817T184708Z.csv` y el manifiesto JSON homónimo. El siguiente agente debe desplegar únicamente la telemetría en PAPER, esperar al menos dos ticks y usar `by_strategy`/`by_symbol` para localizar el motor que produce cero señales. Cualquier ajuste posterior debe compararse con el arnés A/B y pasar walk-forward, costes, slippage y test fuera de muestra antes de entrar en producción.


## 50. Validación de telemetría en 00079 y limpieza final de Telegram

La revisión `polaris-bot-00079-bt6`, commit `daea8f2`, recibió correctamente la telemetría detallada. En el tick observado, los 24 pares estrategia/símbolo fueron escaneados y los tres motores quedaron así:

```text
opt_day_momentum  timeframe=5min  scanned=8  tradable=0  not_tradable=8
opt_day_breakout  timeframe=15min scanned=8  tradable=0  not_tradable=8
opt_swing_trend   timeframe=1d    scanned=8  tradable=0  not_tradable=8
```

El agregado fue `scanned=24`, `tradable=0`, `approved=0`, `orders=0`, `bear_candidates=0`. La telemetría por símbolo confirma el mismo resultado para cada uno de los ocho tickers del universo. Por tanto, la ausencia de operaciones no es un bloqueo del `RiskManager` ni del piso: las tres estrategias simplemente no generaron una señal tradable en esa ventana.

El segundo tick continuó llegando a régimen y datos; tras eliminar las revisiones `00077` y `00078`, quedó únicamente `00079` como revisión operativa. El `HTTP 409` observado a las `18:52:12Z` pertenece al intervalo anterior a esa limpieza; la comprobación posterior debe usar solo logs posteriores a la eliminación. La lista regional confirmó que `00079-bt6` es la única revisión reciente de la serie `0007x`.

La causa de datos sigue siendo la suscripción Alpaca sin SIP reciente, con fallback funcional a yfinance. Debe resolverse con un feed compatible antes de interpretar cambios pequeños de señal como una mejora de estrategia.


## 51. Reactividad y temporización del loop — 17 de agosto de 2026

Se preparó una mejora de scheduling para no confundir un sondeo de cinco minutos con ejecución en tiempo real. `bot.py` admite ahora `--poll-seconds` y `POLL_SECONDS`, con mínimo de 15 s; `--poll-minutes` queda como compatibilidad y sobrescribe el valor en segundos. El valor recomendado para PAPER es `60` segundos.

La caché de `data/feed.py` evita que una cadencia de 60 s descargue los mismos datos continuamente: 5m tiene TTL 240 s, 15m 600 s y 1d 900 s. El loop sigue siendo secuencial y nunca solapa ciclos. Para impedir órdenes duplicadas, las entradas solo se reevalúan cuando cambia la última barra disponible o cambia el régimen/estado del piso; la gestión de posiciones, el heartbeat y el snapshot siguen ejecutándose cada ciclo. Los reintentos sobre la misma barra quedan registrados como `same_bar_context`.

Se añadió `phase_seconds` a `tick_diagnostics` y el log `CYCLE TIMING`, con `entries_s`, `bear_s`, `positions_s`, `publish_s`, `pre_publish_s` y `total_s`. Así se puede distinguir latencia del feed, análisis, gestión, publicación y espera sin inferirlo solo desde `Tick OK`. Se añadieron tres tests deterministas en `tests/test_scheduler_context.py` para barra estable, barra nueva y cambio de régimen/piso.

La implementación está validada localmente con `compileall`, Ruff F/B en cero, los tres tests de scheduler y la suite completa OK. El cambio todavía debe desplegarse en PAPER y medirse en producción antes de considerar una cadencia menor de 60 s. No se modifica el RiskManager, el piso, los circuit breakers ni el modo de trading.


## 52. Validación de reactividad en 00080 — 17 de agosto de 2026

La revisión `polaris-bot-00080-n8x`, commit `2daef98`, está activa al 100% de tráfico en PAPER con `POLL_SECONDS=60`, `cpu-throttling=false`, `minScale=1` y `maxScale=1`. Se verificaron cuatro ciclos consecutivos separados por aproximadamente 60 s.

Los tiempos observados fueron:

| Ciclo | Total | Entradas | Bear | Posiciones | Publicación |
|---:|---:|---:|---:|---:|---:|
| 1 | 8.740 s | 6.963 s | 6.963 s | 6.963 s | 1.774 s |
| 2 | 1.645 s | 0.134 s | 0.134 s | 0.134 s | 1.510 s |
| 3 | 0.309 s | 0.101 s | 0.101 s | 0.101 s | 0.208 s |
| 4 | 0.346 s | 0.138 s | 0.138 s | 0.138 s | 0.207 s |

El ciclo 1 hizo el escaneo completo; los ciclos posteriores reutilizaron el mismo contexto de barra y registraron `same_bar_context`, evitando revaluar señales y duplicar órdenes. La gestión de posiciones, publicación y heartbeat continuaron ejecutándose. No se observaron tracebacks en la validación de la revisión.

El entorno efectivo conserva `DATA_PROVIDER=alpaca` para la cascada configurada, `APCA_API_BASE_URL=paper` y el nuevo `POLL_SECONDS=60`. Esta mejora no cambia las estrategias, el sizing, el piso ni los circuit breakers. El objetivo de la cadencia rápida es detectar una barra nueva antes, no fabricar entradas sobre la misma barra.


## Auditoría de skills y nueva skill trading-setups — 2026-08-18

Se revisaron las 9 skills existentes en `docs/skills/` contra el código y `build_strategies()` del loop. La matriz completa está en `docs/skill_coverage_2026-08-18.md`. En resumen: datos, régimen S78, riesgo y el contrato Telegram/Firestore participan en producción; backtesting, infraestructura y estado operativo son procedimientos; `SMCStrategy` y `WheelStrategy` existen como módulos pero no son motores live principales; y la nueva skill `trading-setups` es por ahora una especificación de investigación, no una señal activa.

Antes de finalizar `trading-setups` se investigaron fuentes sobre BOS, CHoCH, order blocks, liquidity sweeps, BSL/SSL, key levels/KL, EMA, VWAP, EMA Cloud, volumen, Fibonacci, premium/discount, OTE, confluencia multi-timeframe, data snooping y order-flow. La síntesis y las fuentes están en `/home/ubuntu/skills/trading-setups/references/setup-research.md` y en `docs/trading_setups_research_2026-08-18.md`. Las definiciones educativas se tratan como hipótesis: no autorizan órdenes, no demuestran predicción ni sustituyen validación point-in-time.

La cobertura actual del PDF `TRADING_SETUP.pdf` es parcial. El siguiente trabajo recomendado es implementar en shadow una feature `trading_setups` con `bull/bear/neutral`, comenzando por BOS/CHoCH + order block y liquidity sweep + reclaim; después añadir premium/discount/Fibonacci, VWAP/EMA Cloud, volumen proxy y KL como filtros explícitos. Todo debe usar barras cerradas, timestamps as-of, tests deterministas, telemetría por símbolo/setup y A/B reproducible. No conectar a entradas PAPER hasta superar walk-forward, sensibilidad, costes y revisión de riesgo.


## 17. Capa completa de setups del PDF — 18 de agosto de 2026

### 17.1 Cobertura y arquitectura

Se formalizaron e implementaron como observaciones puras los doce setups identificados en `TRADING SETUP.pdf`: `key_level`, `break_and_retest`, `order_block`, `bos`, `choch`, `liquidity_sweep`, `ema_cross`, `ema_cloud`, `vwap`, `volume_proxy`, `fibonacci_ote` y `trendline_channel`. El motor vive en `strategies/setup_confluence.py`, no consulta broker, no calcula sizing y no puede enviar órdenes. Todas las observaciones son serializables y contienen símbolo, setup, dirección, estado, score ordinal, timestamp de decisión, evidencia, invalidación y versión de fuente.

La configuración añadida en `config/config.yaml` es deliberadamente conservadora:

| Clave | Valor | Regla |
|---|---:|---|
| `setups.enabled` | `true` | Evalúa la capa auxiliar |
| `setups.mode` | `shadow` | Publica observaciones sin influir en órdenes |
| `setups.influence_entries` | `false` | No cambiar sin walk-forward, A/B y revisión humana |
| `setups.min_structural_score` | `0.55` | Umbral documentado para futuras pruebas |
| `setups.min_confirmations` | `2` | Umbral documentado para futuras pruebas |
| `setups.timeframes` | `1d/15min/5min` | Contrato régimen/setup/entrada; la integración actual usa los frames disponibles |

`bot.py` llama `_setup_shadow_snapshot()` después de cargar el cache de datos, guarda el resultado en `state["setup_observations"]`, publica conteos resumidos en la telemetría por ciclo y registra `setups_s`. Si alguien cambia `influence_entries`, el loop emite una advertencia y mantiene el bloqueo de promoción; esa bandera no concede autoridad al motor de setups.

### 17.2 Corrección de Key Level

La primera versión de `key_level` tendía a ser siempre neutral porque exigía proximidad al nivel y luego una ruptura más allá de la misma tolerancia en la misma barra. Se corrigió para congelar máximos/mínimos previos y rolling, detectar ruptura cerrada o sweep/reclaim, guardar evidencia e invalidación y conservar neutralidad cuando no existe reacción. Se añadió `test_key_level_detects_closed_break` para evitar regresión. El setup sigue siendo una observación contextual y no una orden.

### 17.3 Validación local

La validación del 18 de agosto terminó con **102 tests ejecutados**, `OK`, un test omitido y dos expected failures ya conocidos del repositorio. La compilación de `bot.py`, estrategias, riesgo, opciones, ejecución, datos, estado, tests y scripts pasó; Ruff F/B/E9 pasó sin hallazgos. Los tests específicos del motor de setups son cuatro y cubren cobertura de los doce nombres, neutralidad ante datos faltantes, detección de ruptura Key Level y ausencia de permisos de orden/sizing/riesgo en la salida.

### 17.4 Backtest de setups

Se ejecutó `scripts/run_setup_backtests.py` y `scripts/analyze_setup_backtests.py` con datos históricos reales cacheados y cuatro ventanas: lateral sep–dic 2025, selloff ene–abr 2026, reciente abr–ago 2026 y últimos 30 días disponibles. La decisión usa únicamente barras hasta `t` y aplica la posición a la variación de `t` a `t+1`; los escenarios de setups descuentan 5 bps por unidad de cambio de posición. El experimento es un proxy direccional del subyacente, no un P&L de opciones.

La corrida final utilizó siete de los ocho símbolos esperados porque `SOFI` no pudo recuperarse de los proveedores disponibles y quedó registrado como faltante en el manifiesto. No se generaron datos sintéticos ni se sustituyó el ticker. Los resultados completos están en `docs/setup_confluence_backtest_2026-08-18.md` y en estos artefactos:

| Artefacto | Ruta |
|---|---|
| Métricas por ventana/escenario | `/home/ubuntu/backtests/setup_confluence_backtests_2026-08-18.csv` |
| Conteos bull/bear/neutral | `/home/ubuntu/backtests/setup_confluence_direction_counts_2026-08-18.csv` |
| Actividad de cada componente | `/home/ubuntu/backtests/setup_confluence_component_activity_2026-08-18.csv` |
| Comparación calculada | `/home/ubuntu/backtests/setup_confluence_analysis_2026-08-18_comparison.csv` |
| Resumen por componente | `/home/ubuntu/backtests/setup_confluence_analysis_2026-08-18_component_summary.csv` |
| Manifiesto y supuestos | `/home/ubuntu/backtests/setup_confluence_backtests_2026-08-18.json` |
| Informe legible | `docs/setup_confluence_backtest_2026-08-18.md` |

Resultado resumido:

| Ventana | Buy-and-hold | Setup moderate | Setup strict | Lectura |
|---|---:|---:|---:|---|
| Lateral 2025 | +25.9695%, DD −17.2397% | +0.3597%, DD −10.5601% | −3.1216%, DD −11.9175% | Menor DD, mucho menor retorno |
| Selloff 2026 | +22.9870%, DD −16.0482% | +5.1687%, DD −7.0323% | +4.4494%, DD −7.3239% | Menor DD, no supera retorno |
| Reciente 2026 | +61.1543%, DD −25.4978% | +15.1953%, DD −14.3550% | +18.1615%, DD −10.4369% | Strict mejora DD, no retorno |
| Últimos 30 días | −4.7056%, DD −20.1163% | −2.8449%, DD −8.6640% | −1.4434%, DD −7.5748% | Única ventana donde supera retorno; ambos negativos |

La clasificación es **`RESEARCH_ONLY`**. No promover `setup_moderate` ni `setup_strict`, no activar `influence_entries`, no modificar RiskManager/floor/circuit breakers y no presentar la mejora de drawdown como rentabilidad esperada. El resultado sugiere una posible función de reducción de exposición que requiere una prueba A/B explícita contra el motor regime-aware, no una estrategia autónoma.

### 17.5 Cobertura observada por componente

En las cuatro ventanas y `setup_moderate`, cada componente tuvo 8,344 evaluaciones. La tasa direccional aproximada fue: VWAP 78.39%, EMA cross 62.91%, volume proxy 48.73%, EMA cloud 46.66%, BOS 33.84%, Fibonacci/OTE 33.31%, break-and-retest 16.07%, Key Level 15.24%, order block 15.20%, CHoCH 9.98%, liquidity sweep 6.74% y trendline channel 53.80% contextual. `trendline_channel` no se contó como activo porque su estado actual es `context`, no confirmación. Los conteos detallados están en el CSV de actividad; no confundir frecuencia direccional con calidad predictiva.

### 17.6 Pendientes y criterio de promoción

El arnés `scripts/run_ab_comparison.py` aún compara motores del contrato `run_scenario`; no debe ejecutarse como A/B de setups sin añadir un puente que evalúe `analyze_setup_confluence` sobre el mismo dataset. La siguiente ronda debe usar un dataset compartido, comparar baseline regime-aware contra filtro de setups, separar train/validation/test, incluir sensibilidad, slippage, coste equity, exposición y estabilidad por régimen, y mantener el test bloqueado durante la selección. Antes de cualquier `paper_filter`, hay que recuperar el histórico faltante de SOFI o repetir oficialmente con un universo declarado de siete símbolos, y revisar la definición de `trendline_channel`/VWAP por timeframe.

Ningún resultado de esta sección justifica REAL. Polaris permanece PAPER. La meta ficticia `$100 → $200` es solo un escenario de investigación y no una promesa ni criterio de selección.


### 17.7 Despliegue y verificación final en PAPER

El primer deploy de la capa fue `polaris-bot-00081-6ns`. La observación local existía y el log mostraba `setup_confluence`, pero la comprobación directa de Firestore reveló que `setup_observations` no estaba incluido en el payload publicado. Se corrigió con el commit `0308314` añadiendo `"setup_observations": state.get("setup_observations", {})` al snapshot; no se modificó ninguna puerta de riesgo ni el modo de trading.

La revisión final es `polaris-bot-00083-f7s`, commit `0308314`, con 100% del tráfico en Cloud Run us-central1. Se construyó con Cloud Build exitoso y se verificó el service account operativo `173223792589-compute@developer.gserviceaccount.com`. La cuenta sigue en `PAPER` y el endpoint de Cloud Run conserva el servicio esperado.

Se observaron tres ciclos consecutivos de la revisión final:

| Ciclo | Total | Setups | Firestore | Resultado |
|---:|---:|---:|---|---|
| 1 | 4.207 s | 0.236 s | Escrito | `Tick OK`, equity 99,288.65, 0 posiciones |
| 2 | 0.722 s | 0.233 s | Escrito | `Tick OK`, 0 órdenes; estrategias `same_bar_context` |
| 3 | 0.663 s | 0.235 s | Escrito | `Tick OK`, 0 órdenes; estrategias `same_bar_context` |

La verificación sanitizada de `diag/state` confirmó `setup_observations`, modo `shadow`, `influence_entries=false` y ocho símbolos observados. La lectura autenticada de Firestore `polaris/2026-08-18` confirmó `updated_at=2026-08-18T01:46:48.534483+00:00`, `trading_mode=PAPER`, `firestore_setup_present=true`, modo `shadow`, `influence_entries=false`, ocho símbolos, cero posiciones y cero órdenes. La ausencia de operaciones no es un fallo de la capa: el snapshot operativo conserva `_floor_below=true` con equity 99,288.65 frente al piso 99,900, por lo que las entradas permanecen bloqueadas por diseño; además, las estrategias reportan `not_tradable` en el primer ciclo y `same_bar_context` en los siguientes.

El log visible de cada ciclo ahora incluye `setups=...s` dentro de `CYCLE TIMING`. No habilitar `influence_entries`, no relajar el floor para crear actividad y no interpretar `Tick OK` como rentabilidad. La clasificación operativa de esta mejora es `HEALTHY_BLOCKED` para entradas por el piso, con la capa de setups funcionando en shadow y publicación Firestore verificada.


## 18. Backtest integrado de setups con la configuración actual — 18 de agosto de 2026

Se ejecutó una ronda nueva donde los setups no se trataron como estrategia independiente. Se probaron como filtro auxiliar sobre dos referencias: (1) la política `regime_hold_cash` actual documentada —bull implica exposición semanal, bear/cash implica efectivo, límite de dos posiciones y detector de crash—; y (2) el código exacto de `strategies.swing_trading.SwingTrend`, uno de los motores live que `bot.py` instancia para `opt_swing_trend`.

La primera referencia se implementó en `scripts/run_current_setup_integration_backtests.py`. Probó `baseline_current` contra filtros diarios, semanales y MTF, con variantes moderate/strict y selección restringida. La segunda referencia se implementó en `scripts/run_live_swing_setup_backtests.py` y usó SMA20/50, filtro SMA200, stop/target por ATR y gestión de hold del motor SwingTrend, añadiendo los mismos filtros de setups.

### 18.1 Datos y límites

El histórico real disponible fue diario, con siete símbolos: AMD, BB, F, NOK, PLTR, TQQQ y TSLA. `SOFI` quedó faltante por recuperación inestable del proveedor y se declaró en los manifiestos. No se generaron barras sintéticas. Las ventanas fueron lateralidad sep–dic 2025, selloff ene–abr 2026, reciente abr–ago 2026 y últimos 30 días hasta 14 ago 2026.

Se respetó anti-look-ahead: cada régimen y setup usó únicamente barras hasta el día de decisión; las velas semanales incompletas se excluyeron; los retornos se marcaron diariamente y se realizaron en rebalanceos semanales. Se aplicó 0.2% de coste round-trip de equity y 5 bps de slippage por lado. Como no hay cadenas históricas point-in-time, bid/ask ni fills de opciones, los retornos son proxy de exposición al subyacente, no P&L de spreads. DTE 10–45, deltas 0.25/0.10, TP 1.4/SL 0.25 y riesgo máximo 5% quedaron registrados como configuración; no se usaron para fabricar P&L de opciones.

### 18.2 Resultado de política de régimen + setups

| Ventana | Baseline actual | Setup diario moderado | Setup semanal moderado | Setup MTF moderado |
|---|---:|---:|---:|---:|
| Lateral 2025 | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Selloff 2026 | +0.91%, DD −0.11% | −0.17%, DD −0.47% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Reciente 2026 | +4.20%, DD −2.39% | **+5.33%, DD −0.92%** | +1.79%, DD −1.42% | +3.09%, DD −0.70% |
| Últimos 30 días | −0.89%, DD −0.90% | **0.00%, DD 0.00%** | −0.66%, DD −0.67% | **0.00%, DD 0.00%** |

El filtro diario moderado mejora retorno en dos ventanas, empeora en una y queda igual en una sin exposición; mejora drawdown en tres. Su resultado positivo principal está concentrado en la ventana reciente y no se reproduce en el selloff.

### 18.3 Resultado del SwingTrend live exacto + setups

| Ventana | SwingTrend baseline | Setup diario moderado | Setup semanal moderado | Setup MTF moderado |
|---|---:|---:|---:|---:|
| Lateral 2025 | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Selloff 2026 | **+2.12%, DD −1.06%** | +2.03%, DD −0.74% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |
| Reciente 2026 | **+4.45%, DD −0.48%** | +3.76%, DD −0.48% | +0.15%, DD −0.48% | +0.15%, DD −0.48% |
| Últimos 30 días | **+0.67%, DD −0.13%** | 0.00%, DD 0.00% | 0.00%, DD 0.00% | 0.00%, DD 0.00% |

En el motor live exacto, ninguna variante con setups aumentó el retorno frente al baseline cuando hubo operaciones. El filtro diario redujo operaciones y profit; los filtros semanales/MTF fueron demasiado restrictivos. Muestras pequeñas, especialmente en la ventana reciente, impiden tomar el win rate como evidencia suficiente.

La clasificación final es **`RESEARCH_ONLY`**. Mantener `setups.mode=shadow` e `influence_entries=false`. No cambiar floor, RiskManager, circuit breakers ni estrategia PAPER por estos resultados. Para una siguiente ronda de promoción sería necesario recuperar históricos intradía 5m/15m para DayMomentum/DayBreakout y cadenas de opciones point-in-time con bid/ask/fills.

Los artefactos se encuentran en `/home/ubuntu/backtests/`: `current_setup_integration_2026-08-18_*` y `live_swing_setup_2026-08-18_*`; el informe legible está en `docs/current_setup_integration_backtest_2026-08-18.md`.


## 19. Auditoría del documento The Wheel — 18 de agosto de 2026

Se localizó en Google Drive el archivo exacto **`The Wheel.pdf`**, ID `1mmBkMnY34t5dr0Y-kCR4awjHXuBskO3B`, PDF de 9 páginas. Su contenido describe el ciclo cash-secured put → posible asignación de 100 acciones → covered call → acciones llamadas → reinicio; recomienda seleccionar acciones según capital, análisis técnico/fundamental, evitar earnings/noticias de alto impacto, buscar aproximadamente 1–2% mensual de ROC sobre colateral, usar deltas de 0.20 o menores y utilizar roll/recompra cuando la posición se mueve en contra.

La skill de repositorio **sí existe** en `docs/skills/wheel_skill.md`. No existe una skill reutilizable separada bajo `/home/ubuntu/skills/` con nombre wheel. La skill del repositorio cubre el documento y amplía sus reglas con parámetros de Polaris, gestión TP/SL, DTE, comisiones, integración SMC y límites derivados de backtests. Debe leerse como especificación documentada e investigación, no como prueba de que el bot la ejecute.

El módulo **sí existe** en `strategies/options_income.py` como `WheelStrategy`. Implementa estados CSP/CC, filtro de earnings, filtro SMA200, selección de puts delta ≤0.20, ROC mensual mínimo de 1%, DTE 21–45, construcción de cash-secured puts y covered calls. Sin embargo, el módulo no implementa todavía un ciclo live completo de asignación/roll persistente equivalente a una cuenta de acciones asignadas: `scan_universe`, `csp_structure` y `cc_structure` existen, pero no están conectados al loop principal.

### Estado real de ejecución

`bot.py::build_strategies()` instancia únicamente `opt_day_momentum`, `opt_day_breakout` y `opt_swing_trend`, según `config.yaml`. El motor bajista `options_bear` se ejecuta aparte cuando el régimen es bear. No instancia `WheelStrategy`, no existe una sección `wheel.enabled` en la configuración activa y no hay señales Wheel en el flujo de entrada live. El sistema actual opera spreads de opciones derivados de señales de momentum, breakout y swing; no vende CSP desnudos/cash-secured puts ni covered calls como rueda.

La matriz de cobertura debe conservar esta distinción: Wheel documentada = sí; módulo existente = sí; conectada al loop = no; activa en PAPER = no; ciclo de asignación/roll probado con datos point-in-time = no. No activar ni cablear Wheel automáticamente: requiere primero un diseño de estado persistente, reconciliación de acciones asignadas, control de colateral 100 acciones, eventos de assignment/exercise, roll con dos órdenes y validación específica en PAPER.


## 20. Skill e investigación profunda de The Wheel — 18 de agosto de 2026

Se creó y validó la skill reutilizable `/home/ubuntu/skills/the-wheel/SKILL.md` mediante el flujo de `skill-creator`. Sus referencias son `references/research.md` y `references/polaris-alpaca.md`. La skill cubre CSP, assignment, covered calls, roll, ROC vs retorno total, datos point-in-time, sesgos de backtest, requisitos de Alpaca y guardarraíles de integración.

La investigación verificó fuentes OCC/OIC sobre CSP y covered calls, exercise americano, assignment temprano, dividendos y exercise-by-exception; Cboe sobre metodología de put-write; Feldman/Roy sobre benchmarks buy-write/put-write; y documentación oficial de Alpaca sobre niveles, ejercicio y polling de actividades no comerciales. La evidencia respalda tratar Wheel como exposición de equity con prima limitada y downside sustancial, no como ingreso pasivo garantizado.

### 20.1 Backtest con barras históricas reales de opciones

Se añadieron `scripts/cache_wheel_option_history.py`, `scripts/run_wheel_backtests.py` y `scripts/analyze_wheel_backtests.py`. Se consultó Alpaca en modo lectura para contratos y barras; no se colocaron órdenes. El cache utilizó siete símbolos del universo disponible —AMD, BB, F, NOK, PLTR, TQQQ, TSLA—, 467 contratos seleccionados, 451 con barras y 9,799 barras diarias entre abril y agosto de 2026. `SOFI` no se incluyó porque el histórico de subyacente requerido no estaba disponible en el cache.

El backtest prueba cinco escenarios: conservador, base, early profit, roll defense y stress; y cinco ventanas: spring selloff, early recovery, summer trend, latest 30d y full recent. La selección usa el contrato disponible más cercano a 21–45 DTE y 5%/10% OTM; el delta histórico point-in-time no estaba disponible y moneyness se declara como proxy. Se usan fills OHLC con slippage paramétrico, comisión de $0.65 por contrato/lado, assignment ITM a vencimiento y fallback a intrinsic cuando falta barra. Early assignment, bid/ask histórico y fecha de listing siguen siendo limitaciones.

El escenario base con capital $100,000 fue positivo en 5/5 ventanas: retorno medio +5.33%, peor retorno +0.62%, drawdown medio −0.35% y peor drawdown −0.62%. Solo superó buy-and-hold en 2/5 ventanas: summer trend +6.24% frente a buy-and-hold −14.08%, latest 30d +6.27% frente a −7.90%; en full recent hizo +12.84% frente a +57.99% de buy-and-hold. El escenario stress mostró peor drawdown −8.71% y 71 data gaps agregados; no se usa para promoción.

Sensibilidad de capital: con $100 no hubo operaciones en ninguna ventana porque la regla cash-secured exige colateral para 100 acciones; con $1,000 la actividad fue limitada y el full recent llegó a ~+1.68% en el mejor escenario, muy por debajo del buy-and-hold de referencia. Esto confirma que The Wheel clásica no es compatible con el reto ficticio $100→$200 sobre el universo actual sin margin o una estructura distinta, que cambiaría el riesgo.

La decisión es **`RESEARCH_ONLY`**. No existe `wheel.enabled` activo, no se conecta `WheelStrategy` a `build_strategies()`, no se despliega a Cloud Run y no se modifica `influence_entries=false`. Antes de una fase PAPER se requieren cadenas/quotes point-in-time, earnings/dividendos as-of, early assignment, reconciliación idempotente de NTA Alpaca, lotes persistentes de 100 acciones, colateral real y roll como dos órdenes. El informe completo es `docs/the_wheel_research_backtest_2026-08-18.md`.


## 21. Matriz de estrategias de opciones de riesgo definido — 18 de agosto de 2026

Se añadió `scripts/cache_defined_risk_option_history.py`, `scripts/run_defined_risk_backtests.py` y `scripts/analyze_defined_risk_backtests.py`. La matriz usó barras históricas reales de opciones Alpaca en solo lectura: 3,626 contratos seleccionados, 3,448 con barras y 73,119 barras diarias para AMD, BB, F, NOK, PLTR, TQQQ y TSLA entre 2026-04-01 y 2026-08-07.

Se probaron 10 familias: bull call debit, bear put debit, bull put credit, bear call credit, iron condor, call butterfly, call calendar, put calendar, call diagonal y put diagonal. Se cruzaron DTE 14/30/45, anchos/moneyness 5%/10%, gestión conservadora/base/agresiva, régimen gated/neutral_ok y cinco ventanas. Total: 1,800 combinaciones. Se mantuvo riesgo definido por estructura, comisión $0.65 por contrato/lado y slippage 2%/5%/10%.

El mayor retorno full_recent fue bull_call_debit 45 DTE, 5% y gestión conservadora gated: +4.62%, drawdown −0.77%, pero con 37 data gaps; no es candidato de promoción. La shortlist de consistencia identificó bear_call_credit 30 DTE, 10%, gestión conservadora gated: retorno medio +0.46% en cinco ventanas, 4/5 positivas, peor retorno 0.00%, drawdown medio −0.10% y 12 data gaps. Su retorno full_recent fue +0.89%, frente a buy-and-hold +57.99%; por tanto es defensivo, no una mejora de profit frente al benchmark.

Iron condor 45 DTE/5% conservador mostró +0.59% en full_recent y drawdown −0.08% con pocas operaciones; put_diagonal 14 DTE/10% conservador mostró +0.42% full_recent y drawdown −0.27% con 1 data gap. Calendars y butterflies tuvieron peor comportamiento agregado en este proxy. Ningún candidato demostró mejora consistente sobre buy-and-hold o el baseline actual.

La decisión es `RESEARCH_ONLY`: no se activaron las estructuras en `bot.py`, `config.yaml`, Cloud Run ni PAPER. Antes de una segunda ronda se requieren bid/ask históricos, delta/IV point-in-time, timestamp de listing/cadena as-of, earnings/dividendos históricos y walk-forward separado. Las métricas de calendars/diagonals son particularmente aproximadas porque su valor depende de term structure e IV.

El informe completo es `docs/defined_risk_options_backtest_2026-08-18.md`.
