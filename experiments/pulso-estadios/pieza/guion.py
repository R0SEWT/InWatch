"""Guion con ritmo: entrada suave, pausa en la patada inicial, pausa en la salida.

    uv run python experiments/pulso-estadios/pieza/guion.py

El barrido anterior corría a paso constante y trataba igual las 13 horas. Pero no son
iguales: la patada inicial y la salida son los dos momentos que la pieza existe para
mostrar, y un lector necesita entre uno y dos segundos parado frente a un número nuevo
para leerlo. El resto de la ventana es contexto y puede pasar más rápido.

El ritmo, por parada:
  · de −6 a −2 h   paso largo, solo horas enteras — es contexto
  · de −2 a 0 h    paso corto, con los intermedios — desacelera hacia el momento
  · patada inicial PAUSA de 1,1 s
  · de 0 a +2 h    paso corto — el partido
  · salida         PAUSA de 1,3 s, que es donde el dato tiene su pico
  · de +2 a +4 h   paso corto, empieza a soltar
  · de +4 a +6 h   paso largo, y cierra

Frenar en seco antes de una pausa se siente como un error de reproducción; por eso
la cadencia se acorta ANTES de llegar, no en el frame de la pausa.
"""
import json

import camara
import rutas

FPS = 12
datos = json.loads(rutas.DATOS.read_text())
ESTADOS, HORAS = datos["estados"], datos["horas"]
IDX = {int(h): i for h, i in datos["indice_hora"].items()}
TWEENS = datos["tweens"]
INICIO = IDX[HORAS[0]]

POS = {"matute": (-12.06850, -77.02293), "nacional": (-12.06707, -77.03386),
       "monumental": (-12.05565, -76.93533)}
FOCO = {"matute": "matute", "nacional": "nacional", "monumental": "monumental"}
CLAVES = ["matute", "nacional", "monumental"]
centro = (sum(p[0] for p in POS.values()) / 3, sum(p[1] for p in POS.values()) / 3)
PANO = dict(lat=centro[0], lng=centro[1], zoom=11.15, pitch=44, bearing=-20)

PAUSA_KICKOFF, PAUSA_SALIDA, HORA_SALIDA = 13, 16, 2
RANGOS = datos["rangos"]


def parada(c, zoom=12.30, pitch=46, bearing=-26):
    """Encuadre de una parada.

    El zoom bajó de 12,55 y el pitch de 55: con la torre exagerada 1,8x, el núcleo del
    Monumental a la salida se salía por arriba del cuadro. Un paso atrás y menos
    inclinación devuelven la punta y además meten más tejido de ciudad en el frame, que
    es lo que le da escala a la torre.
    """
    return dict(lat=POS[c][0], lng=POS[c][1], zoom=zoom, pitch=pitch, bearing=bearing)


def pesos(**kw):
    base = {c: 0.0 for c in CLAVES}
    base.update(kw)
    return base


TODOS = pesos(matute=1.0, nacional=1.0, monumental=1.0)


def cadencia(h_min, h_max):
    """Índices de estado en el orden y con las repeticiones que marca el ritmo.

    Corre solo por las horas MEDIDAS del estadio. El Monumental solo tiene denominador
    entre la patada inicial y +3 h; barrer el resto de la ventana no mostraba un dato
    bajo, mostraba parpadeo, y su primer punto con dato era además el peor sostenido de
    la pieza. El tramo que no mide queda rayado en la línea de tiempo.
    """
    salida = []

    def tramo(h0, h1, paso_corto):
        h0, h1 = max(h0, h_min), min(h1, h_max)
        for h in range(h0, h1):
            salida.append(IDX[h])
            if paso_corto:
                salida.extend(range(IDX[h] + 1, IDX[h] + 1 + TWEENS))

    tramo(-6, -2, False)
    tramo(-2, 0, True)
    if h_min <= 0 <= h_max:
        salida.extend([IDX[0]] * PAUSA_KICKOFF)
    tramo(0, HORA_SALIDA, True)
    if h_min <= HORA_SALIDA <= h_max:
        salida.extend([IDX[HORA_SALIDA]] * PAUSA_SALIDA)
    tramo(HORA_SALIDA, 4, True)
    tramo(4, 6, False)
    salida.extend([IDX[h_max]] * 4)
    return salida
guion = []

# Entrada: la panorámica acercándose despacio, con ease-out (llega frenando).
for i in range(18):
    t = i / 17
    suave = 1 - (1 - t) ** 3
    guion.append({"vista": dict(PANO, zoom=10.75 + 0.40 * suave,
                                bearing=-27 + 7 * suave, pitch=41 + 3 * suave),
                  "estado": INICIO, "foco": "todos", "pesos": TODOS})

for i, clave in enumerate(CLAVES):
    destino = parada(clave, bearing=-26 + i * 7)
    vuelo = camara.volar(guion[-1]["vista"], destino, FPS, 1.35)
    desde, hasta = dict(guion[-1]["pesos"]), pesos(**{clave: 1.0})
    n = max(1, len(vuelo) - 1)
    arranque = IDX[RANGOS[clave][0]]
    for j, v in enumerate(vuelo):
        f = j / n
        guion.append({"vista": v, "estado": arranque, "foco": FOCO[clave],
                      "pesos": {c: desde[c] + (hasta[c] - desde[c]) * f for c in CLAVES}})
    h_min, h_max = RANGOS[clave]
    cad = cadencia(h_min, h_max)
    for k, estado in enumerate(cad):
        guion.append({"vista": dict(destino, bearing=destino["bearing"] + 0.16 * k),
                      "estado": estado, "foco": FOCO[clave], "pesos": hasta})

salida = camara.volar(guion[-1]["vista"], dict(PANO, zoom=11.0, bearing=8), FPS, 1.15)
desde = dict(guion[-1]["pesos"])
n = max(1, len(salida) - 1)
for j, v in enumerate(salida):
    f = j / n
    guion.append({"vista": v, "estado": IDX[6], "foco": "todos",
                  "pesos": {c: desde[c] + (TODOS[c] - desde[c]) * f for c in CLAVES}})
for _ in range(5):
    guion.append(dict(guion[-1]))

rutas.asegurar()
rutas.GUION.write_text(json.dumps(guion))
print("frames por parada:", {c: len(cadencia(*RANGOS[c])) for c in CLAVES},
      "· total:", len(guion),
      f"≈ {len(guion)/FPS:.1f} s a {FPS} fps")
print("pausas:", PAUSA_KICKOFF / FPS, "s en la patada ·", PAUSA_SALIDA / FPS, "s en la salida")
