# Hallazgo 21 — Regeneración reproducible de los 89 escenarios (15 de agosto de 2026)

Cierra el punto 1 de la orden obligatoria de `AGENTS.md` §14.4 y el punto 5 de §13.4:
regenerar el backtest completo con artefactos versionados, en lugar de arrastrar el
documento `polaris/backtest` como evidencia histórica no reproducible.

## 1. Qué se corrió

`loop_backtests.py --all` (89 escenarios, S1–S89) sobre el commit actual de `main`,
que ya incluye las correcciones de `hold_weekly`, `cheap_min_net`, la eliminación de
look-ahead en SMA200/volumen y la normalización UTC.

Artefactos versionados en **`docs/backtests/2026-08-15/`**: `bt_resumen.csv` más
`bt_<escenario>_trades.csv` y `bt_<escenario>_equity.csv` por escenario (151 archivos,
724 KB). Es la primera vez que la matriz queda dentro del repositorio; hasta ahora vivía
en `/home/ubuntu/backtests/`, que se pierde entre sesiones y hacía imposible auditar las
cifras publicadas.

## 2. Fuente de datos y su limitación

**Los datos son de Alpaca, no de yfinance.** En el sandbox de Claude Code, yfinance es
inutilizable: `curl_cffi` (que yfinance usa para imitar el TLS de un navegador) choca con
la intercepción TLS del proxy del entorno y devuelve `Recv failure: Connection reset by
peer` en el 100% de los tickers; sin esa imitación, Yahoo responde 429. Se usó la cascada
`_segmented` de `data/feed.py`, que sirve el tramo lejano desde Alpaca con credenciales de
Secret Manager (`alpaca-key` / `alpaca-secret`).

Consecuencia a declarar en cualquier lectura de estas cifras: el tramo "reciente" (los
últimos ~2 días, que el plan free de Alpaca rechaza por SIP y que solo Yahoo cubre) falta.
**Las ventanas terminan el 2026-08-12 en lugar del 2026-08-15.** La corrida original del
14 de agosto terminaba alrededor del 13 de agosto, así que las ventanas son comparables y
la diferencia de tres sesiones no explica ninguna de las discrepancias de abajo.

## 3. Resultado central: el motor es reproducible; S51 no lo era

| Escenario | Publicado | Regenerado | Delta | Trades |
|---|---:|---:|---:|---:|
| S36 (call spread rebote) | +56.5% | +59.3% | +2.8 | 13 |
| **S51 (benchmark hold semanal)** | **+92.5%** | **+3.6%** | **−88.9** | 105 |
| S63 (put spread CHoCH) | +20.8% | +19.7% | −1.1 | 8 |
| S67 (DTE 7–10 OTM) | −48.0% | −48.3% | −0.3 | 5 |
| S75 (defensiva bear suave) | −32.9% | −32.9% | 0.0 | 2 |
| S76 (defensiva bear suave) | −6.6% | −6.6% | 0.0 | 2 |
| S78 (régimen bull→hold, bear→cash) | +26.7% | +26.7% | 0.0 | 144 |
| S55 (cash en lateral) | 0 trades | 0 trades | 0.0 | 0 |

Siete de los ocho escenarios citados en `AGENTS.md` reproducen dentro de ±3 puntos, y
cuatro de ellos son idénticos. **El motor de backtesting es reproducible.** Esa es la
buena noticia y refuerza la confianza en el resto del corpus.

El único que no reproduce es **S51**, y es exactamente el que §14.3 ya marcaba como
sospechoso: *"declara S51 como benchmark `motor="hold"`, pero el motor genérico abre solo
una posición"*. Con el motor legacy, el "benchmark hold" concentraba el capital en una
sola posición: de ahí un retorno de +92.5% acompañado de un drawdown de −63.5% y 61
trades. Con `hold_weekly` explícito — 8 tickers equally weighted, rebalanceo semanal, que
es lo que la etiqueta "hold semanal equally weighted del universo reto" siempre describió —
el mismo escenario rinde **+3.6% con drawdown −10.2% y 105 trades**.

No es que el backtest estuviera "mal calculado": medía otra cosa distinta de la que decía
su nombre. La corrección elimina el número, no lo ajusta.

## 4. Panorama global de los 89 escenarios

- Mediana de retorno: **0.0%**. Media: +13.3%.
- Positivos: **41 de 89**.
- Escenarios con **0 trades: 28** (casi un tercio del corpus no llega a operar).
- Mejor escenario por retorno: S16 (`swing`, +101.7%) con **3 trades** y drawdown 0% —
  ruido estadístico, no una estrategia. El segundo, S30 (`smc_daily`, +80.5%), carga un
  drawdown de −42.7%.

La lectura honesta del corpus completo es mucho más sobria que la selección de titulares
que circulaba: la mediana del universo de configuraciones probadas es cero, y los retornos
altos vienen acompañados de muestras minúsculas o drawdowns severos.

## 5. Impacto en lo publicado

El documento Firestore `polaris/backtest` (escrito el 2026-08-14T13:02:58Z) anuncia
`best = {scenario: S51, retorno_pct: 92.5, trades: 61, win_rate_pct: 44.3}`, y el
dashboard en Vercel lo muestra como titular (`S51 · 92.5%`). **Ese titular es un artefacto
del motor legacy y sobreestima el benchmark real en un factor de ~26.**

Esto choca de frente con el requisito permanente del usuario recogido en §9: *toda* la
información del dashboard debe ser real y provenir de una fuente identificable. La cifra es
real en el sentido de que salió de una corrida, pero mide una estrategia que no es la que
su etiqueta declara, y que nadie propondría operar.

**Pendiente de decisión del dueño** (no ejecutado en esta sesión, por ser una escritura a
producción visible en el dashboard): republicar `polaris/backtest` desde
`docs/backtests/2026-08-15/bt_resumen.csv`, con S51 en +3.6% y, preferiblemente, sin
promover ningún "mejor escenario" elegido a posteriori sobre la misma muestra en la que se
mide — que es en sí una forma de sobreajuste.

## 6. Qué NO cambia este hallazgo

Se mantienen íntegras las advertencias de §14.3 y §16, que esta corrida no levanta:

- Las primas de opciones siguen siendo proxies Black–Scholes con IV histórica, no cadenas
  point-in-time. Nada aquí mide fills reales, spread bid/ask, liquidez ni asignación.
- Los datos de earnings de yfinance no son point-in-time.
- La validación fuera de muestra sigue siendo insuficiente: el walk-forward de §16 ya
  mostraba pesos inestables entre folds (+34.985% en un test, −2.232% en otro).
- **Nada de esto convierte el reto $100 → $200 en un objetivo con respaldo empírico.** Si
  acaso, la caída del benchmark de +92.5% a +3.6% y una mediana de corpus de 0.0% empujan
  en la dirección contraria.

Mantener Cloud Run en PAPER. No cambiar parámetros productivos a partir de esta corrida.
