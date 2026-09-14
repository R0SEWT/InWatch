# corredores-criticos — dónde se concentra el flujo potencial del eje Metropolitano

> En construcción (bead `inwatch-92d`, TP de Complex Networks, tema 2). Este archivo está
> **vigilado** por `canon check`: toda cifra portante llegará con su ancla `CANON:`.

## La pregunta

¿Qué tramos e intersecciones de la red vial concentran el flujo **potencial** del eje
Metropolitano centro-sur? Se mide con betweenness ponderada por longitud y por tiempo de
viaje, y se contrasta con las vías que OSM declara arteriales. Es flujo potencial, no
observado: no hay aforos, así que nada de lo que salga habla del tránsito real.

## Qué se manipula

- **El peso**: longitud o tiempo de viaje. Cambiarlo es preguntar si el corredor lo es
  por distancia o por velocidad.
- **El tamaño del top**: cuántos tramos o intersecciones cuentan como críticos, y cómo
  cambia su coincidencia con las arterias declaradas.

## Unidad espacial

`tramo` e `interseccion` (ver `design/contrato-unidades.md`, sección *Las unidades de red
vial*). La betweenness se calcula sobre el grafo **dirigido** para respetar los sentidos
de circulación, y se proyecta a tramos para dibujar.

## Área de estudio

Área A: Cercado de Lima, La Victoria, San Isidro, Miraflores y Surquillo, por UBIGEO,
desde la fuente `distritos_limites`. Concentra estaciones del Metropolitano y de la
Línea 1, los estadios Nacional y Matute, y la Vía Expresa.

## Velocidades imputadas

osmnx completa el `maxspeed` que falta con la media de las aristas del mismo tipo de vía
y, si ese tipo no tiene ninguna, con la media del grafo. El loader marca cada arista con
`maxspeed_observado` **antes** de imputar, y reporta qué parte de la red —por aristas y
por longitud— lleva velocidad imputada: el tiempo de viaje de esas aristas es un supuesto,
no un dato.

## Datos

| Fuente (`inwatch.fuentes`) | Qué aporta | Titularidad |
|---|---|---|
| `distritos_limites` | polígono del área | INEI |
| red `drive` de OSM | grafo, descargado con osmnx vía Overpass | © OpenStreetMap contributors (ODbL) |
| `transit_stations` | estaciones del Metropolitano y la Línea 1 | infelix |

## Cómo correrlo

```bash
uv sync --extra geo --extra viz
uv run fuentes estado                                    # ¿resuelven distritos_limites y transit_stations?
uv run python experiments/corredores-criticos/loader.py  # descarga, velocidades, GraphML
```
