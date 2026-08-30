"""Agente de soporte con LLM planner y herramientas controladas sobre Firestore.

Versión web de la solución del laboratorio (clase09_agentes_firebase.ipynb).
Principio central: el LLM NO modifica Firestore directamente; solo propone un
plan JSON que se valida y ejecutan herramientas controladas.

Sin credenciales de Firestore la app corre en "modo demo" (base en memoria).
Sin OPENROUTER_API_KEY el planner cae al modo determinista (regex).
"""
import json
import os
import re
import time
import uuid
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests
from pydantic import BaseModel, Field, ValidationError

# ----------------------------------------------------------------------------
# Datos y utilidades
# ----------------------------------------------------------------------------
ESTADOS_VALIDOS = {"abierto", "en_progreso", "cerrado"}
PRIORIDADES_VALIDAS = {"baja", "media", "alta", "critica"}

CLIENTES_SEMILLA = [
    {"id": "cli_001", "nombre": "Ana Torres", "email": "ana@empresa.cl", "plan": "premium", "riesgo": "medio"},
    {"id": "cli_002", "nombre": "Bruno Díaz", "email": "bruno@empresa.cl", "plan": "standard", "riesgo": "bajo"},
    {"id": "cli_003", "nombre": "Carla Soto", "email": "carla@empresa.cl", "plan": "premium", "riesgo": "alto"},
]

TICKETS_SEMILLA = [
    {"id": "tic_001", "cliente_id": "cli_001", "asunto": "No puede iniciar sesión", "prioridad": "alta", "estado": "abierto"},
    {"id": "tic_002", "cliente_id": "cli_002", "asunto": "Consulta sobre facturación", "prioridad": "media", "estado": "abierto"},
    {"id": "tic_003", "cliente_id": "cli_003", "asunto": "Error intermitente en dashboard", "prioridad": "alta", "estado": "en_progreso"},
]


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------
# Repositorio: Firestore real o memoria (modo demo)
# ----------------------------------------------------------------------------
class RepositorioFirestore:
    def __init__(self, db):
        self.db = db

    def _coleccion(self, nombre):
        return self.db.collection(nombre)

    def sembrar_si_vacio(self):
        if not self.listar_clientes():
            for cliente in CLIENTES_SEMILLA:
                self._coleccion("clientes").document(cliente["id"]).set(deepcopy(cliente))
            for ticket in TICKETS_SEMILLA:
                doc = deepcopy(ticket)
                doc.setdefault("creado_en", ahora_iso())
                doc.setdefault("actualizado_en", ahora_iso())
                self._coleccion("tickets").document(doc["id"]).set(doc)

    def listar_clientes(self):
        return [doc.to_dict() for doc in self._coleccion("clientes").stream()]

    def buscar_cliente(self, texto):
        texto = texto.lower().strip()
        return [
            c for c in self.listar_clientes()
            if texto in c.get("nombre", "").lower()
            or texto in c.get("email", "").lower()
            or texto == c.get("id", "").lower()
        ]

    def obtener_cliente(self, cliente_id):
        doc = self._coleccion("clientes").document(cliente_id).get()
        return doc.to_dict() if doc.exists else None

    def crear_ticket(self, cliente_id, asunto, prioridad):
        existentes = list(self._coleccion("tickets").stream())
        ticket_id = f"tic_{len(existentes) + 1:03d}"
        doc = {
            "id": ticket_id, "cliente_id": cliente_id, "asunto": asunto,
            "prioridad": prioridad, "estado": "abierto",
            "creado_en": ahora_iso(), "actualizado_en": ahora_iso(),
        }
        self._coleccion("tickets").document(ticket_id).set(doc)
        return doc

    def listar_tickets(self, estado=None, prioridad=None, cliente_id=None):
        docs = [doc.to_dict() for doc in self._coleccion("tickets").stream()]
        if estado:
            docs = [d for d in docs if d.get("estado") == estado]
        if prioridad:
            docs = [d for d in docs if d.get("prioridad") == prioridad]
        if cliente_id:
            docs = [d for d in docs if d.get("cliente_id") == cliente_id]
        return docs

    def actualizar_estado_ticket(self, ticket_id, estado):
        ref = self._coleccion("tickets").document(ticket_id)
        if not ref.get().exists:
            return None
        ref.update({"estado": estado, "actualizado_en": ahora_iso()})
        return ref.get().to_dict()

    def guardar_notificacion(self, notificacion):
        self._coleccion("notificaciones").document(notificacion["id"]).set(deepcopy(notificacion))

    def registrar_memoria(self, evento):
        evento_id = evento.get("id", f"mem_{uuid.uuid4().hex[:8]}")
        evento["id"] = evento_id
        evento.setdefault("creado_en", ahora_iso())
        self._coleccion("memoria_agente").document(evento_id).set(deepcopy(evento))
        return evento

    def listar_memoria(self, limite=20):
        docs = [doc.to_dict() for doc in self._coleccion("memoria_agente").stream()]
        return sorted(docs, key=lambda x: x.get("creado_en", ""), reverse=True)[:limite]


class _ColeccionMemoria:
    def __init__(self):
        self.docs: Dict[str, dict] = {}

    class _Doc:
        def __init__(self, col, doc_id):
            self.col, self.doc_id = col, doc_id

        def set(self, data):
            self.col.docs[self.doc_id] = dict(data)

        def get(self):
            col, doc_id = self.col, self.doc_id

            class Snap:
                exists = doc_id in col.docs

                @staticmethod
                def to_dict():
                    return dict(col.docs[doc_id]) if doc_id in col.docs else None
            return Snap

        def update(self, data):
            self.col.docs[self.doc_id].update(data)

    def document(self, doc_id):
        return self._Doc(self, doc_id)

    def stream(self):
        class Snap:
            def __init__(self, d):
                self._d = d

            def to_dict(self):
                return dict(self._d)
        return [Snap(d) for d in self.docs.values()]


class _BaseMemoria:
    """Base en memoria con la misma interfaz mínima que Firestore (modo demo)."""

    def __init__(self):
        self.cols: Dict[str, _ColeccionMemoria] = {}

    def collection(self, nombre):
        return self.cols.setdefault(nombre, _ColeccionMemoria())


def conectar_repositorio():
    """Intenta Firestore real (ADC en Cloud Run, o GOOGLE_APPLICATION_CREDENTIALS).

    Si falla, devuelve (repo_en_memoria, False) para que la app siga corriendo.
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if firebase_admin._apps:
            app = firebase_admin.get_app()
        else:
            ruta = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if ruta and os.path.exists(ruta):
                app = firebase_admin.initialize_app(credentials.Certificate(ruta))
            else:
                app = firebase_admin.initialize_app()  # ADC: en Cloud Run usa la SA del servicio
        db = firestore.client(app=app)
        repo = RepositorioFirestore(db)
        repo.listar_clientes()  # prueba de acceso real
        repo.sembrar_si_vacio()
        return repo, True
    except Exception as error:
        print(f"[agente] Firestore no disponible ({error!r}); usando base en memoria (modo demo).")
        repo = RepositorioFirestore(_BaseMemoria())
        repo.sembrar_si_vacio()
        return repo, False


# ----------------------------------------------------------------------------
# Esquemas y herramientas
# ----------------------------------------------------------------------------
class ToolResult(BaseModel):
    ok: bool
    mensaje: str
    datos: Any = None


class BuscarClienteInput(BaseModel):
    texto: str


class CrearTicketInput(BaseModel):
    cliente_id: str
    asunto: str
    prioridad: str


class ListarTicketsInput(BaseModel):
    estado: Optional[str] = None
    prioridad: Optional[str] = None
    cliente_id: Optional[str] = None


class ActualizarEstadoTicketInput(BaseModel):
    ticket_id: str
    estado: str
    confirmado: bool = False


class NotificarClienteInput(BaseModel):
    cliente_id: str
    mensaje: str
    confirmado: bool = False


class ResumirTicketsClienteInput(BaseModel):
    cliente_id: str


@dataclass
class Accion:
    nombre: str
    argumentos: Dict[str, Any] = field(default_factory=dict)
    requiere_confirmacion: bool = False


class Herramientas:
    """Actuadores del agente. Validan entradas y devuelven observaciones."""

    def __init__(self, repo: RepositorioFirestore):
        self.repo = repo

    def buscar_cliente(self, texto: str) -> ToolResult:
        try:
            args = BuscarClienteInput(texto=texto)
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        resultados = self.repo.buscar_cliente(args.texto)
        if not resultados:
            return ToolResult(ok=False, mensaje="No se encontraron clientes.", datos=[])
        return ToolResult(ok=True, mensaje=f"Se encontraron {len(resultados)} cliente(s).", datos=resultados)

    def crear_ticket(self, cliente_id: str, asunto: str, prioridad: str) -> ToolResult:
        try:
            args = CrearTicketInput(cliente_id=cliente_id, asunto=asunto, prioridad=str(prioridad).lower())
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        if args.prioridad not in PRIORIDADES_VALIDAS:
            return ToolResult(ok=False, mensaje=f"Prioridad inválida: {args.prioridad}.", datos={"validas": sorted(PRIORIDADES_VALIDAS)})
        if not self.repo.obtener_cliente(args.cliente_id):
            return ToolResult(ok=False, mensaje="Cliente no existe.", datos={"cliente_id": args.cliente_id})
        ticket = self.repo.crear_ticket(args.cliente_id, args.asunto, args.prioridad)
        return ToolResult(ok=True, mensaje="Ticket creado correctamente.", datos=ticket)

    def listar_tickets(self, estado=None, prioridad=None, cliente_id=None) -> ToolResult:
        try:
            args = ListarTicketsInput(estado=estado, prioridad=prioridad, cliente_id=cliente_id)
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        if args.estado and args.estado not in ESTADOS_VALIDOS:
            return ToolResult(ok=False, mensaje=f"Estado inválido: {args.estado}.", datos={"validos": sorted(ESTADOS_VALIDOS)})
        if args.prioridad and args.prioridad not in PRIORIDADES_VALIDAS:
            return ToolResult(ok=False, mensaje=f"Prioridad inválida: {args.prioridad}.", datos={"validas": sorted(PRIORIDADES_VALIDAS)})
        tickets = self.repo.listar_tickets(args.estado, args.prioridad, args.cliente_id)
        return ToolResult(ok=True, mensaje=f"Se encontraron {len(tickets)} ticket(s).", datos=tickets)

    def actualizar_estado_ticket(self, ticket_id: str, estado: str, confirmado: bool = False) -> ToolResult:
        try:
            args = ActualizarEstadoTicketInput(ticket_id=ticket_id, estado=str(estado).lower(), confirmado=confirmado)
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        if args.estado not in ESTADOS_VALIDOS:
            return ToolResult(ok=False, mensaje=f"Estado inválido: {args.estado}.", datos={"validos": sorted(ESTADOS_VALIDOS)})
        if not args.confirmado:
            return ToolResult(ok=False, mensaje="Se requiere confirmación humana para cambiar estado.", datos={"requiere_confirmacion": True, "ticket_id": args.ticket_id, "estado": args.estado})
        ticket = self.repo.actualizar_estado_ticket(args.ticket_id, args.estado)
        if not ticket:
            return ToolResult(ok=False, mensaje="Ticket no encontrado.", datos={"ticket_id": args.ticket_id})
        return ToolResult(ok=True, mensaje="Estado actualizado correctamente.", datos=ticket)

    def resumir_tickets(self) -> ToolResult:
        tickets = self.repo.listar_tickets()
        resumen = Counter((t.get("estado"), t.get("prioridad")) for t in tickets)
        filas = [{"estado": e, "prioridad": p, "cantidad": c} for (e, p), c in resumen.items()]
        return ToolResult(ok=True, mensaje="Resumen generado.", datos=filas)

    def notificar_cliente(self, cliente_id: str, mensaje: str, confirmado: bool = False) -> ToolResult:
        try:
            args = NotificarClienteInput(cliente_id=cliente_id, mensaje=mensaje, confirmado=confirmado)
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        cliente = self.repo.obtener_cliente(args.cliente_id)
        if not cliente:
            return ToolResult(ok=False, mensaje="Cliente no existe.", datos={"cliente_id": args.cliente_id})
        if not args.confirmado:
            return ToolResult(ok=False, mensaje="Se requiere confirmación humana para enviar notificaciones.",
                              datos={"requiere_confirmacion": True, "destinatario": cliente["email"], "mensaje": args.mensaje})
        notificacion = {
            "id": f"not_{uuid.uuid4().hex[:8]}", "cliente_id": args.cliente_id,
            "destinatario": cliente["email"], "mensaje": args.mensaje,
            "estado": "simulado", "creado_en": ahora_iso(),
        }
        self.repo.guardar_notificacion(notificacion)
        return ToolResult(ok=True, mensaje=f"Notificación simulada enviada a {cliente['email']}.", datos=notificacion)

    def resumir_tickets_cliente(self, cliente_id: str) -> ToolResult:
        try:
            args = ResumirTicketsClienteInput(cliente_id=cliente_id)
        except ValidationError as e:
            return ToolResult(ok=False, mensaje="Entrada inválida.", datos=str(e))
        cliente = self.repo.obtener_cliente(args.cliente_id)
        if not cliente:
            return ToolResult(ok=False, mensaje="Cliente no existe.", datos={"cliente_id": args.cliente_id})
        tickets = self.repo.listar_tickets(cliente_id=args.cliente_id)
        resumen = {
            "cliente": {"id": cliente["id"], "nombre": cliente["nombre"], "plan": cliente.get("plan")},
            "total_tickets": len(tickets),
            "por_estado": dict(Counter(t.get("estado") for t in tickets)),
            "por_prioridad": dict(Counter(t.get("prioridad") for t in tickets)),
            "asuntos_abiertos": [t["asunto"] for t in tickets if t.get("estado") == "abierto"],
        }
        return ToolResult(ok=True, mensaje=f"Resumen de {len(tickets)} ticket(s) de {cliente['nombre']}.", datos=resumen)


HERRAMIENTAS_SENSIBLES = {"actualizar_estado_ticket", "notificar_cliente"}

ESQUEMAS_ARGUMENTOS: Dict[str, Any] = {
    "buscar_cliente": BuscarClienteInput,
    "crear_ticket": CrearTicketInput,
    "listar_tickets": ListarTicketsInput,
    "actualizar_estado_ticket": ActualizarEstadoTicketInput,
    "resumir_tickets": None,
    "notificar_cliente": NotificarClienteInput,
    "resumir_tickets_cliente": ResumirTicketsClienteInput,
}

CATALOGO_HERRAMIENTAS = [
    {"nombre": "buscar_cliente", "argumentos": {"texto": "nombre, email o id"}, "descripcion": "Busca clientes por nombre, email o identificador.", "requiere_confirmacion": False},
    {"nombre": "crear_ticket", "argumentos": {"cliente_id": "cli_001", "asunto": "texto", "prioridad": "baja|media|alta|critica"}, "descripcion": "Crea un ticket para un cliente existente.", "requiere_confirmacion": False},
    {"nombre": "listar_tickets", "argumentos": {"estado": "abierto|en_progreso|cerrado|null", "prioridad": "baja|media|alta|critica|null", "cliente_id": "cli_001|null"}, "descripcion": "Lista tickets filtrados.", "requiere_confirmacion": False},
    {"nombre": "actualizar_estado_ticket", "argumentos": {"ticket_id": "tic_001", "estado": "abierto|en_progreso|cerrado"}, "descripcion": "Cambia el estado de un ticket. Sensible: requiere confirmación humana.", "requiere_confirmacion": True},
    {"nombre": "resumir_tickets", "argumentos": {}, "descripcion": "Resumen global por estado y prioridad.", "requiere_confirmacion": False},
    {"nombre": "notificar_cliente", "argumentos": {"cliente_id": "cli_001", "mensaje": "texto"}, "descripcion": "Notificación simulada al cliente. Sensible: requiere confirmación humana.", "requiere_confirmacion": True},
    {"nombre": "resumir_tickets_cliente", "argumentos": {"cliente_id": "cli_001"}, "descripcion": "Resumen de tickets de un cliente.", "requiere_confirmacion": False},
]


# ----------------------------------------------------------------------------
# Conexión LLM (OpenRouter) con lista de modelos y diagnóstico de errores
# ----------------------------------------------------------------------------
LLM_MODELOS_CANDIDATOS = [
    m.strip() for m in os.environ.get(
        "LLM_MODELOS",
        "nvidia/nemotron-3.5-lightning:free,thinkingmachines/inkling:free,inclusionai/ling-3.0-flash-fin:free",
    ).split(",") if m.strip()
]
LLM_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODELO_ACTIVO: Optional[str] = None
LLM_FALLOS_SEGUIDOS = 0        # llamadas completas fallidas de forma consecutiva
LLM_CIRCUITO_ABIERTO = False   # tras 2 fallos totales, se desactiva el LLM temporalmente
LLM_REINTENTO_DESDE = 0.0      # cuándo volver a intentar (epoch)


def llm_disponible() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def chat_llm(messages: List[Dict[str, str]], temperatura: float = 0.0, max_tokens: int = 600) -> str:
    global LLM_MODELO_ACTIVO, LLM_FALLOS_SEGUIDOS, LLM_CIRCUITO_ABIERTO, LLM_REINTENTO_DESDE
    if LLM_CIRCUITO_ABIERTO:
        if time.time() < LLM_REINTENTO_DESDE:
            raise RuntimeError("LLM en pausa tras fallos consecutivos (límite de peticiones probable).")
        LLM_CIRCUITO_ABIERTO = False  # reintentar pasado el periodo de espera
        LLM_FALLOS_SEGUIDOS = 0
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY no configurada.")
    candidatos = [LLM_MODELO_ACTIVO] if LLM_MODELO_ACTIVO else list(LLM_MODELOS_CANDIDATOS)
    errores = []
    for modelo in candidatos:
        for intento in range(2):
            r = requests.post(
                LLM_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": modelo, "messages": messages,
                    "temperature": temperatura, "max_tokens": max_tokens,
                    # Excluye la cadena de pensamiento de modelos con razonamiento.
                    "reasoning": {"exclude": True},
                },
                timeout=120,
            )
            if r.status_code == 200:
                LLM_MODELO_ACTIVO = modelo
                LLM_FALLOS_SEGUIDOS = 0
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                # Límite de peticiones del plan gratuito: esperar y reintentar.
                time.sleep(12 * (intento + 1))
                continue
            break  # otro error: probar el siguiente modelo
        errores.append(f"{modelo}: HTTP {r.status_code} -> {r.text[:200]}")
    LLM_MODELO_ACTIVO = None
    LLM_FALLOS_SEGUIDOS += 1
    if LLM_FALLOS_SEGUIDOS >= 2:
        # Pausa de 10 minutos antes de volver a intentar (evita colgar cada request).
        LLM_CIRCUITO_ABIERTO = True
        LLM_REINTENTO_DESDE = time.time() + 600
        print("[chat_llm] LLM en pausa 10 min tras fallos consecutivos; se usa el planner determinista.")
    raise RuntimeError("Ningún modelo LLM respondió. " + " | ".join(errores))


# ----------------------------------------------------------------------------
# Planificación, validación y agente
# ----------------------------------------------------------------------------
class PlanAccion(BaseModel):
    accion: str
    argumentos: Dict[str, Any] = Field(default_factory=dict)
    requiere_confirmacion: bool = False


def extraer_json(texto: str, clave: str = "accion") -> Dict[str, Any]:
    """Extrae el JSON final tolerando texto extra y modelos con razonamiento:
    se queda con el último objeto que contenga la clave pedida."""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", texto).strip()
    try:
        obj = json.loads(texto)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidatos = []
    for m in re.finditer(r"\{", texto):
        try:
            obj, _ = decoder.raw_decode(texto, m.start())
            if isinstance(obj, dict):
                candidatos.append(obj)
        except json.JSONDecodeError:
            continue
    con_clave = [c for c in candidatos if clave in c]
    if con_clave:
        return con_clave[-1]
    if candidatos:
        return candidatos[-1]
    raise json.JSONDecodeError("Sin objeto JSON en la respuesta del modelo.", texto, 0)


class AgenteSoporte:
    def __init__(self):
        self.repo, self.firestore_activo = conectar_repositorio()
        self.tools = Herramientas(self.repo)
        self.registro: Dict[str, Callable[..., ToolResult]] = {
            "buscar_cliente": self.tools.buscar_cliente,
            "crear_ticket": self.tools.crear_ticket,
            "listar_tickets": self.tools.listar_tickets,
            "actualizar_estado_ticket": self.tools.actualizar_estado_ticket,
            "resumir_tickets": self.tools.resumir_tickets,
            "notificar_cliente": self.tools.notificar_cliente,
            "resumir_tickets_cliente": self.tools.resumir_tickets_cliente,
        }

    # ---------------- validación ----------------
    def validar_plan(self, plan_crudo: Dict[str, Any]):
        errores: List[str] = []
        try:
            plan = PlanAccion(**plan_crudo)
        except ValidationError as e:
            return None, [f"Estructura de plan inválida: {e}"]
        if plan.accion not in self.registro:
            return None, [f"Acción no permitida: {plan.accion}"]
        argumentos = dict(plan.argumentos or {})
        argumentos.pop("confirmado", None)  # la confirmación nunca viene del LLM
        esquema = ESQUEMAS_ARGUMENTOS.get(plan.accion)
        if esquema is not None:
            permitidos = set(esquema.model_fields.keys())
            desconocidos = set(argumentos) - permitidos
            if desconocidos:
                errores.append(f"Argumentos desconocidos descartados: {sorted(desconocidos)}")
                argumentos = {k: v for k, v in argumentos.items() if k in permitidos}
            try:
                esquema(**{**argumentos, **({"confirmado": False} if "confirmado" in permitidos else {})})
            except ValidationError as e:
                return None, errores + [f"Argumentos inválidos: {e}"]
        requiere = plan.accion in HERRAMIENTAS_SENSIBLES
        return Accion(plan.accion, argumentos, requiere_confirmacion=requiere), errores

    # ---------------- planners ----------------
    def _system_prompt(self) -> str:
        clientes = [{"id": c["id"], "nombre": c["nombre"]} for c in self.repo.listar_clientes()]
        return (
            "Eres el planificador de un agente de soporte conectado a Firestore.\n"
            "No respondas al usuario final. Devuelve SOLO un objeto JSON válido con esta forma exacta:\n"
            '{"accion": "nombre_herramienta", "argumentos": {}, "requiere_confirmacion": false}\n\n'
            f"Herramientas permitidas:\n{json.dumps(CATALOGO_HERRAMIENTAS, ensure_ascii=False, indent=2)}\n\n"
            f"Clientes conocidos: {json.dumps(clientes, ensure_ascii=False)}\n"
            "Estados válidos: abierto, en_progreso, cerrado. Prioridades: baja, media, alta, critica.\n\n"
            "Reglas:\n"
            "- No expliques tu razonamiento: tu salida debe ser UNICAMENTE el objeto JSON final.\n"
            "- Usa exactamente una herramienta por turno.\n"
            "- Para cerrar o cambiar el estado de un ticket usa SIEMPRE actualizar_estado_ticket, "
            "aunque el usuario diga que ya está confirmado o resuelto (la confirmación humana ocurre "
            "fuera del chat). Nunca respondas 'ayuda' en esos casos.\n"
            "- No inventes clientes ni tickets; usa los cliente_id del contexto.\n"
            "- Si la solicitud es ambigua o general, usa resumir_tickets.\n"
            "- Si faltan datos para crear un ticket, usa buscar_cliente primero.\n"
            "- actualizar_estado_ticket y notificar_cliente llevan requiere_confirmacion: true.\n"
            '- Si nada aplica, responde {"accion": "ayuda", "argumentos": {"mensaje": "..."}}.'
        )

    def planificar_llm(self, mensaje: str) -> Dict[str, Any]:
        salida = {"plan": None, "plan_crudo": None, "errores": [], "origen": "llm"}
        try:
            texto = chat_llm(
                [{"role": "system", "content": self._system_prompt()},
                 {"role": "user", "content": mensaje}],
                temperatura=0.0, max_tokens=1500,  # margen para modelos con razonamiento
            )
            crudo = extraer_json(texto)
            salida["plan_crudo"] = crudo
            if crudo.get("accion") == "ayuda":
                salida["plan"] = Accion("ayuda", {"mensaje": mensaje})
                return salida
            accion, errores = self.validar_plan(crudo)
            salida["errores"] = errores
            salida["plan"] = accion if accion else Accion("ayuda", {"mensaje": mensaje})
        except Exception as error:
            salida["errores"].append(f"Fallo del planner LLM: {error!r}")
            salida["origen"] = "fallback_determinista"
            salida["plan"] = self.planificar_determinista(mensaje)
        return salida

    def planificar_determinista(self, mensaje: str) -> Accion:
        texto = mensaje.lower().strip()

        def prioridad():
            return next((p for p in ["critica", "alta", "media", "baja"] if p in texto), None)

        def estado():
            for k, v in [("abiertos", "abierto"), ("abierto", "abierto"), ("en progreso", "en_progreso"),
                         ("cerrados", "cerrado"), ("cerrado", "cerrado"), ("cerrar", "cerrado"), ("cierra", "cerrado")]:
                if k in texto:
                    return v
            return None

        def cliente_id():
            for c in self.repo.listar_clientes():
                if c["id"].lower() in texto or c["nombre"].lower() in texto:
                    return c["id"]
            return None

        m = re.search(r"tic_\d{3}", texto)
        if any(p in texto for p in ["resumen", "resume", "estado general"]):
            cid = cliente_id()
            return Accion("resumir_tickets_cliente", {"cliente_id": cid}) if cid else Accion("resumir_tickets", {})
        if "buscar" in texto and "cliente" in texto:
            consulta = mensaje.split("cliente", 1)[-1].strip(" :.-") or mensaje
            return Accion("buscar_cliente", {"texto": consulta})
        if "crear" in texto and "ticket" in texto:
            cid = cliente_id()
            if not cid:
                return Accion("buscar_cliente", {"texto": mensaje})
            return Accion("crear_ticket", {"cliente_id": cid, "asunto": mensaje.strip(), "prioridad": prioridad() or "media"})
        if any(p in texto for p in ["listar", "lista", "muestra", "mostrar", "ver"]) and "ticket" in texto:
            return Accion("listar_tickets", {"estado": estado(), "prioridad": prioridad(), "cliente_id": cliente_id()})
        if any(p in texto for p in ["cerrar", "cierra", "actualiza", "cambiar estado"]) and m:
            return Accion("actualizar_estado_ticket", {"ticket_id": m.group(0), "estado": estado() or "cerrado"}, requiere_confirmacion=True)
        if any(p in texto for p in ["notifica", "notificar", "avisa", "avísale", "avisale"]):
            cid = cliente_id()
            if cid:
                return Accion("notificar_cliente", {"cliente_id": cid, "mensaje": mensaje.strip()}, requiere_confirmacion=True)
        return Accion("ayuda", {"mensaje": mensaje})

    # ---------------- ejecución y respuesta ----------------
    def ejecutar(self, accion: Accion, confirmar: bool) -> ToolResult:
        if accion.nombre == "ayuda":
            return ToolResult(ok=False,
                              mensaje="Puedo buscar clientes, crear/listar/cerrar tickets, resumir (global o por cliente) y notificar clientes.",
                              datos={"solicitud": accion.argumentos.get("mensaje")})
        herramienta = self.registro.get(accion.nombre)
        if not herramienta:
            return ToolResult(ok=False, mensaje=f"Herramienta no permitida: {accion.nombre}", datos=None)
        argumentos = dict(accion.argumentos)
        if accion.nombre in HERRAMIENTAS_SENSIBLES:
            argumentos["confirmado"] = confirmar
        return herramienta(**argumentos)

    def formatear(self, accion: Accion, r: ToolResult) -> str:
        if not r.ok:
            return f"No pude completar `{accion.nombre}`: {r.mensaje}"
        d = r.datos
        if accion.nombre == "buscar_cliente":
            return "Clientes encontrados:\n" + "\n".join(f"- {c['id']}: {c['nombre']} ({c['email']}), plan {c['plan']}" for c in d)
        if accion.nombre == "crear_ticket":
            return f"Ticket creado: {d['id']} para {d['cliente_id']} | prioridad {d['prioridad']} | asunto: {d['asunto']}"
        if accion.nombre == "listar_tickets":
            if not d:
                return "No hay tickets con esos filtros."
            return "Tickets:\n" + "\n".join(f"- {t['id']} | {t['cliente_id']} | {t['estado']} | {t['prioridad']} | {t['asunto']}" for t in d)
        if accion.nombre == "actualizar_estado_ticket":
            return f"Ticket {d['id']} actualizado a `{d['estado']}`."
        if accion.nombre == "resumir_tickets":
            return "Resumen de tickets:\n" + "\n".join(f"- {x['estado']} / {x['prioridad']}: {x['cantidad']}" for x in d)
        if accion.nombre == "notificar_cliente":
            return f"Notificación (simulada) enviada a {d['destinatario']}: \"{d['mensaje']}\""
        if accion.nombre == "resumir_tickets_cliente":
            lineas = [f"{d['cliente']['nombre']} ({d['cliente']['id']}): {d['total_tickets']} ticket(s).",
                      f"Por estado: {d['por_estado']} | Por prioridad: {d['por_prioridad']}"]
            if d["asuntos_abiertos"]:
                lineas.append("Abiertos: " + "; ".join(d["asuntos_abiertos"]))
            return "\n".join(lineas)
        return r.mensaje

    def redactar_llm(self, mensaje: str, accion: Accion, r: ToolResult) -> str:
        system = ("Eres un agente de soporte. Redacta una respuesta breve y clara en español "
                  "usando EXCLUSIVAMENTE los datos de la observación. No inventes datos. "
                  "Si la observación pide confirmación humana, explica qué acción quedó pendiente. "
                  "Máximo 4 líneas. Devuelve SOLO un objeto JSON "
                  'con la forma {"respuesta": "texto para el usuario"}, sin nada más.')
        contexto = json.dumps({"solicitud_usuario": mensaje, "herramienta": accion.nombre,
                               "argumentos": accion.argumentos, "observacion": r.model_dump()},
                              ensure_ascii=False, default=str)
        texto = chat_llm([{"role": "system", "content": system}, {"role": "user", "content": contexto}],
                         temperatura=0.2, max_tokens=800)
        # Igual que en el planner: se extrae el JSON final aunque el modelo
        # anteponga su razonamiento como texto.
        respuesta = str(extraer_json(texto, clave="respuesta").get("respuesta", "")).strip()
        if not respuesta:
            raise ValueError("El modelo no entregó el campo 'respuesta'.")
        return respuesta

    def responder(self, mensaje: str, confirmar: bool = False) -> Dict[str, Any]:
        inicio = time.time()
        usar_llm = llm_disponible()
        if usar_llm:
            plan_info = self.planificar_llm(mensaje)
        else:
            plan_info = {"plan": self.planificar_determinista(mensaje), "plan_crudo": None,
                         "errores": [], "origen": "determinista"}
        accion = plan_info["plan"]
        resultado = self.ejecutar(accion, confirmar)

        respuesta = None
        if usar_llm and plan_info["origen"] == "llm":
            try:
                respuesta = self.redactar_llm(mensaje, accion, resultado)
            except Exception as error:
                plan_info["errores"].append(f"Fallo al redactar con LLM: {error!r}")
        if not respuesta:
            respuesta = self.formatear(accion, resultado)

        pendiente_confirmacion = bool(
            isinstance(resultado.datos, dict) and resultado.datos.get("requiere_confirmacion") is True
        )
        evento = self.repo.registrar_memoria({
            "tipo": "interaccion_agente_llm",
            "contenido": {
                "mensaje_usuario": mensaje,
                "origen_plan": plan_info["origen"],
                "plan_crudo_llm": plan_info["plan_crudo"],
                "plan_validado": accion.__dict__,
                "errores_validacion": plan_info["errores"],
                "resultado": resultado.model_dump(),
                "respuesta": respuesta,
                "confirmado": confirmar,
                "segundos": round(time.time() - inicio, 3),
            },
        })
        return {
            "respuesta": respuesta,
            "plan": accion.__dict__,
            "origen_plan": plan_info["origen"],
            "errores_validacion": plan_info["errores"],
            "resultado_ok": resultado.ok,
            "pendiente_confirmacion": pendiente_confirmacion,
            "memoria_id": evento["id"],
            "modelo": LLM_MODELO_ACTIVO,
        }
