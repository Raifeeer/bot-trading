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
