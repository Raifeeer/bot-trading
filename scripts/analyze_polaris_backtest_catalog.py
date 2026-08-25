#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path('/home/ubuntu/backtests')
PATTERNS = [
    '*_backtests_*.csv',
    '*_backtest_*.csv',
    '*_results.csv',
    '*_comparison.csv',
    '*_summary.csv',
    '*_variant_summary.csv',
    '*_robust_candidates.csv',
]
EXCLUDE = {'bt_resumen.csv'}


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(dtype='float64')
    return pd.to_numeric(frame[column], errors='coerce').dropna()


def summarize(path: Path) -> dict | None:
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    returns = numeric(frame, 'return_pct')
    if returns.empty:
        returns = numeric(frame, 'retorno_pct')
    drawdowns = numeric(frame, 'max_drawdown_pct')
    trades = numeric(frame, 'closed_trades')
    if trades.empty:
        trades = numeric(frame, 'trades')
    gaps = numeric(frame, 'data_gaps')
    pf = numeric(frame, 'profit_factor')
    positive = (returns > 0).mean() * 100 if not returns.empty else None
    return {
        'file': str(path),
        'rows': int(len(frame)),
        'columns': list(frame.columns),
        'return_median_pct': float(returns.median()) if not returns.empty else None,
        'return_max_pct': float(returns.max()) if not returns.empty else None,
        'return_min_pct': float(returns.min()) if not returns.empty else None,
        'positive_row_share_pct': float(positive) if positive is not None else None,
        'drawdown_median_pct': float(drawdowns.median()) if not drawdowns.empty else None,
        'drawdown_worst_pct': float(drawdowns.min()) if not drawdowns.empty else None,
        'trades_median': float(trades.median()) if not trades.empty else None,
        'trades_max': float(trades.max()) if not trades.empty else None,
        'data_gaps_total': float(gaps.sum()) if not gaps.empty else None,
        'profit_factor_median': float(pf.median()) if not pf.empty else None,
        'has_window': 'window' in frame.columns,
        'has_variant': any(c in frame.columns for c in ('variant', 'strategy', 'structure', 'setup', 'family')),
    }


def main() -> None:
    paths = set()
    for pattern in PATTERNS:
        paths.update(ROOT.glob(pattern))
    records = []
    for path in sorted(paths):
        if path.name in EXCLUDE:
            continue
        item = summarize(path)
        if item:
            records.append(item)
    records.sort(key=lambda item: (
        item['positive_row_share_pct'] is None,
        -(item['positive_row_share_pct'] or 0),
        -(item['return_median_pct'] or -10**9),
    ))
    out_json = ROOT / 'polaris_backtest_catalog_summary_2026-08-25.json'
    out_json.write_text(json.dumps({
        'as_of': '2026-08-25',
        'source_directory': str(ROOT),
        'selection_note': 'Exploratory file-level summaries; not a promotion decision.',
        'records': records,
    }, indent=2))
    out_md = ROOT / 'polaris_backtest_catalog_summary_2026-08-25.md'
    lines = [
        '# Polaris — catálogo de backtests (resumen exploratorio)',
        '',
        '> Corte del análisis: 2026-08-25. Los archivos disponibles llegan a distintas fechas; no se extrapola a la sesión actual. Este resumen no es una decisión de promoción ni una garantía de rentabilidad.',
        '',
        '| Archivo | Filas | Mediana retorno % | Máx. retorno % | % filas positivas | Mediana DD % | Peor DD % | Mediana trades | Gaps | PF mediano |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for r in records:
        def f(key):
            value = r.get(key)
            return 'NA' if value is None else f'{value:.2f}'
        lines.append(
            f"| `{Path(r['file']).name}` | {r['rows']} | {f('return_median_pct')} | {f('return_max_pct')} | {f('positive_row_share_pct')} | {f('drawdown_median_pct')} | {f('drawdown_worst_pct')} | {f('trades_median')} | {f('data_gaps_total')} | {f('profit_factor_median')} |"
        )
    out_md.write_text('\n'.join(lines) + '\n')
    print(json.dumps({
        'records': len(records),
        'json': str(out_json),
        'markdown': str(out_md),
        'top_5': [Path(r['file']).name for r in records[:5]],
    }, indent=2))


if __name__ == '__main__':
    main()
