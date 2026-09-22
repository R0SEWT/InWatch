"""Escena de la 16: reloj con línea de tiempo, balón en la patada inicial y ficha del partido.

Tres cosas que la 15 no decía y el lector necesita:

  · QUÉ PARTIDO. Ninguno: cada columna promedia decenas de días de partido con público.
    La ficha lo dice con el número exacto por estadio, las competencias y el período, y
    el subtítulo lo dice con todas las letras para que nadie lea «un clásico».
  · CUÁNDO ES LA PATADA INICIAL. Antes era una palabra en una esquina. Ahora es una
    marca sobre una línea de tiempo, con el balón encima, y el cursor con la hora viaja
    por ella: se ve dónde estamos parados dentro de la ventana.
  · A QUÉ HORA JUEGAN. El kickoff mediano son las 20:00, así que «+3 h» es madrugada.
    Sin ese dato, las horas relativas flotan.

## La versión nocturna, y por qué no es decoración

El mapa era claro y eso AFIRMABA algo falso: la patada inicial mediana son las 20:00, o
sea que las trece horas que la pieza recorre son de noche. El suelo ahora se hornea en
paleta nocturna (`asset_basemap_noche.py`) y la pieza pasa a fondo oscuro.

El cambio arrastró cuatro decisiones que NO son de color, sino de codificación:

  · **Solo el núcleo de 0-500 m es torre.** La señal de esta pieza vive ahí. Extruir los
    cuatro anillos ponía al de 1-2 km —RR 1,6 en el Monumental, o sea 860 m de altura
    sobre un área enorme— compitiendo por el eje vertical con el único anillo que se
    mira, y ganándole por superficie. Los anillos de 500-1000 m y 1-2 km pasan a manchas
    planas: llevan la misma información, porque el color ES el cociente, sin disputar la
    altura.
  · **El de 2-4 km queda en contorno.** Su serie completa va de 0,93 a 1,25 en los tres
    estadios: es el anillo donde no pasa nada. Pintarlo era un lavado de color sobre un
    tercio del cuadro para decir «≈1», que es lo que el contorno ya dice al mostrar
    hasta dónde llega la medición.
  · **El color se recalcula acá, no se hereda del parquet.** El RdBu_r horneado asume
    papel blanco: sobre negro sus valores débiles quedan CLAROS, o sea brillantes, y un
    RR≈1 se leía como «alto». La rampa nocturna va de cian (menos riesgo) a transparente
    (igual que sin partido) a ámbar y rojo caliente, y la magnitud sigue en la opacidad.
  · **«Sin dato» se rediseñó.** El deshilachado era un wireframe gris que sobre papel se
    leía y sobre negro desaparecía — y desaparecer es exactamente lo que la primera regla
    dura del repo prohíbe. Ahora es una jaula de alambre CLARA sobre relleno casi nulo:
    estructura sin sustancia, visible, y sin color de la escala para que nadie la lea
    como un valor.

Los iconos son SVG en línea: nada que descargar, nada que se rompa sin red.
"""
import hashlib
import json
import urllib.request

import rutas

# deck.gl, pineado por versión Y por hash. Antes la escena traía el bundle de unpkg con un
# `<script src="https://…">`: la captura abre la página con `file://`, así que grabar
# dependía de tener red en ese instante y de que el CDN respondiera. Sin red, `deck` queda
# indefinido, el script aborta antes de marcar `listo` y la captura moría por timeout a los
# dos minutos sin decir por qué.
#
# No se versiona: es un megabyte de código de terceros y este repo pesa menos que eso. Se
# descarga una vez a la salida ignorada y se verifica por sha256 en cada corrida, que es lo
# que hace la copia local tan confiable como una versionada — y además detecta que el CDN
# sirvió otra cosa.
DECK_VERSION = "9.1.0"
DECK_URL = f"https://unpkg.com/deck.gl@{DECK_VERSION}/dist.min.js"
DECK_SHA256 = "2bedd345fd45691f115a9a0366285b638a52eb9bfe0a5a2986ca245ac941dd2a"


def asegurar_deck() -> str:
    """Devuelve el nombre del bundle local, descargándolo si falta o si no cuadra."""
    if rutas.DECK.exists():
        if hashlib.sha256(rutas.DECK.read_bytes()).hexdigest() == DECK_SHA256:
            return rutas.DECK.name
        print(f"  {rutas.DECK.name} no cuadra con el sha pineado, se vuelve a bajar")
    print(f"  bajando deck.gl {DECK_VERSION}…")
    with urllib.request.urlopen(DECK_URL, timeout=60) as r:  # noqa: S310
        blob = r.read()
    visto = hashlib.sha256(blob).hexdigest()
    if visto != DECK_SHA256:
        raise SystemExit(
            f"el bundle de deck.gl {DECK_VERSION} no cuadra con el sha pineado.\n"
            f"  esperado {DECK_SHA256}\n  recibido {visto}\n"
            "Si la subida de versión es intencional, actualizá DECK_SHA256 a mano."
        )
    rutas.asegurar()
    rutas.DECK.write_bytes(blob)
    return rutas.DECK.name

SALIDA = ("<svg viewBox='0 0 24 24' width='15' height='15'>"
          "<path d='M4 3.2h8.2v17.6H4z' fill='none' stroke='#e8e4db' stroke-width='1.7'/>"
          "<path d='M12.6 12h7.6m0 0l-3-3m3 3l-3 3' fill='none' stroke='#e8e4db' "
          "stroke-width='1.7' stroke-linecap='round'/></svg>")

BALON = ("<svg viewBox='0 0 24 24' width='17' height='17'>"
         "<circle cx='12' cy='12' r='10.5' fill='#e8e4db' stroke='#0b0d10' stroke-width='1.6'/>"
         "<path d='M12 5.6l4.1 3-1.6 4.9h-5L7.9 8.6z' fill='#0b0d10'/>"
         "<path d='M12 2.2v3.4M21.6 9.4l-5 2.9M17.5 21.2l-2.9-4.8M6.5 21.2l2.9-4.8"
         "M2.4 9.4l5 2.9' stroke='#0b0d10' stroke-width='1.3' fill='none'/></svg>")

HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<script src="__DECK__"></script>
<style>
  html,body{margin:0;padding:0;width:900px;height:480px;background:#0b0d10;
            font-family:'Liberation Sans',Arial,Helvetica,sans-serif;color:#f2efe9;}
  #mapa{position:absolute;inset:0;}
  /* Velos. Los rótulos caían sobre calles claras y perdían contraste; un degradado que
     muere en transparente los apoya sin meter una caja opaca en la escena. */
  .velo{position:absolute;left:0;right:0;pointer-events:none;}
  #veloArriba{top:0;height:108px;
              background:linear-gradient(to bottom,rgba(11,13,16,.90),rgba(11,13,16,0));}
  #veloAbajo{bottom:0;height:132px;
             background:linear-gradient(to top,rgba(11,13,16,.92),rgba(11,13,16,0));}
  .cap{position:absolute;}
  #cartel{left:16px;top:12px;}
  #cartel b{font-size:19px;font-weight:700;letter-spacing:-0.2px;}
  #cartel span{display:block;font-size:10.5px;color:#9b978e;margin-top:3px;}
  #cartel i{display:block;font-size:10px;color:#f08a6e;font-style:normal;margin-top:4px;
            font-weight:600;}
  #ficha{right:16px;top:12px;text-align:right;}
  #ficha b{font-size:14.5px;font-weight:700;}
  #ficha span{display:block;font-size:10px;color:#9b978e;margin-top:2px;line-height:1.45;}
  #lectura{display:block;font-size:12.5px;font-weight:700;color:#ff7a52;margin-top:5px;}
  #tiempo{left:16px;bottom:34px;width:392px;}
  #riel{position:relative;height:3px;background:#2b3037;border-radius:2px;}
  #antes{position:absolute;left:0;top:0;height:3px;background:#ff7a52;border-radius:2px;}
  #kick{position:absolute;left:50%;top:-11px;width:1.6px;height:25px;background:#e8e4db;
        transform:translateX(-50%);}
  /* La banda cubre la duración típica de un partido: de la patada inicial a la salida. */
  #partido{position:absolute;left:50%;width:16.67%;top:-4px;height:11px;
           background:rgba(255,122,82,.16);border-left:0;border-right:0;}
  #marcaSalida{position:absolute;left:66.67%;top:-9px;width:1.4px;height:21px;
               background:#e8e4db;transform:translateX(-50%);}
  #iconoSalida{position:absolute;left:66.67%;top:-28px;transform:translateX(-50%);
               line-height:0;}
  #rotSalida{position:absolute;left:66.67%;top:13px;transform:translateX(-50%);
             font-size:9px;color:#9b978e;font-weight:600;white-space:nowrap;}
  /* Tramo que ESTE estadio no puede medir: rayado, nunca vacío ni plano. Puede caer en
     los dos bordes de la ventana, así que son dos bandas. El rayado sube de claridad
     respecto de la versión en papel: sobre fondo oscuro un gris medio no se ve. */
  .nomide{position:absolute;top:-4px;height:11px;background:repeating-linear-gradient(
            -45deg,#6e747e 0 2px,transparent 2px 5px);opacity:.95;display:none;}
  #rotNomide{position:absolute;top:13px;font-size:8.5px;color:#9b978e;
             transform:translateX(-50%);white-space:nowrap;display:none;}
  #balon{position:absolute;left:50%;top:-31px;transform:translateX(-50%);line-height:0;}
  #cursor{position:absolute;top:-7px;width:13px;height:13px;border-radius:50%;
          background:#ff7a52;border:2px solid #0b0d10;transform:translateX(-50%);
          box-shadow:0 0 9px rgba(255,122,82,.65);}
  #hora{position:absolute;top:-56px;transform:translateX(-50%);font-size:15px;
        font-weight:700;color:#ff7a52;white-space:nowrap;}
  #ejes{display:flex;justify-content:space-between;margin-top:6px;font-size:9px;
        color:#7e7a73;}
  #ejes b{color:#9b978e;font-weight:600;}
  #pie{left:16px;bottom:10px;font-size:8px;color:#6f6c66;}
  #leyenda{right:16px;bottom:12px;font-size:8.5px;color:#9b978e;text-align:right;
           line-height:1.6;}
  .muestra{display:inline-block;width:11px;height:8px;vertical-align:middle;margin-right:4px;
           border:0.6px solid #4a4f57;}
  .muestraSin{display:inline-block;width:11px;height:8px;vertical-align:middle;
              margin-right:4px;background:transparent;border:0.9px dashed #ded9ce;}
</style></head>
<body>
<div id="mapa"></div>
<div id="veloArriba" class="velo"></div>
<div id="veloAbajo" class="velo"></div>
<div id="cartel" class="cap"><b>El pulso de estadios</b>
  <span>riesgo de robo callejero alrededor del estadio, hora por hora</span>
  <i id="aviso">__AVISO__</i></div>
<div id="ficha" class="cap"><b id="sede">los tres estadios</b><span id="detalle"></span>
  <span id="lectura"></span></div>
<div id="tiempo" class="cap">
  <div id="riel"><div id="nomideIzq" class="nomide"></div>
    <div id="nomideDer" class="nomide"></div><div id="rotNomide">sin dato</div>
    <div id="antes"></div><div id="partido"></div><div id="kick"></div>
    <div id="marcaSalida"></div><div id="iconoSalida">__SALIDA__</div>
    <div id="rotSalida">salida</div><div id="balon">__BALON__</div>
    <div id="cursor"></div><div id="hora">kickoff</div></div>
  <div id="ejes"><span>6 h antes</span>
    <b>patada inicial &middot; 20:00</b>
    <span>6 h despu&eacute;s</span></div>
</div>
<div id="pie" class="cap">la banda marca la duraci&oacute;n t&iacute;pica de un partido,
  de la patada inicial a la salida<br>
  EPSG:4326 &middot; &copy; OpenStreetMap (ODbL) &middot; l&iacute;mites INEI</div>
<div id="leyenda" class="cap">
  <span class="muestra" style="background:#ff4d2e"></span>riesgo alto &nbsp;
  <span class="muestra" style="background:#2fa3b8"></span>menor que sin partido &nbsp;
  <span class="muestraSin"></span>sin dato<br>
  <span style="opacity:.8">torre = 0-500 m,
    altura log&#8322; del cociente exagerada __EXAG_TXT__&times;
    &middot; el rayado, las horas que no puede medir</span>
</div>
<script>
// Si el bundle no cargó, la página lo DICE en vez de quedarse muda: `listo` se marca
// igual y la captura encuentra el motivo en `errorEscena`. Sin esto, el único síntoma
// era un timeout de dos minutos esperando `window.listo`.
if (typeof deck === 'undefined') {
  window.errorEscena = 'deck.gl no cargó: falta __DECK__ al lado de esta página';
  window.listo = true;
  throw new Error(window.errorEscena);
}
const D = __DATOS__;
const SUELO = __BOUNDS__;
const EST = __ESTADIOS__;
const FICHA = __FICHA__;
const EXAG = __EXAG__, PISO = 45.0;
let foco = 'todos', ultimoEstado = 0;
let pesos = {matute:1, nacional:1, monumental:1};

// Rampa nocturna. El RdBu_r horneado en el parquet asume papel blanco: sobre negro sus
// valores débiles quedan claros, o sea brillantes, y un RR≈1 se leía como «alto». Acá el
// cociente va de cian frío a transparente a rojo caliente, y la magnitud sigue viviendo
// en la opacidad. El lado frío no lleva rampa a propósito: un RR de 0 medido y uno de
// 0,2 son los dos «un cuarto o menos», y fingir que se distinguen sería precisión falsa.
function colorNoche(rr, w) {
  const l2 = Math.log2(Math.max(rr, 1e-3));
  const fuerza = Math.min(Math.abs(l2) / 2.0, 1.0);
  const a = Math.round((55 + 185 * fuerza) * w);
  if (l2 <= 0) { return [47, 163, 184, a]; }
  const t = Math.min(l2 / 3.4, 1.0);
  const paradas = [[255,196,92],[255,122,52],[255,58,38]];
  const i = Math.min(Math.floor(t * 2), 1), f = t * 2 - i;
  const c = paradas[i].map((v, j) => Math.round(v + (paradas[i+1][j] - v) * f));
  return [c[0], c[1], c[2], a];
}
function alto(h) { return PISO + (h - PISO) * EXAG; }

// Durante cada parada solo se dibuja el estadio enfocado. Antes los otros iban al 32 %
// de opacidad, y eso era un error de codificación: la opacidad ya significa tamaño del
// efecto (un RR cercano a 1 se pinta casi transparente), así que un anillo fuerte del
// vecino atenuado quedaba idéntico a uno nulo del estadio mirado. El peso entra y sale
// con un desvanecido durante el vuelo, que es cuando nadie está leyendo valores.
function filas(k) {
  return D.polis.map((p, i) => ({...p, ...D.estados[k][i], w: pesos[p.estadio]}))
                .filter(d => d.w > 0.02);
}

function capas(k) {
  const v = k, f = filas(k);
  const conDato = f.filter(d => d.soporte);
  // La torre es el núcleo. Los anillos intermedios, manchas planas. El de 2-4 km, solo
  // contorno, y en el color del foco: su serie entera va de 0,93 a 1,25.
  const nucleo = conDato.filter(d => d.anillo === 'r0_500');
  const manchas = conDato.filter(d => d.anillo === 'r500_1000' || d.anillo === 'r1000_2000');
  const fantasma = f.filter(d => !d.soporte);
  const aro = D.polis.filter(p => p.estadio === foco && p.anillo === 'r2000_4000'
                                  && pesos[p.estadio] > 0.02);
  // Charco de luz: lo que una torre encendida le hace al suelo. Señal redundante con la
  // altura, no una capa de dato nueva; existe para que el núcleo se despegue del fondo.
  const charcos = EST.filter(e => pesos[e.clave] > 0.02)
                     .map(e => ({...e, nucleo: nucleo.find(d => d.estadio === e.clave)}))
                     .filter(e => e.nucleo);
  return [
    new deck.BitmapLayer({id:'suelo', image:'__SUELO_IMG__', bounds:SUELO}),
    new deck.ScatterplotLayer({id:'charco', data:charcos, getPosition:d=>d.pos,
      getRadius:1500, getFillColor:d=>{
        const c = colorNoche(d.nucleo.rr, pesos[d.clave]);
        return [c[0], c[1], c[2], Math.round(c[3] * 0.16)];},
      stroked:false, parameters:{depthTest:false},
      updateTriggers:{data:[v, foco, pesos], getFillColor:[v, pesos]}}),
    new deck.PolygonLayer({id:'manchas', data:manchas, extruded:false, stroked:true,
      filled:true, getPolygon:d=>d.poligono,
      getFillColor:d=>{const c = colorNoche(d.rr, d.w);
                       return [c[0], c[1], c[2], Math.round(c[3] * 0.42)];},
      getLineColor:[190,186,178,55], lineWidthMinPixels:0.5,
      updateTriggers:{data:[v, pesos], getFillColor:[v, pesos]}}),
    new deck.PolygonLayer({id:'solido', data:nucleo, extruded:true,
      getPolygon:d=>d.poligono, getElevation:d=>alto(d.h),
      getFillColor:d=>colorNoche(d.rr, d.w), getLineColor:[214,209,199,95],
      lineWidthMinPixels:0.5, stroked:true, filled:true, material:true,
      updateTriggers:{data:[v, pesos], getElevation:v, getFillColor:[v, pesos]}}),
    // «Sin dato»: jaula de alambre clara sobre relleno casi nulo. Sobre fondo oscuro el
    // gris de la versión en papel desaparecía, y desaparecer es justo lo prohibido.
    new deck.PolygonLayer({id:'fantasma', data:fantasma, extruded:true, wireframe:true,
      getPolygon:d=>d.poligono, getElevation:d=>alto(d.h), getFillColor:[130,134,142,16],
      getLineColor:d=>[222,217,206, Math.round(205 * d.w)],
      lineWidthMinPixels:0.8, stroked:true, filled:true,
      material:false, updateTriggers:{data:[v, pesos], getElevation:v,
                                      getLineColor:pesos}}),
    new deck.PolygonLayer({id:'aro', data:aro, extruded:false, filled:false, stroked:true,
      getPolygon:d=>d.poligono, getLineColor:[255,122,82,120], lineWidthMinPixels:1.0,
      getLineWidth:24, updateTriggers:{data:foco}}),
    new deck.ScatterplotLayer({id:'sedes', data:EST, getPosition:d=>d.pos, getRadius:70,
      radiusMinPixels:2.5, getFillColor:[245,242,235], stroked:true,
      getLineColor:[11,13,16], lineWidthMinPixels:1, parameters:{depthTest:false}}),
    new deck.TextLayer({id:'nombres', data:EST, getPosition:d=>d.pos, getText:d=>d.nombre,
      getSize:d=>d.clave === foco ? 13.5 : 11.5,
      getColor:d=>d.clave === foco ? [255,170,140] : [146,142,134],
      // El desplazamiento tiene que despejar la torre en una parada, pero en la
      // panorámica esa misma altura deja el rótulo flotando lejos de su punto y pisando
      // el título. Dos alturas, según si hay un estadio enfocado.
      getPixelOffset:d => foco === 'todos' ? d.off : [0,-186],
      getAlignmentBaseline:'bottom', background:true,
      getBackgroundColor:d=>d.clave === foco ? [11,13,16,228] : [11,13,16,185],
      backgroundPadding:[5,3], fontFamily:'Liberation Sans, Arial, sans-serif',
      fontWeight:600, parameters:{depthTest:false},
      updateTriggers:{getSize:foco, getColor:foco, getBackgroundColor:foco,
                      getPixelOffset:foco}})
  ];
}

let pintado = 0;
const inst = new deck.Deck({parent:document.getElementById('mapa'), width:900, height:480,
  initialViewState:{longitude:-76.98, latitude:-12.06, zoom:11.2, pitch:45, bearing:-20},
  controller:false, parameters:{clearColor:[0.043,0.051,0.063,1]},
  layers:capas(0), onAfterRender:()=>{pintado+=1;}});

window.setVista = v => { pintado=0; inst.setProps({viewState:{longitude:v.lng, latitude:v.lat,
  zoom:v.zoom, pitch:v.pitch, bearing:v.bearing}}); };

// El estado se pide por índice de frame; el reloj marca horas enteras y el cursor viaja
// de forma continua por la línea de tiempo.
window.setEstado = k => {
  pintado = 0; ultimoEstado = k;
  inst.setProps({layers: capas(k)});
  const h = D.etiquetas[k];
  const pct = 100 * k / (D.estados.length - 1);
  document.getElementById('cursor').style.left = pct + '%';
  document.getElementById('hora').style.left = pct + '%';
  document.getElementById('antes').style.width = pct + '%';
  // En los dos momentos que la pieza existe para mostrar, el cursor nombra el momento
  // en vez de una hora abstracta: es lo que el lector está mirando.
  const rel = (h > 0 ? '+' : '\\u2212') + Math.abs(h) + ' h';
  document.getElementById('hora').textContent =
    h === 0 ? 'patada inicial' : (h === 2 ? rel + ' \\u00b7 salida' : rel);
  lectura(k);
};

// El color dice «alto» o «bajo»; el número dice cuánto. Los dos, o el lector adivina.
function lectura(k) {
  const caja = document.getElementById('lectura');
  if (foco === 'todos') { caja.textContent = ''; return; }
  const i = D.polis.findIndex(p => p.estadio === foco && p.anillo === 'r0_500');
  // Se lee el estado de la HORA que marca el reloj, no el del frame: en los frames de
  // transición el cursor ya nombra una hora y la ficha tiene que decir lo de esa hora.
  const e = D.estados[D.indice_hora[String(D.etiquetas[k])]][i];
  caja.textContent = e.soporte
    ? 'a 0-500 m: ' + e.rr.toFixed(1).replace('.', ',') + 'x el riesgo sin partido'
    : 'a 0-500 m: sin dato en esta hora';
}
// Los pesos los fija el guion: 1 el estadio en escena, 0 los demás, con rampa en el vuelo.
window.setPesos = p => {
  pesos = p; pintado = 0;
  inst.setProps({layers: capas(ultimoEstado)});
};
window.setFoco = clave => {
  foco = clave; pintado = 0;
  // El rayado cubre, sobre la misma escala de −6 a +6 h, lo que este estadio no mide.
  // El rótulo se pone sobre el tramo más ancho: dos rótulos de 8,5 px son ruido.
  const h0 = D.horas[0], h1 = D.horas[D.horas.length - 1], total = h1 - h0;
  const r = D.rangos[clave];
  const tramos = r ? [[h0, r[0]], [r[1], h1]] : [[0, 0], [0, 0]];
  const rot = document.getElementById('rotNomide');
  let mayor = null;
  ['nomideIzq', 'nomideDer'].forEach((id, i) => {
    const div = document.getElementById(id);
    const ancho = 100 * (tramos[i][1] - tramos[i][0]) / total;
    if (ancho > 0.5) {
      div.style.left = (100 * (tramos[i][0] - h0) / total) + '%';
      div.style.width = ancho + '%';
      div.style.display = 'block';
      if (!mayor || ancho > mayor.ancho) {
        mayor = {ancho, medio: 100 * ((tramos[i][0] + tramos[i][1]) / 2 - h0) / total};
      }
    } else { div.style.display = 'none'; }
  });
  if (mayor) { rot.style.left = mayor.medio + '%'; rot.style.display = 'block'; }
  else { rot.style.display = 'none'; }
  inst.setProps({layers: capas(ultimoEstado)});
  const f = FICHA[clave];
  document.getElementById('sede').textContent = f.titulo;
  document.getElementById('detalle').innerHTML = f.detalle;
  document.getElementById('aviso').innerHTML = f.aviso;
  lectura(ultimoEstado);
};
window.pintados = () => pintado;
window.listo = true;
</script></body></html>
"""

# Exageración vertical. Con 2,5x la torre del Monumental a la salida se salía del cuadro;
# con 1,8x entra y sigue leyéndose como aguja. Va declarada en la leyenda porque una
# altura exagerada sin decirlo es una afirmación falsa sobre la magnitud.
EXAG = 1.8

datos = json.loads(rutas.DATOS.read_text())
bounds = json.loads(rutas.SUELO_BOUNDS.read_text())
# `off` es el desplazamiento del rótulo en la PANORÁMICA. Nacional y Matute están a
# 1,2 km: con el mismo desplazamiento sus rótulos se pisaban y se leía «Estadio
# NaMatute» — justo en el primer y el último frame, que son la miniatura de la pieza.
# En una parada no hace falta: ahí el rótulo del enfocado despeja su propia torre.
estadios = [{"pos": [-77.02293, -12.06850], "nombre": "Matute", "clave": "matute",
             "off": [54, -16]},
            {"pos": [-77.03386, -12.06707], "nombre": "Estadio Nacional",
             "clave": "nacional", "off": [-50, -60]},
            {"pos": [-76.93533, -12.05565], "nombre": "Estadio Monumental",
             "clave": "monumental", "off": [0, -60]}]

# Ficha por estadio. Los días son los que entran a la estimación (con control válido),
# no los partidos jugados: por eso no coinciden con el calendario. Y NO se escriben acá:
# salen del parquet vía `datos["dias"]`, porque un número en pantalla que nadie puede
# re-derivar es justo el fallo que este repo existe para no repetir.
DIAS = datos["dias"]
TOTAL = sum(DIAS.values())
TITULO = {"matute": "Matute", "nacional": "Estadio Nacional",
          "monumental": "Estadio Monumental"}
EN = {"matute": "en Matute", "nacional": "en el Nacional", "monumental": "en el Monumental"}
COMPETENCIA = {"matute": "Liga 1", "nacional": "Liga 1 y Libertadores",
               "monumental": "Liga 1 y Libertadores"}
PERIODO = "2019&ndash;2023"

FICHA = {
    "todos": {"titulo": "los tres estadios",
              "detalle": f"Matute &middot; Nacional &middot; Monumental<br>"
                         f"{TOTAL} d&iacute;as de partido &middot; {PERIODO}",
              "aviso": f"promedio de {TOTAL} d&iacute;as de partido con p&uacute;blico "
                       f"&mdash; no un partido"},
}
for _c, _n in TITULO.items():
    FICHA[_c] = {
        "titulo": _n,
        "detalle": f"{DIAS[_c]} d&iacute;as de partido con p&uacute;blico<br>"
                   f"{COMPETENCIA[_c]} &middot; {PERIODO}",
        "aviso": f"promedio de {DIAS[_c]} d&iacute;as de partido {EN[_c]} &mdash; no un partido",
    }

html = (HTML.replace("__DATOS__", json.dumps(datos))
            .replace("__BOUNDS__", json.dumps(bounds))
            .replace("__ESTADIOS__", json.dumps(estadios))
            .replace("__FICHA__", json.dumps(FICHA))
            .replace("__AVISO__", FICHA["todos"]["aviso"])
            .replace("__EXAG_TXT__", f"{EXAG}".replace(".", ","))
            .replace("__EXAG__", repr(float(EXAG)))
            .replace("__BALON__", BALON)
            .replace("__DECK__", asegurar_deck())
            .replace("__SUELO_IMG__", rutas.SUELO.name)
            .replace("__SALIDA__", SALIDA))
assert "__" not in html.replace("__pycache__", ""), "quedó un placeholder sin reemplazar"
rutas.asegurar()
rutas.ESCENA.write_text(html)
print(f"{rutas.ESCENA.name}: {rutas.ESCENA.stat().st_size / 1e6:.2f} MB · "
      f"exageración {EXAG}x · suelo nocturno")
