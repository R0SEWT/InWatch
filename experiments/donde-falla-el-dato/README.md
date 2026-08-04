# donde-falla-el-dato — Dónde el mapa deja de ser confiable

> Vigilado por `canon check`: cada cifra portante de este archivo lleva su ancla.

## La pregunta

¿En qué parte de Lima y Callao el mapa de denuncias deja de decir algo, y cómo se ve
esa frontera? Casi ningún mapa de crimen del mundo dibuja dónde falla su propio dato:
pinta lo que tiene y deja el resto en blanco, que el ojo lee como calma.

La respuesta corta, y es más dura de lo que parecía antes de medirla: de las
4172 celdas de la grilla canónica,
<!-- CANON: conteo.celdas_grilla = 4172 -->
solo 1439 tienen al menos un registro policial geocodificado
<!-- CANON: conteo.celdas_con_registro = 1439 -->
— el 34.5 % de la grilla.
<!-- CANON: cobertura.celdas_con_registro = 34.5 -->
Y solo el 33.2 % puede además evaluarse, porque a la celda le tiene que constar
también una medida de qué tan bien geocodifica su distrito.
<!-- CANON: cobertura.celdas_evaluables = 33.2 -->

## Qué se manipula

Dos pisos independientes y un selector, en ese orden de importancia:

| Control | Qué mueve |
|---|---|
| **Piso de calidad** | mínimo de calidad geocodificadora distrital para dibujar la celda |
| **Piso de soporte** | mínimo de registros que deben sostener la celda |
| **Qué mide la confianza** | cuál de las tres medidas de calidad se usa |

Subir el piso disuelve el mapa. Lo que hay que ver mientras se disuelve no es cuántas
celdas se pierden, sino **cuántos registros sobreviven**: la fracción de celdas cae en
picada mientras la fracción de datos apenas se mueve. Eso es el sesgo de denuncia visto
de frente — el dato se concentra donde ya se miraba.

Los dos pisos se mantienen separados a propósito. Combinarlos en un índice de confianza
ponderado sería inventar una cifra portante con pesos elegidos a mano, que es
exactamente lo que `inwatch.canon` existe para impedir.

## Unidad espacial

`h3_8`, clave `h3_index`. Una fila por celda de la grilla canónica de Lima + Callao,
incluidas las celdas sin ningún registro. No cruza unidades, así que no usa tabla de
correspondencia. Ver `design/contrato-unidades.md`.

**La calidad geocodificadora es distrital, no celular.** `real_coord_ratio` viene por
fila en el artefacto de origen, pero es constante dentro de cada ubigeo. Se propaga a
todas las celdas del distrito y las columnas se llaman `*_distrito` para que ningún
consumidor pueda confundirlo con resolución celular. Fingir grano celular sobre una
medida distrital es el mismo error, un piso más abajo, que el mapa de denuncias
fingiendo ser un mapa de crimen.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `h3_admin.parquet` | `infelix/data/silver/h3_features/` | `h3_8` | grilla canónica + adscripción distrital |
| `h3_feature_matrix.parquet` | `infelix/data/silver/` | `h3_8` | solo para verificar que la grilla es la misma |
| `h3_observed_geocoded.parquet` | `infelix/data/silver/h3_features/` | `h3_8` | conteo observado y `real_coord_ratio` |
| `geocode_success_distrito.csv` | `infelix/data/silver/analysis/` | ubigeo | auditoría distrital de geocodificación |

Se leen **read-only** del repo de origen y la salida se exporta a
`data/silver/donde-falla-el-dato/`, con la procedencia de cada entrada registrada por
`canon.emit` (hash de cada input y del script emisor). El repo de origen nunca se
escribe.

### Las tres medidas no son intercambiables

Sus rangos ni se solapan, así que no son tres versiones del mismo número y elegir una
cambia qué significa "confiable":

| Columna | Qué mide | Rango observado |
|---|---|---|
| `geo_exito_distrito` | geocodificación exitosa | 22.5 % – 72.6 % |
| `geo_con_coord_distrito` | registro con alguna coordenada | 52.9 % – 95.0 % |
| `geo_coord_real_distrito` | coordenada real, no imputada | 56.6 % – 90.4 % |

<!-- CANON: geocode.exito_min = 22.5 -->
<!-- CANON: geocode.exito_max = 72.6 -->
<!-- CANON: geocode.con_coord_min = 52.9 -->
<!-- CANON: geocode.con_coord_max = 95.0 -->
<!-- CANON: geocode.coord_real_min = 56.6 -->
<!-- CANON: geocode.coord_real_max = 90.4 -->

Los extremos de la primera son Santa Anita y San Isidro. Los seis van al registro
aunque solo la primera se cite en prosa: una cifra tabulada es tan portante como una
en una oración, y el drift no distingue.

## Qué se ve

Un solo tono naranja, y **la opacidad lleva la confianza**. No hay rampa de color que
interpretar y no hay verde que se pueda leer como "acá no pasa nada". Una rampa
monocroma es monótona en luminosidad por construcción, así que no queda información
codificada en el matiz y no hay nada que verificar en deuteranopia. Lo que no se puede
sostener con dato, literalmente no se ve.

Las celdas no evaluables **no desaparecen**: se dibujan como un hexágono encogido al
34 % de su tamaño, un punteado que cubre la región entera sin afirmar nada sobre ella.

**Recordatorio no negociable**: ausencia de registro se dibuja deshilachada, nunca vacía
ni verde.

## Cómo correr

```bash
uv sync --extra viz
uv run python experiments/donde-falla-el-dato/loader.py
uv run marimo edit experiments/donde-falla-el-dato/notebook.py
```

## Verificación

- [x] `uv run pytest` en verde, incluidos los tests que corren sin datos
- [x] `uv run ruff check .` limpio
- [x] `uv run canon check` sin fallos
- [x] El loader es determinista: dos corridas dan los mismos hashes de procedencia
- [x] Render revisado en claro y oscuro, y el punteado se subió tras mirarlo (ver abajo)
- [x] Contraste: no hay información en el matiz, así que la deuteranopia no aplica
- [x] Notebook exportado y servido en un navegador: las nueve celdas corren sin error,
      deck.gl monta el mapa y la consola queda sin errores. El encuadre se corrigió tras
      ver la captura — entraba medio mar y se cortaba el borde este.

Las capturas de verificación no se versionan: son regenerables con los comandos de
arriba, y el repo versiona reportes, no imágenes de una corrida.

## Decisiones tomadas

**El número huérfano queda sustituido, no refutado de palabra.** El proyecto Wachi
afirma una cobertura "medida de 26 % (Ate) a 68 % (Miraflores)". Medido contra la
auditoría real: Ate (ubigeo 150103) está en 40.9 %
<!-- CANON: geocode.exito_ate = 40.9 -->
y Miraflores (150122) en 53.1 %.
<!-- CANON: geocode.exito_miraflores = 53.1 -->
Ni el par ni el rango aparecen en ningún artefacto. El rango real, sobre los mismos
datos, es 22.5 % – 72.6 %, y va con hash de sus inputs.

**No hay un solo modo de falla, hay dos, y el segundo es peor.** Una celda puede no
tener registro, o puede pertenecer a un distrito que nunca se auditó. En el segundo caso
no se afirma que el dato sea malo: se afirma que no se sabe. Son 12 distritos
<!-- CANON: conteo.distritos_sin_auditoria = 12 -->
y el 39.7 % de la grilla,
<!-- CANON: cobertura.celdas_sin_auditoria = 39.7 -->
**el Callao entero entre ellos** — su cobertura observada es 14.3 %
<!-- CANON: cobertura.celdas_con_registro_callao = 14.3 -->
contra 43.7 % en Lima.
<!-- CANON: cobertura.celdas_con_registro_lima = 43.7 -->
Por eso `sin_auditoria` le gana a `sin_registro` en la precedencia de `motivo`: no poder
medir no es lo mismo que medir mal.

**La superficie latente vive exactamente donde vive la auditoría.** Las 2517 celdas con
auditoría distrital
<!-- CANON: conteo.celdas_auditadas = 2517 -->
son, celda por celda, las de `crime_latent_surface.parquet`.
No es aproximado: es identidad de conjuntos, y hay un test que la vigila. Significa que
la corrección observado→latente de E1 no repara el punto ciego de cobertura, lo hereda —
está definida justo sobre el subconjunto auditable. Es un resultado que cruza los dos
experimentos y conviene que E1 lo sepa antes de escribir su propia prosa.

**Descartado: un score único de confianza.** Era la salida obvia para tener un solo
canal de opacidad, y es donde este experimento se habría convertido en el problema que
denuncia. Los pesos no salen de ningún lado.

**Descartado: filtrar las celdas sin registro del artefacto.** Habría hecho la tabla más
chica y el mapa imposible: sin las filas ausentes no hay nada que dibujar deshilachado.

**Ajustado tras mirar el render, no antes.** El punteado empezó en `coverage=0.28` con
alfa 70. Al mirarlo, los huecos **interiores** de la mancha observada —celdas sin
registro rodeadas de celdas con registro— se leían como fondo liso, o sea como "acá no
pasa nada", que es literalmente el error que el punteado existe para evitar. Que la
textura se vea en los bordes no basta. Subió a `coverage=0.34` con alfa 115.

**El mapa va por `to_html` + `mo.iframe`, no dejando que marimo formatee el `Deck`.**
El `_repr_html_` de pydeck importa IPython, que no es dependencia de este repo, y falla
en silencio: la celda del mapa queda vacía sin levantar error. Se descubrió exportando
el notebook y leyendo el HTML, no corriéndolo. De paso se le quita a la plantilla de
pydeck el `<script>` del loader de Google Maps, que trae una API key ajena incrustada y
se inyecta pase el proveedor de basemap que se le pase.

**Procedencia con rutas absolutas.** Los inputs viven fuera de la raíz del repo, así que
el registro guarda su ruta absoluta en vez de una relativa. Es correcto para el hash
—identifica el archivo exacto que se leyó— pero ata las entradas a esta máquina. Queda
anotado como deuda, no resuelto acá.
