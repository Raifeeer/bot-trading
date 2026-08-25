#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path('/home/ubuntu/backtests')
CATALOG = ROOT / 'polaris_backtest_catalog_summary_2026-08-25.json'
OUT = ROOT / 'polaris_strategy_readiness_2026-08-25.md'


def read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def num(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(df[name], errors='coerce') if name in df else pd.Series(index=df.index, dtype=float)


def classify(path: Path, df: pd.DataFrame) -> dict:
    returns = num(df, 'return_pct')
    if returns.isna().all():
        returns = num(df, 'retorno_pct')
    dd = num(df, 'max_drawdown_pct')
    trades = num(df, 'closed_trades')
    if trades.isna().all():
        trades = num(df, 'trades')
    gaps = num(df, 'data_gaps')
    pf = num(df, 'profit_factor')
    valid = returns.notna()
    missing_metrics = []
    for name, series in (
        ('max_drawdown_pct', dd),
        ('closed_trades/trades', trades),
        ('data_gaps', gaps),
        ('profit_factor', pf),
    ):
        if series.empty or series.isna().all():
            missing_metrics.append(name)
    robust = valid & (returns > 0)
    if not missing_metrics:
        robust &= gaps.fillna(0).eq(0)
        robust &= trades.fillna(0).ge(20)
        robust &= dd.ge(-10)
        robust &= pf.fillna(0).ge(1.10)
    if valid.any():
        positive_share = float((returns[valid] > 0).mean() * 100)
        median_return = float(returns[valid].median())
    else:
        positive_share = None
        median_return = None
    robust_count = int(robust.sum()) if not missing_metrics else 0
    window_text = ' '.join(df['window'].astype(str).str.lower().tolist()) if 'window' in df else ''
    has_oos_marker = any(token in window_text for token in ('oos', 'out_of_sample', 'test'))
    decision = 'RESEARCH_ONLY'
    reason = 'No cumple simultáneamente retorno positivo, gaps=0, muestra, drawdown y PF mínimos.'
    if missing_metrics:
        decision = 'INSUFFICIENT_EVIDENCE'
        reason = 'Faltan métricas obligatorias: ' + ', '.join(missing_metrics) + '.'
    elif has_oos_marker and robust_count >= 20 and robust_count / max(1, len(df)) >= 0.50:
        decision = 'PROMOTION_CANDIDATE_PENDING_OOS'
        reason = 'Una ventana marcada OOS y al menos 20 filas/50% del archivo superan filtros mecánicos; aún exige verificación de purging/embargo y fills point-in-time.'
    elif robust_count >= 20 and robust_count / max(1, len(df)) >= 0.50:
        reason = 'Supera filtros mecánicos, pero no contiene una etiqueta OOS verificable; queda en investigación.'
    elif robust_count > 0:
        reason = 'Solo una fracción pequeña del archivo supera filtros mecánicos; no es evidencia de robustez.'
    if not gaps.isna().all() and gaps.fillna(0).sum() > 0:
        reason += ' Presenta gaps de datos.'
    if dd.isna().all():
        reason += ' No reporta drawdown comparable.'
    if trades.isna().all() or trades.fillna(0).max() < 20:
        reason += ' La muestra de trades es insuficiente o no está disponible.'
    return {
        'file': path.name,
        'rows': int(len(df)),
        'median_return_pct': median_return,
        'positive_share_pct': positive_share,
        'robust_rows': robust_count,
        'worst_drawdown_pct': float(dd.min()) if dd.notna().any() else None,
        'total_gaps': float(gaps.sum()) if gaps.notna().any() else None,
        'max_trades': float(trades.max()) if trades.notna().any() else None,
        'has_oos_marker': has_oos_marker,
        'decision': decision,
        'reason': reason,
    }


def main() -> None:
    catalog = json.loads(CATALOG.read_text())
    records = []
    for item in catalog['records']:
        path = Path(item['file'])
        if not path.exists():
            continue
        try:
            df = read(path)
        except Exception:
            continue
        if not any(c in df.columns for c in ('return_pct', 'retorno_pct')):
            continue
        records.append(classify(path, df))
    records.sort(key=lambda x: (x['robust_rows'] == 0, -(x['robust_rows']), -(x['median_return_pct'] or -10**9)))
    candidates = [r for r in records if r['decision'] == 'PROMOTION_CANDIDATE_PENDING_OOS']
    lines = [
        '# Polaris — readiness de estrategias',
        '',
        '> Corte: 2026-08-25. Se analizaron archivos históricos locales disponibles, con ventanas que llegan como máximo a 2026-08-19 y datos de mercado que en varios casos terminan el 2026-08-07. El informe es exploratorio y no prueba rentabilidad futura.',
        '',
        '## Decisión ejecutiva',
        '',
        'No se promueve ninguna estrategia a ejecución automática. Los retornos positivos aislados no superan todavía los requisitos de datos point-in-time, purging/embargo, costes y slippage, walk-forward no solapado, muestra suficiente y prueba de lifecycle del broker. El bot permanece en PAPER contenido con `risk.halt_new_entries=true`.',
        '',
        '| Resultado | Cantidad |',
        '|---|---:|',
        f'| Archivos evaluables | {len(records)} |',
        f'| Candidatos mecánicos pendientes de OOS | {len(candidates)} |',
        f'| Decisiones `PROMOTION_CANDIDATE_PENDING_OOS` | {len(candidates)} |',
        f"| Evidencia insuficiente | {sum(r['decision'] == 'INSUFFICIENT_EVIDENCE' for r in records)} |",
        f"| Decisiones `RESEARCH_ONLY` | {sum(r['decision'] == 'RESEARCH_ONLY' for r in records)} |",
        '',
        '## Lectura de los resultados',
        '',
        'El catálogo muestra que algunas familias parecen atractivas en determinadas tablas, pero sus controles son insuficientes para autorizar operaciones. `relative_strength` presenta retornos altos en ciertas filas, pero también drawdowns muy elevados; `defined_risk` y algunas variantes de `volume_profile` contienen gaps o no reportan una medición comparable de drawdown; `wheel` tiene limitaciones de capital, asignación y muestra que impiden compararla directamente con spreads de riesgo definido. Estas observaciones sirven para priorizar investigación, no para elegir una configuración live.',
        '',
        '| Archivo | Filas | Mediana retorno % | % positivas | Filas robustas mecánicas | OOS marcado | Peor DD % | Gaps | Máx. trades | Decisión |',
        '|---|---:|---:|---:|---:|---|---:|---:|---:|---|',
    ]
    for r in records:
        def f(k):
            v = r[k]
            return 'NA' if v is None else f'{v:.2f}'
        lines.append(f"| `{r['file']}` | {r['rows']} | {f('median_return_pct')} | {f('positive_share_pct')} | {r['robust_rows']} | {'sí' if r['has_oos_marker'] else 'no'} | {f('worst_drawdown_pct')} | {f('total_gaps')} | {f('max_trades')} | `{r['decision']}` |")
    lines += [
        '',
        '## Próxima evaluación segura',
        '',
        'La siguiente iteración debe fijar un dataset point-in-time y un baseline único, separar entrenamiento, purging/embargo y test final, aplicar costes y slippage pesimistas, y medir P&L por operación, drawdown, profit factor, exposición, concentración y sensibilidad. Después se hará un A/B en shadow con el mismo universo y las mismas barras, sin permitir que la señal candidata envíe órdenes. Solo una mejora repetida fuera de muestra podría pasar a `PROMOTION_CANDIDATE`; no existe todavía una base para prometer rentabilidad.',
        '',
        '## Referencias internas',
        '',
        '- `polaris_backtest_catalog_summary_2026-08-25.json` — resumen reproducible del catálogo.',
        '- `AGENTS.md` — reglas operativas, guardarraíles y estado de producción.',
        '- `docs/canary_post_execution_checklist.md` — procedimiento de verificación de broker, ledger y rollback.',
    ]
    OUT.write_text('\n'.join(lines) + '\n')
    print(json.dumps({
        'files_evaluated': len(records),
        'mechanical_candidates': len(candidates),
        'report': str(OUT),
        'top_candidates': [r['file'] for r in candidates[:10]],
    }, indent=2))


if __name__ == '__main__':
    main()
