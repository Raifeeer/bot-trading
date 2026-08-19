# Mean-reversion intradía — fuentes y formalización

**Fecha:** 19 de agosto de 2026.

## Alcance

Evaluar un motor independiente del RSI bounce que detecte extensiones intradía respecto a VWAP y ATR, pero solo opere en investigación. La hipótesis es que parte de las reversiones cortas puede relacionarse con liquidez temporal; no se asume que toda desviación de VWAP deba revertir.

## Evidencia externa

Heston, Korajczyk y Sadka documentan patrones intradía en la sección transversal de retornos y relacionan el volumen intradía y la reversión de corto plazo con efectos de liquidez [1]. Miwa estudia reversión de corto plazo e interacciones intradía, apoyando la necesidad de modelar liquidez y costes en lugar de tratar la reversión como un patrón universal [2].

La literatura y la investigación practitioner sobre VWAP tratan VWAP principalmente como benchmark de ejecución; convertirlo en una señal direccional exige una hipótesis adicional y validación específica. Un estudio reciente sobre una estrategia VWAP condicionada por ADX es evidencia contextual y no un parámetro para Polaris [3]. La advertencia metodológica sobre opportunity-set bias es relevante: elegir solo los símbolos que muestran reversión puede inflar resultados frente a un universo fijo [4].

## Hipótesis determinista para Polaris

1. Calcular VWAP de sesión usando `typical_price * volume` acumulado desde 09:30 ET; no mezclar premarket.
2. Calcular desviación `z_vwap = (close - vwap) / ATR` con ATR as-of.
3. Marcar `oversold_extension` si `z_vwap <= -threshold` y el régimen no es crash.
4. Exigir `reclaim` cuando una barra cerrada recupera VWAP o el umbral de reversión definido.
5. Simular entrada en la apertura siguiente; target hacia VWAP o R explícito; stop bajo el extremo de extensión; máximo de barras intradía.
6. Long-only durante la primera fase; no crear cortas por simetría.
7. Comparar contra DayBreakout y reportar exposición, tasas de señal, costes, drawdown intratrade y concentración por símbolo.

## Guardarraíles

La desviación puede persistir durante un selloff o tendencia fuerte. Por eso se requieren gates de régimen, límite de una señal por sesión, confirmación posterior a la extensión y fail-closed cuando faltan volumen, ATR o timestamps de sesión. Los costes deben aplicarse antes de declarar alpha.

## Referencias

[1] [Heston, Korajczyk and Sadka — Intraday Patterns in the Cross-Section of Stock Returns](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2010.01573.x).

[2] [Miwa — Short-Term Return Reversals and Intraday Transactions](https://www.worldscientific.com/doi/abs/10.1142/S2010139219500022).

[3] [Bhatti — Momentum Exhaustion and Fair Value Reversion: An ADX-conditioned VWAP Strategy in FX Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6454659).

[4] [Opportunity-Set Bias in Mean-Reversion Trading Systems](https://concretumgroup.com/opportunity-set-bias-in-mean-reversion-trading-systems/).
