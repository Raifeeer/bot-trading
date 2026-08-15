from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

OUT = Path('/home/ubuntu/backtests')
CHARTS = OUT / 'charts'
CHARTS.mkdir(parents=True, exist_ok=True)
sns.set_theme(style='whitegrid', context='talk')

matrix = pd.read_csv(OUT / 'research_matrix_2026-08-15.csv')
summary = matrix.groupby(['motor', 'window']).agg(
    median_return=('return_pct', 'median'),
    median_dd=('max_drawdown_pct', 'median'),
    configs=('key', 'count'),
).reset_index()
order = ['regime_hold_cash', 'breakout55', 'breakout20', 'hold_weekly', 'smc_daily', 'put_choch', 'regime_aware']
pivot = summary.pivot(index='motor', columns='window', values='median_return').reindex(order).dropna(how='all')
fig, ax = plt.subplots(figsize=(15, 7))
sns.heatmap(pivot, annot=True, fmt='.1f', cmap='RdYlGn', center=0, linewidths=.5, ax=ax, cbar_kws={'label': 'Retorno mediano (%)'})
ax.set_title('Polaris: retorno mediano por motor y ventana\nCon slippage de opciones y coste equity cuando aplica')
ax.set_xlabel('Ventana histórica')
ax.set_ylabel('Motor de investigación')
fig.tight_layout()
fig.savefig(CHARTS / 'matrix_median_returns.png', dpi=180)
plt.close(fig)

ens = pd.read_csv(OUT / 'ensemble_summary_2026-08-15.csv')
fig, ax = plt.subplots(figsize=(13, 7))
for motor, g in ens.groupby('breakout_motor'):
    g = g.sort_values('weight_breakout')
    ax.plot(g['weight_breakout'] * 100, g['median_return_pct'], marker='o', label=motor)
ax.axhline(0, color='black', linewidth=1)
ax.set_title('Ensembles: sensibilidad del retorno mediano al peso breakout')
ax.set_xlabel('Peso breakout (%)')
ax.set_ylabel('Retorno mediano (%)')
ax.legend(title='Motor')
fig.tight_layout()
fig.savefig(CHARTS / 'ensemble_weight_sensitivity.png', dpi=180)
plt.close(fig)

wf = pd.read_csv(OUT / 'ensemble_walk_forward_2026-08-15.csv')
test = wf[wf['window'] == 'test'].copy()
fig, ax = plt.subplots(figsize=(10, 6))
for fold, g in test.groupby('fold'):
    g = g.sort_values('weight_breakout')
    ax.plot(g['weight_breakout'] * 100, g['return_pct'], marker='o', label=fold)
ax.axhline(0, color='black', linewidth=1)
ax.set_title('Ensemble walk-forward: retorno test según peso breakout')
ax.set_xlabel('Peso breakout (%)')
ax.set_ylabel('Retorno test (%)')
ax.legend(title='Fold')
fig.tight_layout()
fig.savefig(CHARTS / 'ensemble_walk_forward_test.png', dpi=180)
plt.close(fig)

print(CHARTS / 'matrix_median_returns.png')
print(CHARTS / 'ensemble_weight_sensitivity.png')
print(CHARTS / 'ensemble_walk_forward_test.png')
