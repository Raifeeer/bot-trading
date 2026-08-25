# Checklist post-canary PAPER de Polaris

## Alcance

Este checklist corresponde exclusivamente a la canary autorizada del 25 de agosto de 2026: una sola compra límite de `F260828C00015000`, cantidad `1`, precio máximo `$0.02` por acción y débito máximo `$2` más comisiones. No autoriza nuevas entradas, nuevos símbolos, spreads multi-pata ni cambios en `config/config.yaml`.

## 1. Resultado del runner

Registrar el archivo `/home/ubuntu/backtests/canary-20260825-f260828c00015000.json` y clasificar el resultado en uno de estos estados:

| Estado | Acción inmediata |
|---|---|
| `aborted_market_closed` | No hacer nada; esperar una nueva autorización y una nueva ventana de mercado |
| `entry_not_filled` | Confirmar orden terminal y ausencia de posición; mantener contención |
| `completed` | Continuar con reconciliación final; mantener contención |
| `entry_partial_needs_review` | No vender ni comprar automáticamente; revisar la posición y sus fills manualmente |
| Cualquier estado `needs_review` | No reintentar; preservar la posición y el ledger para revisión |

## 2. Alpaca PAPER

Ejecutar el diagnóstico de solo lectura y guardar su salida en un archivo fechado:

```bash
python3 /home/ubuntu/scripts/diagnose_polaris_live_orders.py
```

Confirmar `status=ACTIVE`, modo PAPER, ninguna orden abierta y, si el runner terminó como `completed` o `entry_not_filled`, cero posiciones. Si queda una posición o una orden, no modificarla con un segundo script: identificar el ID, guardar el estado y detener la automatización.

## 3. Ledger y Firestore

Comprobar que el documento de `polaris` refleja el evento, que `polaris_canary_runs/canary-20260825-f260828c00015000` tiene una transición coherente y que `polaris_exit_ledger` contiene como máximo un intent para esa posición. El intent solo puede ser `completed` si Alpaca confirma la ausencia de la posición y la actualización Firestore fue aceptada.

Ante una respuesta HTTP 409, 412, 5xx, timeout o un documento con versión inesperada, clasificar como `needs_review`, no reintentar y activar rollback/inspección manual según corresponda.

## 4. Cloud Run y logs

Confirmar que la revisión `polaris-bot-cbdc186` conserva el 100% del tráfico y que la configuración sigue con `paper=true`, `halt_new_entries=true`, `minScale=1`, `maxScale=1` y CPU always-on. Revisar los logs del intervalo de la canary y del ciclo posterior:

```bash
FILTER='resource.type="cloud_run_revision" AND resource.labels.service_name="polaris-bot" AND resource.labels.revision_name="polaris-bot-cbdc186"'
/home/ubuntu/tools/google-cloud-sdk/bin/gcloud logging read "$FILTER" \
  --project=gen-lang-client-0746441136 --freshness=30m --limit=600 \
  --order=asc --format='value(timestamp,severity,textPayload)'
```

Buscar `Traceback`, `CRITICAL`, `ERROR`, `permission denied`, `partial_submission`, `needs_review`, `open_broker_orders`, `broker_reconciliation_halt` y cualquier ID de orden. Una orden que no pertenezca a los dos `client_order_id` de la canary exige detenerse y hacer rollback.

## 5. Criterios de aceptación

La canary se considera técnicamente aceptable únicamente si se cumplen simultáneamente estas condiciones: el máximo de una compra y una venta se respetó; ambas órdenes tienen IDs registrados; la posición final es cero; no quedan órdenes abiertas; el ledger dedicado termina en `completed`; Firestore y Alpaca coinciden; el bot completa ciclos sin traceback; y `new_entries_halted=true` continúa vigente.

La aceptación técnica no constituye evidencia de rentabilidad. El resultado económico debe registrarse como P&L realizado, comisiones y slippage observados, sin extrapolarlo a futuras operaciones.

## 6. Criterios de bloqueo y rollback

Hacer rollback al 100% hacia `polaris-bot-secretmigrate3` o, si fuera necesario, `polaris-bot-guarddddcda7` ante cualquier orden inesperada, posición residual no explicada, fill parcial, divergencia broker/Firestore, fallo de persistencia, traceback o error de permisos. No crear otra posición para investigar.

Aunque la canary sea técnicamente correcta, mantener las entradas generales bloqueadas. No promover estrategias, no activar `setup_confluence`, `vix_shadow`, `structure_mtf_shadow` ni `defined_risk_shadow`, y no ejecutar spreads hasta completar las pruebas de concurrencia y fallos de Firestore con mocks y una revisión humana posterior.

## 7. Documentación

Actualizar `AGENTS.md` y `docs/skills/estado_operativo_skill.md` con la hora UTC, IDs de órdenes, estados terminales, precio de fill, precio de salida, slippage, P&L, estado final del ledger y cualquier warning. No incluir tokens, claves, respuestas completas de Secret Manager ni datos sensibles.
