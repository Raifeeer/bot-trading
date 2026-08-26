# Matriz de pruebas del lifecycle MLeg — 26 de agosto de 2026

## Objetivo

Validar que una estructura de opciones de 2 a 4 patas se trate como una sola orden combinada, conserve identidad idempotente y quede bloqueada ante cualquier respuesta parcial, ambigua o no persistida. La matriz es complementaria a las pruebas dirigidas; no sustituye una prueba PAPER explícitamente autorizada.

## Factores y restricciones

| Factor | Valores cubiertos | Restricciones |
|---|---|---|
| Clase | MLeg / simple heredada | Los spreads usan MLeg; las órdenes simples no se convierten automáticamente |
| Patas | 2 / 3 / 4 / 1 | 1 pata se rechaza para `submit_spread`; 2–4 son válidas |
| Tipo | limit / market / stop / desconocido | MLeg solo permite limit o market; stop y desconocido se rechazan |
| Precio | neto positivo / neto negativo / cero / faltante / no finito | Limit requiere precio válido; el precio neto mantiene signo débito/crédito |
| Cantidad | 1 / múltiplos / ratio desigual / cero / fraccionaria | `qty` entero positivo; ratios simplificadas; cantidad cero/fraccionaria se rechaza |
| Intent | BTO/STO / BTC/STC / inválido | Se deriva de side y closing, y se valida contra allowlist |
| Broker | 404 lookup / existente abierta / filled / rejected / timeout / payload malformado | Solo 404 permite crear; todo lo demás reutiliza, revisa o bloquea |
| Persistencia | claim OK / claim duplicado / claim fallido / update CAS OK / update fallido | Nunca se envía sin claim; fallo posterior al envío mantiene revisión |
| Momento | antes del envío / respuesta aceptada / fill parcial / reinicio | No hay reintento automático; broker y ledger se reconcilian antes de desbloquear |
| Entorno | dry-run / PAPER | No se permite REAL; dry-run no toca el ledger externo |

## Casos pairwise dirigidos

| ID | Combinación | Resultado esperado | Capa | Riesgo |
|---|---|---|---|---|
| P01 | 2 patas + limit + 1 contrato + lookup 404 | Una petición MLeg, `qty=1`, ratios 1:1 | Contrato SDK | Alto |
| P02 | 2 patas + limit + 2 contratos | Una petición MLeg, padre `qty=2`, ratios 1:1 | Contrato SDK | Alto |
| P03 | 2 patas + limit + precio neto negativo | Se conserva el crédito con signo negativo | Precio | Alto |
| P04 | 3/4 patas + limit | Una sola petición con todas las patas | Contrato SDK | Alto |
| P05 | Ratio desigual | Padre usa GCD y conserva `ratio_qty` | Validación | Alto |
| P06 | Client ID ya existente en estado abierto | Se reutiliza; cero nuevos submits | Idempotencia | Crítico |
| P07 | Client ID ya existente en estado terminal fallido | Se rechaza; no se reenvía | Idempotencia | Crítico |
| P08 | Timeout/error al verificar client ID | Se rechaza fail-closed | Red | Crítico |
| P09 | Error de submit después de posible aceptación | Estado `submission_unknown`; sin reintento | Broker | Crítico |
| P10 | Claim Firestore fallido | No se envía ninguna orden | Persistencia | Crítico |
| P11 | Update Firestore falla después de submit | Se conserva revisión y halt | Persistencia | Crítico |
| P12 | Orden padre abierta con `symbol` vacío | Se detecta por `symbols`/patas anidadas | Reconciliación | Crítico |
| P13 | Padre `partially_filled` | No se declara cierre completo | Fill | Crítico |
| P14 | Padre `filled` pero posiciones aún no coinciden | Se espera snapshot broker; no se libera por sí solo | Fill/reconciliación | Crítico |
| P15 | Posición con símbolos correctos pero polaridad/cantidad incorrecta | No se marca entry como filled | Reconciliación | Crítico |
| P16 | Payload `dict` en open orders | Error y bloqueo, nunca se interpreta como lista vacía | Entrada | Crítico |
| P17 | Reinicio con entry ledger activo | Se restaura identidad y se bloquea hasta reconciliar | Recuperación | Crítico |
| P18 | Reinicio con exit ledger existente | Se conserva `order_ids` del primer reclamante | Concurrencia | Crítico |
| P19 | `time_in_force=gtc` | Se rechaza antes de tocar el broker | Broker | Alto |
| P20 | dry-run | Construye request local sin Firestore ni broker | Entorno | Medio |

## Cobertura ejecutada

Las pruebas offline ejecutadas cubren P01, P02, P03, P05, P06, P07, P10, P12, P15, P16, P19 y P20 directamente, además de las regresiones de reconciliación de posiciones y ledger. La suite completa debe permanecer obligatoria antes de un build.

## Riesgo residual

No se considera validado el comportamiento externo de Alpaca hasta realizar una canary PAPER nueva y explícitamente autorizada. Esa canary debe ser una estructura MLeg pequeña, con contrato, precio límite, pérdida máxima, regla de cierre y criterio de rollback definidos antes del envío. El cambio no autoriza quitar `risk.halt_new_entries`, operar REAL ni asumir rentabilidad.

## Referencias externas

1. https://docs.alpaca.markets/us/docs/options-level-3-trading — Alpaca, Options Level 3 Trading.
2. https://docs.alpaca.markets/us/reference/postorder — Alpaca, Create an Order.
3. https://docs.alpaca.markets/us/docs/options-trading-overview — Alpaca, Options Trading Overview.
