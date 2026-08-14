# Skill: Smart Money Concepts (SMC) Multi-Timeframe

**Archivo de referencia:** `strategies/smc.py`
**Fuente del conocimiento:** material MTF de Jorge Valet (Abacus PRO) y clases de Temporalidades de Jean Vizón (carpeta Abacus del Google Drive del dueño), más la calibración propia de los backtests S1–S89.

## 1. Principio rector

El SMC opera sobre la estructura del mercado, no sobre indicadores retardados. La idea central es que el precio se mueve por la búsqueda de liquidez (los stops de los traders minoristas) y por los bloques de órdenes institucionales (order blocks). El framework se organiza en **cuatro temporalidades jerárquicas**, donde cada nivel responde a una pregunta distinta y la señal solo es válida cuando las temporalidades están alineadas.

> Regla de oro del flujo fractal: **una tendencia en una temporalidad alta debe suceder primero en la temporalidad baja**. Si el marco menor no muestra la continuación, la señal del marco mayor no es operativa.

| Temporalidad | Rol | Qué pregunta responde |
|---|---|---|
| **1D** | Perspectiva | ¿Cuál es la tendencia de fondo, qué niveles críticos hay y en qué etapa del gráfico está el activo? |
| **4H** | Narrativa | ¿El movimiento actual es continuación o retroceso? |
| **M15** | Sesgo inmediato | ¿El CHoCH confirma el fin de la continuación o el inicio del retroceso? |
| **M1** | Temporización | ¿Dónde está la entrada exacta con el menor riesgo posible? |

## 2. Conceptos y definiciones operativas

**Puntos swing (`Swing`).** Cada swing se define por `price`, `idx`, si es alto o bajo (`is_high`) y si es fuerte o débil (`strong`). Un swing es **fuerte** si provocó un movimiento opuesto significativo (rompió un swing contrario); es **débil** si no lo logró. Esta clasificación es la base de toda la estructura: altos débiles y bajos débiles son los objetivos naturales del precio, porque son la liquidez obvia.

**Estructura (BOS vs CHoCH).**

| Patrón | Definición | Interpretación |
|---|---|---|
| **BOS** (Break of Structure) | Cierre de vela (cuerpo) por encima/debajo del swing fuerte previo | Confirmación de continuación de la tendencia establecida |
| **CHoCH** (Change of Character) | Cierre por debajo/debajo del swing que causó el último BOS | Primera señal de que la tendencia puede estar cambiando |

Dos reglas de mapeo críticas que el material de Valet/Vizón enfatiza y que están codificadas en `fractal_swing_points` y `detect_choch`:

1. **Mapéo conservador: mechas para la estructura, cuerpos para el BOS/CHoCH.** La mecha (sweep) define los swings (es donde está la liquidez barrida), pero solo el **cierre del cuerpo** cuenta como ruptura. Las mechas que rompen sin cerrar no invalidan estructura.
2. **El CHoCH nunca opera solo.** Exige confluencia: un **sweep de liquidez** (la mecha barre un swing débil) seguido de un **order block de S&D** en la zona de reacción. Un CHoCH sin sweep es ruido.

**Zonas de oferta y demanda (`Zone`).**

> **Zona de demanda:** la vela base contraria al impulso alcista — se delimita desde el precio de apertura de la vela hasta el mínimo de su mecha inferior. **Zona de supply:** el espejo, con la mecha superior.

Un order block válido es la última vela bajista antes de un impulso alcista fuerte (demanda) o la última vela alcista antes de un impulso bajista (supply), idealmente la que causó el BOS. La zona se invalida si el precio la atraviesa con cuerpo cerrado.

**Objetivos.** El take profit natural es el **high débil o low débil siguiente en la dirección de la tendencia HTF**: son los puntos donde el mercado vuelve a buscar liquidez antes de continuar.

## 3. Implementación en el bot

La detección es puramente geométrica sobre OHLC (sin indicadores salvo como filtro), lo que la hace barata y reproducible en backtests:

1. `fractal_swing_points(df, left, right)` identifica los pivotes usando ventanas de comparación simétricas; clasifica fuertes/débiles por la magnitud del movimiento opuesto posterior.
2. `detect_choch(df)` recorre los pivotes: tras un swing fuerte que causó un BOS, busca el primer cierre del lado contrario más allá del swing que originó ese BOS. En backtests se relajó el criterio original (demasiado estricto, nunca disparaba) a la versión pragmática validada en S63: **cierre bajo el swing LOW con el HI dominante a menos de 60 días**, que fue la única configuración positiva en el selloff de enero–abril 2026.
3. En el motor de producción (`risk/regime.py`), el CHoCH se usa agregado a nivel de **universo** para la clasificación de régimen: si ≥30% del universo muestra CHoCH bear, el régimen global es "bear" y el bot no abre posiciones.

## 4. Errores conocidos y cómo se corrigieron

| Error | Consecuencia | Corrección |
|---|---|---|
| CHoCH original demasiado estricto | `put_choch_entry` nunca disparaba en backtests | CHoCH pragmático: cierre bajo swing LOW con HI dominante <60 días (validado en S63: +20.8% en selloff) |
| `build_spread(put)` devolvía `None` | El swap de strikes invertía las patas del put spread | Put long = strike MAYOR (más ATM), put short = strike menor; débito = precio long − precio short |
| LCID/MARA con vol. histórica ~150% | El simulador generaba strikes tan OTM (46%) que el spread neto caía a ~0 | Filtro `max_vol_pct: 100` y exclusión explícita del universo reto |

## 5. Criterios de uso por el agente

Al construir o ajustar señales SMC, verificar siempre: (1) que el sesgo del M15 coincide con la narrativa del 4H y la perspectiva del 1D; (2) que el CHoCH tiene confluencia con sweep de liquidez; (3) que el objetivo es un weak high/low en dirección de la tendencia HTF; (4) que la zona de entrada respeta el delimitado open-to-mecha. Nunca usar el CHoCH como señal única: es un disparador de atención, no una entrada.
