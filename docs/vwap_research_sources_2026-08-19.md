# Investigación VWAP — fuentes y hallazgos

**Fecha de consulta:** 19 de agosto de 2026.

## Alcance

La pregunta es si un motor de `VWAP reclaim/pullback` puede cubrir un hueco distinto de EMA/Donchian en Polaris y si existe evidencia suficiente para justificar un backtest. La investigación distingue VWAP como benchmark de ejecución de una regla direccional de trading; que una institución use VWAP como referencia no demuestra que comprar un reclaim tenga alpha.

## Fuente 1 — preprint académico sobre ejecución VWAP

**URL:** https://ar5iv.labs.arxiv.org/html/2502.13722

El trabajo define VWAP como precio medio ponderado por volumen, `sum(price_i * volume_i) / sum(volume_i)`, y lo presenta principalmente como benchmark para comparar ejecuciones y estudiar market impact/slippage. También descompone el error frente a VWAP en componentes de precio y de distribución temporal del volumen. La fuente respalda que volumen y precio son variables dinámicas y que la ejecución VWAP no es trivial.

**Aplicación:** El backtest no debe tratar VWAP como un nivel mágico ni asumir que el precio vuelve al promedio. Debe calcularlo con datos hasta la barra cerrada, anclado a una sesión declarada, e incluir slippage y volumen de confirmación. El paper estudia ejecución, no valida un reclaim long/short en acciones de Polaris.

## Fuente 2 — guía practitioner sobre VWAP pullback

**URL:** https://tradediary.in/strategies/vwap-pullback

El resultado de búsqueda describe una heurística discrecional: un toque de VWAP no es suficiente; se busca desplazamiento previo, retroceso controlado y un trigger como rechazo, ruptura de microestructura o reclaim. También advierte que si el retroceso destruye la estructura, la premisa queda invalidada.

**Aplicación:** Esta fuente sirve para generar hipótesis algorítmicas, no evidencia de rentabilidad. En Polaris se debe separar `touch`, `reclaim`, `hold` y `failure`, y probar cada uno con reglas objetivas.

## Fuente 3 — definición contractual de VWAP

**URL:** https://dictionary.contracts.justia.com/volume-weighted-average-price

El resultado expone una definición contractual de VWAP calculada durante la sesión de mercado, desde la apertura oficial hasta el cierre oficial, ponderando el precio por volumen. La fuente es un ejemplo contractual, no un estándar académico.

**Aplicación:** La implementación inicial usará VWAP de sesión regular `09:30–16:00 America/New_York`, excluyendo premarket y after-hours salvo una variante explícita. Las sesiones se reinician por fecha local.

## Hipótesis a formalizar

| Variante | Regla inicial | Riesgo de sesgo |
|---|---|---|
| Reclaim long | precio cruza desde abajo a cierre sobre VWAP después de un desplazamiento bajo VWAP | Puede duplicar momentum EMA |
| Pullback long | tendencia/pendiente VWAP positiva, precio vuelve cerca de VWAP y cierra arriba | Definir “cerca” sin optimizar excesivamente |
| Failure short | precio pierde VWAP tras estar arriba y cierra debajo | Las cortas no están habilitadas como política live |
| Volumen | volumen de confirmación relativo a barras previas | Evitar usar el volumen futuro en el promedio |
| Régimen | gate bull para long; bear/crash solo como observación short | No confundir régimen diario con entrada intradía |

La hipótesis solo se promoverá si supera DayBreakout/DayMomentum con varias ventanas cronológicas, costes, muestra suficiente y estabilidad por símbolo. Ninguna fuente consultada autoriza cambiar `RiskManager`, floor, circuit breakers o `influence_entries`.

## Fuente 4 — patrón intradía de volumen

**URL:** https://www.ime.usp.br/~jstern/papers/papersJS/MaxEnt15T.pdf

Takada y Stern estudian el volumen intradía de acciones y señalan que la actividad suele presentar una forma de U: volumen elevado al inicio y al final de la sesión y menor volumen en el centro. El trabajo relaciona explícitamente esa forma con el diseño de estrategias de ejecución cuyo benchmark es VWAP y menciona como práctica usar promedios históricos de volumen por tramo, por ejemplo los últimos 21 días.

**Aplicación:** Un filtro `volume >= rolling_mean * k` sin ajustar por minuto puede favorecer artificialmente las barras de apertura y penalizar el mediodía. Para el motor VWAP se deben comparar, como mínimo, una referencia rolling por barras anteriores y una referencia por minuto de sesión construida solo con días previos. La segunda debe quedar como variante separada, sin elegir parámetros usando el mismo test.

**Límite:** El estudio trata modelado de volumen/ejecución, no prueba una señal direccional de reclaim. La evidencia se usa para especificar el control de volumen, no para afirmar rentabilidad.
