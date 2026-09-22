"""Interpolación de cámara de van Wijk & Nuij (2003), la de `flyTo` de Mapbox.

Resuelve el camino óptimo en el espacio percibido: arquea el zoom hacia afuera mientras
viaja y lo cierra al llegar, con velocidad angular constante. Interpolar tramo a tramo
con smoothstep deja velocidad cero en cada waypoint y la cámara frena en seco.
"""
import math

RHO = 1.42


def mercator(lat, lng):
    x = (lng + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def inv_mercator(x, y):
    """El factor es 2π, no 4π: con 4π la cámara apunta 11 grados al sur y el mapa sale vacío."""
    lng = x * 360.0 - 180.0
    lat = math.degrees(2 * math.atan(math.exp((0.5 - y) * 2 * math.pi)) - math.pi / 2)
    return lat, lng


def van_wijk(v0, v1):
    x0, y0 = mercator(v0["lat"], v0["lng"])
    w0 = 1.0 / 2 ** v0["zoom"]
    x1, y1 = mercator(v1["lat"], v1["lng"])
    w1 = 1.0 / 2 ** v1["zoom"]
    dx, dy = x1 - x0, y1 - y0
    d1 = math.hypot(dx, dy)
    rho2 = RHO * RHO
    if d1 < 1e-9:
        S = abs(math.log(w1 / w0)) / RHO if w1 != w0 else 0.0
        signo = 1 if w1 > w0 else -1

        def f(s, _S=S):
            t = 0.0 if _S == 0 else s / _S
            return x0 + t * dx, y0 + t * dy, w0 * math.exp(RHO * s * signo)
        return S, f
    d2 = d1 * d1
    b0 = (w1 * w1 - w0 * w0 + rho2 * rho2 * d2) / (2 * w0 * rho2 * d1)
    b1 = (w1 * w1 - w0 * w0 - rho2 * rho2 * d2) / (2 * w1 * rho2 * d1)
    r0 = math.log(math.sqrt(b0 * b0 + 1) - b0)
    r1 = math.log(math.sqrt(b1 * b1 + 1) - b1)
    S = (r1 - r0) / RHO

    def f(s):
        u = (w0 / (rho2 * d1)) * (math.cosh(r0) * math.tanh(RHO * s + r0) - math.sinh(r0))
        w = w0 * math.cosh(r0) / math.cosh(RHO * s + r0)
        return x0 + u * dx, y0 + u * dy, w
    return S, f


def volar(a, b, fps, seg_por_unidad, extra=("pitch", "bearing"), minimo_seg=1.3):
    """Frames entre dos vistas. La duración sale de la longitud del camino, con piso.

    Sin piso, un salto corto —Matute al Nacional son 1,2 km— recibe cuatro frames y se
    siente como un corte. `minimo_seg` garantiza que todo vuelo se lea como vuelo.
    """
    S, f = van_wijk(a, b)
    n = max(int(round(minimo_seg * fps)), int(round(S * seg_por_unidad * fps)))
    salida = []
    for k in range(n):
        t = k / n
        x, y, w = f(t * S)
        lat, lng = inv_mercator(x, y)
        v = dict(lat=lat, lng=lng, zoom=math.log2(1.0 / w))
        for clave in extra:
            v[clave] = a[clave] + (b[clave] - a[clave]) * t
        salida.append(v)
    return salida
