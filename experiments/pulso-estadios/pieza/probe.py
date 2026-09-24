"""Cinco frames sueltos de la escena para revisar un cambio sin capturar los 253.

    uv run --extra pieza python experiments/pulso-estadios/pieza/probe.py

Elige un frame por momento —entrada, cada parada, cierre— resolviendo los índices desde
el guion en vez de a mano, así sigue apuntando al momento correcto cuando el guion cambia
de largo. Y avisa si la consola del navegador tiró algo: un error de JS deja la escena a
medio dibujar sin que el screenshot lo diga.
"""
import json
import time

import rutas
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu-sandbox",
        "--allow-file-access-from-files"]

guion = json.loads(rutas.GUION.read_text())
datos = json.loads(rutas.DATOS.read_text())


def primero_quieto(clave):
    """Primer frame de esa parada con la cámara ya fija: el vuelo no sirve para juzgar."""
    idx = [i for i, p in enumerate(guion) if p["foco"] == clave]
    for i in idx[:-1]:
        if guion[i]["vista"]["zoom"] == guion[i + 1]["vista"]["zoom"]:
            return i
    return idx[len(idx) // 2]


momentos = {
    "entrada": 10,
    "matute": primero_quieto("matute") + 18,
    "nacional": primero_quieto("nacional") + 18,
    "monumental": primero_quieto("monumental") + 14,
    "cierre": len(guion) - 3,
}

with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", headless=True, args=ARGS)
    pg = b.new_page(viewport={"width": 900, "height": 480}, device_scale_factor=2)
    errores = []
    pg.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.goto(rutas.ESCENA.as_uri(), wait_until="load", timeout=180_000)
    pg.wait_for_function("window.listo === true", timeout=120_000)
    fallo = pg.evaluate("window.errorEscena || null")
    if fallo:
        raise SystemExit(f"la escena no se pudo dibujar: {fallo}")
    pg.wait_for_timeout(7000)

    for nombre, i in momentos.items():
        paso = guion[i]
        pg.evaluate("a => { window.setVista(a.vista); window.setPesos(a.pesos); "
                    "window.setEstado(a.estado); window.setFoco(a.foco); }", paso)
        fin = time.time() + 20
        while time.time() < fin and pg.evaluate("window.pintados()") < 1:
            pg.wait_for_timeout(120)
        pg.wait_for_timeout(2200)
        destino = rutas.SALIDA / f"probe_{nombre}.png"
        pg.screenshot(path=str(destino))
        st = ImageStat.Stat(Image.open(destino).convert("RGB").resize((160, 85)))
        print(f"probe_{nombre}.png  frame {i:3d}  hora {datos['etiquetas'][paso['estado']]:+d}"
              f"  desvío {sum(st.stddev)/3:5.1f}", flush=True)
    b.close()

print("errores de consola:", errores or "ninguno")
