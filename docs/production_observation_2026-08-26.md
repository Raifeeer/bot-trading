# Ventana de observación PAPER — 26 de agosto de 2026

## Alcance

Se observó en modo solo lectura la revisión `polaris-bot-00118-d45` desde el 2026-08-26 15:41:25 UTC hasta el menos 2026-08-26 15:53:21 UTC, sin modificar Cloud Run, Firestore, Secret Manager, configuración de riesgo ni Alpaca. La revisión recibió 100% del tráfico y el bot permaneció en PAPER con `risk.halt_new_entries=true`.

## Resultado de salud

| Señal | Resultado observado |
|---|---:|
| `Tick OK` | 12 |
| `CYCLE TIMING` | 12 |
| Escrituras Firestore | 12 |
| Señales publicadas | 12 |
| `approved=0` | 12/12 |
| `orders=0` | 12/12 |
| `new_entries_halted=True` | 12/12 |
| `open_broker_orders=0` | 12/12 |
| `unmanaged_broker_legs=0` | 12/12 |
| `unmanaged_state_positions=0` | 12/12 |
| `Traceback` | 0 |
| `CRITICAL` | 0 |
| Telegram `409 Conflict` | 0 |
| Envíos MLeg | 0 |
| Equity observada | `$96,914.08` |
| Posiciones observadas | 0 |

Los ciclos observados duraron aproximadamente entre 1,441 s y 2,602 s después del ciclo inicial, con poll de 60 s. Las señales se bloquearon por el halt global y, según el ciclo, por `same_bar_context` o `not_tradable`; no hubo intento de aprobación ni de envío.

## Riesgo residual

La ventana no mostró fallos del lifecycle MLeg, pérdida de ledgers, divergencias con el broker, errores de Firestore ni conflictos de Telegram. Sí permanecen warnings conocidos de disponibilidad del feed: consultas recientes SIP rechazadas por la suscripción y el símbolo `^VIX` inválido. No provocaron órdenes ni caída del loop en esta ventana, pero deben conservarse como riesgo de calidad de datos. La observación por sí sola no convierte la revisión en `PROMOTION_CANDIDATE` ni autoriza una canary.

## Decisión

```text
observation_status: HEALTHY_BLOCKED_WITH_FEED_WARNINGS
orders_allowed: false
production_config_changed: false
next_action: do_not_run_canary_until_explicit_parameters_and_authorization
```

El punto 3 queda cumplido como observación operativa estable bajo contención. Antes de pasar al punto 4 se requiere resolver o aceptar explícitamente el riesgo de feed, mantener la compuerta OOS reconocida como `EOD_PRELIMINARY`, definir una canary PAPER nueva con contrato, cantidad, límite, pérdida máxima y cierre, y recibir confirmación específica. La canary anterior no se reutiliza.

> Esta observación es técnica y corresponde a un entorno PAPER; no demuestra rentabilidad ni garantiza que una estrategia futura sea segura o rentable.
