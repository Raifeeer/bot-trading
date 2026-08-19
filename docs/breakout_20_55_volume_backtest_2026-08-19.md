# Breakout20/55 con volumen — 2026-08-19

## Decisión

**Decisión: integrar únicamente como `shadow` en PAPER.** La variante 15m `lookback=55`, volumen relativo mínimo `1.0x` y gate bull fue la más consistente de la matriz: en la cobertura completa obtuvo +9.542% frente a +8.485% de DayBreakout S78, con DD −2.945% frente a −3.097%, y en el resumen por ventanas superó al baseline en 4 de 6 ventanas bajo el criterio conservador usado. El walk-forward no solapado mejora en dos de los tres folds con actividad y queda por debajo en uno; los otros dos folds no tuvieron señales. Esto justifica observación, no autoridad sobre entradas.

El canal 55 no se considera alpha independiente: pertenece a la misma familia Donchian que el motor actual de 10 barras. La integración solo registra si la ruptura alternativa habría confirmado y si habría pasado el gate bull. No puede abrir órdenes, cambiar sizing, saltarse RiskManager, modificar el floor o alterar circuit breakers.

## Hipótesis

Un canal Donchian de 20 o 55 barras puede reducir ruido frente a la ruptura de 10 barras y encontrar continuaciones de tendencia más maduras. El filtro de volumen relativo pretende distinguir aceptación de una ruptura con actividad normal, pero también puede reducir exposición sin mejorar el edge. Por eso se compararon ambos efectos por separado.

La evidencia externa sobre time-series momentum respalda investigar persistencia de retornos en horizontes largos, pero no demuestra que 20/55 sea óptimo en acciones intradía ni que un breakout con volumen sea rentable después de costes [1] [2]. Un trabajo aplicado sobre canales Donchian prueba 20/55 en futuros sudafricanos, pero su universo y frecuencia no son transferibles directamente a Polaris [3].

## Metodología

Se ejecutaron **24 variantes** y **138 filas** sobre caches reales OHLCV de Alpaca IEX: 5m y 15m, con daily setup history para el régimen. La cobertura usable fue PLTR, F, TSLA, AMD, NOK, BB y TQQQ; SOFI quedó fuera por falta de cache intradía utilizable.

Las variantes combinaron lookbacks 20/55, volumen mínimo 0/1.0x/1.2x, gate none/bull y timeframes 5m/15m. La entrada simulada se ejecutó en la apertura siguiente al cierre de ruptura. Se aplicaron stop ATR/estructura, target 1.5R, máximo de 36 barras en 5m o 20 barras en 15m, cierre intradía y 5 bps de slippage por lado.

El canal excluye la barra actual mediante `shift(1)`. El volumen relativo usa una media rolling desplazada. El régimen diario solo usa datos as-of previos a la sesión. Las ventanas 5m no se comparan contra el baseline 15m en `full_available` cuando no existe una cobertura equivalente.

## Cobertura completa

| Variante | Retorno full | Max drawdown | Delta retorno vs S78 | Delta drawdown vs S78 | Trades | Interpretación |
|---|---:|---:|---:|---:|---:|---|
| DayBreakout S78 15m | +8.485% | −3.097% | — | — | 156 | Baseline |
| LB55 + vol 1.0x + gate bull | **+9.542%** | **−2.945%** | **+1.057 pp** | **+0.152 pp** | 93 | Candidato shadow |
| LB20 + vol 1.0x + gate bull | +9.144% | −2.501% | +0.660 pp | +0.596 pp | 118 | También prometedora, más cercana al baseline |
| LB20 + vol 1.2x + gate bull | +9.013% | −2.492% | +0.528 pp | +0.604 pp | 111 | Similar, algo más selectiva |
| LB55 + vol 1.2x + gate bull | +8.206% | −3.825% | −0.278 pp | −0.728 pp | 87 | No robusta en full |
| LB55 sin volumen + gate bull | +7.886% | −3.657% | −0.599 pp | −0.560 pp | 99 | Volumen aporta selección |
| LB20 sin volumen + gate bull | +6.307% | −3.751% | −2.178 pp | −0.654 pp | 130 | Inferior |

Sin gate, los canales se degradan: LB20 sin volumen termina en −13.108% con DD −24.116%, y LB55 sin volumen en −2.130% con DD −14.799%. El gate bull no es un detalle cosmético; evita que una ruptura alcista se aplique durante regímenes que el baseline no considera favorables.

## Walk-forward no solapado

Se utilizaron cinco folds cronológicos de 15m, excluyendo 20 sesiones iniciales como warm-up. Dos folds no generaron señales ni para baseline ni para candidatos; se conservan como no-signal y no se imputan.

| Fold | Baseline S78 | LB55 vol1.0 bull | LB20 vol1.0 bull | LB20 vol1.2 bull | LB55 vol1.2 bull |
|---|---:|---:|---:|---:|---:|
| 1 | 0.000% | 0.000% | 0.000% | 0.000% | 0.000% |
| 2 | +0.384% | −0.240% | −0.992% | −0.992% | −0.240% |
| 3 | 0.000% | 0.000% | 0.000% | 0.000% | 0.000% |
| 4 | +8.948% | **+9.782%** | +10.664% | +10.481% | +8.452% |
| 5 | −1.038% | **+0.105%** | −0.308% | −0.308% | +0.105% |

En los tres folds con actividad del baseline, LB55 vol1.0 bull supera al baseline en dos y pierde en uno. Su delta de drawdown es +0.431 pp, −0.437 pp y +0.492 pp, por lo que también mejora el drawdown en dos de los tres. La muestra fuera de muestra sigue siendo corta para promocionarlo a filtro.

## Concentración y riesgos

La ventaja no es uniforme por símbolo. Parte del P&L positivo se concentra en AMD, PLTR y NOK, y el universo solo contiene siete símbolos con histórico intradía válido. Antes de cualquier promoción futura se necesita leave-one-symbol-out y un ledger de exposición; además, debe comprobarse cuánto se solapan las señales con el DayBreakout de 10 barras.

La configuración shadow congelada es LB55, 15m, volumen 1.0x, gate bull, una señal por sesión y long-only. Si la señal actual no está en régimen bull, se registra como confirmada pero `would_pass_gate=false`; la observación no se convierte en entrada.

## Integración segura

Se añadió `breakout_20_55_shadow` a `config/config.yaml` y un wrapper en `bot.py`. El estado se publica bajo `breakout_20_55_shadow_observations`, se resume en `signal_stats.breakout_20_55_shadow` y se cronometra como `breakout_20_55_shadow_s` en `CYCLE TIMING`. El wrapper fuerza `mode=shadow`, `influence_entries=false`, `orders_allowed=false` y `allow_shorts=false`.

## Artefactos

- `strategies/breakout_20_55_volume.py`
- `tests/test_breakout_20_55_volume.py`
- `tests/test_breakout_20_55_shadow.py`
- `scripts/run_breakout_20_55_backtests.py`
- `scripts/analyze_breakout_20_55_backtests.py`
- `scripts/run_breakout_20_55_walkforward.py`
- `docs/breakout_20_55_research_sources_2026-08-19.md`
- `backtests/breakout_20_55_backtests_2026-08-19.csv`
- `backtests/breakout_20_55_backtest_trades_2026-08-19.csv`
- `backtests/breakout_20_55_backtest_comparison_2026-08-19.csv`
- `backtests/breakout_20_55_backtest_variant_summary_2026-08-19.csv`
- `backtests/breakout_20_55_walkforward_2026-08-19.csv`

## Referencias

[1] [Moskowitz, Ooi and Pedersen — Time Series Momentum](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf).

[2] [Technical Trading Rule Profitability in Currencies: It's All About Momentum](https://www.sciencedirect.com/science/article/pii/S0275531922001659).

[3] [Testing a Price Breakout Strategy Using Donchian Channels](https://open.uct.ac.za/handle/11427/21754).
