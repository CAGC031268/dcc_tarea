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
    return {
        "firestore": agente.firestore_activo,
        "llm": ag.llm_disponible(),
        "modelo_activo": ag.LLM_MODELO_ACTIVO,
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
  :root { --bg:#f4f6fb; --panel:#ffffff; --texto:#1f2937; --sec:#6b7280;
          --azul:#2563eb; --azul-osc:#1d4ed8; --amar:#b45309; --amar-bg:#fef3c7;
          --verde:#047857; --borde:#e5e7eb; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
         background:var(--bg); color:var(--texto); }
  .contenedor { max-width:760px; margin:0 auto; padding:16px; display:flex;
                flex-direction:column; height:100dvh; }
  header { display:flex; align-items:center; justify-content:space-between; gap:8px;
           padding:10px 0 14px; }
  header h1 { font-size:1.15rem; margin:0; }
  .badges { display:flex; gap:6px; flex-wrap:wrap; }
  .badge { font-size:.72rem; padding:3px 9px; border-radius:999px; border:1px solid var(--borde);
           background:var(--panel); color:var(--sec); }
  .badge.on { color:var(--verde); border-color:#a7f3d0; background:#ecfdf5; }
  #chat { flex:1; overflow-y:auto; background:var(--panel); border:1px solid var(--borde);
          border-radius:14px; padding:16px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:85%; padding:10px 14px; border-radius:14px; white-space:pre-wrap;
         line-height:1.45; font-size:.93rem; }
  .usuario { align-self:flex-end; background:var(--azul); color:#fff; border-bottom-right-radius:4px; }
  .agente  { align-self:flex-start; background:#f1f5f9; border-bottom-left-radius:4px; }
  .meta { font-size:.7rem; color:var(--sec); margin-top:6px; }
  .confirmar { align-self:flex-start; background:var(--amar-bg); border:1px solid #fcd34d;
               border-radius:14px; padding:10px 14px; font-size:.9rem; color:var(--amar); }
  .confirmar button { margin-top:8px; margin-right:8px; border:0; border-radius:8px; padding:7px 14px;
                      cursor:pointer; font-size:.85rem; }
  .btn-si { background:var(--amar); color:#fff; }
  .btn-no { background:#e5e7eb; color:var(--texto); }
  form { display:flex; gap:8px; padding-top:12px; }
  input[type=text] { flex:1; padding:12px 14px; border:1px solid var(--borde); border-radius:12px;
                     font-size:.95rem; background:var(--panel); color:var(--texto); }
  input[type=text]:focus { outline:2px solid var(--azul); border-color:transparent; }
  button.enviar { background:var(--azul); color:#fff; border:0; border-radius:12px;
                  padding:0 20px; font-size:.95rem; cursor:pointer; }
  button.enviar:disabled { opacity:.5; cursor:default; }
  button.enviar:hover:not(:disabled) { background:var(--azul-osc); }
  .sugerencias { display:flex; gap:6px; flex-wrap:wrap; padding-top:8px; }
  .sugerencias span { font-size:.75rem; border:1px solid var(--borde); background:var(--panel);
                      color:var(--sec); padding:4px 10px; border-radius:999px; cursor:pointer; }
  .sugerencias span:hover { color:var(--azul); border-color:var(--azul); }
  details.info { background:var(--panel); border:1px solid var(--borde); border-radius:12px;
                 padding:10px 14px; margin-bottom:10px; font-size:.85rem; }
  details.info summary { cursor:pointer; color:var(--azul); font-weight:600; }
  details.info ul { margin:10px 0 6px; padding-left:18px; }
  details.info li { margin-bottom:6px; line-height:1.4; }
  details.info code { background:#f1f5f9; padding:1px 5px; border-radius:5px; font-size:.8rem; }
  .tag-conf { font-size:.7rem; background:var(--amar-bg); color:var(--amar);
              border:1px solid #fcd34d; border-radius:999px; padding:1px 8px; margin-left:6px; }
  .descargo { font-size:.75rem; color:var(--sec); line-height:1.45; border-top:1px solid var(--borde);
              margin-top:8px; padding-top:8px; }
  .descargo-pie { font-size:.7rem; color:var(--sec); text-align:center; padding:6px 0 2px; }
</style>
</head>
<body>
<div class="contenedor">
  <header>
    <h1>🛟 Agente de Soporte</h1>
    <div class="badges" id="badges"></div>
  </header>
  <details class="info" id="panelInfo">
    <summary>ℹ️ ¿Qué puede hacer este agente? — herramientas y limitaciones</summary>
    <ul id="listaHerramientas"><li>Cargando catálogo...</li></ul>
    <div class="descargo">
      <strong>Limitaciones:</strong> el agente solo ejecuta las operaciones listadas arriba;
      cualquier otra solicitud no está soportada ni se valida, y será rechazada o respondida
      con ayuda. Las respuestas las genera un modelo de IA y <strong>pueden contener errores</strong>:
      verifica los datos antes de tomar decisiones, y recuerda que las acciones sensibles
      (cambiar estado de tickets, notificar clientes) siempre exigen tu confirmación explícita.
    </div>
  </details>
  <div id="chat">
    <div class="msg agente">Hola, soy el agente de soporte. Puedo buscar clientes, crear, listar y cerrar tickets, hacer resúmenes y enviar notificaciones (simuladas). Las acciones sensibles te pedirán confirmación. Revisa "¿Qué puede hacer este agente?" para ver el detalle.</div>
  </div>
  <div class="sugerencias" id="sugerencias"></div>
  <form id="form">
    <input type="text" id="entrada" placeholder="Escribe tu solicitud..." autocomplete="off" maxlength="500">
    <button class="enviar" id="btn" type="submit">Enviar</button>
  </form>
  <div class="descargo-pie">Agente demo con IA: puede cometer errores. Solo opera sobre los datos de prueba del laboratorio.</div>
</div>
<script>
const chat = document.getElementById('chat');
const form = document.getElementById('form');
const entrada = document.getElementById('entrada');
const btn = document.getElementById('btn');

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

function agregar(clase, texto, meta) {
  const div = document.createElement('div');
  div.className = 'msg ' + clase;
  div.textContent = texto;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    div.appendChild(m);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

async function enviar(mensaje, confirmar) {
  btn.disabled = true;
  const cargando = agregar('agente', confirmar ? 'Ejecutando acción confirmada...' : 'Pensando...');
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mensaje, confirmar}),
    });
    const data = await r.json();
    cargando.remove();
    const meta = data.plan ? ('herramienta: ' + data.plan.nombre + ' · plan: ' + (data.origen_plan || '-')) : null;
    agregar('agente', data.respuesta || 'Sin respuesta.', meta);
    if (data.pendiente_confirmacion && !confirmar) {
      const div = document.createElement('div');
      div.className = 'confirmar';
      div.textContent = '⚠ Esta acción es sensible y requiere tu confirmación.';
      const si = document.createElement('button');
      si.className = 'btn-si'; si.textContent = 'Confirmar y ejecutar';
      const no = document.createElement('button');
      no.className = 'btn-no'; no.textContent = 'Cancelar';
      si.onclick = () => { div.remove(); agregar('usuario', '[Confirmado] ' + mensaje); enviar(mensaje, true); };
      no.onclick = () => { div.remove(); agregar('agente', 'Acción cancelada. No se realizaron cambios.'); };
      div.appendChild(document.createElement('br'));
      div.appendChild(si); div.appendChild(no);
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }
  } catch (e) {
    cargando.textContent = 'Error de conexión: ' + e;
  } finally {
    btn.disabled = false;
    entrada.focus();
  }
}

form.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const mensaje = entrada.value.trim();
  if (!mensaje) return;
  agregar('usuario', mensaje);
  entrada.value = '';
  enviar(mensaje, false);
});

const NOMBRES_AMIGABLES = {
  buscar_cliente: 'Buscar cliente',
  crear_ticket: 'Crear ticket',
  listar_tickets: 'Listar tickets',
  actualizar_estado_ticket: 'Cambiar estado de un ticket',
  resumir_tickets: 'Resumen general de tickets',
  notificar_cliente: 'Notificar a un cliente (simulado)',
  resumir_tickets_cliente: 'Resumen de tickets por cliente',
};

fetch('/api/info').then(r => r.json()).then(info => {
  const lista = document.getElementById('listaHerramientas');
  if (info.herramientas && info.herramientas.length) {
    lista.innerHTML = '';
    info.herramientas.forEach(h => {
      const li = document.createElement('li');
      const nombre = document.createElement('strong');
      nombre.textContent = NOMBRES_AMIGABLES[h.nombre] || h.nombre;
      li.appendChild(nombre);
      const cod = document.createElement('code');
      cod.textContent = h.nombre;
      li.appendChild(document.createTextNode(' '));
      li.appendChild(cod);
      li.appendChild(document.createTextNode(' — ' + h.descripcion));
      if (h.requiere_confirmacion) {
        const tag = document.createElement('span');
        tag.className = 'tag-conf';
        tag.textContent = 'requiere confirmación';
        li.appendChild(tag);
      }
      lista.appendChild(li);
    });
  }
  const badges = document.getElementById('badges');
  const b1 = document.createElement('span');
  b1.className = 'badge' + (info.llm ? ' on' : '');
  b1.textContent = info.llm ? ('LLM: ' + (info.modelo_activo || 'listo')) : 'LLM: no configurado (modo regex)';
  const b2 = document.createElement('span');
  b2.className = 'badge' + (info.firestore ? ' on' : '');
  b2.textContent = info.firestore ? 'Firestore: conectado' : 'Firestore: modo demo (memoria)';
  badges.appendChild(b1); badges.appendChild(b2);
});
</script>
</body>
</html>
"""
