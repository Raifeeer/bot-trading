# Skill: Dashboard (Vercel) y Telegram (alertas + asistente IA)

**Archivos de referencia:** `client/src/lib/firestore.ts`, `client/src/pages/*.tsx` (repo `Raifeeer/Polaris-Web-Studio` / proyecto Vercel `polaris-options-dashboard`), y en el bot `state/telegram_bot.py`, `state/telegram_notify.py`, `state/ai_assistant.py`.

## 1. Dashboard — arquitectura de datos

El dashboard es una SPA React 19 + Tailwind 4 desplegada en Vercel (`polaris-options-dashboard.vercel.app`). **No tiene backend propio:** toda la información vive en Firestore y llega por suscripción en tiempo real.

| Elemento | Fuente |
|---|---|
| Posiciones (SEC-02) y consola (EQ-01, STR-01) | `onSnapshot` sobre `polaris/YYYY-MM-DD` → `payload.alpaca_positions` / `payload.equity` / `payload.regime` |
| Señales (SIG-01) | `payload.decisions_today` + `payload.orders_executed` |
| Riesgo (RSK-01/RSK-02) | `payload.risk` (límites reales del bot) + `payload.open_positions` |
| Modo PAPER/REAL y antigüedad del tick | `payload.trading_mode` + `updated_at` |
| Configuración (perfil reto, universo) | `polaris/config` + `payload.universe` |
| Curva de equity | `equity_curve` del doc del día |

**Regla permanente del dueño:** cero mock. Si un doc del día no existe aún, el dashboard muestra estado vacío con etiqueta explícita ("esperando primer tick"), nunca cifras inventadas. El bundle de producción auditado el 15 de agosto de 2026 contiene estados vacíos explícitos y la ruta principal de Firestore; no debe conservar cifras demo como fallback visible.

**Detalle crítico de las posiciones:** el bot publica las piernas crudas de Alpaca en `payload.alpaca_positions` (ej. `TQQQ260918C00085000` long 10 @2.32 + `TQQQ260918C00100000` short -10 @0.35). El frontend las **agrupa por subyacente** (`toPosRaw` + `mapPositions`): detecta spreads call/put debit/credit y calcula prima de entrada, prima actual neta, P&L, theta y vega agregados. Priorizar siempre `alpaca_positions` cuando `positions` esté vacío; no revertir ese orden.

**Guardas visibles:** el KPI de equity (EQ-01) muestra la guarda del piso $99,900 y la meta $100,100, con aviso destacado si el equity cruza bajo el piso.

**Deploy del dashboard:** el build de Vercel falla de forma reproducible (pnpm/Node 24, `ERR_PNPM_META_FETCH_FAIL`). Flujo permanente: build local (`pnpm build` en el sandbox) + deploy de artefactos estáticos precompilados vía MCP de Vercel (`framework: null`, outputDirectory = `dist` compilado, `vercel.json` SPA).

## 1.1 Auditoría de producción — 15 ago 2026

La URL pública `https://polaris-options-dashboard.vercel.app` se cargó correctamente y mostró `Fuente Firestore · polaris`, equity `$99,689.50`, modo `PAPER`, curva de equity, dos piernas Alpaca agrupadas como spread TQQQ y el documento de backtest. El documento `polaris/backtest` es real y declara `source=loop_backtests.py (89 escenarios S1-S89)`, mejor escenario `S51`, retorno `92.5%`, win rate `44.3%` y 61 trades; por tanto, BT-04 puede mostrar `44% win` y `S51 · 92.5%` con redondeo legítimo.

El bundle conserva la ruta de fuente `client/src/pages/Home.tsx` en `data-loc`, pero esa fuente no está disponible en la sandbox ni dentro del repo local `Raifeeer/Polaris-Web-Studio`; dicho repositorio es el sitio comercial principal. No modificarlo como dashboard de trading sin recuperar la fuente correcta del proyecto Vercel/Manus.

Se detectó una posible corrección de presentación: el bundle formatea `x.riskPerTradePct.toFixed(1)` directamente. El payload real usa `risk.risk_per_trade_pct=0.01`, por lo que la interfaz muestra `0.0% del capital` si el frontend no convierte fracción a porcentaje. Antes de corregirlo, recuperar la fuente `Home.tsx`, confirmar el contrato y añadir una prueba. El texto `Gestión: esperando reglas publicadas por el bot` también indica que el payload actual no publica reglas de gestión suficientes para ese panel; no inventar valores.

## 2. Telegram — alerta + conversación

El bot de Telegram corre **dentro del mismo contenedor** de Cloud Run (hilo de polling sobre `api.telegram.org`) y responde solo al chat autorizado del dueño (`TELEGRAM_CHAT_ID=1779931930`).

**Comandos:** `/estado` (equity, cash, buying power, P&L del día), `/posiciones` (detalle de spreads y de Alpaca), `/historial` (operaciones cerradas), `/señales` (decisiones recientes), `/riesgo` (circuit breakers y límites), `/ayuda`.

**Asistente conversacional:** cualquier mensaje que no sea comando cae en `ai_assistant.py`, que envía al LLM el **estado real del bot** como contexto y responde en español. Stack de modelos: DeepSeek V4 Flash (`deepseek-chat`) como principal, con fallbacks a Gemini y Grok (API keys en Secret Manager: `deepseek-api-key`, `gemini-api-key`, `grok-api-key`). Cada llamada tiene **timeout de 45 s**; sin él, el LLM lento congelaba el hilo de polling (incidente documentado).

**Alertas salientes** (`telegram_notify.py`): apertura/cierre de posiciones, eventos de riesgo (halt por circuit breaker, piso de equity cruzado, régimen bear) y el heartbeat del watchdog de Telegram.

**Watchdog del hilo:** el main loop del bot verifica el heartbeat del hilo de Telegram cada ciclo; si supera `TG_HB_TIMEOUT_S` sin latir, `sys.exit(1)` y Cloud Run recrea el contenedor.

## 3. Contrato de publicación (lo que el bot escribe a Firestore por tick)

```json
{
  "updated_at": "...",
  "payload": {
    "equity": 99719.50, "cash": ..., "buying_power": ...,
    "positions": [], "alpaca_positions": [{...legs...}],
    "orders_executed": [], "decisions_today": [],
    "risk": {"risk_per_trade_pct": 5.0, "max_positions": 2, "halted": false},
    "regime": "bull", "trading_mode": "PAPER",
    "strategies": [...], "universe": {...}
  },
  "equity_curve": [{"t": "...", "value": 99719.50}, ...]
}
```

`payload.regime` es string (`"bull"`/`"bear"`); cualquier nuevo valor requiere actualizar el frontend simultáneamente. El campo `payload.risk.risk_per_trade_pct` se publica como fracción decimal en el bot actual (por ejemplo, `0.01` = 1%); el frontend debe convertirlo a porcentaje antes de mostrarlo. El doc se escribe con **merge** (no overwrite) una vez por tick; el dashboard se actualiza solo.

## 4. Mobile y UX (decisiones de diseño)

El dashboard es responsive con sidebar drawer en <lg (hoja lateral desde el botón hamburguesa del header), grids responsivos y beacons/fechas adaptados; verificado en viewport 375px. Las secciones son Consola, Posiciones, Señales, Riesgo, Backtest y Config. Estilo elegido en el desarrollo: tema oscuro de torre de control de trading, con acentos semánticos (verde ganancia/rojo pérdida/ámbar advertencias) y tablas densas legibles en móvil.

## 5. Criterios de uso por el agente

Si se añade un campo nuevo al payload del bot, añadir su consumo al dashboard en el mismo checkpoint (el contrato de datos es estricto). Si se cambia el doc de Firestore o las reglas de seguridad, probar la lectura pública con la API key del dashboard antes de desplegar. Los cambios del dashboard se suben al repo `Raifeeer/Polaris-Web-Studio` (git push main) y el deploy a Vercel sigue el flujo de artefactos estáticos. Nunca reintroducir datos mock: si una fuente real aún no existe, el panel se declara vacío con estado explícito.
