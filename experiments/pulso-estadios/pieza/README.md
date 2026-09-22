# La pieza: el pulso de estadios en video

Pieza de difusión del experimento `pulso-estadios`. Recorre las trece horas alrededor de
la patada inicial en los tres estadios y muestra cuánto sube el riesgo de robo callejero
denunciado respecto del mismo estadio, el mismo día de semana y el mismo mes **sin
partido**.

No es un experimento: no estima nada. Lee el parquet que produce `../loader.py` y lo
dibuja. Las cifras que cita en pantalla salen del mismo parquet; las cifras portantes del
experimento viven en el registro canónico y se citan en `../README.md` por ancla — acá no
se escribe ninguna a mano.

El video, el basemap horneado y el bundle de deck.gl son **regenerables** y por eso no
están versionados: van a `data/pieza/pulso-estadios/`, que el repo ignora. Lo versionado es
el código, este documento y `poster.jpg`.

## Cómo leerla

- **La torre es el anillo de 0-500 m**, y solo ese. Su altura es log₂ del cociente, con
  una exageración vertical declarada en la leyenda de la propia pieza.
- **Los anillos de 500-1000 m y 1-2 km son manchas planas.** Llevan la misma información,
  porque el color *es* el cociente, sin disputarle el eje vertical al único anillo que la
  pieza mira. Extruir los cuatro ponía al de 1-2 km ganándole por superficie al núcleo.
- **El de 2-4 km queda en contorno.** Su serie entera está pegada a 1 en los tres
  estadios: pintarlo era un lavado de color sobre un tercio del cuadro para decir «nada».
- **El color va de cian a transparente a rojo caliente**, y la magnitud vive en la
  opacidad: un cociente cercano a 1 se pinta casi invisible a propósito.
- **«Sin dato» es una jaula de alambre**, nunca un vacío ni un cero. El Monumental entra
  deshilachado, se vuelve sólido durante el partido y vuelve a la jaula en el cierre.
- **El rayado en la línea de tiempo** marca las horas que *ese* estadio no puede medir.

## Los siete pasos

```bash
# 1 · suelo nocturno (~1 min). Solo si cambia la ventana o la paleta.
uv run --extra geo --extra viz python experiments/pulso-estadios/pieza/suelo.py
# 2 · estados por hora: ventana móvil, interpolación de apariencia, rango por estadio
uv run --extra geo --extra viz python experiments/pulso-estadios/pieza/datos.py
# 3 · guion de cámara y ritmo
uv run python experiments/pulso-estadios/pieza/guion.py
# 4 · escena deck.gl
uv run python experiments/pulso-estadios/pieza/escena.py
# 5 · cinco frames sueltos (~40 s). Revisar ANTES del paso 6.
uv run --extra pieza python experiments/pulso-estadios/pieza/probe.py
# 6 · todos los frames (~5 min)
uv run --extra pieza python experiments/pulso-estadios/pieza/captura.py
# 7 · video
ffmpeg -y -framerate 12 -i data/pieza/pulso-estadios/frames/f%03d.png \
       -vf "scale=900:-2:flags=lanczos" -c:v libx264 -pix_fmt yuv420p -crf 21 \
       -movflags +faststart data/pieza/pulso-estadios/pulso-estadios.mp4
```

La primera vez, el navegador de la captura: `uv run --extra pieza python -m playwright
install chromium`. El paso 4 baja el bundle de deck.gl a la salida la primera vez; de ahí
en adelante solo verifica su sha, así que la captura corre sin red.

El paso 5 existe porque el 6 cuesta cinco minutos. El probe resuelve los índices de los
momentos clave desde el guion, así que sigue apuntando al frame correcto cuando el guion
cambia de largo, y avisa si la consola del navegador tiró algo — un error de JS deja la
escena a medio dibujar sin que el screenshot lo diga.

## Lo que hay que saber si se toca

- **El tejido urbano y el dato no caben en la misma escala vertical.** Se probó extruir
  las huellas de edificio de OSM para darle escala a la torre: al zoom de la pieza, la
  altura de un edificio típico queda por debajo del píxel, contra una torre de miles de
  metros exagerados. El frame salió indistinguible del de sin edificios. El contraste de
  tejido entre el Monumental y los otros dos —que es real y es parte del hallazgo— se
  cuenta con el conteo de huellas, no con ese dibujo.
- **Hay un piso de denominador, `PISO_CONTROL` en `datos.py`.** Un cociente cuyo control
  es un solo evento no es una medición: el anillo interior del Monumental una hora antes
  de la patada saturaba la escala apoyado en un único robo de control, y era la torre más
  alta de la pieza. Con el piso, ese punto se dibuja como lo que es —sin dato— y la
  ventana medible del Monumental queda donde su denominador existe. Afecta solo a su
  anillo interior.
- **Ese piso no es el mismo criterio que usa el notebook**, que filtra por estratos de
  soporte. Dos nociones de «medible» para la misma curva: **inwatch-ap1**.
- **Cada estadio barre solo sus horas medidas** (`rangos` en `datos.json`). Barrer horas
  vacías no mostraba un dato bajo, mostraba parpadeo.
- **Nunca se cruza un hueco con una rampa de valores.** Cuando una hora medida da paso a
  una sin soporte se interpola la *apariencia* —la columna baja hasta la lámina y el color
  se apaga— no el cociente. No hay ningún valor intermedio afirmado. Y los huecos de los
  extremos no se rellenan: extrapolar es peor que interpolar.
- **La exageración vertical tiene que seguir declarada en la leyenda.** Una altura
  exagerada sin decirlo es una afirmación falsa sobre la magnitud.
- **El color se calcula en la escena, no se hornea en el JSON.** Antes venía de un RdBu_r
  de matplotlib, que asume papel blanco: sobre fondo oscuro sus valores débiles quedaban
  claros, o sea brillantes, y un cociente cercano a 1 se leía como «alto».
- **Los días de partido en pantalla salen del parquet**, no escritos a mano. Es la segunda
  regla dura del repo, y en esta pieza ya se rompió una vez.
- **`camara.py` es van Wijk & Nuij (2003)**, la interpolación de `flyTo` de Mapbox.
  Interpolar tramo a tramo con smoothstep deja velocidad cero en cada waypoint y la
  cámara frena en seco en cada parada.
- **El piso de duración gobierna tres de los cuatro vuelos.** Solo el salto del Nacional
  al Monumental —unos 9,5 km— dura más por su propio camino; los otros tres caen al piso.
  O sea que `seg_por_unidad` casi no interviene y lo que de verdad acorta la pieza es
  bajar `minimo_seg`. Está cubierto por `tests/test_pulso_pieza.py`.
- **deck.gl se cachea local, pineado por versión y por sha256.** La escena traía el
  bundle de unpkg con un `<script src="https://…">`, y la captura abre la página con
  `file://`: grabar dependía de tener red en ese instante. Sin red, `deck` quedaba
  indefinido, el script abortaba antes de marcar `listo` y la captura moría por timeout a
  los dos minutos sin decir por qué. Ahora `escena.py` lo baja una vez y verifica el sha
  en cada corrida, y si falta, la página lo dice y la captura falla en segundos con el
  motivo. Subir de versión exige actualizar `DECK_SHA256` a mano, a propósito.
- WebGL headless anda con `--use-angle=swiftshader --enable-unsafe-swiftshader`; no hace
  falta Xvfb.

## Procedencia

Las rutas de OSM y de los límites distritales salen del **catálogo de fuentes**
(`osm_peru_gpkg`, `distritos_limites`), no de constantes: la versión de esta pieza que
vivía fuera del repo tenía rutas `/home/<usuario>/…` escritas a mano, que la ataban a una
laptop y al árbol de infelix (inwatch-iv1.2, inwatch-8sm).

`poster.jpg` es el frame del Monumental en la patada inicial, el más fuerte de la pieza.
