# corredores-criticos — dónde se concentra el flujo potencial del eje Metropolitano

> Vigilado por `canon check`: cada cifra portante de este archivo lleva su ancla.
> TP de Complex Networks (UPC 2026-2), tema 2. Bead `inwatch-92d`.

## La pregunta

¿Qué tramos e intersecciones de la red vial concentran el flujo **potencial** del eje
Metropolitano centro-sur, y coincide eso con lo que OSM declara arterial?

**Flujo potencial, no observado.** No hay datos de aforo, así que nada de lo que sigue
habla del tránsito real: la betweenness cuenta caminos mínimos entre pares de
intersecciones, suponiendo demanda uniforme. Es una propiedad de la forma de la red.

## Qué se manipula

- **El peso**: longitud o tiempo de viaje. Es el control principal, y mover ese
  deslizador **reordena el mapa**: las dos betweenness correlacionan
  0.764 en intersecciones
  <!-- CANON: corredores.corr.length_travel_time_nodos = 0.764 -->
  y solo 0.715 en tramos.
  <!-- CANON: corredores.corr.length_travel_time_tramos = 0.715 -->
  No son la misma pregunta: una mide rodeo, la otra mide demora.
- **El tamaño del top**: cuántos tramos cuentan como críticos, y cómo cambia su
  coincidencia con las arterias declaradas.

## Unidad espacial

`tramo` e `interseccion` (ver `design/contrato-unidades.md`). La betweenness se calcula
sobre el grafo **dirigido**, para que una vía de un solo sentido no cargue caminos que
ningún vehículo puede recorrer, y se proyecta a tramos para dibujar.

## Área de estudio

Área A: Cercado de Lima, La Victoria, San Isidro, Miraflores y Surquillo, por UBIGEO,
desde la fuente `distritos_limites_area_a`, que viaja en el repo.

| | |
|---|---|
| Intersecciones | 7559 <!-- CANON: corredores.conteo.nodos = 7559 --> |
| Aristas dirigidas | 15813 <!-- CANON: corredores.conteo.aristas = 15813 --> |
| Tramos no dirigidos | 12025 <!-- CANON: corredores.conteo.tramos = 12025 --> |
| Estaciones del Metropolitano y la Línea 1 | 20 <!-- CANON: corredores.conteo.estaciones_area_a = 20 --> |
| Estadios | 2 <!-- CANON: corredores.conteo.estadios_area_a = 2 --> |

`simplify=True` elimina el 76.7 % de los nodos
<!-- CANON: corredores.pct.reduccion_simplificacion = 76.7 -->
del grafo crudo: son vértices de geometría, no intersecciones.

### Por qué esta área

- **Hay un corredor declarado contra el cual leer la betweenness.** Es el tramo
  centro-sur del Metropolitano, que cruza los cinco distritos de norte a sur y, junto con
  la Línea 1, tiene 20 estaciones dentro del polígono. El tema pregunta por corredores
  críticos; un área sin un corredor de transporte reconocido dejaría el resultado sin
  nada con qué contrastarse.
- **Tiene dos generadores de viajes puntuales**, los estadios Nacional y Alejandro
  Villanueva (Matute), que entran como capa complementaria.
- **El tamaño permite el cálculo exacto.** El grafo cumple con holgura el mínimo del
  enunciado (3 000 nodos y 6 000 aristas) y queda muy por debajo del máximo recomendado
  (60 000 nodos). La betweenness exacta cuesta minutos, así que el resultado principal no
  depende de muestreo; la aproximación con `k` solo se corre para medir su error.
- **`drive`, porque el tema es tránsito vehicular.** El enunciado lo exige para los temas
  de tránsito y reserva `walk` para accesibilidad peatonal.
- **Mide lo mismo en cualquier máquina.** El área se define por UBIGEO sobre un
  polígono versionado en el repo, y su superficie, 54.2 km²,
  <!-- CANON: corredores.area.km2 = 54.2 -->
  se calcula en EPSG:32718 a partir de ese polígono, no se copia de otra fuente.

## Forma de la red

Las métricas globales que el Hito 1 pide, normalizadas por área donde dependen de la
escala (`metricas.py`).

| Métrica | Valor |
|---|---|
| Intersecciones por km² | 131.1 <!-- CANON: corredores.area.intersecciones_por_km2 = 131.1 --> |
| km de calle por km² | 19.1 <!-- CANON: corredores.area.km_calle_por_km2 = 19.1 --> |
| Densidad dirigida, m/n(n−1), ×10⁴ | 2.768 <!-- CANON: corredores.red.densidad_x1e4 = 2.768 --> |
| Arcos salientes por intersección | 2.092 <!-- CANON: corredores.red.grado_medio_salida = 2.092 --> |
| Calles por intersección (`street_count`) | 3.233 <!-- CANON: corredores.red.calles_por_nodo = 3.233 --> |
| Intersecciones de 3 calles | 59.4 % <!-- CANON: corredores.pct.nodos_3_calles = 59.4 --> |
| Intersecciones de 4 calles o más | 34.4 % <!-- CANON: corredores.pct.nodos_4_o_mas = 34.4 --> |
| Callejones sin salida | 5.9 % <!-- CANON: corredores.pct.nodos_callejon = 5.9 --> |
| Componentes fuertemente conexas | 144 <!-- CANON: corredores.conteo.scc = 144 --> |
| Nodos en la componente fuerte gigante | 97.2 % <!-- CANON: corredores.pct.nodos_scc_gigante = 97.2 --> |
| Componentes débilmente conexas | 1 <!-- CANON: corredores.conteo.wcc = 1 --> |
| Circuidad (Σ largo / Σ recta) | 1.018 <!-- CANON: corredores.red.circuidad = 1.018 --> |
| Entropía de orientación (nats) | 3.341 <!-- CANON: corredores.red.orientacion_entropia = 3.341 --> |
| Orden de orientación φ (0 = aleatoria, 1 = grilla) | 0.208 <!-- CANON: corredores.red.orientacion_orden = 0.208 --> |
| Clustering medio (grafo simple no dirigido) | 0.040 <!-- CANON: corredores.red.clustering_medio = 0.040 --> |

Cómo leerlas:

- **La densidad casi nula no es un defecto, es la naturaleza de una red plana.** Cada
  intersección toca unas tres calles sin importar cuántas haya en total, así que la
  densidad cae con n. Por eso la comparación útil es por km², no por pares de nodos.
- **Casi toda la red es mutuamente alcanzable.** Las otras 143 componentes fuertes son
  nodos que los sentidos únicos dejan sin retorno. Son pocos, pero la betweenness los
  trata como destinos inalcanzables, y por eso aparecen en Limitaciones.
- **Las calles son casi rectas y no forman una sola grilla.** La circuidad está muy cerca
  de 1. φ está mucho más cerca de 0 que de 1: conviven trazas con orientaciones
  distintas, que es justo lo que hace que el camino mínimo tenga que elegir corredor.
- **Pocos triángulos.** Las manzanas cierran ciclos de cuatro calles, no de tres, así que
  el clustering de una red vial es bajo por construcción.

Como métrica local, junto a la betweenness, se calcula la **closeness de llegada** por
longitud dentro de la componente fuerte gigante. Las dos casi no se ordenan igual
(ρ de Spearman = 0.241):
<!-- CANON: corredores.corr.closeness_betweenness_nodos = 0.241 -->
la closeness premia estar en el centro geográfico, y la betweenness, estar en el paso
obligado entre zonas. Un corredor crítico se define por lo segundo.

## Qué tan bueno es el dato

El enunciado pide declararlo, y conviene mirarlo antes que cualquier resultado.

| Atributo | Tramos sin dato |
|---|---|
| `maxspeed` | 23.0 % <!-- CANON: corredores.pct.sin_maxspeed = 23.0 --> |
| `lanes` | 35.4 % <!-- CANON: corredores.pct.sin_lanes = 35.4 --> |
| `name` | 6.0 % <!-- CANON: corredores.pct.sin_name = 6.0 --> |

Donde falta `maxspeed`, osmnx imputa con la media del tipo de vía. Eso alcanza al
30.1 % de las aristas dirigidas
<!-- CANON: corredores.pct.maxspeed_imputado_aristas = 30.1 -->
y al 25.1 % de la longitud.
<!-- CANON: corredores.pct.maxspeed_imputado_largo = 25.1 -->
**El tiempo de viaje de esas aristas es un supuesto, no un dato**, y toda la betweenness
por tiempo lo hereda. La imputación se concentra en calles locales: en `secondary`,
`primary` y `motorway` el `maxspeed` es observado en el 97-100 % de los casos.

## Resultados

### El peso decide qué es un corredor

Ya está arriba: 0.715 de correlación entre los dos rankings de tramos. Un corredor por
distancia no es un corredor por tiempo, y presentar solo uno esconde la mitad del mapa.

### La jerarquía de OSM reconoce parte de los corredores, no todos

Las arterias declaradas (`motorway`, `trunk`, `primary` y sus `_link`) son el
12.5 % de los tramos
<!-- CANON: corredores.pct.arterial_declarada_tramos = 12.5 -->
y el 16.3 % de la longitud.
<!-- CANON: corredores.pct.arterial_declarada_largo = 16.3 -->
Esa es la tasa base contra la que hay que leer todo lo demás.

| Peso | Precisión@100 | Exceso sobre la tasa base |
|---|---|---|
| longitud | 20.0 % <!-- CANON: corredores.pct.precision_top100_length = 20.0 --> | +7.5 pp <!-- CANON: corredores.pct.exceso_sobre_base_top100_length = 7.5 --> |
| tiempo de viaje | 28.0 % <!-- CANON: corredores.pct.precision_top100_travel_time = 28.0 --> | +15.5 pp <!-- CANON: corredores.pct.exceso_sobre_base_top100_travel_time = 15.5 --> |

Hay concentración real —el top está enriquecido en arterias respecto de la red—, pero
cuatro de cada cinco tramos críticos por longitud **no** están declarados arteriales.
Son corredores de hecho que la clasificación no reconoce, y son el hallazgo.

En el otro sentido, el 31.0 % de las arterias declaradas
<!-- CANON: corredores.pct.arterias_bajo_mediana_length = 31.0 -->
queda bajo la mediana de betweenness por longitud, y el 19.0 % por tiempo.
<!-- CANON: corredores.pct.arterias_bajo_mediana_travel_time = 19.0 -->

### Los corredores forman una columna vertebral, no puentes sueltos

El 91.0 % de los tramos del top-100 por longitud
<!-- CANON: corredores.pct.top_tramos_entre_hubs_length = 91.0 -->
tiene sus **dos** extremos en el top-100 de intersecciones, y el 85.0 % por tiempo.
<!-- CANON: corredores.pct.top_tramos_entre_hubs_travel_time = 85.0 -->
Es decir: lo crítico es un subgrafo conectado, no un conjunto disperso.

### Las capas de transporte tocan los corredores, pero no sus nodos

El 26.0 % de los tramos del top por longitud
<!-- CANON: corredores.pct.top_tramos_con_capa_length = 26.0 -->
cae dentro del buffer de una estación o un estadio, y el 33.0 % por tiempo.
<!-- CANON: corredores.pct.top_tramos_con_capa_travel_time = 33.0 -->
En cambio, **casi ninguna** de las 22 intersecciones asociadas a una capa entra al
top-100 de nodos: 0.0 % por longitud
<!-- CANON: corredores.pct.top_nodos_con_capa_length = 0.0 -->
y 1.0 % por tiempo.
<!-- CANON: corredores.pct.top_nodos_con_capa_travel_time = 1.0 -->
Ojo con sobreinterpretar el contraste: solo 22 nodos pueden coincidir con el top-100
de 7 559, así que lo esperable por azar ya era menos de un nodo. La cifra de tramos es
la informativa; la de nodos apenas dice que no hay coincidencia sistemática.

## Cuánto error admite la aproximación

La betweenness exacta cuesta unos 10 minutos por peso. La aproximación con `k`=500
<!-- CANON: corredores.conteo.k_aprox = 500 -->
fuentes muestreadas tarda 40 segundos y se midió contra la exacta sobre el mismo grafo,
por unidad y por peso:

| Unidad | Spearman (longitud) | Solape top-100 | Spearman (tiempo) | Solape top-100 |
|---|---|---|---|---|
| intersecciones | 0.966 <!-- CANON: corredores.error.spearman_nodos_length = 0.966 --> | 0.940 <!-- CANON: corredores.error.solape_top_nodos_length = 0.940 --> | 0.954 <!-- CANON: corredores.error.spearman_nodos_travel_time = 0.954 --> | 0.890 <!-- CANON: corredores.error.solape_top_nodos_travel_time = 0.890 --> |
| tramos | 0.935 <!-- CANON: corredores.error.spearman_tramos_length = 0.935 --> | 0.900 <!-- CANON: corredores.error.solape_top_tramos_length = 0.900 --> | 0.918 <!-- CANON: corredores.error.spearman_tramos_travel_time = 0.918 --> | 0.870 <!-- CANON: corredores.error.solape_top_tramos_travel_time = 0.870 --> |

En el área A se usa la **exacta**; la aproximación se reporta solo para saber cuánto
costaría escalar a un área mayor, donde 9 de cada 10 tramos del top se recuperan.

## Limitaciones

1. **El busway del Metropolitano está dentro del grafo.** El filtro `drive` de osmnx
   excluye `bus_guideway` pero no `highway=busway`, aunque OSM marque esas vías
   `access=no` (84 de 86 en el área A). Son el 0.4 % de los tramos
   <!-- CANON: corredores.pct.busway_tramos = 0.4 -->
   y el 0.7 % de la longitud,
   <!-- CANON: corredores.pct.busway_largo = 0.7 -->
   y acumulan el 0.1 % de la betweenness por longitud
   <!-- CANON: corredores.pct.busway_bc_length = 0.1 -->
   pero el 1.2 % por tiempo de viaje.
   <!-- CANON: corredores.pct.busway_bc_travel_time = 1.2 -->
   Hay 0 en el top-100 por longitud
   <!-- CANON: corredores.conteo.busway_en_top100_length = 0 -->
   y 1 por tiempo,
   <!-- CANON: corredores.conteo.busway_en_top100_travel_time = 1 -->
   y ese tramo **encabeza** el ranking. Un camino mínimo que lo use no está disponible
   para un vehículo particular. Se decidió mantenerlo y declararlo (bead
   `inwatch-92d.8`); excluirlo es el análisis de sensibilidad natural.
2. **Efecto de borde.** Los caminos que en la realidad saldrían del área y volverían a
   entrar quedan forzados adentro, lo que infla la betweenness de los tramos perimetrales.
3. **Demanda uniforme.** La betweenness pesa todos los pares de intersecciones igual,
   sin población ni empleo. No es un modelo de tránsito.
4. **El grafo tiene 144 componentes fuertemente conexas**, con una gigante de 7 346
   nodos. La normalización de networkx supone todos los pares conectados, así que los
   valores absolutos quedan subestimados hasta un ~6 % **por el mismo factor en toda
   unidad**: los rankings y los solapes no se ven afectados, pero un valor suelto no se
   lee como "fracción de todos los pares".

## Datos

| Fuente (`inwatch.fuentes`) | Qué aporta | Titularidad |
|---|---|---|
| `distritos_limites_area_a` | polígono del área, versionado en el repo | INEI (dato público) |
| red `drive` de OSM | grafo, descargado con osmnx vía Overpass | © OpenStreetMap contributors (ODbL) |
| `transit_stations` | estaciones del Metropolitano y la Línea 1 | infelix — **no viaja en el repo**: pídela al grupo y apúntala con `INWATCH_FUENTE_TRANSIT_STATIONS` |

## Cómo correrlo

Las cinco etapas, en orden. Cada una deja sus artefactos en
`data/silver/corredores-criticos/` y emite sus cifras al registro.

```bash
uv sync --extra geo --extra viz
uv run fuentes estado        # distritos_limites_area_a sale como `curado`

uv run python experiments/corredores-criticos/loader.py       # grafo, velocidades  (~1 min)
uv run python experiments/corredores-criticos/centralidad.py  # betweenness exacta  (~20 min)
uv run python experiments/corredores-criticos/capas.py        # estaciones, ranking (~1 min)
uv run python experiments/corredores-criticos/arterias.py     # contraste OSM       (~1 min)
uv run python experiments/corredores-criticos/metricas.py     # métricas globales   (~2 min)

uv run marimo edit experiments/corredores-criticos/notebook.py
```

Para la entrega, el notebook se exporta a `.ipynb` con sus salidas. El resultado está
versionado en [`entrega/hito1.ipynb`](entrega/hito1.ipynb), que se abre en GitHub sin
correr nada:

```bash
uv run --extra geo --extra viz --with nbformat python -m marimo export ipynb \
  experiments/corredores-criticos/notebook.py --include-outputs \
  -o experiments/corredores-criticos/entrega/hito1.ipynb
```

**Sin uv.** El entorno también está en `requirements.txt`, en la raíz, generado desde
`uv.lock` (la CI falla si se desincroniza):

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt nbformat
```

**En otra máquina** falta un solo insumo: `transit_stations.csv`, que no viaja en el
repo. Pídeselo al grupo y apúntalo antes de correr `capas.py`:

```bash
export INWATCH_FUENTE_TRANSIT_STATIONS=/ruta/a/transit_stations.csv
```

La cadena completa se reprodujo el 2026-09-24 desde un clon limpio en otra máquina (11
núcleos, Ubuntu): el grafo salió con los mismos nodos y aristas, las cifras del registro
coincidieron y el export no dio errores. Solo cambió el conteo del grafo **sin
simplificar**, en 4 nodos, porque OSM se editó en esos 9 días. Por eso el grafo
descargado se guarda en disco con su fecha. **No commitees
`registry/canonical_numbers.json` después de correr en tu máquina**: el GraphML nuevo
tiene otro hash y re-sellaría la procedencia de las 65 cifras sin que haya cambiado
ningún valor.
