# Gamma walls y niveles de opciones — resultado de investigación y backtest-gate

**Fecha de corte:** 2026-08-18. **Estado:** `REJECT_DATA`; no se conectó a `bot.py`.

## Pregunta

¿Call walls, put walls, open-interest walls y gamma flip pueden funcionar como niveles de soporte/resistencia o filtro de DayBreakout/SwingTrend en Polaris?

## Investigación

Se creó y validó `/home/ubuntu/skills/gamma-walls/SKILL.md`, con referencia en `references/research.md`. OCC y OIC distinguen open interest de volumen: OI es el acumulado de contratos abiertos, calculado a partir de transacciones de apertura/cierre y ajustado por ejercicio/asignación.[1] [2] OI no dice quién está largo o corto ni si el dealer está short gamma. Un GEX proxy requiere OI, gamma, spot, multiplicador y una hipótesis de signo.

La literatura de Pearson, Poteshman y White encuentra una relación entre posiciones de inversores que probablemente cubren y volatilidad del subyacente, pero no demuestra que un strike con OI alto sea un soporte o resistencia negociable.[3] La fuente educativa de SpotGamma define call wall y put wall como términos de posicionamiento, pero no convierte su metodología comercial en un dato histórico público verificable.

## Cobertura histórica real

Se inspeccionaron los dos caches de opciones históricos disponibles en la sandbox:

| Cache | Filas | Columnas disponibles | Resultado |
|---|---:|---|---|
| Defined-risk options | 73,119 | OHLCV, trade_count, vwap | `REJECT_DATA` |
| Wheel options | 9,799 | OHLCV, trade_count, vwap | `REJECT_DATA` |

Ninguno contiene `open_interest`, `gamma`, `spot` ni `multiplier`. Los contratos seleccionados conservan symbol, underlying, type, strike, expiration y uso en una estructura, pero no snapshots históricos diarios de OI ni gamma.

## Backtest-gate ejecutado

Se evaluaron cinco variantes conceptuales: `oi_only`, `gex_proxy`, `gamma_flip`, `call_wall_filter` y `put_wall_filter`. El motor `scripts/run_gamma_walls_backtests.py` no inventó valores ni reemplazó faltantes por cero. Produjo `REJECT_DATA` para cada variante y cada cache, con cero trades y sin retorno/drawdown calculados.

Esto es el resultado correcto: un backtest que rellene gamma u open interest ausente con datos actuales produciría look-ahead y una falsa sensación de evidencia.

## Decisión

**No crear un backtest de rendimiento proxy y no integrar gamma walls en Polaris.** La estrategia queda documentada, pero rechazada por falta de datos point-in-time. Para volver a evaluarla se necesitaría un proveedor o archivo histórico que contenga, por fecha y símbolo, cadena completa, spot, strike, tipo, expiración, OI, IV o gamma y timestamp. Idealmente también open/close classification para reducir la hipótesis de signo dealer.

Hasta entonces, un nivel de strike observado en una cadena actual solo puede ser una observación diagnóstica presente, no una señal histórica ni evidencia de profits.

## Reproducibilidad

- Skill: `/home/ubuntu/skills/gamma-walls/SKILL.md`
- Investigación: `/home/ubuntu/skills/gamma-walls/references/research.md`
- Módulo: `strategies/gamma_walls.py`
- Tests: `tests/test_gamma_walls.py`
- Gate: `scripts/run_gamma_walls_backtests.py`
- Resultados: `/home/ubuntu/backtests/gamma_walls_backtests_2026-08-18_results.csv`
- Manifiesto: `/home/ubuntu/backtests/gamma_walls_backtests_2026-08-18_manifest.json`

**Basis:** cobertura de opciones reales, sin P&L porque faltan campos esenciales. **Time:** caches hasta 2026-08-18. **Assumptions:** ninguna imputación; solo `OK` si hay OI/gamma/spot/multiplier point-in-time. **Sources & confidence:** OCC, OIC, Cboe/availability check y literatura; confianza alta en el rechazo de datos, nula para rendimiento. **Compliance:** This is research and analysis only, not personalized financial advice.

## Referencias

[1] [OCC — Open Interest](https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/open-interest)
[2] [OIC — Open Interest: Why It Matters](https://www.optionseducation.org/news/open-interest-why-it-matters)
[3] [Pearson, Poteshman & White — Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=970592)
