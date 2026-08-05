# curva-de-evaluabilidad — hasta dónde se puede saber si el mapa sirve

> Vigilado por `canon check`: cada cifra portante de este archivo lleva su ancla.

## La pregunta

Un modelo de riesgo se juzga por su desempeño en el registro que la ciudad tiene. ¿Y si el
registro es tan flaco que el juicio mismo deja de valer? La pregunta no es «¿el modelo
acierta?» sino la anterior: **¿se puede saber si acierta?**

La respuesta corta es que las dos cosas se rompen a ritmos muy distintos. Bajando la tasa
de geocodificación de 83.4 % —la real de Lima—
<!-- CANON: evaluabilidad.tasa_lima = 83.4 -->
hasta el 10 %, la habilidad real del modelo cae de 0.464 a 0.433 de ρ.
<!-- CANON: evaluabilidad.rho_real_r83 = 0.464 -->
<!-- CANON: evaluabilidad.rho_real_r10 = 0.433 -->
La habilidad *medible* —la única que un analista de esa ciudad puede calcular— cae de
0.464 a 0.316.
<!-- CANON: evaluabilidad.rho_medible_r83 = 0.464 -->
<!-- CANON: evaluabilidad.rho_medible_r10 = 0.316 -->
Lo que colapsa no es el modelo. Es el termómetro.

## Qué se manipula

Tres controles, y el tercero es el que convierte el hallazgo en una regla:

| Control | Qué mueve |
|---|---|
| **Tasa de geocodificación** | de 83.4 % (Lima real) a 10 %; separa las dos curvas |
| **Mecanismo de pérdida** | aleatoria (cota optimista) ↔ selectiva (cota empírica) |
| **Error de medición tolerado (τ)** | cuánto ρ de equivocación se acepta antes de declarar «no evaluable» |

Las dos primeras curvas del gráfico son **lo que creerías saber** (ρ contra el oráculo
degradado) y **lo que realmente sabes** (ρ contra el oráculo completo). La segunda no es
calculable en la ciudad degradada: exigiría exactamente el dato que falta. Esa
imposibilidad *es* el problema, y por eso el experimento simula la degradación sobre Lima,
donde el oráculo completo sí existe.

El tercer control no sale de los datos. Ningún número dice cuánto error de medición es
aceptable; es una decisión de quien publica el mapa. El control existe para que esa
decisión sea **visible y de alguien**, en vez de quedar enterrada en un umbral por defecto.
Movido τ, el experimento devuelve el **piso de geocodificación**: la tasa mínima por debajo
de la cual lo correcto no es una nota al pie, sino no publicar el número de desempeño.

## Unidad espacial

**Ninguna, y decirlo importa.** La fila del artefacto es `(curva, tasa)`, no una celda: es
una curva sobre un parámetro escalar, no un mapa. No hay clave espacial y no hay tabla de
correspondencia porque no hay nada que corresponder.

La unidad de observación *subyacente* sí es `h3_8`. El ρ que va en el eje y es un Spearman
intra-distrital macro: se correlaciona predicción contra objetivo sobre las celdas H3 res-8
**dentro** de cada distrito, se promedia sobre distritos y después sobre categorías. Mide
si el modelo ordena bien las celdas de un distrito, no el nivel de delito ni el orden entre
distritos. Ver `design/contrato-unidades.md`.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `geocoding_degradation.csv` | `infelix/data/silver/predictions/` | tasa × semilla | 5 niveles × 10 semillas; sostiene `fig-simbig-degradation` del paper |
| `selective_geocoding_degradation.csv` | `infelix/data/silver/predictions/` | mecanismo × tasa × semilla | 2 mecanismos × 6 niveles; incluye el 24.9 % real de Trujillo |
| `curvas.parquet` | este loader | curva × tasa | medias y sd por nivel, con `brecha` y `ventaja` |
| `penalidad.parquet` | este loader | tasa | Δρ selectivo − aleatorio, pareado por semilla |
| `pisos.parquet` | este loader | curva × τ | el piso precomputado para la rejilla de tolerancias |

Se leen **read-only** del repo de origen y la salida se exporta a
`data/silver/curva-de-evaluabilidad/`, con la procedencia de cada entrada registrada por
`canon.emit` (hash de cada input y del script emisor). El repo de origen nunca se escribe.

En total son 152 corridas modelo × nivel × semilla,
<!-- CANON: evaluabilidad.conteo_corridas = 152 -->
con 10 semillas por nivel.
<!-- CANON: evaluabilidad.conteo_semillas = 10 -->
El nivel base (83.4 %) es determinista por construcción: sin adelgazamiento no hay nada que
aleatorizar, así que no lleva sd y **no se rellena con cero** — no medir dispersión y medir
cero dispersión son cosas distintas.

### Por qué entran dos CSV y no uno

El experimento de origen supone pérdida **aleatoria**: cada hecho retiene su coordenada con
la misma probabilidad. El propio repo de origen declara ese supuesto como cota optimista, y
un segundo experimento lo mide: la pérdida real es selectiva por comisaría y categoría, con
gradiente de pobreza.

Presentar solo la curva optimista sería cometer, un piso más arriba, exactamente el error
que este repo existe para no cometer. Así que el mecanismo es un control, no una nota al
pie. Las dos curvas del segundo CSV comparten grilla, semillas y script de origen, que es
lo único que hace la comparación válida: la penalidad selectiva se mide **contra su brazo
pareado**, nunca contra la corrida del paper.

Que las dos corridas uniformes —la del paper y el brazo pareado— coinciden donde sus
grillas se tocan lo **verifica el loader**, y aborta si dejan de hacerlo. Sin esa
verificación, poner ambas curvas en el mismo eje mezclaría diferencia de mecanismo con
diferencia de corrida.

## Qué se ve

La curva de evaluabilidad: tres series sobre un solo eje de ρ, con banda de ±1 sd entre
semillas y **marcadores en los niveles medidos** — el trazo entre ellos es interpolación y
la figura no finge lo contrario. Dos vistas de apoyo: la ventaja sobre la persistencia nivel
por nivel, y la penalidad de suponer pérdida aleatoria.

La paleta es el subconjunto de Okabe-Ito heredado de `infelix/scripts/figures_simbig.py`,
donde ya está validado para esta misma figura, y re-verificado acá contra las seis pruebas
de paleta en claro y en oscuro (peor par adyacente: ΔE 11.0 bajo deuteranopia, 25.8 en
visión normal; todos los checks en PASS). **El color no es la única señal de identidad**:
cada serie lleva su propio estilo de línea, su propio marcador, una etiqueta directa y una
entrada de leyenda.

Es una paleta categórica —tres series con nombre—, no una rampa de riesgo, así que la regla
de «nada de verde para bajo riesgo» no aplica: acá el verde nombra a la persistencia, no a
una zona del mapa.

**Codificación de lo que no se sabe.** Por debajo del piso, la zona se dibuja
**deshilachada**: trama diagonal, sin relleno, con su rótulo. Es la misma regla que la celda
sin registro del mapa, aplicada a un eje. No dice «acá el modelo falla»; dice «acá no se
puede saber». La trama va más gruesa que en `observado-latente` (0.5 contra 0.3) y a
propósito: allá el deshilachado cubre novecientos hexágonos chicos y a 0.5 formaría una
malla que se come el mapa; acá es una sola región grande y a 0.3 la ausencia se volvía
invisible. Mismo criterio, geometría distinta.

## Cómo correr

```bash
uv sync --extra viz
uv run python experiments/curva-de-evaluabilidad/loader.py
uv run marimo edit experiments/curva-de-evaluabilidad/notebook.py
```

## Los números

Todos salen del registro canónico. Ninguno está escrito a mano acá.

### La curva del paper (pérdida aleatoria)

| tasa geocod. | ρ medible | ρ real | brecha | ρ persistencia | ventaja |
|--:|--:|--:|--:|--:|--:|
| 83.4 % | 0.464 | 0.464 | 0.000 | 0.401 | 0.063 |
| 70 % | 0.452 | 0.461 | 0.009 | 0.386 | 0.066 |
| 50 % | 0.429 | 0.459 | 0.030 | 0.359 | 0.070 |
| 25 % | 0.384 | 0.450 | 0.066 | 0.302 | 0.082 |
| 10 % | 0.316 | 0.433 | 0.117 | 0.218 | 0.098 |

<!-- CANON: evaluabilidad.rho_persistencia_r83 = 0.401 -->
<!-- CANON: evaluabilidad.brecha_r83 = 0.000 -->
<!-- CANON: evaluabilidad.ventaja_r83 = 0.063 -->
<!-- CANON: evaluabilidad.rho_medible_r70 = 0.452 -->
<!-- CANON: evaluabilidad.rho_real_r70 = 0.461 -->
<!-- CANON: evaluabilidad.rho_persistencia_r70 = 0.386 -->
<!-- CANON: evaluabilidad.brecha_r70 = 0.009 -->
<!-- CANON: evaluabilidad.ventaja_r70 = 0.066 -->
<!-- CANON: evaluabilidad.rho_medible_r50 = 0.429 -->
<!-- CANON: evaluabilidad.rho_real_r50 = 0.459 -->
<!-- CANON: evaluabilidad.rho_persistencia_r50 = 0.359 -->
<!-- CANON: evaluabilidad.brecha_r50 = 0.030 -->
<!-- CANON: evaluabilidad.ventaja_r50 = 0.070 -->
<!-- CANON: evaluabilidad.rho_medible_r25 = 0.384 -->
<!-- CANON: evaluabilidad.rho_real_r25 = 0.450 -->
<!-- CANON: evaluabilidad.rho_persistencia_r25 = 0.302 -->
<!-- CANON: evaluabilidad.brecha_r25 = 0.066 -->
<!-- CANON: evaluabilidad.ventaja_r25 = 0.082 -->
<!-- CANON: evaluabilidad.rho_persistencia_r10 = 0.218 -->
<!-- CANON: evaluabilidad.brecha_r10 = 0.117 -->
<!-- CANON: evaluabilidad.ventaja_r10 = 0.098 -->

Los veinticinco van al registro aunque el hallazgo se cite con tres: una cifra tabulada es
tan portante como una en prosa, y el drift no distingue.

### Trujillo, a su tasa real

24.9 % de geocodificación
<!-- CANON: evaluabilidad.tasa_trujillo = 24.9 -->
es un nivel **medido** en el segundo CSV, no interpolado desde el 25 % del primero. Las
cifras canónicas son las de la cota **selectiva**, porque citar la optimista por defecto
sería elegir el número más cómodo:

| | pérdida selectiva (canónica) | pérdida aleatoria |
|---|--:|--:|
| ρ medible | 0.354 | 0.386 |
| ρ real | 0.435 | 0.447 |
| brecha | 0.081 | 0.062 |

<!-- CANON: evaluabilidad.rho_medible_trujillo = 0.354 -->
<!-- CANON: evaluabilidad.rho_real_trujillo = 0.435 -->
<!-- CANON: evaluabilidad.brecha_trujillo = 0.081 -->
<!-- CANON: evaluabilidad.rho_persistencia_trujillo = 0.270 -->
<!-- CANON: evaluabilidad.ventaja_trujillo = 0.084 -->
<!-- CANON: evaluabilidad.rho_medible_trujillo.uniforme = 0.386 variant-ok -->
<!-- CANON: evaluabilidad.rho_real_trujillo.uniforme = 0.447 variant-ok -->
<!-- CANON: evaluabilidad.brecha_trujillo.uniforme = 0.062 variant-ok -->

La penalidad de que la pérdida sea selectiva y no aleatoria, pareada por semilla, es
−0.032 de ρ medible
<!-- CANON: evaluabilidad.penalidad_medible_trujillo = -0.032 -->
contra solo −0.013 de ρ real.
<!-- CANON: evaluabilidad.penalidad_real_trujillo = -0.013 -->
Dos veces y media más castigo sobre la medición que sobre la señal. La selectividad no
rompe lo que el modelo aprende; rompe la posibilidad de comprobarlo.

### El piso

Con τ = 0.05 de ρ tolerado, el piso de geocodificación es 43.8 %
<!-- CANON: evaluabilidad.piso_geocod_tau05 = 43.8 -->
bajo pérdida selectiva, y 36.2 % bajo el supuesto optimista.
<!-- CANON: evaluabilidad.piso_geocod_tau05.uniforme = 36.2 variant-ok -->
Lima pasa cómodamente. Trujillo no pasa con ninguno de los dos.

El piso lo calcula **el loader**, no el notebook, y por eso hay un `pisos.parquet`: la vista
necesita mover τ, pero si recalculara la inversión por su cuenta podría discrepar del número
que el registro declara canónico, y una vista que contradice al registro es peor que no
tener registro. Hay un test que compara las dos.

## El hallazgo

**La mala geocodificación no rompe el modelo; rompe la evaluación.** A la tasa real de
Trujillo el analista mediría 0.354 y concluiría que su modelo rinde eso. Rinde 0.435. No
tiene forma de enterarse: calcular la segunda cifra exigiría el oráculo completo, que es
justamente el dato que su ciudad no tiene.

Y la señal sigue ahí. El modelo con features supera a la persistencia en el 100 % de las
semillas,
<!-- CANON: evaluabilidad.pct_seeds_feat_gana = 100 -->
en todos los niveles y con los dos mecanismos, incluso al 10 % de geocodificación. Lo que no
sigue ahí es la prueba de que sigue ahí.

**La consecuencia de diseño.** Por debajo del piso, lo correcto no es dibujar el mapa con
una advertencia: es no publicar el número de desempeño que lo respaldaría. «No evaluable»
no significa «el modelo es malo» — significa que la afirmación «el modelo es bueno» no tiene
con qué sostenerse. Es la regla dura del repo un piso más arriba: ausencia de evaluación es
ausencia de evidencia, no evidencia de fracaso.

**Un resultado secundario que no se puede afirmar en general.** Bajo pérdida aleatoria la
ventaja del modelo sobre la persistencia se *ensancha* al empeorar el registro (0.063 →
0.082 → 0.098): la persistencia sufre dos veces, en el historial de entrenamiento y en la
referencia de evaluación, así que justo donde el dato es peor la práctica estándar —hotspots
por persistencia— es la que más pierde. Es lo contrario de «si el dato es malo, usa algo
simple». Pero **bajo pérdida selectiva la monotonía se rompe** y los intervalos entre
semillas se solapan. El título de esa figura se dejó neutro y la lectura se calcula de la
curva elegida: una leyenda fija habría mentido en la mitad de los estados del control.

## Verificación

- [x] `uv run pytest` en verde — 20 tests del experimento (14 corren sin datos y 6 llevan
      `needs_data`), 47 en el gate de CI (`-m "not needs_data"`)
- [x] `uv run ruff check .` limpio
- [x] `uv run canon check` sin fallos
- [x] El loader es determinista: dos corridas seguidas no producen diff en el registro
- [x] El notebook corre de punta a punta (`marimo export html`) sin traceback en cinco
      estados: base, Trujillo × selectivo, Trujillo × selectivo en oscuro, tolerancia al
      máximo × tasa al mínimo, y el estado por defecto tras cada ajuste de figura
- [x] Las tres figuras se extrajeron del HTML exportado y se miraron una por una, en claro y
      compuestas sobre el fondo oscuro real (`#1a1a19`), no supuestas
- [x] Paleta validada con el script de las seis pruebas en `--mode light` y `--mode dark`:
      todos los checks en PASS, peor par adyacente ΔE 11.0 (deuteranopia) y 25.8 (normal)
- [x] Identidad de serie nunca solo por color: estilo de línea + marcador + etiqueta directa
      + leyenda

Las capturas de verificación no se versionan: son regenerables con los comandos de arriba, y
el repo versiona reportes, no imágenes de una corrida.

## Decisiones tomadas

**El mecanismo de pérdida es un control, no una nota al pie.** El bead nombraba un solo CSV.
Presentar únicamente la curva optimista habría dado un experimento más simple y una cifra de
Trujillo interpolada desde el 25 %; con el segundo CSV la tasa de Trujillo está **medida** y
la cota que se recomienda es la empírica. Se descartó dejar la pérdida selectiva en prosa
por el mismo motivo por el que este repo no dibuja las celdas sin dato en blanco.

**La comparación de mecanismos vive solo dentro del segundo CSV.** Las dos rejillas de tasas
no coinciden (83.4/70/50/25/10 contra 83.4/80/60/40/24.9/10), así que restar la curva del
paper de la selectiva mezclaría mecanismo con corrida. La penalidad se mide pareada por
semilla contra el brazo uniforme del mismo script. La curva del paper se conserva como
réplica cruzada y el loader **aborta** si las dos uniformes divergen más de 0.03 de ρ donde
sus grillas se tocan.

**La brecha y la ventaja se derivan por semilla, no restando promedios.** Las dos son
diferencias pareadas —la misma corrida produce el ρ medible y el ρ real—, así que su sd es
la de la diferencia, mucho más estrecha que la suma de las marginales. Restar promedios
habría dado el mismo centro y una dispersión inventada. Hay un test que lo fija.

**El piso se precomputa en el loader y el notebook lo busca.** Era tentador dejar la
inversión de cinco líneas en el notebook. Habría creado dos implementaciones de la misma
regla, una de las cuales emite el número canónico. Un `pisos.parquet` de 159 filas cuesta
menos que esa divergencia.

**Descartado: extrapolar el piso fuera del rango medido.** Con τ mayor que la brecha máxima
observada, `piso_de_evaluabilidad` devuelve el extremo medido en vez de continuar la recta.
Más allá del 10 % el experimento no sabe nada, y una recta prolongada ahí sería una
afirmación sin dato debajo.

**Descartado: un veredicto binario fijo.** La tentación era fijar τ y publicar un piso único.
El umbral no sale de ningún lado; dejarlo movible es la diferencia entre una regla de diseño
y un número de autoridad.

**El rótulo de la zona no evaluable solo se dibuja si la zona lo puede contener.** Con la
tolerancia al máximo el piso cae al 10 % y el rótulo sobresalía de su propia franja,
señalando justo la región que no describe. Se encontró mirando el estado extremo, no
razonándolo.

**La franja inferior del gráfico está reservada.** El lectorado de la brecha se colgaba del
medio de la cuña y aterrizaba encima de alguna curva en casi todo el recorrido: en la base
porque las tres convergen, a tasas bajas porque la cuña cruza la naranja. Perseguir el hueco
con desplazamientos condicionales es una carrera que se pierde. Se ancló al pie del cursor,
en la única banda que ninguna curva visita, y la leyenda se movió fuera del área de datos
para dejarla libre.

**El test se llama `test_curva.py` y carga el loader por ruta.** Dos experimentos con un
`loader.py` cada uno colisionan bajo `import loader` — es `inwatch-0ge`, que este archivo no
arrastra: `importlib` le da un nombre de módulo único y no toca el `sys.path` del proceso.
Y dos `test_loader.py` en el árbol chocan al recolectar, porque pytest sin `__init__.py`
resuelve los módulos de test por nombre base.
