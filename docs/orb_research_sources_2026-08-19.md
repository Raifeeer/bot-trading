# ORB — registro de investigación 2026-08-19

## Fuente 1

- **Título:** Assessing the profitability of intraday opening range breakout strategies
- **URL:** https://ideas.repec.org/p/hhs/umnees/0845.html
- **Tipo:** Registro académico RePEc de un working paper.
- **Estado:** Página abierta en navegador y HTML guardado localmente en `/home/ubuntu/browser_html/ideas_repec_org_0845.html_1787156675426.html` para extracción posterior.
- **Hallazgo inicial:** El resultado de búsqueda identifica un estudio de U. Holmberg (2012), citado 51 veces, que presenta una estrategia ORB basada en retornos intradía y reporta rentabilidad superior en determinadas condiciones. La cifra y el método deben verificarse en el texto/PDF original antes de usarse.
- **Limitación:** La extracción visual inicial no mostró el cuerpo de la página; no se adopta ninguna conclusión cuantitativa todavía.

## Fuente 2

- **Título:** A Profitable Day Trading Strategy For The U.S. Equity Market
- **Autores:** Carlo Zarattini, Andrea Barbon y Andrew Aziz.
- **URL:** https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- **Tipo:** Swiss Finance Institute Research Paper No. 24-98; publicado en SSRN el 15 de marzo de 2024, revisado el 29 de abril de 2025.
- **Hechos del resumen:** Analiza principalmente ORB de 5 minutos sobre más de 7,000 acciones estadounidenses entre 2016 y 2023. Estudia el filtro `Stocks in Play`, definido por actividad anormal asociada principalmente a noticias fundamentales, y compara ventanas de 5, 15, 30 y 60 minutos. El resumen reporta que limitar el universo a las 20 mejores `Stocks in Play` produjo más de 1,600% de rendimiento neto total, Sharpe 2.81 y alpha anualizada 36%, frente a 198% del S&P 500 en el mismo periodo.
- **Uso prudente:** No trasladar esas cifras directamente a Polaris: el universo, la selección diaria de acciones, la calidad de datos, el calendario de noticias, el modelo de ejecución y la exposición son distintos. La fuente sí justifica probar ORB con un filtro de actividad relativa y comparar ventanas, pero exige reconstruir esas variables point-in-time.
- **Limitación de acceso:** La página SSRN expone el resumen y enlaces al PDF, pero la navegación del PDF fue redirigida a la ficha; las reglas exactas de ejecución y costes deben extraerse del PDF si se consigue acceso completo. El resumen no basta para validar un P&L operativo.

## Fuente 3

- **Título:** Assessing the profitability of intraday opening range breakout strategies
- **URL:** https://swopec.hhs.se/umnees/abs/umnees0845.htm
- **Tipo:** Repositorio S-WoPEc de Umeå School of Business and Economics.
- **Estado:** Página abierta en navegador; HTML guardado en `/home/ubuntu/browser_html/swopec_hhs_se_umnees0845.htm_1787156775980.html` para extracción posterior.
- **Hallazgo inicial:** El registro universitario corresponde al mismo trabajo de Holmberg, Lönnbark y Lundström sobre rentabilidad de ORB y estados de volatilidad. La página visual no entregó el cuerpo textual en esta sesión; se debe parsear el HTML o localizar el PDF antes de citar cifras.
- **Criterio:** Se conserva como fuente primaria/universitaria potencial, pero no se incorporan todavía sus resultados numéricos al diseño del bot.

### Extracción verificada de la Fuente 3

El HTML contiene la descripción oficial de Umeå University: la estrategia busca identificar movimientos intradía grandes y operar solo cuando el precio supera un umbral predeterminado. El trabajo presenta una variante basada en retornos normalmente distribuidos para identificar esos días y afirma que obtiene retornos significativamente superiores a cero y una tasa de éxito superior a la de un juego justo. La descripción destaca que el enfoque usa conjuntamente la distribución de `Low`, `High`, `Open` y `Close` en un horizonte dado. Esta evidencia respalda formalizar ORB como una regla de rango y umbral, pero no proporciona por sí sola una ventaja para el universo reducido de Polaris ni sustituye un backtest con costes y datos point-in-time.

## Fuente 4 — microestructura y horario de sesión

- **Fuente:** NYSE Trading Information, https://www.nyse.com/trade/trading-information
- **Estado:** El sitio mostró un bloqueo/captcha parcial, pero la extracción de contenido proporcionó la página oficial.
- **Hechos verificables:** Para NYSE Tape A, la subasta de apertura core ocurre a las 9:30 a.m. ET y la sesión core va de 9:30 a.m. a 4:00 p.m. ET. El pre-opening session comienza a las 6:30 a.m. ET y las órdenes esperan hasta la subasta de apertura. Para ORB de Polaris, el rango debe empezar en la sesión regular de 9:30 ET y excluir premarket salvo que una variante lo defina explícitamente.

## Fuente 5 — documentación de datos Alpaca

- **Fuente buscada:** Alpaca Historical Stock Bars, https://docs.alpaca.markets/us/reference/stockbars
- **Estado:** La navegación fue redirigida a una página de restricción geográfica; no se usa como evidencia primaria adicional.
- **Consecuencia metodológica:** El backtest ORB se basará en los caches locales ya generados y en la inspección directa de sus timestamps/columnas. No se asumirán propiedades de la API que no estén verificadas en el código o en los datos locales.
