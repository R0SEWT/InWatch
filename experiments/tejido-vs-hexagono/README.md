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
Sobre Lima y Callao, la tesselación morfológica produce 215427 celdas
<!-- CANON: tejido.celdas = 215427 -->
donde el hexágono pone 4172.
<!-- CANON: conteo.celdas_grilla = 4172 -->

La respuesta corta: el **11.0 %** de las celdas
morfológicas cae repartido entre dos o más hexágonos,
<!-- CANON: correspondencia.celdas_partidas = 11.0 -->
y eso es el **27.2 %** del área del tejido.
<!-- CANON: correspondencia.area_partida = 27.2 -->
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
0.000000990 en términos relativos.
<!-- CANON: correspondencia.desvio_masa = 0.000000990 -->
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
5.87 sobre las 4172 celdas de la grilla:
<!-- CANON: hexagono.grado_medio = 5.87 -->
seis vecinos para todo hexágono interior **por construcción del dibujo**. No es una
medición de la ciudad. El tejido tiene grado medio 3.05
<!-- CANON: tejido.grado_medio = 3.05 -->
con desviación 2.30,
<!-- CANON: tejido.grado_desviacion = 2.30 -->
y **la dispersión es el dato**: el grado varía con la forma real de la manzana porque
`touched_to` solo une celdas dentro de la misma manzana cerrada. Dos edificios a ambos
lados de una avenida se tocan en el mapa y no son vecinos acá.

**3 · El hueco.** El 64.6 % de la grilla no tiene
una sola celda morfológica debajo,
<!-- CANON: correspondencia.hexagonos_sin_tejido = 64.6 -->
y en la mitad de los que sí tienen, el tejido cubre
31.7 % del hexágono o menos.
<!-- CANON: correspondencia.cobertura_areal_mediana = 31.7 -->
Ese hueco **no aparece solo**: es lo que deja ver la máscara de área construida, y sin
ella daba cero por construcción (ver *Decisiones tomadas*).
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

**La primera corrida tarda ~45 min; las siguientes, ~2.** La tesselación de ~170 000
edificios es 40 de esos 45 minutos y **no depende de `RADIO_CONSTRUIDO_M`**, así que se
cachea en `data/silver/tejido-vs-hexagono/_cache_tejido_*`. Sin eso, "el radio es un
parámetro" era una frase bonita: nadie barre un parámetro a 45 minutos por punto.

La clave del caché no hashea el gpkg de 1,1 GB —costaría más que el ahorro— sino la
identidad del archivo, cuántos insumos entraron, el área del límite y la lista de vías
barrera. Ante la duda, `rm data/silver/tejido-vs-hexagono/_cache_tejido_*` y recomputa.

## Verificación

- [x] `uv run pytest -m "not needs_data"` en verde, con el extra `geo` instalado
- [x] `uv run ruff check .` limpio
- [x] `uv run canon check` sin fallos
- [x] El test de conservación de masa que exige `design/contrato-unidades.md` existe y
      corre **sin datos**, sobre geometría sintética cuadrada
- [x] La tabla de correspondencia se verifica además sobre el artefacto real
      (`needs_data`), incluido que no reparta masa hacia una celda no declarada
- [x] Sobre el artefacto real (`needs_data`): ningún hexágono queda cubierto más de una
      vez, y la grilla **sí** deja hueco donde no hay edificación. Los dos invariantes se
      comprobaban solo sobre geometría sintética, donde se cumplían siempre — y por eso
      `inwatch-72j` llegó hasta la emisión sin que nada avisara

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

**El hueco hay que construirlo: la tesselación no lo deja sola.** Es la decisión más
importante del loader y costó una corrida entera descubrirla (`inwatch-72j`).
`morphological_graph(limit=)` hace tesselación **encerrada**, que particiona *todo* el
interior del límite sin dejar huecos. Corriendo así, los 4172 hexágonos salían con
tejido, la celda del edificio más cercano se estiraba sobre el desierto —415 celdas más
grandes que un hexágono entero, la mayor de 136 km²— y `hexagonos_sin_tejido` daba
0,0 % **por construcción**: una constante disfrazada de medición. Peor que inútil,
porque dibujaba la ausencia de dato como si fuera ciudad, que es exactamente lo que este
proyecto existe para no hacer.

Por eso la tesselación se recorta contra una **máscara de área construida**: la unión de
los buffers de los edificios OSM. Fuera de ella no hay unidad morfológica, hay hueco
declarado. Ninguna celda desaparece al recortar —cada una contiene su edificio semilla y
la máscara contiene a todos los edificios—, así que las aristas `touched_to` siguen
valiendo tal cual: se recorta el dominio sobre el que se mide, no la morfología medida.

**El radio de la máscara es la perilla, y está declarado.** `RADIO_CONSTRUIDO_M = 100`,
arriba del loader. No es arbitrario: dos edificios separados por menos de 200 m quedan
en la misma mancha, que es el criterio clásico de aglomeración urbana para delinear área
construida a partir de edificación. Con un radio mucho menor la trama densa se fragmenta
en islas por cada avenida ancha; con uno mucho mayor la máscara vuelve a tragarse el
desierto y reaparece el problema. Moverlo mueve `hexagonos_sin_tejido` y `area_partida`:
es el experimento, no un detalle de implementación.

**Las celdas se desolapan antes de medir.** `morphological_graph` no siempre entrega
celdas disjuntas —avisa de 81 enclosures con celdas que se solapan o dejan huecos— y
sobre el artefacto sin reparar el peor hexágono tenía un 5,5 % de suelo contado dos
veces, con `Σ frac_h3` llegando a 1,068. Eso es imposible por definición y es una fuga de
masa silenciosa para cualquier experimento que reparta cantidades con esta tabla. El
desempate es **gana el `tess_id` menor**: arbitrario y declarado, porque lo que no puede
ser arbitrario es que el área disputada se cuente dos veces. Hay un guard en
`cobertura_por_hexagono` que aborta si algún hexágono queda cubierto más de una vez, y un
test `needs_data` que lo verifica sobre la salida real — el invariante solo se
comprobaba sobre geometría sintética, y por eso el fallo llegó hasta la emisión.

**Las aristas H3 se normalizan a no dirigidas antes de comparar.** El artefacto de origen
guarda cada vecindad dos veces, una por sentido: son 12249 pares únicos.
<!-- CANON: hexagono.aristas = 12249 -->
Compararlas contra las 328223 del tejido sin normalizar
<!-- CANON: tejido.aristas = 328223 -->
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
