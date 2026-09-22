"""Captura: una sola página, y por frame se fija cámara, hora y foco.

Necesita el extra `pieza` (playwright + pillow) y el chromium de playwright:

    uv run --extra pieza python -m playwright install chromium
    uv run --extra pieza python experiments/pulso-estadios/pieza/captura.py
"""
import json
import time

import rutas
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

DEST = rutas.FRAMES
DEST.mkdir(parents=True, exist_ok=True)
for f in DEST.glob("*.png"):
    f.unlink()
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu-sandbox",
        "--allow-file-access-from-files"]
guion = json.loads(rutas.GUION.read_text())


def plano(ruta):
    st = ImageStat.Stat(Image.open(ruta).convert("RGB").resize((160, 85)))
    return sum(st.stddev) / 3 < 12


with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", headless=True, args=ARGS)
    pg = b.new_page(viewport={"width": 900, "height": 480}, device_scale_factor=2)
    # Sin teselas externas ya no hay nada en vuelo que esperar: el suelo es un asset local.
    vuelo = {"n": 0}

    pg.goto(rutas.ESCENA.as_uri(), wait_until="load", timeout=120_000)
    pg.wait_for_function("window.listo === true", timeout=60_000)
    pg.wait_for_timeout(7000)

    def quieto(limite=14.0):
        fin, estable = time.time() + limite, 0
        while time.time() < fin:
            if vuelo["n"] == 0 and pg.evaluate("window.pintados()") > 0:
                estable += 1
                if estable >= 2:
                    return
            else:
                estable = 0
            pg.wait_for_timeout(110)

    for i, paso in enumerate(guion):
        pg.evaluate(
            "a => { window.setVista(a.vista); window.setPesos(a.pesos); "
            "window.setEstado(a.estado); window.setFoco(a.foco); }", paso)
        quieto()
        pg.wait_for_timeout(150)
        destino = DEST / f"f{i:03d}.png"
        pg.screenshot(path=str(destino))
        if plano(destino):
            pg.wait_for_timeout(1600)
            pg.screenshot(path=str(destino))
        if i % 25 == 0:
            print("frame", i, flush=True)
    b.close()

malos = [f.name for f in sorted(DEST.glob("*.png")) if plano(f)]
print("capturados:", len(list(DEST.glob("*.png"))), "· planos:", len(malos), malos[:4])
