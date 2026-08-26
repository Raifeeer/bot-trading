from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

base = Path('/home/ubuntu/backtests/free_eod_preliminary_2026-08-26')
results = pd.read_csv(str(base) + '_results.csv')
manifest = json.loads(Path(str(base) + '_manifest.json').read_text())

results['positive'] = results['return_pct'] > 0
results['loss'] = results['return_pct'] < 0
summary_structure = (results.groupby('structure')
    .agg(runs=('return_pct','size'), mean_return_pct=('return_pct','mean'),
         median_return_pct=('return_pct','median'), worst_return_pct=('return_pct','min'),
         best_return_pct=('return_pct','max'), positive_run_pct=('positive','mean'),
         mean_drawdown_pct=('max_drawdown_pct','mean'), worst_drawdown_pct=('max_drawdown_pct','min'),
         mean_closed_trades=('closed_trades','mean'), mean_data_gaps=('data_gaps','mean'))
    .sort_values(['mean_return_pct','median_return_pct'], ascending=False))
summary_structure['positive_run_pct'] *= 100

summary_window = (results.groupby('window')
    .agg(runs=('return_pct','size'), mean_return_pct=('return_pct','mean'),
         median_return_pct=('return_pct','median'), worst_return_pct=('return_pct','min'),
         best_return_pct=('return_pct','max'), positive_run_pct=('positive','mean'),
         mean_drawdown_pct=('max_drawdown_pct','mean'), worst_drawdown_pct=('max_drawdown_pct','min'),
         mean_closed_trades=('closed_trades','mean'), mean_data_gaps=('data_gaps','mean')))
summary_window['positive_run_pct'] *= 100

summary_management = (results.groupby('management')
    .agg(runs=('return_pct','size'), mean_return_pct=('return_pct','mean'),
         median_return_pct=('return_pct','median'), worst_return_pct=('return_pct','min'),
         positive_run_pct=('positive','mean'), mean_drawdown_pct=('max_drawdown_pct','mean'),
         mean_closed_trades=('closed_trades','mean'), mean_data_gaps=('data_gaps','mean')))
summary_management['positive_run_pct'] *= 100

# Configuration rankings are descriptive, not a promotion selection.
full_recent = results[results['window'] == 'full_recent'].copy()
full_recent_rank = full_recent.sort_values(['return_pct','max_drawdown_pct'], ascending=[False, False]).head(20)
latest_rank = results[results['window'] == 'latest_30d'].sort_values(['return_pct','max_drawdown_pct'], ascending=[False, False]).head(20)

# Aggregate every configuration by the five windows, then identify stability.
config_cols = ['structure','dte_target','width','management','regime_mode']
config_summary = (results.groupby(config_cols)
    .agg(mean_return_pct=('return_pct','mean'), median_return_pct=('return_pct','median'),
         worst_return_pct=('return_pct','min'), positive_windows=('positive','sum'),
         mean_drawdown_pct=('max_drawdown_pct','mean'), worst_drawdown_pct=('max_drawdown_pct','min'),
         total_closed_trades=('closed_trades','sum'), total_data_gaps=('data_gaps','sum'))
    .reset_index().sort_values(['positive_windows','mean_return_pct','worst_return_pct'], ascending=[False,False,False]))

out = base.parent / 'free_eod_preliminary_2026-08-26_analysis'
summary_structure.to_csv(str(out) + '_by_structure.csv')
summary_window.to_csv(str(out) + '_by_window.csv')
summary_management.to_csv(str(out) + '_by_management.csv')
full_recent_rank.to_csv(str(out) + '_full_recent_rank.csv', index=False)
latest_rank.to_csv(str(out) + '_latest_30d_rank.csv', index=False)
config_summary.to_csv(str(out) + '_configuration_stability.csv', index=False)

sns.set_theme(style='whitegrid', context='talk')
heat = results.pivot_table(index='structure', columns='window', values='return_pct', aggfunc='mean')
heat = heat[['spring_selloff','early_recovery','summer_trend','latest_30d','full_recent']]
fig, ax = plt.subplots(figsize=(14, 8))
sns.heatmap(heat, annot=True, fmt='.2f', cmap='RdYlGn', center=0, linewidths=.5, ax=ax, cbar_kws={'label':'Mean return (%)'})
ax.set_title('Preliminary EOD options research — mean return by structure and window')
ax.set_xlabel('Window')
ax.set_ylabel('Structure')
fig.tight_layout()
fig.savefig(str(out) + '_return_heatmap.png', dpi=160)
plt.close(fig)

report = {
    'source': manifest.get('source'),
    'rows': int(len(results)),
    'structures': sorted(results['structure'].unique()),
    'windows': sorted(results['window'].unique()),
    'mean_return_all_runs_pct': float(results['return_pct'].mean()),
    'median_return_all_runs_pct': float(results['return_pct'].median()),
    'positive_run_pct': float(results['positive'].mean() * 100),
    'mean_drawdown_all_runs_pct': float(results['max_drawdown_pct'].mean()),
    'worst_drawdown_pct': float(results['max_drawdown_pct'].min()),
    'total_data_gaps_sum': int(results['data_gaps'].sum()),
    'total_commissions_sum': float(results['commissions'].sum()),
    'best_full_recent_row': full_recent_rank.iloc[0].to_dict(),
    'best_latest_30d_row': latest_rank.iloc[0].to_dict(),
    'best_stability_row': config_summary.iloc[0].to_dict(),
    'data_limitations': [
        'Alpaca daily OHLC bars, not historical NBBO/intraday quotes',
        'moneyness proxy rather than point-in-time historical delta',
        'historical chain membership/listing timestamp unavailable',
        'intraday fills and partial fills are not simulated',
        'intrinsic fallback increments data_gaps when an option bar is missing',
    ],
}
Path(str(out) + '.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
print(json.dumps({
    'rows': report['rows'],
    'mean_return_all_runs_pct': round(report['mean_return_all_runs_pct'], 6),
    'median_return_all_runs_pct': round(report['median_return_all_runs_pct'], 6),
    'positive_run_pct': round(report['positive_run_pct'], 6),
    'mean_drawdown_all_runs_pct': round(report['mean_drawdown_all_runs_pct'], 6),
    'worst_drawdown_pct': round(report['worst_drawdown_pct'], 6),
    'total_data_gaps_sum': report['total_data_gaps_sum'],
    'total_commissions_sum': round(report['total_commissions_sum'], 6),
}, sort_keys=True))
print('\nBY_STRUCTURE')
print(summary_structure.round(3).to_string())
print('\nBY_WINDOW')
print(summary_window.round(3).to_string())
print('\nTOP_STABILITY')
print(config_summary.head(10).round(3).to_string(index=False))
