# VIX shadow en producción — 18 de agosto de 2026

## Estado final

La revisión activa de Cloud Run es `polaris-bot-vixshadow3`, basada en el commit `379dc84`, con 100% del tráfico y CPU always-on (`cpu-throttling=false`). La revisión anterior saludable `polaris-bot-00086-n4n` quedó disponible como rollback. Las revisiones `00087`, `vixshadow` y `vixshadow2` no se dejaron activas por timeout de conexión inicial a Alpaca; no llegaron a ejecutar ciclos.

La revisión `vixshadow3` conectó correctamente a Alpaca PAPER y completó ciclos. El arranque registró:

- `vix shadow enabled=True mode=shadow influence_entries=False orders_allowed=False`.
- `Alpaca conectado: status=AccountStatus.ACTIVE, equity=99288.27`.
- `Bot iniciado: 3 estrategias, 8 tickers, poll=60s`.

## Evidencia de ciclos

Se observaron ciclos consecutivos entre 19:50 y 20:04 UTC. Cada ciclo terminó con `Tick OK`, escribió Firestore y mantuvo cero órdenes y cero posiciones. El primer ciclo incluyó la descarga inicial; los siguientes tuvieron tiempos VIX de aproximadamente 0.006–0.009 s.

`CYCLE TIMING` confirmó el nuevo campo `vix_shadow`, por ejemplo: `vix_shadow=0.007s`. Firestore confirmó múltiples escrituras con `trading_mode=PAPER`.

## Snapshot VIX verificado

Firestore contiene `vix_shadow_observations` con:

| Campo | Valor |
|---|---|
| `mode` | `shadow` |
| `influence_entries` | `false` |
| `orders_allowed` | `false` |
| `available` | `true` |
| Alineación | último cierre estrictamente anterior a la fecha de mercado |
| Fecha de operación observada | 2026-08-18 |
| Fecha del cierre VIX usado | 2026-08-17 |
| Variantes | `shock_10`, `percentile_70`, `level_25` |
| Resultado observado | ninguna variante habría bloqueado (`would_block=false`) |
| Símbolos observados | 8 |
| Órdenes | 0 |
| Posiciones | 0 |

La consulta del símbolo `^VIX` intentó primero Alpaca y recibió `invalid symbol`, tras lo cual el feed utilizó su fallback real de yfinance. El snapshot se marcó como disponible y no se rellenaron datos artificialmente.

## Decisión

VIX queda conectado como **observabilidad shadow**. No bloquea entradas, no cambia sizing, no cierra posiciones, no modifica el RiskManager y no tiene acceso al executor. Para promoverlo a filtro PAPER se necesitarían más observaciones shadow, una segunda validación walk-forward y revisión humana explícita.

**Estado operativo:** `HEALTHY_NO_SIGNAL`/`HEALTHY_BLOCKED` según el ciclo; el bot está vivo, pero las entradas siguen bloqueadas por el piso de equity y las puertas actuales. Este documento es evidencia operativa, no una afirmación de rentabilidad.
