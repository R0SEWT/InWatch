# tejido-vs-hexagono — La unidad espacial es un parámetro

> Vigilado por `canon check`: cada cifra portante de este archivo lleva su ancla.

## La pregunta

¿Cuánto cuesta haber mirado Lima a través de hexágonos? La grilla canónica H3 res-8
existe porque los artefactos del trabajo de origen están calculados sobre ella, no
porque respete la ciudad. La escalera de atribución encontró **un solo escalón
significativo, la manzana censal**, y eso dice que la señal vive en la forma urbana a
granularidad sub-distrital — justo la escala que un hexágono de cientos de metros de
arista promedia sin declararlo.

Este experimento construye la tercera unidad y mide la diferencia en vez de suponerla.
Sobre Lima y Callao, la tesselación morfológica produce @@tejido.celdas@@ celdas
<!-- CANON: tejido.celdas = @@tejido.celdas@@ -->
donde el hexágono pone 4172.
<!-- CANON: conteo.celdas_grilla = 4172 -->

La respuesta corta: el **@@correspondencia.celdas_partidas@@ %** de las celdas
morfológicas cae repartido entre dos o más hexágonos,
<!-- CANON: correspondencia.celdas_partidas = @@correspondencia.celdas_partidas@@ -->
y eso es el **@@correspondencia.area_partida@@ %** del área del tejido.
<!-- CANON: correspondencia.area_partida = @@correspondencia.area_partida@@ -->
Cada una de esas celdas es una manzana cuyo valor el mapa hexagonal promedió con la de
al lado.

## Qué se manipula

| Control | Qué mueve |
|---|---|
| **Capa tesselación / capa hexágono** | qué partición se dibuja sobre la misma cuadra |
| **Piso de cobertura areal** | mínimo de hexágono cubierto por tejido para dibujarlo |

El primero es el que hace del experimento un experimento: en los otros se mueve un
umbral y el mapa cambia de contenido, acá se cambia la rejilla y el mapa cambia de
**sujeto**. "La unidad espacial es un parámetro" deja de ser una frase de diseño y pasa
a ser una perilla que, al girarla, parte manzanas a la vista.

## Unidad espacial

`morfologica`, clave `tess_id`. **Cruza unidades**, así que va con tabla de
correspondencia explícita — es lo que `design/contrato-unidades.md` exige antes de
admitir una unidad nueva, y el motivo por el que existe la mitad de este loader.

| Artefacto | Clave | Filas | Qué es |
|---|---|---|---|
| `tejido_celdas.parquet` | `tess_id` | una por celda | área, grado y enclosure. Sin geometría |
| `tejido_aristas.parquet` | — | una por arista | adyacencia `touched_to`, no dirigida |
| `correspondencia_h3_tejido.parquet` | `tess_id` + `h3_index` | una por intersección | los dos factores de área |
| `hexagonos_cobertura.parquet` | `h3_index` | **una por hexágono de la grilla** | cuánto tejido lo sostiene |
| `ventana_*.parquet` | — | la ventana del notebook | anillos exteriores en WGS84 |
| `tejido_geometria.parquet` | `tess_id` | una por celda | los polígonos, en WKB, **aparte** |

**La geometría va en un artefacto separado y eso no viola el contrato: lo cumple.** El
contrato prohíbe geometría en las tablas de features porque la de un hexágono se
reconstruye desde su clave con `h3.cell_to_boundary`. Un polígono de tesselación no: no
hay función que lo derive de `tess_id`. Se guarda una vez, en su propio archivo, y las
tablas de features siguen sin geometría.

### Los dos factores de área, y por qué son dos

- `frac_tess` — proporción **de la celda morfológica** en ese hexágono. Reparte del
  tejido hacia H3. Suma 1 en toda celda contenida en la grilla.
- `frac_h3` — proporción **del hexágono** que ocupa esa celda. Reparte de H3 hacia el
  tejido. **No suma 1.**

Las dos unidades no se anidan, así que un solo factor no alcanza: usar `frac_tess` en el
sentido contrario duplicaría o perdería masa según qué tan cubierto esté el hexágono, en
silencio y sin que ningún test lo note.

Reconstruir el área de una celda desde la tabla desvía como máximo
@@correspondencia.desvio_masa@@ en términos relativos.
<!-- CANON: correspondencia.desvio_masa = @@correspondencia.desvio_masa@@ -->
Los nueve decimales son a propósito: es la cifra que sostiene la afirmación de que el
reparto no pierde ni inventa masa, y redondearla a dos la volvería un cero decorativo.

## Datos

| Artefacto | Origen | Notas |
|---|---|---|
| `peru.gpkg` | `infelix/data/datasets/osm/` | capas `gis_osm_buildings_a_free` y `gis_osm_roads_free` |
| `h3_admin.parquet` | `infelix/data/silver/h3_features/` | grilla canónica y su límite |
| `h3_graph_edges.parquet` | `infelix/data/silver/` | adyacencia hexagonal contra la que se compara |

Se leen **read-only** del repo de origen y la salida se exporta a
`data/silver/tejido-vs-hexagono/`, con la procedencia registrada por `canon.emit` (hash
de cada input y del script emisor). El repo de origen nunca se escribe.

Recortado al límite de la grilla canónica quedan 172 700 edificios y 134 648 vías
barrera sobre 3614 km². Esas tres cifras describen los **insumos**, no un hallazgo: son
lo que OSM tiene hoy en esa extensión, cambian con cada extracto y no se citan en ningún
argumento, así que no van al registro.

### Qué cuenta como barrera

`footway`, `steps`, `path`, `cycleway`, `bridleway` y `track` **se excluyen**. Un pasaje
peatonal o una escalera atraviesan la manzana por dentro; no separan dos tejidos.
Usarlos como barrera fragmentaría la manzana en astillas sin significado morfológico.
La decisión está en la constante `VIAS_BARRERA`, arriba del archivo y no enterrada en un
filtro, y hay un test que la fija para que un cambio de criterio sea deliberado.

## Qué se ve

**1 · El corte.** La misma cuadra con las dos particiones superpuestas: la tesselación
en azul con relleno tenue y borde nítido, el hexágono en naranja **sin relleno y
encima** — es el que corta, y tiene que leerse como una cuchilla sobre el tejido, no
como otra mancha. Donde el borde naranja cruza una celda azul hay una manzana partida.

**2 · La adyacencia hexagonal no informa.** El grado medio del hexágono es
@@hexagono.grado_medio@@ sobre las 4172 celdas de la grilla:
<!-- CANON: hexagono.grado_medio = @@hexagono.grado_medio@@ -->
seis vecinos para todo hexágono interior **por construcción del dibujo**. No es una
medición de la ciudad. El tejido tiene grado medio @@tejido.grado_medio@@
<!-- CANON: tejido.grado_medio = @@tejido.grado_medio@@ -->
con desviación @@tejido.grado_desviacion@@,
<!-- CANON: tejido.grado_desviacion = @@tejido.grado_desviacion@@ -->
y **la dispersión es el dato**: el grado varía con la forma real de la manzana porque
`touched_to` solo une celdas dentro de la misma manzana cerrada. Dos edificios a ambos
lados de una avenida se tocan en el mapa y no son vecinos acá.

**3 · El hueco.** El @@correspondencia.hexagonos_sin_tejido@@ % de la grilla no tiene
una sola celda morfológica debajo.
<!-- CANON: correspondencia.hexagonos_sin_tejido = @@correspondencia.hexagonos_sin_tejido@@ -->
Esas celdas se dibujan **encogidas al 34 %**, un punteado que cubre la región sin
afirmar nada sobre ella — mismo tratamiento y mismo valor que en `donde-falla-el-dato`,
por la misma razón: con menos, los huecos interiores de la mancha se leen como fondo
liso, o sea como "acá no pasa nada".

**Recordatorio no negociable**: un hexágono sin tejido registrado no es campo vacío ni
zona tranquila. Es una celda sobre la que OSM no tiene edificación, y se dibuja
deshilachada, nunca verde ni ausente.

## Cómo correr

```bash
uv sync --extra geo --extra viz
uv run --extra geo python experiments/tejido-vs-hexagono/loader.py
uv run marimo edit experiments/tejido-vs-hexagono/notebook.py
```

El loader tarda: la tesselación de ~170 000 edificios no es interactiva. Corre una vez y
deja los parquets.

## Verificación

- [x] `uv run pytest -m "not needs_data"` en verde, con el extra `geo` instalado
- [x] `uv run ruff check .` limpio
- [x] `uv run canon check` sin fallos
- [x] El test de conservación de masa que exige `design/contrato-unidades.md` existe y
      corre **sin datos**, sobre geometría sintética cuadrada
- [x] La tabla de correspondencia se verifica además sobre el artefacto real
      (`needs_data`), incluido que no reparta masa hacia una celda no declarada

## Decisiones tomadas

**Las manzanas INEI no sirven de semilla.** `data/raw/cofopri/inei_manzana_lima_raw.parquet`
tiene 132 755 filas de manzana censal, pero solo con centroide (`_lat`, `_lng`): no hay
polígono. Una tesselación necesita geometría de área o al menos barreras lineales, así
que las semillas salen de los edificios OSM. La unidad `manzana` del contrato sigue sin
artefacto propio, y eso es una carencia real de datos, no una decisión de diseño.

**El límite es la unión de la grilla canónica, pasada como `limit=`.** Sin eso, la
tesselación se extendería hasta donde llegara el extracto OSM y la tabla de
correspondencia compararía dos unidades sobre territorios distintos — el
`correspondencia.hexagonos_sin_tejido` mediría el recorte del gpkg en vez de la ciudad.

**Las aristas H3 se normalizan a no dirigidas antes de comparar.** El artefacto de origen
guarda cada vecindad dos veces, una por sentido: son @@hexagono.aristas@@ pares únicos.
<!-- CANON: hexagono.aristas = @@hexagono.aristas@@ -->
Compararlas contra las @@tejido.aristas@@ del tejido sin normalizar
<!-- CANON: tejido.aristas = @@tejido.aristas@@ -->
duplicaría un lado de la comparación y regalaría el hallazgo.

**El piso de 1 m² en la correspondencia.** El borde compartido entre dos hexágonos genera
astillas de área microscópica al intersecar. Sin el piso, "celda partida" mediría el
épsilon de la librería geométrica en vez de la ciudad. Con él, una celda solo cuenta como
repartida si tiene al menos un metro cuadrado a cada lado.

**El déficit de `frac_h3` no se normaliza.** Escalarlo a 1 convertiría "acá no hay tejido
registrado" en "acá el tejido que hay lo es todo": ausencia de evidencia disfrazada de
evidencia. Qué hacer con ese hueco es decisión del experimento que reparta, y tiene que
ser explícita. Queda anotado en `design/contrato-unidades.md`.

**Descartado: colapsar las dos adyacencias en una métrica de similitud.** Era la salida
obvia —un índice de cuánto se parecen los dos grafos— y habría escondido justo lo que
importa: que uno tiene grado constante por construcción y el otro no. Un solo número
que resume eso no distingue "grafos distintos" de "un grafo y una rejilla".

**Descartado: `inner join` de la grilla contra el tejido.** Habría hecho
`hexagonos_cobertura` más chica y el mapa imposible: sin las filas de los hexágonos sin
tejido no hay nada que dibujar deshilachado, y el mapa siguiente diría que ahí no hay
nada que mirar cuando lo que no hay es dato.

**El área media de celda no se cita en prosa, pero va al registro.** `tejido.area_mediana`,
`tejido.area_p05` y `tejido.area_p95` se emiten aunque este README no las use en ninguna
oración: la comparación de escala contra `hexagono.area_mediana` es el insumo natural del
siguiente experimento, y una cifra que no está en el registro es una cifra que alguien va
a escribir a mano.

**Colisión de tests entre experimentos, encontrada acá.** Dos `test_loader.py` con el
mismo basename y sin paquete rompían la **recolección** entera de pytest, no un test. Se
resolvió con `--import-mode=importlib` en `pyproject.toml`. Aparte, `import loader` mete
todos los loaders bajo la misma clave de `sys.modules`; este experimento carga el suyo
por ruta explícita con nombre único, y portar `donde-falla-el-dato` al mismo patrón queda
en `inwatch-0ge`.

**El CI ahora sincroniza con `--extra geo`.** Los tests de este experimento hacen
`importorskip("city2graph")`: sin el extra se saltaban enteros y el CI quedaba verde sin
haber verificado nada, que es peor que quedar rojo. El extra no arrastra torch — eso vive
en `ml` — así que el costo es geopandas y poco más.
