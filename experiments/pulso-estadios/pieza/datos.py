"""Estados de la pieza: ventana móvil de 3 h e interpolación entre horas.

    uv run --extra geo --extra viz python experiments/pulso-estadios/pieza/datos.py

Dos suavizados, y conviene no confundirlos:

  · ESTIMACIÓN — el perfil se calcula con una ventana móvil de 3 h centrada en cada
    hora, no con bins de 1 h. Con bins de una hora los conteos por estadio son de dos o
    tres eventos: el salto medio entre horas consecutivas era de 0,98 en log2(RR) —el
    riesgo se duplicaba y se dividía cada hora— y había horas con RR cero. Con la
    ventana móvil el salto baja a 0,53 y el soporte mejora. Es el mismo estimador sobre
    más masa, con su propio IC en cada punto.

  · ANIMACIÓN — entre dos horas medidas se dibujan dos frames intermedios, interpolando
    altura y color. Eso es render, no dato: el reloj sigue marcando horas enteras y
    ninguna cifra sale de ahí. Es lo mismo que une con una línea los puntos de una serie.

Regla que se respeta en la interpolación: NUNCA se cruza un hueco con una rampa de
valores. Cuando una hora medida da paso a una sin soporte, lo que se interpola no es el
RR sino la APARIENCIA — el color se apaga hacia el gris y la columna baja hasta la
lámina de «sin dato». El lector ve que el dato se acaba, no un valor intermedio que
nadie estimó. Antes el cambio era un corte seco y en el Monumental, con 5 de 13 horas
sin controles, la escena parpadeaba.
"""
import json

import geografia
import numpy as np
import pandas as pd
import rutas

ALTURA, TOPE_RR = 480.0, 12.0
# Piso de denominador. Un cociente cuyo control es un solo robo no es una medición: el
# Monumental a −1 h daba RR 24× —capado a 12, o sea saturando la escala— sobre UN evento
# de control, y era la torre más alta de la pieza entera. Con el piso, ese punto se
# dibuja como lo que es, sin dato, y la ventana medible del Monumental queda donde su
# denominador existe: de la patada inicial a +3 h.
PISO_CONTROL = 2
# Piso de altura. Un anillo en RR=1 con altura 0 queda coplanar con la textura del suelo
# y la GPU no sabe cuál dibujar delante: aparecen bandas de mapa asomando por encima del
# anillo (z-fighting). 45 m a esta escala es una lámina, no una columna.
PISO_M = 45.0
# Suelo del cociente para el logaritmo. Hay ceros MEDIDOS —el Monumental a 500-1000 m en
# la salida es uno—, y log2(0) es −inf: sin este suelo el tween entre un cero medido y el
# valor siguiente colapsaba a cero en vez de subir, y numpy lo avisaba por stderr en cada
# corrida. Cero medido y «un milésimo» se dibujan igual, que es lo honesto: los dos son
# «tan bajo como la escala llega».
MINIMO_RR = 1e-3
HORAS = list(range(-6, 7))
TWEENS = 2                      # frames intermedios entre dos horas medidas
CLAVE = {v: k for k, v in geografia.CLAVES.items()}

est, lim, _ = geografia.ventana()
anillos = geografia.anillos_vectoriales(est, lim).to_crs(4326)
perfil = pd.read_parquet(rutas.PERFIL)


def poligonos(geom):
    """Cada parte como [exterior, agujero, ...], que es el formato de deck con huecos.

    Quedarse solo con `exterior` convertía cada corona en un DISCO: el de 500-1000 m
    tapaba al de 0-500, el de 1-2 km a los dos, y así. Todos los que están en RR≈1
    quedan además a la misma altura, así que sus caras superiores coinciden en el plano
    y la GPU alterna entre ellas — el dentado que parpadea. Con el agujero, una corona
    es una corona y no hay dos superficies disputándose el mismo píxel.
    """
    partes = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
    salida = []
    for parte in partes:
        anillos_geom = [[[float(x), float(y)] for x, y in parte.exterior.coords]]
        anillos_geom += [[[float(x), float(y)] for x, y in hueco.coords]
                         for hueco in parte.interiors]
        salida.append(anillos_geom)
    return salida


polis = []
for clave, nombre in CLAVE.items():
    for anillo in geografia.ANILLOS:
        sub = anillos[(anillos["estadio"] == nombre) & (anillos["anillo"] == anillo)]
        for poly in poligonos(sub.geometry.iloc[0]):
            polis.append({"poligono": poly, "estadio": clave, "anillo": anillo})


def lectura(p, hora):
    r = perfil[(perfil["estadio"] == p["estadio"]) & (perfil["anillo"] == p["anillo"])
               & (perfil["offset_h"] == hora)]
    if r.empty:
        return None
    r = r.iloc[0]
    if (r["n_control"] < PISO_CONTROL) or (r["n_control_estratos"] == 0) \
            or not np.isfinite(r["rr"]):
        return None
    return min(float(r["rr"]), TOPE_RR)


def marcar(estado, interpolado):
    estado["interpolado"] = bool(interpolado)
    return estado


def pintar(rr):
    """De RR a altura. log2 porque un cociente es multiplicativo.

    El COLOR no se calcula acá. Antes se horneaba con un RdBu_r de matplotlib, que asume
    papel blanco: sobre el fondo oscuro de la pieza sus valores débiles quedaban claros,
    o sea brillantes, y un cociente cercano a 1 se leía como «alto». La escena lo deriva
    de `rr` con su propia rampa; este archivo solo emite geometría, altura y soporte.
    """
    if rr is None:
        return {"h": PISO_M + 85.0, "soporte": False, "rr": None}
    l2 = np.log2(max(rr, MINIMO_RR))
    return {"h": PISO_M + max(l2, 0.0) * ALTURA,
            "soporte": True, "rr": round(float(rr), 2)}


FANTASMA = pintar(None)


def mezclar_apariencia(origen, f):
    """Desvanece entre un estado con dato y la lámina de «sin dato».

    Se interpola la ALTURA, no el RR: no hay ningún valor intermedio afirmado. El color
    lo apaga la escena, que sabe hacia qué fondo desvanecer.
    """
    return {"h": (1 - f) * origen["h"] + f * FANTASMA["h"],
            "soporte": True, "rr": origen["rr"], "transicion": True}


def serie_rellena(p):
    """RR por hora, con los huecos interiores rellenados por rampa en log2.

    Los huecos de los extremos no se rellenan: extrapolar es peor que interpolar, y no
    hay dos puntos entre los cuales tender la rampa.
    """
    medidos = {h: lectura(p, h) for h in HORAS}
    conocidas = [h for h in HORAS if medidos[h] is not None]
    salida = {}
    for h in HORAS:
        if medidos[h] is not None:
            salida[h] = (medidos[h], False)
            continue
        antes = [c for c in conocidas if c < h]
        despues = [c for c in conocidas if c > h]
        if not antes or not despues:
            salida[h] = (None, False)              # borde: se queda sin dato
            continue
        h0, h1 = antes[-1], despues[0]
        f = (h - h0) / (h1 - h0)
        l0, l1 = np.log2(max(medidos[h0], MINIMO_RR)), np.log2(max(medidos[h1], MINIMO_RR))
        rr = 2 ** ((1 - f) * l0 + f * l1)
        salida[h] = (rr, True)
    return salida


# Días de partido que entran a la estimación, por estadio. La ficha los cita en pantalla
# y hasta ahora estaban escritos a mano en la escena: exactamente el drift que el repo
# persigue. Salen del mismo parquet que las curvas.
DIAS = {c: int(perfil.loc[perfil["estadio"] == c, "dias_tratados"].iloc[0]) for c in CLAVE}

SERIES = {id(p): serie_rellena(p) for p in polis}
INTERPOLADAS, RANGOS = {}, {}
for clave in CLAVE:
    p = next(x for x in polis if x["estadio"] == clave and x["anillo"] == "r0_500")
    INTERPOLADAS[clave] = [h for h in HORAS if SERIES[id(p)][h][1]]
    medidas = [h for h in HORAS if SERIES[id(p)][h][0] is not None]
    RANGOS[clave] = [min(medidas), max(medidas)] if medidas else [HORAS[0], HORAS[-1]]

estados, etiquetas, indice_hora = [], [], {}
for i, hora in enumerate(HORAS):
    indice_hora[str(hora)] = len(estados)
    estados.append([marcar(pintar(SERIES[id(p)][hora][0]), SERIES[id(p)][hora][1])
                    for p in polis])
    etiquetas.append(hora)
    if i + 1 < len(HORAS):
        siguiente = HORAS[i + 1]
        for t in range(1, TWEENS + 1):
            f = t / (TWEENS + 1)
            fila = []
            for p in polis:
                a, b = lectura(p, hora), lectura(p, siguiente)
                if a is None and b is None:
                    fila.append(pintar(None))
                elif a is None:                       # el dato entra: aparece
                    fila.append(mezclar_apariencia(pintar(b), 1 - f))
                elif b is None:                       # el dato se acaba: se apaga
                    fila.append(mezclar_apariencia(pintar(a), f))
                else:
                    la, lb = np.log2(max(a, MINIMO_RR)), np.log2(max(b, MINIMO_RR))
                    fila.append(pintar(2 ** ((1 - f) * la + f * lb)))
            estados.append(fila)
            etiquetas.append(hora if f < 0.5 else siguiente)

rutas.asegurar()
rutas.DATOS.write_text(json.dumps({"polis": polis, "estados": estados, "etiquetas": etiquetas,
                               "indice_hora": indice_hora, "horas": HORAS,
                               "tweens": TWEENS, "interpoladas": INTERPOLADAS,
                               "rangos": RANGOS, "dias": DIAS}))
sin = {c: len(v) for c, v in INTERPOLADAS.items()}
print("polígonos:", len(polis), "· estados:", len(estados),
      f"({len(HORAS)} horas × {TWEENS + 1})")
print("horas rellenadas por rampa (huecos interiores):", sin)
print("rango medido por estadio:", {c: f"{a:+d} a {b:+d} h" for c, (a, b) in RANGOS.items()})
print("días de partido:", DIAS, "· total", sum(DIAS.values()))
print("→", rutas.DATOS.name, round(rutas.DATOS.stat().st_size / 1e6, 2), "MB")
