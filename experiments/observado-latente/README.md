# observado-latente — el slider entre lo denunciado y lo latente

## La pregunta

Corregir un mapa de denuncias por subdenuncia lo oscurece entero. ¿También lo
**reordena**? Es decir: ¿las celdas que la corrección señala como más cargadas son otras
que las que ya señalaba el registro policial, o son las mismas con otro número encima?

La respuesta importa porque decide qué tipo de objeto es la corrección. Si reordena, es
un mapa nuevo. Si no, es una recalibración de magnitud — y entonces el valor de la
corrección está en *cuánto* y en *de qué delito*, no en *dónde*.

## Qué se manipula

Un slider entre la superficie observada y la latente, con interpolación lineal
`v(α) = (1−α)·observado + α·latente`. En `α = 0` se ve el registro policial; en `α = 1`,
el estimador latente. **La escala de color no se mueve nunca**: está fijada al techo de
la superficie latente, para los dos paneles.

Esa decisión no es estética y no se re-litiga. Si cada panel se autonormaliza, ambos se
ven igual de intensos y la brecha —que es el hallazgo— desaparece de la imagen. Viene de
`infelix/scripts/figures_carrera.py`, donde ya está justificada.

Dos controles secundarios, ambos sobre la honestidad de la vista y no sobre el dato:

- **codificar incertidumbre** — la opacidad de cada celda es proporcional a la estrechez
  de su intervalo. Apagarlo muestra el mapa que uno dibujaría sin pensar en el IC.
- **declarar «no evaluable»** — umbral sobre el ancho relativo del intervalo. Bajarlo
  convierte en deshilachadas las celdas cuyo número no sostiene un color. Es el control
  que hace visible cuánto del mapa es, en rigor, incognoscible.

## Unidad espacial

`h3_8`, clave `h3_index`. Es la unidad en la que el artefacto de origen está calculado.

Ver `design/contrato-unidades.md`. Este experimento **no cruza unidades**: no hay tabla
de correspondencia porque no hay nada que corresponder. La advertencia del contrato sigue
en pie y está repetida en el notebook: un hexágono res-8 promedia sobre el borde entre
tejidos urbanos distintos, y el escalón que la escalera de atribución encontró
significativo es la manzana censal, no el hexágono.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `crime_latent_surface.parquet` | `infelix/data/silver/` | `h3_8` × año × categoría | 86 673 filas. Entrada, **read-only** |
| `celdas.parquet` | este loader | `h3_8` | una fila por celda, pooled 2018–2024 × 5 categorías |
| `fronteras.parquet` | este loader | `h3_8` | vértices de cada hexágono, formato largo |
| `composicion.parquet` | este loader | categoría | shares y multiplicador por delito |

Los artefactos se leen read-only del repo de origen y se exportan a `data/` con su
procedencia registrada en `registry/canonical_numbers.json`. Nunca se escribe en el repo
de origen.

### Por qué la geometría va en un parquet aparte

El contrato de unidades dice «sin geometría en las tablas de features; se reconstruye al
dibujar». Reconstruirla al dibujar exigiría importar `h3` en el notebook, y `h3` no corre
en Pyodide — que es la razón de existir de la separación loader/notebook.

La salida es un compromiso explícito: `celdas.parquet` queda geometry-free como manda el
contrato, y la geometría vive en `fronteras.parquet`, que la capa de presentación lee
como diccionario. Se reconstruye una sola vez, en el loader, no quince veces en quince
parquets de features.

## Qué se ve

Dos paneles hombro con hombro sobre una sola rampa `carrera_teal` —secuencial de un solo
tono, luminosidad monótona, sin verde para «bajo riesgo»—, más dos vistas de apoyo:

- **rango observado vs rango latente**: la nube pegada a la diagonal *es* el hallazgo.
- **composición por delito**: lo que sí se da vuelta.

Codificación de lo que no se sabe:

- **Sin registro → deshilachada.** Sin relleno, solo trama y un hilo tenue. Nunca vacía,
  nunca verde. Son celdas donde nadie denunció nada en siete años.
- **Intervalo ancho → celda desvaída.** La opacidad baja hasta 0,30.
- **Sobre el umbral → deshilachada también.** Se trata igual que la ausencia de registro,
  porque es lo mismo: un número que no sostiene una afirmación.

## Cómo correr

```bash
uv sync --extra geo --extra viz
uv run python experiments/observado-latente/loader.py    # → data/silver/observado-latente/
uv run marimo edit experiments/observado-latente/notebook.py
```

## Los números

Todos salen del registro canónico. Ninguno está escrito a mano acá.

| | |
|---|---|
| Multiplicador global, las 5 categorías | ×10.3 |
| ρ de Spearman entre superficie observada y latente | 0.997 |
| Solapamiento del top-50 de celdas | 0.82 |
| Celdas sin una sola denuncia registrada | 924 de 2517 |
| Celdas con registro (las que sostienen el ρ) | 1593 |
| Tope de la rampa de color compartida | 59974 hechos |
| Pico de la superficie latente | 101459 hechos |
| Estafa: share observado → latente | 4.3 % → 32.1 % |
| Robo callejero: share observado → latente | 54.1 % → 24.2 % |

<!-- CANON: multiplier.total = 10.3 -->
<!-- CANON: rango_espacial.spearman = 0.997 -->
<!-- CANON: rango_espacial.top_overlap = 0.82 -->
<!-- CANON: conteo.celdas_superficie_sin_observado = 924 -->
<!-- CANON: conteo.celdas_superficie = 2517 -->
<!-- CANON: conteo.celdas_superficie_con_observado = 1593 -->
<!-- CANON: escala.tope = 59974 -->
<!-- CANON: escala.pico_latente = 101459 -->
<!-- CANON: superficie_share_observado.estafa = 4.3 -->
<!-- CANON: superficie_share_latente.estafa = 32.1 -->
<!-- CANON: superficie_share_observado.robo_hurto_callejero = 54.1 -->
<!-- CANON: superficie_share_latente.robo_hurto_callejero = 24.2 -->

Los cinco multiplicadores por categoría (`multiplier.<cat>.victim`) se emiten también, y
**duplican a propósito** los del repo de origen: robo ×4.6, extorsión ×6.9, secuestro
×8.4, violencia familiar ×11.1, estafa ×76. Si alguno divergiera del valor publicado
allá, el pipeline de acá se rompió.

<!-- CANON: multiplier.robo_hurto_callejero = 4.6 -->
<!-- CANON: multiplier.extorsion = 6.9 -->
<!-- CANON: multiplier.secuestro = 8.4 -->
<!-- CANON: multiplier.violencia_familiar_sexual = 11.1 -->
<!-- CANON: multiplier.estafa = 76 -->

## El hallazgo

**La corrección no reordena el mapa.** ρ de Spearman 0.997 sobre las 1593 celdas con
registro, y el top-50 de celdas más cargadas se solapa en 0.82 entre las dos superficies.
La magnitud se multiplica por diez; el orden espacial casi no se mueve.

Lo que sí se da vuelta es la **composición**: el robo callejero deja de ser la mitad de
la superficie y la estafa —la categoría con peor tasa de denuncia— pasa de 4,3 % a
32,1 %. La corrección cambia *de qué* está hecho el riesgo, no *dónde* está.

Es un resultado más honesto y más incómodo que un «todo cambia», y es también el que
hace al experimento útil: dice que quien ya usaba el mapa de denuncias para priorizar
territorio no estaba tan equivocado en el ranking, y sí lo estaba —mucho— en la escala
del problema y en qué delito lo compone.

## Verificación

- [x] `uv run pytest` en verde — 27 tests
- [x] `uv run canon check` sin fallos — 17 anclas verificadas contra el registro
- [x] `uv run ruff check .` limpio
- [x] El loader es determinista: dos corridas seguidas no producen diff en el registro
- [x] El notebook corre de punta a punta (`marimo export html`) sin traceback, en
      `α = 0`, `α = 0.6` y `α = 1`
- [x] Revisado en claro y en oscuro (control «fondo oscuro»)
- [x] Ejercido el camino de «no evaluable» con el umbral en 3.5: el mapa queda casi
      todo deshilachado, que es el resultado correcto y vale la pena mirarlo
- [x] Rampa de luminosidad monótona, verificada numéricamente: estrictamente
      decreciente en visión normal (span 0,854) y bajo simulación de deuteranopia
      (span 0,699)

**Caveat de la rampa**, encontrado al verificar: bajo deuteranopia los dos escalones
más claros quedan a ΔL ≈ 0,02, prácticamente indistinguibles. Es inherente a una rampa
secuencial que arranca casi en blanco. No se corrigió porque el extremo que sostiene la
lectura —dónde están los focos— es el oscuro, y ahí la separación es amplia; pero
significa que esta vista **no sirve para distinguir «bajo» de «muy bajo»**. Para eso
haría falta otra codificación, no otra rampa.

## Decisiones tomadas

- **Interpolación lineal y no logarítmica** entre las dos superficies. Se probó pensar el
  slider como «fracción de la corrección aplicada» en escala log; se descartó porque el
  valor intermedio dejaba de tener unidades interpretables. Con la lineal, `v(α)` sigue
  siendo un conteo de hechos en todo el recorrido.
- **El tope de la escala es el percentil 99,5 del latente, no el máximo.** La cola es tan
  larga (pico 101459 contra un tope de 59974) que con el máximo casi todo el mapa queda
  en el primer escalón de color. La barra lleva flecha de desborde. El tope no se
  recalcula en el notebook: sale del registro, como cualquier otra cifra portante.
- **El Spearman se calcula solo sobre las celdas con registro.** Incluir las 924 celdas
  donde ambas superficies valen cero mete empates que no significan acuerdo entre
  superficies sino ausencia de dato en las dos. La cifra honesta es la de 1593 celdas.
- **`latente_rate_100k` de la fuente no se usa.** Tiene filas con tasa positiva y latente
  cero, así que no es la tasa de esta superficie sino un agregado de otra resolución. Se
  trabaja en conteos, que es lo que la figura del repo de origen compara.
- **El IC por celda suma los extremos de las cinco categorías.** Equivale a asumir que
  las cinco se equivocan en la misma dirección: es una cota conservadora, no un intervalo
  conjunto. Un IC conjunto propio exigiría los posteriors por categoría, que no están en
  este artefacto. Queda anotado como límite en el notebook.
- **Se descartó pydeck** para el mapa pese a que `H3HexagonLayer` acepta índices H3
  directamente: arrastra un runtime JS que complica el export a WASM. Con matplotlib y
  `PolyCollection` el camino a Pyodide es el mismo que el del resto del repo.
- **El deshilachado se dibuja con trama fina (`hatch.linewidth = 0.3`).** Con el ancho por
  defecto, las 924 celdas sin registro forman una malla que se come el mapa: la ausencia
  terminaba gritando más que el dato, que es el error opuesto al que la regla previene.
