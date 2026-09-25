# escalera-de-unidades — ¿el escalón de manzana sobrevive a cambiar de unidad?

> **Estado: exploratorio.** Nada de este experimento se emite todavía al registro
> canónico de InWatch. Las cifras viven en los parquets de
> `data/silver/escalera-de-unidades/` y en el notebook, no en este archivo; cuando se
> emitan, entran acá con su ancla `CANON:`. Las cifras de origen que se reproducen son
> las `ladder_mult.*` del registro de infelix, que este experimento **lee** y nunca
> escribe. Bead: `inwatch-uiv`.

## La pregunta

La escalera de atribución del trabajo de origen (`scripts/exp_ladder_multiplicity.py`
en infelix) agrega fuentes de a una a un modelo HGB por categoría y mide cuánto mejora
el ρ de Spearman intra-distrital contra el crimen geocodificado de 2023. Con once
fuentes, en hexágonos H3 res-8, encontró **un solo escalón** que sobrevive a
Westfall-Young: la manzana censal INEI. La forma urbana OSM y las otras ocho fuentes
dieron nulos.

La escalera se midió en una sola unidad. Este experimento la corre en las tres del
repo y pregunta si el escalón —y los nulos— siguen donde estaban.

## Qué se manipula

Dos perillas, y la segunda salió de intentar reproducir la primera:

1. **La unidad de evaluación**: `h3_8`, `manzana` o `morfologica`.
2. **Cómo se tratan los hexágonos que cruzan un límite distrital.** El oráculo de
   origen agrupa por `(h3_index, ubigeo del hecho, año, categoría)`, así que un
   hexágono de borde trae una fila por cada distrito donde ocurrieron sus hechos.
   Tres lecturas:
   - `h3_8_origen`: como `load_panel` de infelix. El hexágono entra repetido, una vez
     por fila del oráculo, y el `merge` del rezago lo vuelve a multiplicar. Es la
     única que reproduce las cifras del registro de origen.
   - `h3_8`: una fila por hexágono y el conteo sumado sobre los distritos del hecho.
     Es la base con la que se comparan las unidades finas, que se construyen igual.
   - `h3_8_propio`: una fila por hexágono, contando solo los puntos cuyo distrito del
     hecho es el que la matriz le asigna al hexágono.

Además hay una tercera perilla, de control: la **semilla del modelo** (`random_state`
de HGB). Con más de 10 000 filas HGB activa early stopping con un split aleatorio, así
que la semilla cambia cuántas iteraciones entrena cada escalón. El loader corre la
escalera con cinco semillas más y B menor (`semillas.parquet`). Un veredicto que cambie
con la semilla no es un veredicto.

## Unidad espacial

Las tres, comparables. Ver `design/contrato-unidades.md`.

- `h3_8` (`h3_index`): features y oráculo como en origen.
- `manzana` (`mzn_id` = `OBJECTID` de la capa INEI/COFOPRI): la capa solo trae
  **centroides**, no polígonos. Cada punto de denuncia va a la manzana cuyo centroide
  está más cerca, hasta 150 m (`RADIO_MANZANA_M`); más lejos queda sin unidad y se
  cuenta. Es un Voronoi implícito: aproxima la manzana, no la dibuja.
- `morfologica` (`tess_id`): la tesselación de `tejido-vs-hexagono`. Cada punto va a la
  celda que lo contiene (`sjoin within`). Donde no hay tejido, el punto queda sin
  unidad: el tejido no cubre toda la grilla y eso es dato, no error.

Cruces: manzana → hexágono por su centroide; celda morfológica → hexágono con mayor
`frac_tess` en `correspondencia_h3_tejido.parquet`; celda morfológica → manzana más
cercana a su centroide. El distrito de evaluación es **siempre** el `ubigeo` que la
matriz le da al hexágono, en las tres unidades: los ρ se promedian sobre los mismos
grupos y lo único que cambia es qué se ordena dentro de cada uno.

## Datos

| Artefacto | Fuente (`registry/fuentes.toml`) | Unidad | Notas |
|---|---|---|---|
| matriz de features | `h3_feature_matrix` | `h3_8` × año | los once bloques de fuentes |
| oráculo geocodificado | `h3_observed_geocoded` | `h3_8` × distrito × año | target en `h3_8` |
| denuncias | `denuncias_lima` | punto | target en las unidades finas |
| manzana censal | `inei_manzana_lima` (alta en este PR) | centroide | bloque de manzana nativo |
| tesselación | `data/silver/tejido-vs-hexagono/` | `morfologica` | salida de ese experimento |

Los puntos se limpian con las reglas del oráculo de origen
(`build_observed_h3_points.py`): solo denuncias, `CON COORDENADA`, bbox de Lima,
anti-centroide sobre 30 por coordenada exacta. Agregados a H3 **rehacen el oráculo
exacto** — si no, la diferencia entre unidades podría venir de la limpieza.

**Qué es nativo y qué se hereda.** En `manzana`, el bloque de manzana censal es el de
la propia manzana (con las fórmulas de `fetch_inei_manzana_h3.py`); en `morfologica`,
el de la manzana más cercana. Todas las demás fuentes —demografía, OSM y las ocho
restantes— se **heredan** del hexágono. Consecuencia: dentro de un hexágono esas
fuentes son constantes y no pueden ordenar unidades, así que en una unidad fina los
contrastes H2 y H3 miden cuánto aporta el contexto del hexágono, no la fuente a esa
escala. Un nulo ahí no dice que OSM no sirva en la manzana; dice que el OSM de
hexágono no ayuda a ordenar manzanas.

## Salidas

`data/silver/escalera-de-unidades/`:

| Archivo | Qué es |
|---|---|
| `contrastes.parquet` | una fila por (unidad, contraste): Δρ, CI marginal y simultáneo, p Westfall-Young |
| `reproduccion_h3.parquet` | las siete `ladder_mult.*` de origen contra lo que dio `h3_8_origen` |
| `rho_por_distrito.parquet` | ρ por (unidad, escalón, categoría, distrito) |
| `semillas.parquet` | la familia de contrastes con cinco semillas de HGB más |
| `familias.json` | c max-t, pares alineados, diagnósticos de asignación y `inputs_sha256` |

## Qué se ve

Un waterfall por unidad: la barra base es ρ de la demografía distrital y cada escalón
suma su Δρ con el intervalo (simultáneo o marginal, a elección) colgado del tope. Tono
único: oscuro si sobrevive la corrección, gris si no. Sin verde ni rojo. Los nulos se
dibujan con el intervalo entero, nunca como barra en cero: un nulo es un efecto que este
diseño no resuelve, no evidencia de ausencia. Debajo, la tabla de las cuatro lecturas y
la sensibilidad a la semilla.

## Cómo correr

```bash
uv sync --extra geo --extra ml --extra viz
uv run python experiments/escalera-de-unidades/loader.py          # B=20000, ~12 min
uv run python experiments/escalera-de-unidades/loader.py --unidades h3_8 --semillas ""   # solo la reproducción, ~1 min
uv run marimo edit experiments/escalera-de-unidades/notebook.py
```

El costo no está en el bootstrap —B=20000 réplicas sobre ρ ya calculados tarda
segundos— sino en los 20 modelos HGB por unidad y semilla; la unidad morfológica es la
más cara (~1 M filas de panel).

## Verificación

- [x] `uv run pytest tests/test_escalera_unidades.py` en verde (sintéticos + `needs_data`)
- [x] `uv run canon check` sin fallos
- [x] Reproducción de las siete `ladder_mult.*` con diferencia < 1e-6
- [x] Los puntos limpios rehacen el oráculo exacto
- [ ] Screenshot del notebook en claro y oscuro
- [ ] Contraste verificado en deuteranopia (tono único, pero sin verificar)

## Decisiones tomadas

- **Replicar la duplicación del borde para reproducir, y no usarla para comparar.**
  Sin ella, la cifra de origen no sale; con ella, el panel de H3 no se construye igual
  que el de las unidades finas. Se reportan las tres lecturas y se deja visible que el
  veredicto de los nulos depende de cuál se elija.
- **Heredar en vez de re-derivar las fuentes a escala fina.** Rehacer once fuentes por
  manzana y por celda morfológica es otro proyecto; heredar es honesto si se declara
  qué contrastes pierden sentido.
- **Distrito de evaluación fijo** (el de la matriz) para que el cambio de unidad sea lo
  único que cambia.
- **Descartado**: asignar puntos a manzanas por polígono. La capa disponible no tiene
  polígonos; el shapefile INEI está pendiente como fuente.
