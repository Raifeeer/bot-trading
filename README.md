# Polaris Options Bot

Bot de trading de **opciones avanzadas** para acciones de Nasdaq y S&P 500, con broker **Alpaca Markets** (paper trading). Soporta day trading y swing trading sobre estructuras de spreads (call/put spreads e iron condors), con gestión de riesgo completa y dashboard web.

## Arquitectura

El sistema está organizado en siete módulos desacoplados. Las señales de entrada provienen del análisis del subyacente (acciones), y el módulo de opciones traduce cada señal en una estructura de derivados concreta.

| Módulo | Ruta | Función |
|---|---|---|
| Configuración | `config/` | Parámetros centralizados en `config.yaml` |
| Datos | `data/feed.py` | Pipeline OHLCV con Alpaca + respaldo yfinance, degradación automática por símbolo |
| Estrategias | `strategies/` | Señales de subyacente: `day_trading` (momentum 5 min, breakout 15 min), `swing_trading` (cruce SMA 20/50 diario) |
| Opciones | `options/` | Cadena de contratos, Black-Scholes (griegas e IV implícita), selección de strikes por delta, construcción de spreads |
| Ingresos | `strategies/options_income.py` | **The Wheel** (CSP + Covered Call): venta de puts delta ≤ 0.20, prima ≥ 1% mensual del colateral, sin earnings cercanos, CC solo con spot > SMA200 |
| Estructura | `strategies/smc.py` | **SMC multi-timeframe**: cascada 1D → 4H (tendencia) → 15M (CHoCH + zonas de supply/demand) → 1M (timing), confluencia ≥ 0.5 |
| Riesgo | `risk/manager.py` | Posición sizing por riesgo fijo, circuit breakers (drawdown diario/total, PDT), límites de exposición |
| Backtesting | `engine/` | Motor por evento sobre historia real + simulador de opciones con pricing BS teórico |
| Ejecución | `execution/alpaca_executor.py` | Órdenes de acciones y opciones en Alpaca, modo DRY-RUN incluido |
| Bot en vivo | `bot.py` | Loop principal: datos → señales → estructura → aprobación de riesgo → ejecución |

## Requisitos y entorno

Necesitas Python 3.10+ y una cuenta gratuita de [Alpaca](https://app.alpaca.markets) (paper trading, sin mínimo de depósito). Crea las credenciales en la sección API de tu cuenta.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Sin credenciales configuradas, todo el sistema funciona en **modo simulado** (datos de yfinance, contratos sintéticos con pricing Black-Scholes, órdenes DRY-RUN). Esto permite desarrollar y validar sin riesgo.

## Nuevas estrategias (del material de formación Abacus)

Además de las estrategias base, el bot incluye dos estrategias derivadas del corpus de formación. **The Wheel** (`strategies/options_income.py`) opera con cash-secured puts de delta ≤ 0.20 y ≥ 14 días al vencimiento, exige un retorno de prima ≥ 1% mensual del colateral, excluye símbolos cercanos a resultados y solo vende calls cubiertas cuando el spot está por encima de su media de 200 días. **SMC** (`strategies/smc.py`) implementa la cascada multi-timeframe: determina la tendencia en diario y 4 horas (estructura HH/HL), espera un cambio de carácter (CHoCH) en 15 minutos dentro de una zona de oferta/demanda institucional y usa 1 minuto para el timing, con un índice de confluencia mínimo de 0.5 para generar señal.

## Validación contra Alpaca real

El módulo de opciones fue validado el 13-ago-2026 contra una cuenta paper de Alpaca: conexión activa (equity $100,000), cadena de contratos real (AAPL), snapshots en lotes de 25 símbolos (dentro del límite de 60 req/min), IV implícita calculada localmente a ~23% para AAPL ATM y construcción real de un call spread (BUY K300 + SELL K302.5, prima neta −$4.16, breakeven 295.84). Los snapshots de paper no entregan greeks; el bot los calcula con Black-Scholes + IV implícita propia, descartando strikes profundos ITM/OTM donde la IV no es informativa.

## Uso rápido

```bash
# Backtest de acciones (3 estrategias · universo Nasdaq/S&P 500)
DATA_PROVIDER=yfinance ./venv/bin/python scripts/run_backtest.py

# Backtest de opciones (spreads 15/30 DTE sobre historia real del subyacente)
DATA_PROVIDER=yfinance ./venv/bin/python -m options.backtest_options

# Bot en vivo en modo simulado (sin credenciales, órdenes DRY-RUN)
DATA_PROVIDER=yfinance ./venv/bin/python bot.py --dry-run --poll-minutes 5

# Bot en vivo conectado a Alpaca paper
export APCA_API_KEY_ID=tu_key
export APCA_API_SECRET_KEY=tu_secret
./venv/bin/python bot.py --dry-run          # credenciales reales pero sin enviar órdenes
./venv/bin/python bot.py                    # ejecución real en paper trading
```

## Gestión de riesgo implementada

El sistema aplica riesgo definido antes de cada entrada: 1% de capital máximo por spread, máximo 5 posiciones simultáneas, stop por débito total del spread (−100%), take profit del +50% de la prima, cierre preventivo a 21 días de vencimiento (gamma de expiración), y circuit breakers que detienen el bot con −3% diario o −10% total. Las órdenes de day trading también respetan el límite de 3 operaciones intradía para cuentas menores a $25k (regla PDT).

## Dashboard

El dashboard web está en el proyecto `polaris-options-dashboard` (React + Tailwind), con seis vistas: consola (equity, spreads abiertos, señales en tiempo real), posiciones con griegas, señales, gestión de riesgo, backtest y configuración. Por ahora muestra datos simulados que reflejan el formato real que producirá el bot; la conexión del bot al dashboard se recomienda hacer mediante una API intermedia (FastAPI) o un archivo JSON compartido, ya que el dashboard es estático.

## Configuración del fondeo desde República Dominicana

Alpaca fondea cuentas internacionales mediante wire o depósito en moneda local vía CurrencyCloud. El flujo práctico es: cuenta en Alpaca → dirección bancaria asignada → enviar remesa (Remesas Directas o similar) a esa cuenta. No acepta PayPal directo (ningún broker de acciones de EE. UU. lo acepta por regulaciones AML).

## Asistente IA conversacional (Telegram)

El hilo de Telegram (`state/telegram_bot.py`) responde a comandos fijos
(` /estado`, `/posiciones`, `/historial`, `/señales`, `/riesgo`, `/ayuda`) y,
como fallback, a preguntas en lenguaje natural mediante el módulo
`state/ai_assistant.py`, que envía el estado real del bot (equity, posiciones,
P&L del día, decisiones recientes) como contexto al LLM.

**Habilitación** (variables de entorno en Cloud Run):

| Variable | Qué habilita |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API directa (`deepseek-chat`; cambiable con `DEEPSEEK_MODEL`) |
| `OPENAI_API_BASE` + `OPENAI_API_KEY` | Cualquier API compatible con OpenAI |
| `OPENAI_API_KEY` | OpenAI directa (`gpt-4o-mini`; cambiable con `OPENAI_MODEL`) |

Sin clave configurada, el fallback IA queda desactivado y los mensajes que no
sean comandos reciben la respuesta "no entendí el comando", como siempre.

**Ejemplos de preguntas naturales:** "¿cuánto ganamos hoy?", "¿cómo va la
posición de SPY?", "¿estamos arriesgando mucho?".

## Advertencia

Las opciones implican riesgo de pérdida total de la prima. Este sistema opera primero en paper trading y solo debe validarse con capital real tras semanas de resultados consistentes y entendiendo plenamente cada estrategia.
