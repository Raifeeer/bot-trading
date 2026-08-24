# Diseño del ledger dedicado de salidas de Polaris

## Objetivo

Evitar que un reinicio, una instancia concurrente o un fallo de Firestore convierta una salida multi-pata ya iniciada en un nuevo envío. Alpaca sigue siendo la autoridad de posiciones y órdenes; Firestore guarda la intención, los identificadores y la transición operativa.

## Colección

`polaris_exit_ledger/{ledger_id}` en la base Firestore Native `polaris`. `ledger_id` es un hash determinista de `position_key` y `entry_ts`, de modo que la misma posición reclama siempre el mismo documento, mientras que una posición nueva con la misma estructura obtiene una generación distinta.

## Campos mínimos

| Campo | Uso |
|---|---|
| `ledger_id` | Identidad estable del intento |
| `position_key` | Clave compatible con el estado local |
| `entry_ts` | Generación de la posición |
| `status` | `submitting`, `submitted`, `partial_submission`, `needs_review`, `completed` |
| `active` | Consulta rápida de intents no terminales |
| `order_ids` | IDs reales de Alpaca, nunca símbolos inventados |
| `close_orders` | Resumen normalizado de las patas enviadas |
| `position`, `specs` | Contexto necesario para reconciliar sin reabrir |
| `version` | Control monotónico de actualización |
| `created_at`, `updated_at` | Auditoría temporal |
| `reason`, `signal_type`, `last_error` | Explicación operativa sin secretos |

## Reglas

1. Antes de enviar la primera pata se crea el documento con `create()`. Si ya existe, no se envía nada y el estado queda bloqueado para revisión/reconciliación.
2. Cada pata enviada actualiza el mismo documento con su ID. Si esa actualización falla después de un envío, el sistema marca la salida como revisión manual y no reintenta.
3. En cada arranque se leen los documentos `active=true`, se fusionan con el estado local sin sobrescribir una versión local más nueva y se consultan de nuevo las órdenes abiertas de Alpaca.
4. Una salida solo pasa a `completed` después de que Alpaca confirme que todas las patas desaparecieron. Si Firestore falla al marcar `completed`, la posición y el intent permanecen en estado bloqueado; no se elimina estado local.
5. Una respuesta vacía de `order_statuses()` o una combinación `FILLED` + `OPEN/REJECTED` es `needs_review`; nunca se reenvía automáticamente.
6. `risk.halt_new_entries`, RiskManager, floor, circuit breakers y validación de cotizaciones continúan siendo autoridades superiores.

## Riesgo residual

La operación `create()` evita la doble reclamación del mismo intento, pero la API de Firestore y el broker siguen siendo sistemas externos. Por eso se necesitan timeouts, pruebas de caída, idempotencia por ID, una sola instancia Cloud Run y observabilidad de cada transición. Ninguna prueba de persistencia autoriza entradas nuevas ni convierte PAPER en REAL.
