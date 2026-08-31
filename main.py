"""App web del agente de soporte (FastAPI) para Cloud Run."""
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import agente as ag

app = FastAPI(title="Agente de Soporte LLM")
agente = ag.AgenteSoporte()


class ChatIn(BaseModel):
    mensaje: str
    confirmar: bool = False


@app.get("/api/info")
def info():
    cadena = ag.cadena_llm()
    return {
        "firestore": agente.firestore_activo,
        "llm": ag.llm_disponible(),
        "proveedor": cadena[0] if cadena else None,
        "cadena": cadena + ["regex"],
        "modelo_activo": ag.modelo_en_uso(),
        "modelos_candidatos": ag.LLM_MODELOS_CANDIDATOS,
        "herramientas": ag.CATALOGO_HERRAMIENTAS,
    }


@app.post("/api/chat")
def chat(entrada: ChatIn):
    mensaje = entrada.mensaje.strip()[:500]
    if not mensaje:
        return {"respuesta": "Escribe un mensaje.", "pendiente_confirmacion": False}
    return agente.responder(mensaje, confirmar=entrada.confirmar)


@app.get("/api/memoria")
def memoria():
    return {"eventos": agente.repo.listar_memoria(limite=15)}


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGINA


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agente de Soporte</title>
<style>
  :root {
    --fondo:#eef1f7; --panel:#ffffff; --panel-suave:#f7f9fc;
    --texto:#1a2233; --sec:#64748b; --borde:#e4e8f0;
    --primario:#2563eb; --primario-osc:#1d4ed8; --primario-tenue:#eff4ff;
    --acento:#d92632;
    --ambar:#b45309; --ambar-bg:#fef3c7; --ambar-borde:#fcd34d;
    --verde:#047857; --verde-bg:#ecfdf5;
    --rojo:#b91c1c; --rojo-bg:#fee2e2;
    --sombra:0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.08);
    --radio:16px;
  }
  * { box-sizing:border-box; }
  html, body { height:100%; }
  body {
    margin:0; background:var(--fondo); color:var(--texto);
    font-family:ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    font-size:15px; line-height:1.5;
  }

  .app { display:grid; grid-template-columns:340px minmax(0,1fr); gap:20px;
         max-width:1180px; margin:0 auto; padding:20px; height:100dvh; }

  /* ---------- Barra lateral ---------- */
  .lateral { display:flex; flex-direction:column; gap:14px; overflow-y:auto;
             padding-right:2px; }
  .tarjeta { background:var(--panel); border:1px solid var(--borde);
             border-radius:var(--radio); box-shadow:var(--sombra); }
  .marca { padding:18px; display:flex; flex-direction:column; gap:12px;
           border-top:3px solid var(--acento); }
  .marca-fila { display:flex; align-items:center; gap:12px; }
  a.logo { background:#141c2b; border-radius:12px; padding:8px 12px;
           display:flex; align-items:center; flex-shrink:0; }
  a.logo img { height:36px; display:block; }
  .marca h1 { font-size:1.12rem; margin:0; letter-spacing:-.01em; }
  .subtitulo { font-size:.78rem; color:var(--sec); margin-top:2px; line-height:1.35; }
  .estados { display:flex; flex-wrap:wrap; gap:6px; }
  .badge { display:inline-flex; align-items:center; gap:6px; font-size:.74rem;
           padding:4px 10px; border-radius:999px; border:1px solid var(--borde);
           background:var(--panel-suave); color:var(--sec); font-weight:500; }
  .badge .punto { width:7px; height:7px; border-radius:50%; background:#cbd5e1; }
  .badge.on { color:var(--verde); border-color:#a7f3d0; background:var(--verde-bg); }
  .badge.on .punto { background:#10b981; }

  details.info { padding:0 18px 14px; }
  details.info summary { cursor:pointer; color:var(--primario); font-weight:600;
                         font-size:.86rem; padding:14px 0 6px; list-style-position:inside; }
  .herramienta { display:flex; gap:10px; padding:9px 0; border-bottom:1px solid var(--panel-suave);
                 font-size:.8rem; align-items:flex-start; }
  .herramienta:last-of-type { border-bottom:0; }
  .herramienta .icono { flex-shrink:0; width:26px; height:26px; border-radius:8px;
                        background:var(--primario-tenue); display:flex; align-items:center;
                        justify-content:center; font-size:.85rem; }
  .herramienta strong { display:block; font-size:.8rem; }
  .herramienta .desc { color:var(--sec); font-size:.75rem; line-height:1.4; }
  .tag-conf { display:inline-block; font-size:.66rem; background:var(--ambar-bg);
              color:var(--ambar); border:1px solid var(--ambar-borde); border-radius:999px;
              padding:0 7px; margin-left:4px; vertical-align:middle; }
  .descargo { font-size:.74rem; color:var(--sec); line-height:1.5;
              border-top:1px solid var(--borde); margin-top:10px; padding-top:10px; }
  .descargo strong { color:var(--texto); }

  /* ---------- Zona principal ---------- */
  .principal { display:flex; flex-direction:column; min-height:0; gap:10px; }
  #chat { flex:1; overflow-y:auto; background:var(--panel); border:1px solid var(--borde);
          border-radius:var(--radio); box-shadow:var(--sombra); padding:20px;
          display:flex; flex-direction:column; gap:14px; scroll-behavior:smooth; }
  .fila { display:flex; gap:10px; max-width:88%; }
  .fila.usuario { align-self:flex-end; flex-direction:row-reverse; }
  .avatar { width:30px; height:30px; border-radius:50%; flex-shrink:0;
            display:flex; align-items:center; justify-content:center; font-size:.9rem;
            background:var(--primario-tenue); margin-top:2px; }
  .burbuja { padding:11px 14px; border-radius:14px; font-size:.92rem; line-height:1.5;
             white-space:pre-wrap; overflow-wrap:anywhere; }
  .fila.agente .burbuja { background:var(--panel-suave); border:1px solid var(--borde);
                          border-bottom-left-radius:4px; white-space:normal; }
  .fila.usuario .burbuja { background:var(--primario); color:#fff;
                           border-bottom-right-radius:4px; }
  .meta { display:flex; gap:6px; margin-top:9px; flex-wrap:wrap; }
  .meta span { font-size:.68rem; background:#fff; border:1px solid var(--borde);
               color:var(--sec); border-radius:999px; padding:1px 8px; }

  /* Filas de tickets estructuradas */
  .tickets { display:flex; flex-direction:column; gap:6px; margin-top:8px; }
  .ticket { display:flex; align-items:center; gap:8px; flex-wrap:wrap; background:#fff;
            border:1px solid var(--borde); border-radius:10px; padding:7px 10px; font-size:.8rem; }
  .ticket code { background:var(--primario-tenue); color:var(--primario); border-radius:6px;
                 padding:1px 7px; font-size:.74rem; font-weight:600; }
  .ticket .asunto { flex:1 1 100%; color:var(--texto); }
  .pill { font-size:.68rem; font-weight:600; border-radius:999px; padding:1px 9px; }
  .est-abierto { background:var(--primario-tenue); color:var(--primario); }
  .est-en_progreso { background:var(--ambar-bg); color:var(--ambar); }
  .est-cerrado { background:var(--verde-bg); color:var(--verde); }
  .pri-baja { background:#f1f5f9; color:var(--sec); }
  .pri-media { background:var(--primario-tenue); color:var(--primario); }
  .pri-alta { background:var(--ambar-bg); color:var(--ambar); }
  .pri-critica { background:var(--rojo-bg); color:var(--rojo); }

  /* Confirmación */
  .confirmar { align-self:flex-start; max-width:88%; background:var(--ambar-bg);
               border:1px solid var(--ambar-borde); border-radius:14px; padding:12px 14px;
               font-size:.88rem; color:var(--ambar); }
  .confirmar .acciones { margin-top:10px; display:flex; gap:8px; }
  .confirmar button { border:0; border-radius:9px; padding:8px 16px; cursor:pointer;
                      font-size:.84rem; font-weight:600; }
  .btn-si { background:var(--ambar); color:#fff; }
  .btn-si:hover { filter:brightness(1.1); }
  .btn-no { background:#fff; color:var(--texto); border:1px solid var(--borde) !important; }

  /* Escribiendo... */
  .escribiendo { display:flex; gap:4px; padding:6px 2px; }
  .escribiendo i { width:7px; height:7px; border-radius:50%; background:#94a3b8;
                   animation:latido 1.2s infinite ease-in-out; }
  .escribiendo i:nth-child(2) { animation-delay:.15s; }
  .escribiendo i:nth-child(3) { animation-delay:.3s; }
  @keyframes latido { 0%,60%,100% { opacity:.3; transform:translateY(0); }
                      30% { opacity:1; transform:translateY(-3px); } }

  /* Sugerencias + formulario */
  .sugerencias { display:flex; gap:6px; flex-wrap:wrap; }
  .sugerencias span { font-size:.76rem; border:1px solid var(--borde); background:var(--panel);
                      color:var(--sec); padding:5px 12px; border-radius:999px; cursor:pointer;
                      transition:all .12s; }
  .sugerencias span:hover { color:var(--primario); border-color:var(--primario);
                            background:var(--primario-tenue); }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; padding:13px 16px; border:1px solid var(--borde); border-radius:13px;
                     font-size:.94rem; background:var(--panel); color:var(--texto);
                     box-shadow:var(--sombra); }
  input[type=text]:focus { outline:2px solid var(--primario); border-color:transparent; }
  button.enviar { background:var(--primario); color:#fff; border:0; border-radius:13px;
                  padding:0 22px; font-size:.94rem; font-weight:600; cursor:pointer;
                  box-shadow:var(--sombra); }
  button.enviar:disabled { opacity:.5; cursor:default; }
  button.enviar:hover:not(:disabled) { background:var(--primario-osc); }
  .descargo-pie { font-size:14.2px; color:var(--sec); text-align:center; padding:2px 8px 4px;
                  line-height:1.4; }

  /* ---------- Responsive ---------- */
  @media (max-width: 959px) {
    .app { grid-template-columns:1fr; height:auto; min-height:100dvh; padding:12px; gap:12px; }
    .lateral { overflow:visible; }
    #chat { min-height:420px; }
  }
</style>
</head>
<body>
<div class="app">

  <aside class="lateral">
    <div class="tarjeta marca">
      <div class="marca-fila">
        <a class="logo" href="https://dcc.uchile.cl/" target="_blank" rel="noopener"
           title="DCC — Universidad de Chile">
          <img src="https://dcc.uchile.cl/static/images/base/logo.svg"
               alt="DCC — Ciencias de la Computación, Universidad de Chile"
               onerror="this.parentElement.hidden = true;">
        </a>
        <div>
          <h1>🛟 Agente de Soporte</h1>
          <div class="subtitulo">Trabajo final — Curso Transformers y Agentes · DCC, Universidad de Chile</div>
        </div>
      </div>
      <div class="estados" id="badges"></div>
    </div>

    <div class="tarjeta">
      <details class="info" id="panelInfo" open>
        <summary>¿Qué puede hacer este agente?</summary>
        <div id="listaHerramientas"></div>
        <div class="descargo">
          <strong>Acerca de este sitio:</strong> trabajo final del curso
          <em>Transformers y Agentes</em> del DCC de la Universidad de Chile, realizado por
          <strong>Carlos González C.</strong> No es una versión productiva: existe únicamente
          con fines académicos de cierre de curso.
        </div>
        <div class="descargo">
          <strong>Limitaciones:</strong> el agente solo ejecuta las operaciones listadas;
          cualquier otra solicitud no está soportada ni se valida. Las respuestas las genera
          un modelo de IA y <strong>pueden contener errores</strong>: verifica los datos antes
          de tomar decisiones. Las acciones sensibles siempre exigen tu confirmación explícita.
        </div>
      </details>
    </div>
  </aside>

  <main class="principal">
    <div id="chat"></div>
    <div class="sugerencias" id="sugerencias"></div>
    <form id="form">
      <input type="text" id="entrada" placeholder="Escribe tu solicitud..." autocomplete="off" maxlength="500">
      <button class="enviar" id="btn" type="submit">Enviar</button>
    </form>
    <div class="descargo-pie">Trabajo final del curso Transformers y Agentes (DCC, U. de Chile) · Carlos González C. · Versión académica, no productiva — la IA puede cometer errores.</div>
  </main>
</div>

<script>
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const entrada = document.getElementById('entrada');
const btn = document.getElementById('btn');

const ICONOS = {
  buscar_cliente: '🔍', crear_ticket: '📝', listar_tickets: '📋',
  actualizar_estado_ticket: '🔄', resumir_tickets: '📊',
  notificar_cliente: '📨', resumir_tickets_cliente: '👤',
};
const NOMBRES_AMIGABLES = {
  buscar_cliente: 'Buscar cliente',
  crear_ticket: 'Crear ticket',
  listar_tickets: 'Listar tickets',
  actualizar_estado_ticket: 'Cambiar estado de un ticket',
  resumir_tickets: 'Resumen general de tickets',
  notificar_cliente: 'Notificar a un cliente (simulado)',
  resumir_tickets_cliente: 'Resumen de tickets por cliente',
};

const SUGERENCIAS = [
  'Dame un resumen de tickets',
  'Buscar cliente Ana',
  'Muestra los tickets abiertos',
  'Cierra tic_002',
  'Avísale a Carla Soto que su caso fue escalado',
];
const cajaSug = document.getElementById('sugerencias');
SUGERENCIAS.forEach(s => {
  const el = document.createElement('span');
  el.textContent = s;
  el.onclick = () => { entrada.value = s; entrada.focus(); };
  cajaSug.appendChild(el);
});

const RE_TICKET = /^-\\s*(tic_\\d+)\\s*\\|\\s*(\\S+)\\s*\\|\\s*(\\w+)\\s*\\|\\s*(\\w+)\\s*\\|\\s*(.+)$/;

function pill(clasePrefijo, valor) {
  const s = document.createElement('span');
  s.className = 'pill ' + clasePrefijo + '-' + valor;
  s.textContent = valor.replace('_', ' ');
  return s;
}

// Convierte las respuestas del agente en contenido estructurado:
// las líneas "- tic_xxx | cliente | estado | prioridad | asunto" se
// renderizan como filas con chips de color; el resto, como texto.
function renderContenido(texto, contenedor) {
  const lineas = texto.split('\\n');
  let parrafo = [];
  let listaTickets = null;

  const cerrarParrafo = () => {
    if (parrafo.length) {
      const p = document.createElement('div');
      p.textContent = parrafo.join('\\n');
      p.style.whiteSpace = 'pre-wrap';
      contenedor.appendChild(p);
      parrafo = [];
    }
  };

  lineas.forEach(linea => {
    const m = linea.match(RE_TICKET);
    if (m) {
      cerrarParrafo();
      if (!listaTickets) {
        listaTickets = document.createElement('div');
        listaTickets.className = 'tickets';
        contenedor.appendChild(listaTickets);
      }
      const fila = document.createElement('div');
      fila.className = 'ticket';
      const id = document.createElement('code');
      id.textContent = m[1];
      fila.appendChild(id);
      fila.appendChild(pill('est', m[3]));
      fila.appendChild(pill('pri', m[4]));
      const cli = document.createElement('span');
      cli.style.color = 'var(--sec)';
      cli.textContent = m[2];
      fila.appendChild(cli);
      const asunto = document.createElement('span');
      asunto.className = 'asunto';
      asunto.textContent = m[5];
      fila.appendChild(asunto);
      listaTickets.appendChild(fila);
    } else {
      listaTickets = null;
      parrafo.push(linea);
    }
  });
  cerrarParrafo();
}

function filaMensaje(clase) {
  const fila = document.createElement('div');
  fila.className = 'fila ' + clase;
  if (clase === 'agente') {
    const av = document.createElement('div');
    av.className = 'avatar';
    av.textContent = '🛟';
    fila.appendChild(av);
  }
  const burbuja = document.createElement('div');
  burbuja.className = 'burbuja';
  fila.appendChild(burbuja);
  chat.appendChild(fila);
  chat.scrollTop = chat.scrollHeight;
  return { fila, burbuja };
}

function agregarUsuario(texto) {
  filaMensaje('usuario').burbuja.textContent = texto;
}

function agregarAgente(texto, plan, origen) {
  const { burbuja } = filaMensaje('agente');
  renderContenido(texto, burbuja);
  if (plan) {
    const meta = document.createElement('div');
    meta.className = 'meta';
    const h = document.createElement('span');
    h.textContent = (ICONOS[plan.nombre] || '⚙️') + ' ' + (NOMBRES_AMIGABLES[plan.nombre] || plan.nombre);
    meta.appendChild(h);
    if (origen) {
      const o = document.createElement('span');
      o.textContent = origen === 'llm' ? 'plan: LLM' : 'plan: ' + origen;
      meta.appendChild(o);
    }
    burbuja.appendChild(meta);
  }
  chat.scrollTop = chat.scrollHeight;
}

function agregarEscribiendo() {
  const { fila, burbuja } = filaMensaje('agente');
  const dots = document.createElement('div');
  dots.className = 'escribiendo';
  for (let i = 0; i < 3; i++) dots.appendChild(document.createElement('i'));
  burbuja.appendChild(dots);
  return fila;
}

async function enviar(mensaje, confirmar) {
  btn.disabled = true;
  const cargando = agregarEscribiendo();
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mensaje, confirmar}),
    });
    const data = await r.json();
    cargando.remove();
    agregarAgente(data.respuesta || 'Sin respuesta.', data.plan, data.origen_plan);
    if (data.pendiente_confirmacion && !confirmar) {
      const div = document.createElement('div');
      div.className = 'confirmar';
      div.textContent = '⚠ Esta acción es sensible y requiere tu confirmación.';
      const acciones = document.createElement('div');
      acciones.className = 'acciones';
      const si = document.createElement('button');
      si.className = 'btn-si'; si.textContent = 'Confirmar y ejecutar';
      const no = document.createElement('button');
      no.className = 'btn-no'; no.textContent = 'Cancelar';
      si.onclick = () => { div.remove(); agregarUsuario('✓ Confirmado'); enviar(mensaje, true); };
      no.onclick = () => { div.remove(); agregarAgente('Acción cancelada. No se realizaron cambios.'); };
      acciones.appendChild(si); acciones.appendChild(no);
      div.appendChild(acciones);
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (e) {
    cargando.remove();
    agregarAgente('Error de conexión: ' + e);
  } finally {
    btn.disabled = false;
    entrada.focus();
  }
}

form.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const mensaje = entrada.value.trim();
  if (!mensaje || btn.disabled) return;
  agregarUsuario(mensaje);
  entrada.value = '';
  enviar(mensaje, false);
});

// Mensaje de bienvenida
agregarAgente('Hola, soy el agente de soporte. Puedo buscar clientes, crear, listar y cerrar tickets, hacer resúmenes y enviar notificaciones (simuladas). Las acciones sensibles te pedirán confirmación — revisa el panel lateral para ver el detalle de herramientas y limitaciones.');

// Panel lateral: cerrado por defecto en pantallas pequeñas
if (window.matchMedia('(max-width: 959px)').matches) {
  document.getElementById('panelInfo').removeAttribute('open');
}

function badge(texto, ok) {
  const b = document.createElement('span');
  b.className = 'badge' + (ok ? ' on' : '');
  const punto = document.createElement('i');
  punto.className = 'punto';
  b.appendChild(punto);
  b.appendChild(document.createTextNode(texto));
  return b;
}

fetch('/api/info').then(r => r.json()).then(info => {
  const lista = document.getElementById('listaHerramientas');
  (info.herramientas || []).forEach(h => {
    const fila = document.createElement('div');
    fila.className = 'herramienta';
    const icono = document.createElement('div');
    icono.className = 'icono';
    icono.textContent = ICONOS[h.nombre] || '⚙️';
    fila.appendChild(icono);
    const cuerpo = document.createElement('div');
    const nombre = document.createElement('strong');
    nombre.textContent = NOMBRES_AMIGABLES[h.nombre] || h.nombre;
    cuerpo.appendChild(nombre);
    if (h.requiere_confirmacion) {
      const tag = document.createElement('span');
      tag.className = 'tag-conf';
      tag.textContent = 'requiere confirmación';
      nombre.appendChild(tag);
    }
    const desc = document.createElement('div');
    desc.className = 'desc';
    desc.textContent = h.descripcion;
    cuerpo.appendChild(desc);
    fila.appendChild(cuerpo);
    lista.appendChild(fila);
  });

  const badges = document.getElementById('badges');
  let llmTexto = 'LLM: no configurado';
  if (info.llm) {
    let modelo = info.modelo_activo || info.proveedor || 'listo';
    if (modelo.includes('por definir')) modelo = info.proveedor || 'listo';
    llmTexto = 'LLM: ' + modelo.split('/').pop().replace(':free', '');
  }
  badges.appendChild(badge(llmTexto, info.llm));
  badges.appendChild(badge(info.firestore ? 'Firestore conectado' : 'Firestore: modo demo', info.firestore));
});

entrada.focus();
</script>
</body>
</html>
"""
