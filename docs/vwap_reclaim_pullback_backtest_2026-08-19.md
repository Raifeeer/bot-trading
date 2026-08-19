# Evaluación VWAP reclaim/pullback — 2026-08-19

## Pregunta

¿Puede un motor intradía de `VWAP reclaim/pullback` cubrir una oportunidad distinta de los motores EMA/RSI/Donchian actuales de Polaris y mejorar el retorno ajustado por riesgo en PAPER sin introducir una dependencia excesiva de un símbolo, una ventana o una regla de volumen?

## Decisión ejecutiva

**Resultado: `RESEARCH_ONLY`; no integrar VWAP en `bot.py`, no activar un filtro PAPER y no añadirlo como shadow en Cloud Run por ahora.** Las variantes con volumen y gate direccional muestran pequeñas mejoras en algunas ventanas recientes, pero las muestras son reducidas y el resultado completo de 15 minutos queda muy por debajo del baseline DayBreakout. Las variantes sin gate de volumen generan muchas más operaciones y pérdidas importantes. El motor queda en el repositorio como detector puro y arnés reproducible, sin autoridad sobre entradas, sizing, floor, RiskManager o executor.

La observación VWAP que ya existe dentro de `setup_confluence` no se modificó. Esa observación contextual no equivale a este motor de fases `displacement → retracement → resumption`.

## Método

VWAP se calculó como el promedio de `(high + low + close) / 3` ponderado por volumen, reiniciado cada sesión local. La literatura consultada presenta VWAP principalmente como benchmark de ejecución y no como una predicción automática de rebote; su formulación básica es `sum(price × volume) / sum(volume)` [1]. La guía practitioner utilizada para generar la hipótesis separa desplazamiento, retroceso ordenado y reanudación, y advierte que un toque aislado no es un pullback válido [2].

El backtest usa caches históricos reales de Alpaca IEX: 5 minutos de `structure_mtf_history`, 15 minutos de `volume_profile_history` y diarios de `setup_history` para el régimen. El universo solicitado era SOFI, PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI quedó fuera por falta de datos, por lo que la corrida usa siete símbolos. La cobertura 5m común es aproximadamente de 38 sesiones y la de 15m llega aproximadamente a un año.

Se probaron **48 variantes**: 5m/15m, `reclaim`/`pullback`, long/short/both, gate de régimen `none`/`directional` y volumen `novol`/`vol12`. El gate direccional deja pasar long en bull y short en bear/crash. Las cortas son solo investigación. Cada señal usa barras cerradas, llena en la apertura siguiente, no mantiene overnight, aplica 5 bps de slippage por lado y usa stop estructural con buffer ATR, target 2R y máximo de 36 barras en 5m o 20 barras en 15m. La referencia es `DayBreakout` S78 con sus parámetros actuales y warm-up histórico fuera de la métrica.

El volumen se probó con y sin filtro. No se asumió que una media bruta sea neutral: la evidencia académica describe una curva intradía de volumen en forma de U, con actividad alta al principio y final de sesión y menor en el centro [3]. Por eso no se escogió un parámetro por mirar el test y se mantiene como pendiente una normalización por minuto de sesión construida solo con días anteriores.

## Baseline DayBreakout

| Ventana | Retorno | Max drawdown | Trades |
|---|---:|---:|---:|
| recent_5d | −0.5681% | −0.6573% | 2 |
| prior_5d | 0.0000% | 0.0000% | 0 |
| prior_10d | 0.0000% | 0.0000% | 0 |
| recent_20d | −0.5681% | −0.6573% | 2 |
| full_available 15m | **+8.4848%** | −3.0969% | 156 |
| recent_40d | −0.8199% | −1.2562% | 6 |

Las ventanas recientes tienen poca actividad del baseline. El dato más informativo para evitar sobreajuste es la ventana completa 15m, en la que DayBreakout produjo +8.48% con 156 trades.

## Resultados principales

| Variante | Evidencia reciente | Cobertura completa | Lectura |
|---|---|---|---|
| `vwap_5min_reclaim_short_vol12_directional` | En recent_20d: +0.0599%, delta +0.6279 pp frente a baseline; 4 trades | −0.2129% en full 5m; 12 trades | Mejora pequeña y muestra insuficiente; no comparable contra full 15m |
| `vwap_5min_pullback_both_vol12_directional` | En recent_20d: +0.0170%, delta +0.5851 pp; 2 trades | −0.3710% en full 5m; 12 trades | Señal escasa, no robusta fuera de la ventana reciente |
| `vwap_5min_pullback_both_vol12_none` | En recent_20d: −0.0762%, delta +0.4919 pp; 7 trades | −0.4474% en full 5m; 19 trades | Menor ventaja reciente, pérdida completa y sin gate direccional |
| `vwap_15min_pullback_short_vol12_directional` | En recent_20d: +0.3137%, delta +0.8818 pp; 1 trade | **−0.0695% en full 15m**, delta **−8.5543 pp**; 5 trades | Queda muy por debajo del baseline en la ventana comparable |
| `vwap_15min_pullback_both_vol12_directional` | En recent_20d: +0.3137%, delta +0.8818 pp; 1 trade | −0.2207% en full 15m, delta −8.7055 pp; 5 trades | Misma fragilidad; no mejora el periodo completo |
| `vwap_15min_pullback_long_novol_none` | Muchas operaciones y algunas ventanas positivas | −17.3634% en full 15m, DD −20.0317%; 622 trades | El filtro de volumen es importante; sin él el motor se degrada severamente |

En el resumen de ventanas comparables, las variantes 5m con volumen alcanzan como máximo 3 de 4 ventanas positivas/robustas, pero con entre 4 y 16 trades agregados en esas ventanas. Las variantes 15m con volumen alcanzan 4 de 6 ventanas robustas en algunos casos, pero solo con 5–26 trades totales y una pérdida o estancamiento en `full_available` frente a un baseline de +8.48%. La media delta negativa en varias de esas variantes confirma que la ventaja reciente no se sostiene en el periodo completo.

## Concentración y sensibilidad

El resumen por símbolo muestra que los mejores P&L aislados se concentran en PLTR, NOK, BB, F, AMD y TQQQ según la combinación; por ejemplo, `vwap_5min_pullback_long_novol_none` obtuvo gran parte de su P&L en PLTR, NOK, BB y AMD, pero esa variante tiene −17.36% en full 15m y no es candidata. La concentración por símbolo no puede considerarse evidencia de edge universal.

| Control | Resultado | Interpretación |
|---|---|---|
| Volumen `vol12` vs `novol` | Las variantes con volumen son menos activas y menos negativas; las `novol` 15m llegan a pérdidas de −17% a −44% en la matriz completa | El volumen parece necesario para evitar ruido, pero no demuestra alpha |
| Gate `directional` vs `none` | Reduce operaciones y limita algunas pérdidas, pero no elimina la caída frente al baseline completo | El régimen ayuda como control de riesgo, no convierte VWAP en motor robusto |
| 5m vs 15m | 5m tiene pequeñas mejoras recientes, pero cobertura corta y poca muestra; 15m tiene más cobertura y queda debajo del baseline | No existe evidencia suficiente para elegir timeframe |
| Reclaim vs pullback | Reclaim short con volumen es la mejor señal reciente 5m; pullback short con volumen es la mejor lectura 15m reciente | El resultado depende de la definición seleccionada |
| Ventana completa | Todas las variantes prometedoras quedan negativas o muy por debajo de DayBreakout en la cobertura comparable | Control principal contra sobreajuste |

## Incertidumbres

La ausencia de SOFI reduce la representatividad del universo original. La cobertura 5m es corta y no contiene suficientes ciclos de mercado para un walk-forward sólido. El histórico disponible es OHLCV del subyacente; no hay P&L histórico de opciones, IV, bid/ask, fills de las patas, assignment ni coste de spread. Los 5 bps por lado son un coste conservador del subyacente, no una reconstrucción de ejecución de opciones.

La fuente académica sobre VWAP estudia ejecución y market impact, no una estrategia direccional de reclaim [1]. La fuente practitioner aporta una estructura útil para convertir la hipótesis en reglas, pero no valida su rentabilidad [2]. La definición contractual de sesión 09:30–16:00 ET se usa como referencia de anclaje, pero el motor limita entradas a 15:30 para cerrar posiciones antes del final de sesión [4].

## Implicaciones para Polaris

No modificar el runtime live. No añadir `vwap_shadow_observations`, no cambiar `influence_entries`, no tocar el floor de recuperación de $99,000, no relajar los circuit breakers y no habilitar cortas intradía. El detector puro puede servir para una futura ronda de investigación, pero antes se requieren más sesiones 5m, folds cronológicos no solapados, normalización de volumen por minuto as-of, y un backtest integrado contra la política exacta `regime_hold_cash` y contra los fills de opciones disponibles.

Polaris continúa en PAPER con la revisión `polaris-bot-brshadow0724650`; la capa bearish de breakdown/retest permanece shadow y no existe ningún despliegue VWAP.

## Artefactos reproducibles

- `strategies/vwap_reclaim_pullback.py`
- `tests/test_vwap_reclaim_pullback.py`
- `scripts/run_vwap_backtests.py`
- `scripts/analyze_vwap_backtests.py`
- `docs/vwap_research_sources_2026-08-19.md`
- `/home/ubuntu/backtests/vwap_backtests_2026-08-19.csv`
- `/home/ubuntu/backtests/vwap_backtest_comparison_2026-08-19.csv`
- `/home/ubuntu/backtests/vwap_backtest_variant_summary_2026-08-19.csv`
- `/home/ubuntu/backtests/vwap_backtest_symbol_summary_2026-08-19.csv`
- `/home/ubuntu/backtests/vwap_backtest_trades_2026-08-19.csv`
- `/home/ubuntu/backtests/vwap_backtest_manifest_2026-08-19.json`

## Referencias

[1] [Deep Learning for VWAP Execution in Crypto Markets: Beyond the Volume Curve](https://ar5iv.labs.arxiv.org/html/2502.13722).

[2] [VWAP Pullback Strategy: Entry, Exit, Risk & Journal Guide](https://tradediary.in/strategies/vwap-pullback).

[3] [Intraday trading volume and non-negative matrix factorization](https://www.ime.usp.br/~jstern/papers/papersJS/MaxEnt15T.pdf).

[4] [Volume Weighted Average Price Definitions](https://dictionary.contracts.justia.com/volume-weighted-average-price).
