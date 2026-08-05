# Contrato de unidades espaciales

> Este documento está **vigilado** por `canon check`: toda cifra portante que aparezca
> acá necesita su ancla `CANON:` en un comentario. Ver la sintaxis en el README.

Existe porque varios experimentos corren en paralelo y, sin un contrato escrito antes,
cada uno inventa su propia convención de rejilla. El resultado sería un conjunto de
mapas que no se pueden comparar entre sí — que es justo lo que este repo quiere evitar.

## La regla

**Todo artefacto declara su unidad.** No hay unidad por defecto ni inferencia por el
nombre de la columna.

Los cruces entre unidades pasan por una tabla de correspondencia explícita con su
factor de área. **Nunca por un join implícito.** Un `merge` entre una capa H3 y una
capa de manzanas que "parece funcionar" está repartiendo masa sin declarar cómo.

## Las tres unidades

| Unidad | Clave | Tipo | Origen | Geometría |
|---|---|---|---|---|
| `h3_8` | `h3_index` | `str` | grilla canónica H3 res-8, Lima + Callao | reconstruible con `h3.cell_to_boundary` |
| `manzana` | `mzn_id` | `str` | manzana censal INEI | polígono del shapefile INEI |
| `morfologica` | `tess_id` | `str` | `city2graph.morphological_graph` | polígono de la tesselación |

### Por qué tres y no una

La escalera de atribución del trabajo de origen midió once fuentes de datos y encontró
**un solo escalón significativo: la manzana censal INEI**. La forma urbana OSM y las
otras ocho fuentes resultaron nulas, con intervalos que cruzan cero, y el hallazgo
sobrevivió corrección por multiplicidad.

Eso dice que la señal es socioeconómica y estructural, a granularidad sub-distrital.
Un hexágono de ~530 m de arista no respeta manzanas: promedia sobre el borde entre un
tejido y otro. Pero H3 es la unidad en la que están calculados los artefactos
existentes, y la tesselación morfológica es la que respeta la forma real.

Ninguna es "la correcta". **Poder cambiar de unidad y ver moverse el resultado es uno
de los experimentos**, no una decisión previa a los experimentos.

## Las tablas de correspondencia que existen

| Cruce | Artefacto | Emitido por |
|---|---|---|
| `morfologica` ↔ `h3_8` | `correspondencia_h3_tejido.parquet` | `experiments/tejido-vs-hexagono/loader.py` |

Columnas del cruce, y por qué son dos factores y no uno:

- `area_m2` — área de la intersección. El piso de 1 m² descarta las astillas de
  precisión del borde compartido, que si no se contarían como reparto real.
- `frac_tess` — proporción **de la celda morfológica** que cae en ese hexágono.
  Reparte una cantidad del tejido hacia H3. Suma 1 en toda celda contenida en la grilla.
- `frac_h3` — proporción **del hexágono** que ocupa esa celda. Reparte una cantidad de
  H3 hacia el tejido. **No suma 1**, y el déficit no es un error de la tabla: es área
  del hexágono sin tejido edificado debajo.

Un factor solo no basta porque las dos unidades no se anidan. Usar `frac_tess` para
repartir en el sentido contrario duplicaría o perdería masa según qué tan cubierto esté
el hexágono, en silencio y sin que ningún test lo note.

**El déficit de `frac_h3` no se normaliza.** Escalarlo a 1 convertiría "acá no hay
tejido registrado" en "acá el tejido que hay lo es todo" — ausencia de evidencia
disfrazada de evidencia. Qué hacer con ese hueco es decisión del experimento que
reparta, y tiene que ser explícita.

## Convenciones de columna

Heredadas del contrato silver del repo de origen, que ya resolvió estos problemas:

- **Clave obligatoria** en toda tabla: `h3_index`, `mzn_id` o `tess_id`, como `str`.
- **`year`** solo cuando la fuente mide variación anual **real**. Una fuente estática
  replicada por año miente sobre su propia resolución temporal.
- **Prefijo por fuente** cuando el origen no sea obvio: `osm_*`, `inei_*`, `s2_*`.
- **`float32`** para features continuos; `int16` para `year`; boolean para flags.
- **Sin geometría en las tablas de features.** Se reconstruye al dibujar. Una columna
  de geometría duplicada en quince parquets es quince oportunidades de divergencia.
- **`left join` sobre la grilla canónica**, preservando `NaN`. Un `0` y un "no
  observado" son cosas distintas y el pipeline entero depende de no confundirlos —
  es la misma regla que *sin datos ≠ seguro*, expresada en el esquema.

## Cobertura y confianza

Toda tabla de observación lleva su medida de cobertura junto al valor. Sin eso, la capa
visual no puede cumplir la regla de dibujar deshilachado lo que no se observó bien.

Como mínimo: la proporción de registros con coordenada real por unidad, y el conteo de
eventos que sostiene cada celda. Un score alto sostenido por un evento y uno sostenido
por doscientos no son el mismo dato, y pintarlos igual es el error que este repo existe
para no cometer.

## Cómo añadir una unidad

1. Documentarla en la tabla de arriba: clave, tipo, origen, geometría.
2. Escribir la tabla de correspondencia contra al menos una unidad existente, con su
   factor de área.
3. Un test que verifique que la correspondencia no pierde ni inventa masa.
4. Declararla en el `README.md` del experimento que la usa.
