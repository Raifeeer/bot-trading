# Auditoría conjunta de capas shadow en PAPER — 2026-08-19

## Resumen ejecutivo

La revisión activa de Polaris es `polaris-bot-br5520c4f3` con **100% del tráfico**, `minScale=1`, `maxScale=1`, CPU always-on y endpoint Alpaca PAPER. El snapshot real de Firestore `polaris/2026-08-19` fue actualizado a `2026-08-19T20:46:46.673843+00:00`, con equity `$99,288.27`, cero posiciones y cero órdenes ejecutadas.

Las tres capas de señales intradía auditadas —breakdown bearish, trend pullback y Breakout20/55— no tienen cobertura independiente en el ciclo observado. Entre las ocho símbolos, cada uno apareció confirmado en exactamente dos de las tres capas y ninguno en las tres. Esto revela **solapamiento total de oportunidad**, no tres fuentes independientes de alpha. Las capas deben seguir siendo observacionales; no hay base para activar filtros o combinar sus confirmaciones.

## Estado operativo observado

| Control | Evidencia |
|---|---|
| Revisión | `polaris-bot-br5520c4f3` |
| Tráfico | 100% |
| Broker | Alpaca PAPER |
| Equity | `$99,288.27` |
| Posiciones | 0 |
| Órdenes ejecutadas | 0 |
| Snapshot Firestore | `polaris/2026-08-19`, actualizado 20:46:46 UTC |
| Ciclos auditados en logs | 24 `Tick OK`, 24 `CYCLE TIMING` |
| Tracebacks | 0 |
| `Error en el loop` | 0 |
| Errores de capas shadow | 0 |

Las estrategias live reportaron `scanned=0` y razón `same_bar_context` para los ocho símbolos en el ciclo representativo. La deduplicación evita revaluar una señal sobre la misma barra y no es una orden fallida. Las capas shadow no fueron la causa de cero operaciones.

## Conteo real por capa

| Capa | Confirmadas | Sin setup | Datos faltantes | Errores | `mode` | `influence_entries` | `orders_allowed` |
|---|---:|---:|---:|---:|---|---|---|
| Bearish breakdown/retest | 5 | 3 | 0 | 0 | shadow | false | false |
| Trend pullback EMA/VWAP | 4 | 4 | 0 | 0 | shadow | false | false |
| Breakout20/55 | 7 | 1 | 0 | 0 | shadow | false | false |
| Estructura MTF | 1 bull / 2 bear | — | 0 | 0 | shadow | false | false |
| VIX | 0 `would_block` | — | fallback real | 0 | shadow | false | false |

El gate bull de Breakout20/55 tuvo `gate_allowed=0` en el snapshot porque el régimen vigente no era bull. Sus siete confirmaciones son observaciones técnicas, no entradas permitidas.

## Solapamiento por símbolo

| Símbolo | Bearish | Trend pullback | Breakout20/55 | Estructura MTF |
|---|---|---|---|---|
| AMD | confirmada | no setup | confirmada | neutral |
| BB | confirmada | confirmada | no setup | bear |
| F | confirmada | no setup | confirmada | bull |
| NOK | no setup | confirmada | confirmada | mixed |
| PLTR | no setup | confirmada | confirmada | mixed |
| SOFI | confirmada | no setup | confirmada | neutral |
| TQQQ | no setup | confirmada | confirmada | bear |
| TSLA | confirmada | no setup | confirmada | neutral |

| Intersección | Símbolos | Tamaño |
|---|---|---:|
| Bearish ∩ Trend pullback | BB | 1 |
| Bearish ∩ Breakout20/55 | AMD, F, SOFI, TSLA | 4 |
| Trend pullback ∩ Breakout20/55 | NOK, PLTR, TQQQ | 3 |
| Triple intersección | Ninguna | 0 |
| Unión de confirmadas | AMD, BB, F, NOK, PLTR, SOFI, TQQQ, TSLA | 8 |

La suma de confirmaciones por capa es 16 y la unión es 8: cada símbolo confirmado pertenece a dos capas. Por tanto, en este snapshot no existe una señal confirmada única de alguna de las tres capas. El siguiente experimento correcto no es activar confluencia, sino medir la estabilidad temporal del solapamiento y comparar la calidad marginal de cada capa por régimen.

## Otras capas shadow

`setup_confluence` mostró una confirmación en `break_and_retest` y dos en `bos`, pero sus subcomponentes son observaciones contextuales y no deben sumarse directamente a las señales de los tres motores. `defined_risk_shadow` tuvo cinco candidatos bear-call disponibles, tres no disponibles y cero errores; bull-put e iron-condor no encontraron estructuras líquidas. VIX estaba disponible mediante fallback real a yfinance, con `would_block=0` en sus tres variantes.

## Errores y ruido operativo

| Evento | Conteo en logs auditados | Clasificación |
|---|---:|---|
| Traceback | 0 | Sin fallo de código observado |
| Error en el loop | 0 | Sin fallo de ciclo |
| Error shadow con count positivo | 0 | Sin fallo de capa |
| Telegram HTTP 409/Conflict | 2 | Ruido por pollers superpuestos durante revisiones |
| VIX `invalid symbol` en Alpaca | 2 | Esperado; fallback real a yfinance |
| Warnings de feed/API | 82 | Ruido conocido de yfinance/plan Alpaca; no produjo error de ciclo |

El warning de VIX confirma una limitación de proveedor: Alpaca no acepta `^VIX`, por lo que el cálculo usa fallback de yfinance. No se imputaron datos ni se convirtió el warning en señal.

## Auditoría de seguridad del contrato

La revisión de código encontró que bearish, trend pullback, Breakout20/55 y estructura MTF ya forzaban `mode=shadow`, `influence_entries=false` y `orders_allowed=false`. Se endurecieron adicionalmente los wrappers de `setup_confluence`, VIX y defined-risk para que también sobrescriban configuraciones peligrosas y expongan las banderas false incluso cuando están disabled. Se añadieron regresiones en `tests/test_shadow_contracts.py`.

La suite focalizada del endurecimiento terminó con 16 tests pasados. La suite completa terminó con 173 tests pasados, 1 omitido y 2 expected failures heredados; Ruff F/B/E9 y compilación pasaron. Las 22 advertencias son conocidas, principalmente `datetime.utcnow()` y el `SystemExit` intencional del test de watchdog.

El parche de seguridad aún debe versionarse y desplegarse como una revisión separada, inicialmente sin tráfico; después de verificar readiness y dos ciclos se podrá mover el 100% del tráfico PAPER. No se debe usar `set-env-vars` o `set-secrets` aislado.

## Decisión y siguientes pasos

No activar ninguna capa auxiliar como filtro ni combinar confirmaciones para abrir operaciones. El resultado actual demuestra redundancia de señales, no confluencia predictiva. Priorizar una auditoría temporal con snapshots diarios de Firestore durante varias sesiones: calcular tasas de confirmación por régimen, intersección por símbolo y P&L teórico marginal con un ledger común, sin modificar el bot live.

El modo operativo sigue siendo PAPER y la cuenta no constituye una recomendación de inversión. Los resultados son investigación experimental, sujetos a costes, disponibilidad de datos y riesgo de sobreajuste.

## Artefactos

- `backtests/shadow_audit_service_spec_2026-08-19.yaml`
- `backtests/shadow_audit_logs_2026-08-19.txt`
- `backtests/shadow_audit_firestore_2026-08-19.txt`
- `backtests/shadow_audit_snapshot_analysis_2026-08-19.txt`
- `backtests/shadow_audit_bot_contracts_2026-08-19.txt`
- `docs/shadow_layers_audit_2026-08-19.md`
