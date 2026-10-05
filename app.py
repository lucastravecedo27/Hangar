"""Hangar — control de flota, mantenimiento y operación de drones y avionetas agrícolas (Flask + PostgreSQL).

Arranque en servidor: gunicorn -w 3 -b 0.0.0.0:8000 app:app   (ver Dockerfile / docker-compose)
Arranque local:       HANGAR_ENTORNO=desarrollo python app.py
La configuración sale de variables de entorno (core/config.py, archivo .env).
"""
import hmac
import logging
import secrets
from datetime import date, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (Flask, abort, g, jsonify, redirect, request, render_template, send_file,
                   send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from core import alertas as core_alertas
from core import bodega as core_bodega
from core import config
from core import conexion as core_conexion
from core import correo as core_correo
from core import db as core_db
from core import flota as core_flota
from core import excel as core_excel
from core import modelos as core_modelos
from core import ordenes as core_ordenes
from core import proyeccion as core_proyeccion

RAIZ = Path(__file__).resolve().parent
NOMBRE_APP = "Hangar"
LEMA_APP = "Control de flota aérea agrícola"


def _clave_secreta():
    """SECRET_KEY del entorno; si no hay, una generada una vez y guardada en datos/secret.key."""
    if config.SECRET_KEY:
        return config.SECRET_KEY
    ruta = RAIZ / "datos" / "secret.key"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        ruta.write_text(secrets.token_hex(32))
        try:
            ruta.chmod(0o600)
        except OSError:
            pass
    return ruta.read_text().strip()


app = Flask(__name__, static_folder=None, template_folder=str(RAIZ / "templates"))
# En el escritorio las plantillas se releen si cambian: una actualización se ve sin reiniciar.
app.config["TEMPLATES_AUTO_RELOAD"] = config.ES_ESCRITORIO
app.config.update(
    SECRET_KEY=_clave_secreta(),
    SESSION_COOKIE_NAME="hangar_sesion",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.COOKIE_SEGURA,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=config.HORAS_SESION),
    MAX_CONTENT_LENGTH=config.MAX_SUBIDA_MB * 1024 * 1024,
    JSON_SORT_KEYS=False,
    # En desarrollo las plantillas se releen al cambiar (en producción se cachean).
    TEMPLATES_AUTO_RELOAD=config.ENTORNO == "desarrollo",
)
# Detrás de Caddy/Nginx: la app ve la IP y el esquema (https) reales del cliente.
if config.PROXIES_DELANTE:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=config.PROXIES_DELANTE, x_proto=config.PROXIES_DELANTE,
                            x_host=config.PROXIES_DELANTE)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def get_con():
    """Conexión de la petición, fijada a la empresa de la sesión. Sin sesión no hay empresa y las
    tablas de datos se ven vacías (PostgreSQL filtra por Row-Level Security)."""
    if "con" not in g:
        g.con = core_db.conectar(session.get("empresa_id"))
    return g.con


def _es_admin():
    return session.get("rol") in ("admin", core_db.ROL_SUPERADMIN)


def _ve_costos():
    return session.get("rol") in core_db.ROLES_COSTOS


def _es_superadmin():
    return session.get("rol") == core_db.ROL_SUPERADMIN


@app.teardown_appcontext
def cerrar_con(exc=None):
    con = g.pop("con", None)
    if con is not None:
        con.close()


@app.context_processor
def inyectar_globales():
    # La marca se inyecta siempre (la usa también la pantalla de acceso); el resumen de alertas
    # requiere sesión porque consulta la base de datos.
    base = {"nombre_app": NOMBRE_APP, "lema_app": LEMA_APP, "csrf_token": _csrf_token(),
            "tema": session.get("tema") or "sistema"}
    if not session.get("usuario"):
        return base
    base.update({
        "usuario_actual": session.get("usuario"),
        "rol_actual": session.get("rol", "admin"),
        "es_admin": _es_admin(),
        "ve_costos": _ve_costos(),
        "es_superadmin": _es_superadmin(),
        "empresa_actual": session.get("empresa_nombre"),
        "alertas_resumen": core_alertas.resumen_alertas(get_con()),
        "avisos_txt": core_alertas.texto_avisos(core_alertas.config_avisos(get_con())),
        "ordenes_resumen": _resumen_ordenes(get_con()),
    })
    return base


def _resumen_ordenes(con):
    """Contadores para las insignias de la barra lateral (órdenes aún abiertas)."""
    ot = con.execute("SELECT COUNT(*) n FROM ordenes_trabajo WHERE estado NOT IN ('completada','cancelada')").fetchone()["n"]
    os_ = con.execute("SELECT COUNT(*) n FROM ordenes_servicio WHERE estado NOT IN ('finalizada','cancelada')").fetchone()["n"]
    return {"ot": ot, "os": os_}


@app.route("/favicon.ico")
@app.route("/favicon.svg")
def favicon():
    return send_from_directory(RAIZ / "static_shell", "favicon.svg", mimetype="image/svg+xml")


@app.route("/static_shell/<path:archivo>")
def static_shell(archivo):
    # Los estáticos cambian poco; en producción los sirve el proxy con caché larga y aquí se
    # deja una caché corta por si se llega directo al servidor de la app.
    return send_from_directory(RAIZ / "static_shell", archivo,
                               max_age=0 if config.ENTORNO == "desarrollo" or config.ES_ESCRITORIO else 3600)


def login_requerido(vista):
    @wraps(vista)
    def envoltorio(*a, **kw):
        if not session.get("usuario"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "sesión requerida"}), 401
            return redirect(url_for("login"))
        # El superadministrador trabaja en su panel; sólo ve la operación de una empresa si
        # decide «entrar» a ella. Sin empresa elegida, cualquier pantalla operativa lo lleva al panel.
        if (not session.get("empresa_id") and session.get("rol") == core_db.ROL_SUPERADMIN
                and not request.path.startswith(("/api/empresas", "/api/admin/", "/api/cuenta/", "/api/log-js"))):
            if request.path.startswith("/api/"):
                return jsonify({"error": "elige una empresa desde el panel de administración"}), 409
            return redirect(url_for("admin_panel"))
        return vista(*a, **kw)
    return envoltorio


def admin_requerido(vista):
    @wraps(vista)
    @login_requerido
    def envoltorio(*a, **kw):
        if not _es_admin():
            if request.path.startswith("/api/"):
                return jsonify({"error": "sólo el administrador puede hacer esto"}), 403
            abort(403)
        return vista(*a, **kw)
    return envoltorio


def superadmin_requerido(vista):
    @wraps(vista)
    @login_requerido
    def envoltorio(*a, **kw):
        if not _es_superadmin():
            return jsonify({"error": "sólo el superadministrador gestiona las empresas"}), 403
        return vista(*a, **kw)
    return envoltorio


# ---------- Seguridad: CSRF, permisos por rol, cabeceras ----------

def _csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _origen_valido():
    """El Origin/Referer (si el navegador lo manda) debe ser el propio sitio."""
    for cab in ("Origin", "Referer"):
        v = request.headers.get(cab)
        if v:
            return urlsplit(v).netloc == request.host
    return True


# Qué puede hacer cada rol además de LEER (GET). El admin puede todo. Cada entrada es
# (método o "*", prefijo de ruta). Lo que no esté aquí queda prohibido para ese rol.
_PERMISOS_TECNICO = [
    ("*", "/api/equipos"), ("*", "/api/componentes"), ("*", "/api/mantenimientos"),
    ("*", "/api/ot"), ("*", "/api/registros"), ("*", "/api/diagramas"),
    ("*", "/api/personal"), ("*", "/api/operaciones"), ("POST", "/api/os/"),
    ("POST", "/api/log-js"), ("*", "/api/cuenta/"),
    # Flota mixta
    ("*", "/api/piezas-serie"), ("*", "/api/baterias"), ("*", "/api/checklists"),
    ("POST", "/api/archivos"), ("*", "/api/documentos"),
    # Registrar que una directiva «no aplica» o dejar nota; «cumplida» exige certificador
    # (se valida dentro de la ruta).
    ("POST", "/api/directivas/"),
    ("POST", "/api/combustible"), ("PUT", "/api/combustible/equipo/"),
    # Bodega: entradas, salidas y traslados (el tipo se valida en la ruta), repuestos de las OT
    # y productos aplicados en las operaciones.
    ("POST", "/api/bodega/movimientos"), ("*", "/api/bodega/ot-lineas"), ("POST", "/api/bodega/aplicaciones"),
    ("POST", "/api/bodega/envases"), ("PUT", "/api/bodega/envases"),
    # Incidentes: reportarlos y firmar su inspección (en un avión sólo el certificador; se valida en la ruta).
    ("POST", "/api/incidentes"),
    # Criterio de rechazo de piezas on-condition (sólo certificador; se valida en la ruta).
    ("PUT", "/api/criterios-rechazo"),
]
PERMISOS = {
    "tecnico": _PERMISOS_TECNICO,
    # Mecánico certificador: todo lo del técnico, más directivas y la firma de la liberación
    # (cierre de OT de avión y cumplimiento de directivas, validados en sus rutas).
    "certificador": _PERMISOS_TECNICO + [("*", "/api/directivas")],
    # Gerencia / finanzas: ve todo, incluida la rentabilidad, y no cambia la operación.
    "gerencia": [("POST", "/api/log-js"), ("*", "/api/cuenta/")],
    "piloto": [
        ("*", "/api/operaciones"), ("POST", "/api/os/"), ("*", "/api/registros"),
        ("POST", "/api/log-js"), ("*", "/api/cuenta/"),
        ("POST", "/api/checklists"), ("POST", "/api/archivos"),
        ("POST", "/api/combustible"),
        # Bodega: salidas y consumos de insumos en la operación (no entradas ni ajustes).
        ("POST", "/api/bodega/movimientos"), ("POST", "/api/bodega/aplicaciones"),
        # Triple lavado y devolución de envases vacíos.
        ("POST", "/api/bodega/envases"), ("PUT", "/api/bodega/envases"),
        # Reportar un golpe, caída o aterrizaje duro (la inspección no la firma el piloto).
        ("POST", "/api/incidentes"),
    ],
}
# Lo que sólo hace el administrador aunque el prefijo esté permitido arriba.
SOLO_ADMIN = [("DELETE", "/api/equipos"), ("DELETE", "/api/operaciones"), ("DELETE", "/api/ot"),
              ("DELETE", "/api/personal"), ("*", "/api/usuarios"), ("*", "/api/correo"),
              ("PUT", "/api/diagramas"), ("DELETE", "/api/diagramas"), ("*", "/api/empresas"),
              ("PUT", "/api/avisos-config"),
              # Flota mixta: catálogo, modelos, tarifas, costos y auditoría son del administrador.
              ("POST", "/api/modelos-activo"), ("PUT", "/api/modelos-activo"),
              ("DELETE", "/api/modelos-activo"), ("POST", "/api/catalogo"), ("PUT", "/api/catalogo"),
              ("DELETE", "/api/catalogo"), ("*", "/api/tarifas"), ("PUT", "/api/costos"),
              ("*", "/api/auditoria"), ("*", "/api/rentabilidad"), ("DELETE", "/api/documentos"),
              ("DELETE", "/api/directivas"), ("DELETE", "/api/piezas-serie"),
              # Combustible: borrar movimientos y crear o cambiar depósitos es del administrador.
              ("DELETE", "/api/combustible"), ("POST", "/api/combustible/depositos"),
              ("PUT", "/api/combustible/depositos"),
              # Bodega: artículos, ubicaciones y tanques los crea y cambia el administrador; borrar
              # movimientos o productos aplicados también (el ajuste y la baja se validan en la ruta).
              ("POST", "/api/bodega/items"), ("PUT", "/api/bodega/items"), ("DELETE", "/api/bodega/items"),
              ("POST", "/api/bodega/ubicaciones"), ("PUT", "/api/bodega/ubicaciones"),
              ("DELETE", "/api/bodega/ubicaciones"), ("POST", "/api/bodega/tanques"),
              ("PUT", "/api/bodega/tanques"), ("DELETE", "/api/bodega/tanques"),
              ("DELETE", "/api/bodega/movimientos"), ("DELETE", "/api/bodega/aplicaciones")]


def _permitido(rol, metodo, ruta):
    if rol in ("admin", core_db.ROL_SUPERADMIN):
        return True
    for m, prefijo in SOLO_ADMIN:
        if ruta.startswith(prefijo) and m in ("*", metodo):
            return False
    if metodo in ("GET", "HEAD", "OPTIONS"):
        return True
    for m, prefijo in PERMISOS.get(rol, []):
        if ruta.startswith(prefijo) and m in ("*", metodo):
            return True
    return False


# Lo único accesible con una contraseña temporal: cambiarla, salir y los estáticos de la pantalla.
_LIBRE_CON_CLAVE_TEMPORAL = ("/cambiar-clave", "/salir", "/login", "/favicon", "/static_shell/",
                             "/api/cuenta/password", "/api/log-js")


@app.before_request
def exigir_cambio_de_clave():
    """Con contraseña temporal (p. ej. el superadministrador sembrado) no se usa nada más hasta
    cambiarla. Va aquí y no en `login_requerido` para cubrir también las rutas que validan la
    sesión por su cuenta, como /admin."""
    if not session.get("debe_cambiar") or request.path.startswith(_LIBRE_CON_CLAVE_TEMPORAL):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "debes cambiar tu contraseña antes de continuar"}), 403
    return redirect(url_for("cambiar_clave"))


@app.before_request
def proteger_peticion():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    # 1) Anti-CSRF: token de sesión en cabecera (API) o en el formulario (login), y origen propio.
    if not _origen_valido():
        return jsonify({"error": "origen no permitido"}), 403
    esperado = session.get("csrf")
    recibido = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not esperado or not recibido or not hmac.compare_digest(esperado, recibido):
        if request.path.startswith("/api/"):
            return jsonify({"error": "token CSRF ausente o inválido; recarga la página"}), 403
        if request.path != "/login":
            abort(403)
        # En /login sin token válido (sesión caducada) se deja pasar sólo si el origen es propio.
    # 2) Permisos por rol sobre la API.
    if request.path.startswith("/api/") and session.get("usuario"):
        if not _permitido(session.get("rol", "admin"), request.method, request.path):
            return jsonify({"error": "tu rol no permite esta acción"}), 403
    return None


@app.after_request
def cabeceras_seguridad(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Las plantillas llevan scripts y estilos en línea, por eso 'unsafe-inline'; lo que sí se
    # cierra es de dónde pueden venir scripts externos (sólo las CDN del visor 3D) y a dónde se
    # puede conectar la página (sólo a sí misma).
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com "
        "https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; "
        "font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' blob: data:; worker-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")
    if request.is_secure or config.COOKIE_SEGURA:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.errorhandler(core_conexion.ERROR_REFERENCIA)
def referencia_invalida(e):
    """Un id de dron, componente u orden que no existe o que es de otra empresa."""
    get_con().rollback()
    if core_conexion.ES_SQLITE and "FOREIGN KEY" not in str(e):
        return jsonify({"error": "ya existe un registro con esos datos"}), 409
    return jsonify({"error": "el registro al que apunta no existe o no pertenece a tu empresa"}), 400


@app.errorhandler(413)
def demasiado_grande(_e):
    return jsonify({"error": f"El archivo supera el máximo de {config.MAX_SUBIDA_MB} MB."}), 413


@app.errorhandler(403)
def prohibido(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "no permitido"}), 403
    return render_template("login.html", primera_vez=False,
                           error="No tienes permiso para esa acción o tu sesión caducó."), 403


# ---------- Acceso ----------

def _ip():
    return (request.remote_addr or "?")[:64]


def _hace_minutos(n):
    """Instante de hace n minutos, comparable con `login_intentos.creado` en los dos motores."""
    if core_conexion.ES_SQLITE:
        return f"datetime('now','localtime', '-' || CAST({n} AS INTEGER) || ' minutes')"
    return f"now() - ({n} * interval '1 minute')"


def _login_bloqueado(con, usuario):
    # Por usuario: INTENTOS_LOGIN en la ventana. Por IP: el cuádruple, porque una oficina entera
    # suele salir con la misma IP y no hay que bloquearla por un compañero que olvidó su clave.
    fila = con.execute(
        "SELECT COUNT(*) FILTER (WHERE usuario=?) por_usuario, COUNT(*) FILTER (WHERE ip=?) por_ip "
        f"FROM login_intentos WHERE creado > {_hace_minutos('?')}",
        (usuario, _ip(), config.MINUTOS_BLOQUEO_LOGIN)).fetchone()
    return fila["por_usuario"] >= config.INTENTOS_LOGIN or fila["por_ip"] >= config.INTENTOS_LOGIN * 4


def _anotar_fallo(con, usuario):
    con.execute("INSERT INTO login_intentos(usuario, ip) VALUES(?,?)", (usuario, _ip()))
    con.execute(f"DELETE FROM login_intentos WHERE creado < {_hace_minutos('1440')}")
    con.commit()


def _abrir_sesion(con, fila, empresa_id=None):
    session.clear()
    session.permanent = True
    session["usuario"] = fila["usuario"]
    session["rol"] = fila["rol"] or "admin"
    session["usuario_id"] = fila["id"]
    session["tema"] = (fila["tema"] if "tema" in fila.keys() else None) or "sistema"
    if "debe_cambiar_password" in fila.keys() and fila["debe_cambiar_password"]:
        session["debe_cambiar"] = True
    # El superadministrador arranca en el panel de clientes, sin empresa activa.
    if fila["rol"] == core_db.ROL_SUPERADMIN and not empresa_id:
        _fijar_empresa_sesion(con, None)
    else:
        _fijar_empresa_sesion(con, empresa_id or fila["empresa_id"])
    _csrf_token()
    con.execute("UPDATE usuarios SET ultimo_acceso=datetime('now') WHERE id=?", (fila["id"],))
    con.execute("DELETE FROM login_intentos WHERE usuario=?", (fila["usuario"],))
    con.commit()


def _fijar_empresa_sesion(con, empresa_id):
    """Deja en la sesión la empresa con la que se trabaja (y su nombre para la barra lateral)."""
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        emp = core_db.empresa(admin_con, empresa_id) if empresa_id else None
    finally:
        admin_con.close()
    session["empresa_id"] = empresa_id
    session["empresa_nombre"] = emp["nombre"] if emp else None
    return emp


@app.route("/login", methods=["GET", "POST"])
def login():
    con = get_con()
    # El formulario de «crear superadministrador» sólo existe en desarrollo y en el escritorio
    # (127.0.0.1). En el servidor el superadministrador lo crea `manage.py init` al arrancar el
    # contenedor, así nadie puede adelantarse a reclamar la plataforma con sólo abrir la página.
    primera_vez = (config.ENTORNO == "desarrollo" or config.ES_ESCRITORIO) and not core_db.hay_usuarios(con)

    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip()[:64]
        password = request.form.get("password") or ""

        if primera_vez:
            # Primer arranque: sólo se crea el superadministrador de la plataforma. Las empresas
            # (clientes) y sus usuarios se dan de alta después, desde el Panel de clientes.
            password2 = request.form.get("password2") or ""
            if not usuario or len(password) < config.LONGITUD_MINIMA_PASSWORD:
                return render_template("login.html", primera_vez=True,
                                       error=f"Datos incompletos: la contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres.")
            if password != password2:
                return render_template("login.html", primera_vez=True, error="Las contraseñas no coinciden.")
            admin_con = core_db.conectar(core_db.TODAS)
            core_db.crear_usuario(admin_con, usuario, password, rol=core_db.ROL_SUPERADMIN, empresa_id=None)
            admin_con.close()
            _abrir_sesion(con, core_db.usuario_por_nombre(con, usuario))
            return redirect(url_for("admin_panel"))

        if _login_bloqueado(con, usuario):
            app.logger.warning("login bloqueado usuario=%s ip=%s", usuario, _ip())
            return render_template("login.html", primera_vez=False,
                                   error=f"Demasiados intentos. Espera {config.MINUTOS_BLOQUEO_LOGIN} minutos."), 429

        fila = core_db.usuario_por_nombre(con, usuario)
        if fila and fila["activo"] and check_password_hash(fila["password_hash"], password):
            emp = core_db.empresa(core_db.conectar(core_db.TODAS), fila["empresa_id"]) if fila["empresa_id"] else None
            if emp and not emp["activa"] and fila["rol"] != core_db.ROL_SUPERADMIN:
                return render_template("login.html", primera_vez=False,
                                       error="La empresa está desactivada. Contacta al administrador del servicio."), 403
            _abrir_sesion(con, fila)
            app.logger.info("login ok usuario=%s ip=%s", usuario, _ip())
            if session.get("debe_cambiar"):
                return redirect(url_for("cambiar_clave"))
            return redirect(url_for("admin_panel" if _es_superadmin() else "resumen"))
        _anotar_fallo(con, usuario)
        app.logger.warning("login fallido usuario=%s ip=%s", usuario, _ip())
        return render_template("login.html", primera_vez=False, error="Usuario o contraseña incorrectos."), 401

    return render_template("login.html", primera_vez=primera_vez, error=None)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cambiar-clave", methods=["GET", "POST"])
def cambiar_clave():
    """Cambio obligatorio de la contraseña temporal (p. ej. la del superadministrador sembrado)."""
    if not session.get("usuario"):
        return redirect(url_for("login"))
    if not session.get("debe_cambiar"):
        return redirect(url_for("admin_panel" if _es_superadmin() else "resumen"))
    error = None
    if request.method == "POST":
        con = get_con()
        actual = request.form.get("actual") or ""
        nueva, nueva2 = request.form.get("nueva") or "", request.form.get("nueva2") or ""
        fila = core_db.usuario_por_nombre(con, session["usuario"])
        if not fila or not check_password_hash(fila["password_hash"], actual):
            error = "La contraseña actual no es correcta."
        elif len(nueva) < config.LONGITUD_MINIMA_PASSWORD:
            error = f"La nueva contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres."
        elif nueva != nueva2:
            error = "Las contraseñas nuevas no coinciden."
        elif nueva == actual:
            error = "La nueva contraseña debe ser distinta de la temporal."
        else:
            core_db.cambiar_password(con, session["usuario"], nueva)
            session.pop("debe_cambiar", None)
            app.logger.info("contraseña temporal cambiada usuario=%s", session["usuario"])
            return redirect(url_for("admin_panel" if _es_superadmin() else "resumen"))
    return render_template("login.html", primera_vez=False, cambiar_clave=True,
                           usuario=session["usuario"], error=error), (400 if error else 200)


# ---------- Pantallas ----------

@app.route("/")
@login_requerido
def resumen():
    return render_template("resumen.html", activo="resumen")


@app.route("/inventario")
@login_requerido
def inventario():
    return render_template("inventario.html", activo="inventario")


@app.route("/operaciones")
@login_requerido
def operaciones():
    return render_template("operaciones.html", activo="operaciones")


@app.route("/mantenimiento")
@login_requerido
def mantenimiento():
    return render_template("mantenimiento.html", activo="mantenimiento")


@app.route("/actividades")
@login_requerido
def actividades():
    return render_template("actividades.html", activo="actividades")


@app.route("/reportes")
@login_requerido
def reportes():
    return render_template("reportes.html", activo="reportes")


@app.route("/diagramas")
@app.route("/despiece")
@login_requerido
def despiece():
    return render_template("despiece.html", activo="despiece")


@app.route("/vista3d")
@login_requerido
def vista3d():
    return render_template("vista3d.html", activo="vista3d")


@app.route("/ordenes-trabajo")
@login_requerido
def ordenes_trabajo():
    return render_template("ordenes_trabajo.html", activo="ot")


@app.route("/ordenes-servicio")
@login_requerido
def ordenes_servicio():
    return render_template("ordenes_servicio.html", activo="os")


@app.route("/contactos")
@login_requerido
def contactos():
    return render_template("contactos.html", activo="contactos")


@app.route("/bitacora")
@login_requerido
def bitacora():
    return render_template("bitacora.html", activo="bitacora")


@app.route("/admin")
def admin_panel():
    """Panel del superadministrador: clientes (empresas) y sus usuarios. No muestra datos operativos."""
    if not session.get("usuario"):
        return redirect(url_for("login"))
    if not _es_superadmin():
        abort(403)
    return render_template("admin.html", activo="admin")


@app.route("/ajustes")
@login_requerido
def ajustes():
    # Cada usuario elige aquí la apariencia (claro / oscuro) y cambia su contraseña. El correo,
    # los usuarios y los permisos los gestiona la plataforma desde el panel administrativo.
    return render_template("ajustes.html", activo="ajustes")


# ---------- Vistas para imprimir / guardar como PDF ----------

@app.route("/imprimir/orden-trabajo/<int:id_>")
@login_requerido
def imprimir_ot(id_):
    ot = core_ordenes.ot_completa(get_con(), id_)
    if not ot:
        return "Orden no encontrada", 404
    return render_template("imprimir_ot.html", ot=ot)


@app.route("/imprimir/orden-servicio/<int:id_>")
@login_requerido
def imprimir_os(id_):
    orden = core_ordenes.os_completa(get_con(), id_)
    if not orden:
        return "Orden no encontrada", 404
    return render_template("imprimir_os.html", orden=orden, etiquetas=core_ordenes.ETIQUETA_OS)


@app.route("/imprimir/reporte")
@login_requerido
def imprimir_reporte():
    return render_template("imprimir_reporte.html")


# ---------- API: modelos de la flota ----------

@app.route("/api/modelos")
@login_requerido
def api_modelos():
    """Los modelos que maneja la app y con qué datos cuenta cada uno."""
    con = get_con()
    en_uso = {f["modelo"]: f["n"] for f in con.execute(
        "SELECT modelo, COUNT(*) n FROM equipos GROUP BY modelo").fetchall()}
    salida = []
    for ficha in core_modelos.todos_resumidos():
        ficha["n_equipos"] = en_uso.get(ficha["clave"], 0)
        ficha["tipo_activo"] = "dron"
        ficha["contadores"] = core_flota.CONTADORES_POR_TIPO["dron"]
        salida.append(ficha)
    # Modelos de la base que no son DJI: plantillas de avión y modelos propios de la empresa.
    dji = set(core_modelos.claves())
    for m in core_flota.modelos(con):
        if m["clave"] in dji:
            continue
        # Un modelo propio creado desde una plantilla hereda el 3D de ella (misma clave base).
        archivos = core_modelos.archivos_3d_extra(m["clave"]) or core_modelos.archivos_3d_extra(m.get("plantilla") or "")
        # Láminas del fabricante: las suyas o las de la plantilla de la que sale.
        lam = core_modelos.con_laminas(m["clave"], m.get("plantilla"))
        res = core_modelos.resumen(lam) if lam else {}
        salida.append({"clave": m["clave"], "nombre": m["nombre"], "tipo_activo": m["tipo_activo"],
                       "tipo": m["tipo_activo"],
                       "fabricante": m["fabricante"], "descripcion": m["descripcion"], "tanque": None,
                       "contadores": m["contadores"], "es_plantilla": bool(m["es_plantilla"]),
                       "propio": m["propio"], "n_catalogo": m["n_items"], "n_equipos": en_uso.get(m["clave"], 0),
                       "tiene_diagramas": bool(res.get("tiene_diagramas")), "tiene_3d": bool(archivos),
                       "archivos_3d": archivos, "n_laminas": res.get("n_laminas", 0),
                       "n_despiece": res.get("n_despiece", 0), "sistemas": res.get("sistemas", []),
                       "vida_en": "horas y meses"})
    return jsonify({"modelos": salida, "predeterminado": core_modelos.PREDETERMINADO})


# ---------- API: diagramas oficiales del fabricante ----------

def _modelo_pedido(con):
    """Modelo del que se piden las láminas: el que se pide, el del dron elegido, o el de casa."""
    pedido = (request.args.get("modelo") or "").strip()
    if not pedido:
        pedido = core_db.modelo_de_equipo(con, request.args.get("equipo_id", type=int))
    modelo = core_db.modelo_de_laminas(con, pedido)
    return modelo if core_modelos.con_laminas(modelo) else core_modelos.PREDETERMINADO


@app.route("/api/diagramas")
@login_requerido
def api_diagramas():
    import json
    con = get_con()
    equipo_id = request.args.get("equipo_id", type=int)
    modelo = _modelo_pedido(con)
    comps = {c["clave"]: c for c in core_alertas.componentes_con_estado(con, equipo_id)} if equipo_id else {}
    modulos = core_modelos.cargar_diagramas(modelo)
    for m in modulos:
        guardado = core_db.meta_get(con, f"hotspots:{modelo}:{m['clave']}")
        m["hotspots_personalizados"] = bool(guardado)
        if guardado:
            m["hotspots"] = json.loads(guardado)
        m["estado_piezas"] = [comps[k] for k in m.get("piezas_catalogo", []) if k in comps]
        niveles = [p["nivel"] for p in m["estado_piezas"]]
        m["nivel"] = next((n for n in ("vencido", "critico", "proximo") if n in niveles), "ok")
    return jsonify({"modelo": core_modelos.resumen(modelo), "laminas": modulos})


@app.route("/api/diagramas/<modelo>/<clave>/hotspots", methods=["PUT", "DELETE"])
@login_requerido
def api_diagrama_hotspots(modelo, clave):
    import json
    con = get_con()
    meta = f"hotspots:{modelo}:{clave}"
    if request.method == "DELETE":
        con.execute("DELETE FROM meta WHERE clave=?", (meta,))
        con.commit()
        return jsonify({"ok": True})
    datos = request.get_json(force=True) or []
    limpio = [{"n": int(h["n"]), "x": round(float(h["x"]), 2), "y": round(float(h["y"]), 2)} for h in datos]
    core_db.meta_set(con, meta, json.dumps(limpio))
    return jsonify({"ok": True, "n": len(limpio)})


# ---------- API: equipos ----------

def _equipo_dict(con, fila, comps_por_equipo=None, stats=None):
    """Ficha de un dron con sus alertas y su actividad.

    `comps_por_equipo` y `stats` permiten pasar los datos ya calculados para toda la flota:
    listar 60 drones lanzaba 180 consultas (tres por dron); así son tres en total.
    """
    d = dict(fila)
    d["horas_totales"] = round(d["horas_totales"] or 0, 1)
    if comps_por_equipo is None:
        comps = core_alertas.componentes_con_estado(con, d["id"])
    else:
        comps = comps_por_equipo.get(d["id"], [])
    d["alertas"] = {
        "vencido": sum(c["nivel"] == "vencido" for c in comps),
        "critico": sum(c["nivel"] == "critico" for c in comps),
        "proximo": sum(c["nivel"] == "proximo" for c in comps),
    }
    if stats is None:
        st = con.execute("SELECT COUNT(*) n, MAX(fecha) f FROM operaciones WHERE equipo_id=?", (d["id"],)).fetchone()
    else:
        st = stats.get(d["id"], {"n": 0, "f": None})
    d["n_operaciones"] = st["n"]
    d["ultima_operacion"] = st["f"]
    d["tipo_txt"] = core_flota.TIPOS_ACTIVO.get(d.get("tipo_activo") or "dron")
    return d


def _equipo_valido(con, equipo_id):
    """El dron existe y es de la empresa de la sesión (RLS: si no, no se ve)."""
    try:
        equipo_id = int(equipo_id)
    except (TypeError, ValueError):
        return False
    return bool(con.execute("SELECT 1 FROM equipos WHERE id=?", (equipo_id,)).fetchone())


def _flota_dicts(con, filas):
    """Fichas de varios drones con los datos de toda la flota calculados de una vez."""
    comps_por_equipo = {}
    for c in core_alertas.componentes_con_estado(con):
        comps_por_equipo.setdefault(c["equipo_id"], []).append(c)
    stats = {f["equipo_id"]: f for f in con.execute(
        "SELECT equipo_id, COUNT(*) n, MAX(fecha) f FROM operaciones GROUP BY equipo_id").fetchall()}
    lista = [_equipo_dict(con, f, comps_por_equipo, stats) for f in filas]
    # Estado de aeronavegabilidad y lecturas de contador de toda la flota, en una pasada.
    estados = core_flota.estado_aeronavegable(con, comps_por_equipo, core_flota.directivas_con_estado(con),
                                              core_flota.documentos_con_estado(con), [dict(f) for f in filas])
    lect = core_flota.lecturas(con, [d["id"] for d in lista])
    for d in lista:
        d["aeronavegable"] = estados.get(d["id"])
        d["contadores"] = lect.get(d["id"], {})
    # Foto del día para la disponibilidad histórica (se actualiza con cada consulta de la flota).
    try:
        core_flota.registrar_estado_diario(con, estados, [dict(f) for f in filas])
        con.commit()
    except Exception:          # la foto nunca debe tumbar la pantalla
        con.rollback()
    return lista


@app.route("/api/equipos", methods=["GET", "POST"])
@login_requerido
def api_equipos():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"error": "falta el nombre"}), 400
        modelo = datos.get("modelo") or core_modelos.PREDETERMINADO
        m = core_flota.modelo_activo(con, modelo)
        if not m:
            return jsonify({"error": "el modelo no existe"}), 400
        if m["tipo_activo"] == "avion" and not (datos.get("matricula") or "").strip():
            return jsonify({"error": "un avión lleva matrícula (p. ej. HK-1234)"}), 400
        try:
            equipo_id = core_db.crear_equipo(
                con, nombre, modelo, datos.get("numero_serie"), datos.get("nota"),
                matricula=(datos.get("matricula") or "").strip().upper() or None,
                anio=int(datos["anio"]) if str(datos.get("anio") or "").isdigit() else None,
                base=datos.get("base"), fabricante=datos.get("fabricante"),
                contadores=datos.get("contadores") or {}, fecha_alta=datos.get("fecha_alta") or None)
        except core_conexion.ERROR_UNICO:
            get_con().rollback()
            return jsonify({"error": "ya existe un activo con esos datos"}), 409
        return jsonify({"ok": True, "id": equipo_id}), 201
    tipo = request.args.get("tipo") or None
    filas = con.execute("SELECT * FROM equipos " + ("WHERE tipo_activo=? " if tipo else "")
                        + "ORDER BY estado='baja', tipo_activo DESC, nombre", (tipo,) if tipo else ()).fetchall()
    return jsonify(_flota_dicts(con, filas))


@app.route("/api/equipos/<int:id_>", methods=["GET", "PUT", "DELETE"])
@login_requerido
def api_equipo(id_):
    con = get_con()
    fila = con.execute("SELECT * FROM equipos WHERE id=?", (id_,)).fetchone()
    if not fila:
        return jsonify({"error": "no existe"}), 404
    if request.method == "DELETE":
        # Un activo nunca se borra: se da de baja y conserva toda su historia (operaciones,
        # mantenimientos, piezas, órdenes). Se puede reactivar cambiando su estado.
        datos = request.get_json(silent=True) or {}
        motivo = (datos.get("motivo") or "").strip() or "Dado de baja"
        con.execute("UPDATE equipos SET estado='baja', fecha_baja=?, motivo_baja=? WHERE id=?",
                    (datos.get("fecha") or date.today().isoformat(), motivo, id_))
        core_flota.auditar(con, "equipos", id_, "estado", fila["estado"], "baja", session.get("usuario"), motivo)
        con.commit()
        return jsonify({"ok": True, "estado": "baja"})
    if request.method == "PUT":
        datos = request.get_json(force=True) or {}
        campos, valores = [], []
        for campo in ("nombre", "modelo", "numero_serie", "estado", "nota", "fecha_alta", "matricula", "anio",
                      "base", "fabricante"):
            if campo in datos:
                campos.append(f"{campo}=?")
                valores.append(datos[campo])
        if campos:
            if datos.get("estado") and datos["estado"] != "baja":
                campos += ["fecha_baja=NULL", "motivo_baja=NULL"]      # reactivado
            if datos.get("estado") and datos["estado"] != fila["estado"]:
                core_flota.auditar(con, "equipos", id_, "estado", fila["estado"], datos["estado"],
                                   session.get("usuario"), datos.get("motivo"))
            valores.append(id_)
            con.execute(f"UPDATE equipos SET {', '.join(campos)} WHERE id=?", valores)
            con.commit()
        return jsonify({"ok": True})
    d = _flota_dicts(con, [fila])[0]
    d["componentes"] = core_alertas.componentes_con_estado(con, id_)
    d["modelo_info"] = core_flota.modelo_activo(con, d["modelo"])
    d["piezas_serie"] = core_flota.piezas_serie(con, equipo_id=id_)
    d["baterias"] = core_flota.baterias(con, id_) if d.get("tipo_activo") == "dron" else []
    d["directivas"] = core_flota.directivas_con_estado(con, id_)
    d["documentos"] = core_flota.documentos_con_estado(con, id_)
    d["repuestos"] = core_proyeccion.proximos_repuestos(con, id_, limite=12)
    d["ultimas_operaciones"] = [dict(f) for f in con.execute(
        "SELECT * FROM operaciones WHERE equipo_id=? ORDER BY fecha DESC, id DESC LIMIT 10", (id_,)).fetchall()]
    d["mantenimientos"] = [dict(f) for f in con.execute(
        "SELECT * FROM mantenimientos WHERE equipo_id=? ORDER BY fecha DESC, id DESC LIMIT 10", (id_,)).fetchall()]
    d["contadores_info"] = {c: {"nombre": core_flota.nombre_contador(c), "unidad": core_flota.unidad(c)}
                            for c in d["contadores"]}
    return jsonify(d)


@app.route("/api/componentes")
@login_requerido
def api_componentes():
    equipo_id = request.args.get("equipo_id", type=int)
    return jsonify(core_alertas.componentes_con_estado(get_con(), equipo_id))


@app.route("/api/componentes/<int:id_>", methods=["PUT"])
@login_requerido
def api_componente(id_):
    con = get_con()
    datos = request.get_json(force=True) or {}
    if "horas_uso" in datos:
        try:
            valor = float(str(datos["horas_uso"] or 0).replace(",", "."))
        except ValueError:
            return jsonify({"error": "valor no numérico"}), 400
        if valor < 0:
            return jsonify({"error": "el uso no puede ser negativo"}), 400
        # La corrección queda auditada: quién, cuándo, antes, después y por qué.
        if not core_flota.fijar_uso_componente(con, id_, valor, session.get("usuario"),
                                               (datos.get("motivo") or "Corrección manual").strip()):
            return jsonify({"error": "no existe"}), 404
        con.commit()
    return jsonify({"ok": True})


@app.route("/api/catalogo")
@login_requerido
def api_catalogo():
    filas = get_con().execute("SELECT * FROM catalogo_piezas ORDER BY modulo, nombre").fetchall()
    return jsonify([dict(f) for f in filas])


# ---------- API: operaciones ----------

@app.route("/api/operaciones", methods=["GET", "POST"])
@login_requerido
def api_operaciones():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        def num(k):
            v = datos.get(k)
            try:
                return float(str(v).replace(",", ".")) if v not in (None, "") else None
            except ValueError:
                return None

        try:
            equipo_id = int(datos.get("equipo_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "falta el equipo"}), 400
        horas = num("horas_vuelo")
        # Avión: las horas salen del Hobbs si se dan lectura inicial y final.
        if horas is None and num("hobbs_ini") is not None and num("hobbs_fin") is not None:
            horas = round(num("hobbs_fin") - num("hobbs_ini"), 2)
        if horas is None:
            return jsonify({"error": "faltan las horas de vuelo (en un avión, o el Hobbs inicial y final)"}), 400
        if horas <= 0:
            return jsonify({"error": "las horas deben ser mayores a 0"}), 400
        if not _equipo_valido(con, equipo_id):
            return jsonify({"error": "el equipo no existe"}), 404
        fecha = datos.get("fecha") or None
        errores = core_db.validar_operacion({**datos, "horas_vuelo": horas, "fecha": fecha})
        if errores:
            return jsonify({"error": "; ".join(errores), "errores": errores}), 400
        texto = ("producto", "piloto", "cliente", "zona", "lote", "nota", "pista",
                 "hora_salida", "hora_llegada", "origen", "destino", "proposito")
        enteros = ("despegues", "aterrizajes", "arranques", "personal_id")
        # Piloto elegido del directorio: su nombre queda también en el texto (reportes antiguos).
        if datos.get("personal_id") and not datos.get("piloto"):
            p = con.execute("SELECT nombre FROM personal WHERE id=?", (datos.get("personal_id"),)).fetchone()
            datos["piloto"] = p["nombre"] if p else None
        campos = {}
        for c in core_db.COLUMNAS_OPERACION:
            if c in texto:
                campos[c] = datos.get(c) or None
            elif c in enteros:
                campos[c] = int(num(c) or 0) or None
            else:
                campos[c] = num(c)
        nuevo = core_db.registrar_operacion(con, equipo_id, horas, fecha=fecha, **campos)
        return jsonify({"ok": True, "id": nuevo}), 201

    equipo_id = request.args.get("equipo_id", type=int)
    limite = request.args.get("limite", default=500, type=int)
    filtro = "WHERE o.equipo_id=?" if equipo_id else ""
    params = (equipo_id, limite) if equipo_id else (limite,)
    filas = con.execute(
        f"""SELECT o.*, e.nombre AS equipo FROM operaciones o JOIN equipos e ON e.id=o.equipo_id
            {filtro} ORDER BY o.fecha DESC, o.id DESC LIMIT ?""",
        params,
    ).fetchall()
    return jsonify([dict(f) for f in filas])


@app.route("/api/operaciones/<int:id_>", methods=["PUT", "DELETE"])
@login_requerido
def api_operacion(id_):
    con = get_con()
    fila = con.execute("SELECT equipo_id, horas_vuelo FROM operaciones WHERE id=?", (id_,)).fetchone()
    if not fila:
        return jsonify({"error": "no existe"}), 404

    if request.method == "PUT":
        # Edición en la propia tabla: llega un solo campo por pulsación y se guarda al vuelo.
        datos = request.get_json(force=True) or {}
        previa = dict(con.execute("SELECT * FROM operaciones WHERE id=?", (id_,)).fetchone())
        errores = core_db.validar_operacion(datos, previa)
        if errores:
            return jsonify({"error": "; ".join(errores), "errores": errores}), 400
        if "horas_vuelo" in datos:
            try:
                if float(str(datos["horas_vuelo"]).replace(",", ".")) <= 0:
                    return jsonify({"error": "las horas deben ser mayores a 0"}), 400
            except ValueError:
                return jsonify({"error": "horas de vuelo no numéricas"}), 400
        try:
            actualizada = core_db.actualizar_operacion(con, id_, datos)
        except ValueError:
            return jsonify({"error": "valor no numérico"}), 400
        equipo = con.execute("SELECT horas_totales FROM equipos WHERE id=?", (fila["equipo_id"],)).fetchone()
        return jsonify({"ok": True, "operacion": actualizada, "horas_equipo": round(equipo["horas_totales"], 1)})

    core_db.eliminar_operacion(con, id_)
    return jsonify({"ok": True})


# ---------- API: mantenimientos y alertas ----------

@app.route("/api/mantenimientos", methods=["GET", "POST"])
@login_requerido
def api_mantenimientos():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        try:
            equipo_id = int(datos.get("equipo_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "falta el equipo"}), 400
        if not _equipo_valido(con, equipo_id):
            return jsonify({"error": "el equipo no existe"}), 404
        componente_id = datos.get("componente_id") or None
        try:
            costo = float(datos.get("costo")) if datos.get("costo") not in (None, "") else None
        except ValueError:
            costo = None
        core_db.registrar_mantenimiento(
            con, equipo_id, int(componente_id) if componente_id else None,
            datos.get("tipo") or "preventivo", datos.get("descripcion") or None,
            costo, datos.get("realizado_por") or None, datos.get("fecha") or None,
            motivo=datos.get("motivo") or None,
            codigo_pieza=datos.get("codigo_pieza") or None,
            nombre_pieza=datos.get("nombre_pieza") or None,
            costo_repuesto=core_flota._num(datos.get("costo_repuesto")),
            costo_mano_obra=core_flota._num(datos.get("costo_mano_obra")),
            firmado_por=datos.get("firmado_por") or None, licencia_firma=datos.get("licencia_firma") or None,
        )
        return jsonify({"ok": True}), 201

    equipo_id = request.args.get("equipo_id", type=int)
    filtro = "WHERE m.equipo_id=?" if equipo_id else ""
    params = (equipo_id,) if equipo_id else ()
    filas = con.execute(
        f"""SELECT m.*, e.nombre AS equipo, p.nombre AS pieza, p.modulo
            FROM mantenimientos m
            JOIN equipos e ON e.id=m.equipo_id
            LEFT JOIN componentes c ON c.id=m.componente_id
            LEFT JOIN catalogo_piezas p ON p.id=c.pieza_id
            {filtro} ORDER BY m.fecha DESC, m.id DESC""",
        params,
    ).fetchall()
    return jsonify([dict(f) for f in filas])


@app.route("/api/mantenimientos/<int:id_>", methods=["DELETE"])
@login_requerido
def api_mantenimiento(id_):
    con = get_con()
    if not core_db.eliminar_mantenimiento(con, id_, session.get("usuario")):
        return jsonify({"error": "no existe"}), 404
    return jsonify({"ok": True})


@app.route("/api/alertas")
@login_requerido
def api_alertas():
    return jsonify(core_alertas.alertas(get_con()))


# ---------- API: resumen y reportes ----------

@app.route("/api/resumen")
@login_requerido
def api_resumen():
    con = get_con()
    tipo = request.args.get("tipo") or None
    equipos = con.execute("SELECT * FROM equipos " + ("WHERE tipo_activo=? " if tipo else "")
                          + "ORDER BY tipo_activo DESC, nombre", (tipo,) if tipo else ()).fetchall()
    ultimas = con.execute(
        "SELECT o.*, e.nombre AS equipo, e.tipo_activo FROM operaciones o JOIN equipos e ON e.id=o.equipo_id "
        + ("WHERE e.tipo_activo=? " if tipo else "") + "ORDER BY o.fecha DESC, o.id DESC LIMIT 6", (tipo,) if tipo else ()
    ).fetchall()
    pendientes = con.execute(
        "SELECT r.*, e.nombre AS equipo FROM registros r LEFT JOIN equipos e ON e.id=r.equipo_id "
        "WHERE r.estado='pendiente' ORDER BY r.vence IS NULL, r.vence LIMIT 6"
    ).fetchall()
    tot = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(horas_vuelo),0) h, COALESCE(SUM(hectareas),0) ha, COALESCE(SUM(litros),0) l FROM operaciones"
    ).fetchone()
    mes = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(horas_vuelo),0) h, COALESCE(SUM(hectareas),0) ha FROM operaciones "
        "WHERE fecha >= date('now','start of month')"
    ).fetchone()
    activas = core_alertas.alertas(con, tipo)
    conteo = {"vencido": 0, "critico": 0, "proximo": 0}
    for c in activas:
        conteo[c["nivel"]] += 1
    conteo["total"] = len(activas)
    return jsonify({
        "equipos": _flota_dicts(con, equipos),
        "alertas": activas[:8],
        "alertas_resumen": conteo,
        "ultimas_operaciones": [dict(f) for f in ultimas],
        "actividades_pendientes": [dict(f) for f in pendientes],
        "n_actividades_pendientes": con.execute("SELECT COUNT(*) n FROM registros WHERE estado='pendiente'").fetchone()["n"],
        "totales": {"operaciones": tot["n"], "horas": round(tot["h"], 1), "hectareas": round(tot["ha"], 1), "litros": round(tot["l"], 0)},
        "mes": {"operaciones": mes["n"], "horas": round(mes["h"], 1), "hectareas": round(mes["ha"], 1)},
    })


@app.route("/api/reportes")
@login_requerido
def api_reportes():
    con = get_con()
    equipo_id = request.args.get("equipo_id", type=int)
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    cond, params = ["1=1"], []
    if equipo_id:
        cond.append("o.equipo_id=?"); params.append(equipo_id)
    if desde:
        cond.append("o.fecha>=?"); params.append(desde)
    if hasta:
        cond.append("o.fecha<=?"); params.append(hasta)
    where = " AND ".join(cond)

    def q(sql):
        return [dict(f) for f in con.execute(sql, params).fetchall()]

    por_mes = q(f"""SELECT substr(o.fecha,1,7) mes, COUNT(*) n, ROUND(SUM(o.horas_vuelo),1) horas,
                    ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas, ROUND(COALESCE(SUM(o.litros),0),0) litros
                    FROM operaciones o WHERE {where} GROUP BY mes ORDER BY mes""")
    por_equipo = q(f"""SELECT e.nombre equipo, COUNT(o.id) n, ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas,
                       ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
                       FROM equipos e LEFT JOIN operaciones o ON o.equipo_id=e.id AND {where}
                       GROUP BY e.id ORDER BY horas DESC""")
    por_producto = q(f"""SELECT COALESCE(o.producto,'Sin especificar') producto, COUNT(*) n,
                         ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas, ROUND(COALESCE(SUM(o.litros),0),0) litros
                         FROM operaciones o WHERE {where} GROUP BY producto ORDER BY hectareas DESC LIMIT 10""")
    por_piloto = q(f"""SELECT COALESCE(o.piloto,'Sin piloto') piloto, COUNT(*) n, ROUND(SUM(o.horas_vuelo),1) horas,
                       ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
                       FROM operaciones o WHERE {where} GROUP BY piloto ORDER BY horas DESC LIMIT 10""")
    por_finca = q(f"""SELECT COALESCE(o.lote,'Sin finca') finca, COALESCE(o.cliente,'') cliente, COUNT(*) n,
                      ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
                      FROM operaciones o WHERE {where} GROUP BY finca, cliente ORDER BY hectareas DESC LIMIT 10""")
    tot = q(f"""SELECT COUNT(*) n, ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas, ROUND(COALESCE(SUM(o.tiempo_total),0),1) tiempo_total,
                ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas, ROUND(COALESCE(SUM(o.litros),0),0) litros,
                COALESCE(SUM(COALESCE(o.despegues, o.aterrizajes)),0) despegues FROM operaciones o WHERE {where}""")[0]

    por_dia = q(f"""SELECT o.fecha dia, COUNT(*) n, ROUND(SUM(o.horas_vuelo),2) horas,
                    ROUND(COALESCE(SUM(o.hectareas),0),2) hectareas
                    FROM operaciones o WHERE {where} GROUP BY dia ORDER BY dia""")
    por_cliente = q(f"""SELECT COALESCE(o.cliente,'Sin cliente') cliente, COUNT(*) n,
                        ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas, ROUND(SUM(o.horas_vuelo),1) horas
                        FROM operaciones o WHERE {where} GROUP BY cliente ORDER BY hectareas DESC LIMIT 10""")
    por_zona = q(f"""SELECT COALESCE(o.zona,'Sin zona') zona, COUNT(*) n,
                     ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
                     FROM operaciones o WHERE {where} GROUP BY zona ORDER BY hectareas DESC LIMIT 10""")
    # Reparto semanal: sirve para ver en qué días se concentra la operación.
    por_dia_semana = q(f"""SELECT {core_conexion.sql_dow('o.fecha')} dow, COUNT(*) n,
                           ROUND(SUM(o.horas_vuelo),1) horas FROM operaciones o WHERE {where}
                           GROUP BY dow ORDER BY dow""")

    mcond = where.replace("o.", "m.")
    mant = [dict(f) for f in con.execute(
        f"""SELECT m.tipo, COUNT(*) n, ROUND(COALESCE(SUM(m.costo),0),0) costo FROM mantenimientos m
            WHERE {mcond} GROUP BY m.tipo""", params).fetchall()]
    mant_mes = [dict(f) for f in con.execute(
        f"""SELECT substr(m.fecha,1,7) mes, COUNT(*) n, ROUND(COALESCE(SUM(m.costo),0),0) costo
            FROM mantenimientos m WHERE {mcond} GROUP BY mes ORDER BY mes""", params).fetchall()]

    # Salud de la flota: piezas por nivel en cada equipo, para el panel de gráficas. La proyección
    # de repuestos ya trae cada componente con su estado, así que se recorre una sola vez.
    repuestos = core_proyeccion.proximos_repuestos(con, equipo_id, limite=10 ** 6)
    flota = {}
    for c in repuestos:
        d = flota.setdefault(c["equipo"], {"equipo": c["equipo"], "ok": 0, "proximo": 0, "critico": 0, "vencido": 0})
        d[c["nivel"]] += 1
    resumen_alertas = {"vencido": 0, "critico": 0, "proximo": 0}
    for c in repuestos:
        if c["nivel"] in resumen_alertas:
            resumen_alertas[c["nivel"]] += 1
    resumen_alertas["total"] = sum(resumen_alertas.values())

    return jsonify({
        "totales": tot, "por_mes": por_mes, "por_equipo": por_equipo, "por_producto": por_producto,
        "por_piloto": por_piloto, "por_finca": por_finca, "por_dia": por_dia, "por_cliente": por_cliente,
        "por_zona": por_zona, "por_dia_semana": por_dia_semana,
        "mantenimientos": mant, "mantenimientos_mes": mant_mes, "flota": list(flota.values()),
        "alertas_resumen": resumen_alertas,
        "repuestos": repuestos[:12],
        "repuestos_resumen": core_proyeccion.resumen(con, equipo_id, lista=repuestos),
        "filtros": {"equipo_id": equipo_id, "desde": desde, "hasta": hasta},
    })


# ---------- API: actividades (registros) ----------

@app.route("/api/registros", methods=["GET", "POST"])
@login_requerido
def api_registros():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        titulo = (datos.get("titulo") or "").strip()
        if not titulo:
            return jsonify({"error": "falta el título"}), 400
        con.execute(
            "INSERT INTO registros(titulo, categoria, vence, nota, equipo_id) VALUES(?,?,?,?,?)",
            (titulo, datos.get("categoria") or "General", datos.get("vence") or None, datos.get("nota"), datos.get("equipo_id") or None),
        )
        con.commit()
        return jsonify({"ok": True}), 201

    filas = con.execute(
        "SELECT r.*, e.nombre AS equipo FROM registros r LEFT JOIN equipos e ON e.id=r.equipo_id "
        "ORDER BY r.estado='completado', r.vence IS NULL, r.vence, r.creado DESC"
    ).fetchall()
    return jsonify([dict(f) for f in filas])


@app.route("/api/registros/<int:id_>", methods=["PUT", "DELETE"])
@login_requerido
def api_registro(id_):
    con = get_con()
    if request.method == "DELETE":
        con.execute("DELETE FROM registros WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})

    datos = request.get_json(force=True) or {}
    campos, valores = [], []
    for campo in ("titulo", "categoria", "estado", "vence", "nota", "equipo_id"):
        if campo in datos:
            campos.append(f"{campo}=?")
            valores.append(datos[campo])
    if campos:
        campos.append("actualizado=datetime('now')")
        valores.append(id_)
        con.execute(f"UPDATE registros SET {', '.join(campos)} WHERE id=?", valores)
        con.commit()
    return jsonify({"ok": True})



# ---------- API: operaciones en Excel (plantilla, exportar, importar) ----------

def _filtros_operaciones():
    return (request.args.get("equipo_id", type=int), request.args.get("desde") or None,
            request.args.get("hasta") or None)


@app.route("/api/operaciones/plantilla.xlsx")
@login_requerido
def api_operaciones_plantilla():
    """Plantilla de operaciones CON los datos al día.

    Antes bajaba vacía, y entonces el archivo que se llenaba a mano y se subía a Drive no
    coincidía con lo que tenía la app: dos versiones de la verdad. Ahora la plantilla y la
    exportación son el mismo archivo, y sobre él se añaden las filas nuevas al final.
    """
    con = get_con()
    filas = core_excel.operaciones_para_excel(con)
    libro = core_excel.libro_operaciones(con, filas)
    from datetime import date as _date
    nombre = f"Operaciones {_date.today().isoformat()} - Hangar.xlsx"
    return send_file(libro, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/operaciones/exportar.xlsx")
@login_requerido
def api_operaciones_exportar():
    con = get_con()
    equipo_id, desde, hasta = _filtros_operaciones()
    filas = core_excel.operaciones_para_excel(con, equipo_id, desde, hasta)
    libro = core_excel.libro_operaciones(con, filas)
    from datetime import date as _date
    nombre = f"Operaciones {_date.today().isoformat()} - Hangar.xlsx"
    return send_file(libro, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/operaciones/importar", methods=["POST"])
@login_requerido
def api_operaciones_importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "error": "No llegó ningún archivo."}), 400
    if not archivo.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "error": "El archivo debe ser .xlsx (el que descarga la app)."}), 400
    crear = (request.form.get("crear_equipos") or "").lower() in ("1", "true", "si", "sí")
    # openpyxl necesita un archivo con seek/seekable: el stream de Werkzeug no siempre lo es.
    import io as _io
    contenido = _io.BytesIO(archivo.read())
    try:
        informe = core_excel.procesar_importacion(get_con(), contenido, crear_equipos=crear)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No pude leer el archivo: {exc}"}), 400
    return jsonify(informe), (200 if informe.get("ok") else 400)


# ---------- API: próximos repuestos según el ritmo de operación ----------

@app.route("/api/repuestos")
@login_requerido
def api_repuestos():
    con = get_con()
    equipo_id = request.args.get("equipo_id", type=int)
    horizonte = request.args.get("horizonte", type=int)
    limite = request.args.get("limite", default=40, type=int)
    # Una sola pasada por la flota: la lista completa sirve para el resumen y para el recorte.
    todos = core_proyeccion.proximos_repuestos(con, equipo_id, limite=10 ** 6)
    lista = todos
    if horizonte:
        lista = [d for d in lista if d["dias_estimados"] is not None and d["dias_estimados"] <= horizonte]
    return jsonify({
        "lista": lista[:limite],
        "resumen": core_proyeccion.resumen(con, equipo_id, lista=todos),
        "ritmo": core_proyeccion.ritmo_por_equipo(con),
    })


# ---------- Registro de errores del navegador ----------

@app.route("/api/log-js", methods=["POST"])
@login_requerido
def api_log_js():
    """Recibe los errores de JavaScript del navegador y los deja en el registro del servidor."""
    d = request.get_json(silent=True) or {}
    app.logger.warning("JS %s | %s | %s | %s", str(d.get("pagina"))[:200], str(d.get("mensaje"))[:600],
                       str(d.get("origen"))[:300], " / ".join(str(d.get("pila") or "").splitlines()[:6])[:900])
    return jsonify({"ok": True})


# ---------- API: cuenta propia y usuarios (admin) ----------

TEMAS = ("sistema", "claro", "oscuro")


@app.route("/api/cuenta/tema", methods=["GET", "PUT"])
@login_requerido
def api_cuenta_tema():
    """Apariencia de la app para el usuario: claro, oscuro o la del sistema operativo."""
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        if request.method == "PUT":
            tema = (request.get_json(force=True) or {}).get("tema")
            if tema not in TEMAS:
                return jsonify({"error": "tema no válido"}), 400
            admin_con.execute("UPDATE usuarios SET tema=? WHERE usuario=?", (tema, session["usuario"]))
            admin_con.commit()
            session["tema"] = tema
        fila = admin_con.execute("SELECT tema FROM usuarios WHERE usuario=?", (session["usuario"],)).fetchone()
        return jsonify({"tema": (fila and fila["tema"]) or "sistema"})
    finally:
        admin_con.close()


@app.route("/api/avisos-config", methods=["GET", "PUT"])
@login_requerido
def api_avisos_config():
    """Cuándo avisa la app que algo está por vencer. «Vencido» es siempre el límite del fabricante
    o del RAC: aquí sólo se adelanta el aviso, nunca se retrasa."""
    con = get_con()
    if request.method == "PUT":
        datos = request.get_json(silent=True) or {}
        modo = datos.get("modo") or "restante"
        if modo not in ("restante", "porcentaje"):
            return jsonify({"error": "modo de aviso no válido"}), 400
        valores = {}
        for k in core_alertas.AVISOS_DEFECTO:
            v = core_flota._num(datos.get(k))
            if v is None or v < 0:
                return jsonify({"error": "los umbrales son números mayores o iguales a cero"}), 400
            valores[k] = v
        for pareja in ("horas", "ciclos", "dias"):
            if valores[f"aviso_{pareja}_critico"] > valores[f"aviso_{pareja}_proximo"]:
                return jsonify({"error": "el aviso crítico tiene que saltar después del aviso de «próximo»"}), 400
        core_db.meta_set(con, "aviso_modo", modo)
        for k, v in valores.items():
            core_db.meta_set(con, k, f"{v:g}")
        con.commit()
    cfg = core_alertas.config_avisos(con)
    return jsonify({**cfg, "texto": core_alertas.texto_avisos(cfg)})


@app.route("/api/cuenta/password", methods=["POST"])
@login_requerido
def api_cuenta_password():
    con = get_con()
    datos = request.get_json(force=True) or {}
    actual, nueva = datos.get("actual") or "", datos.get("nueva") or ""
    fila = core_db.usuario_por_nombre(con, session["usuario"])
    if not fila or not check_password_hash(fila["password_hash"], actual):
        return jsonify({"error": "la contraseña actual no es correcta"}), 400
    if len(nueva) < config.LONGITUD_MINIMA_PASSWORD:
        return jsonify({"error": f"la nueva contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
    core_db.cambiar_password(con, session["usuario"], nueva)
    session.pop("debe_cambiar", None)
    return jsonify({"ok": True})


@app.route("/api/usuarios", methods=["GET", "POST"])
@superadmin_requerido
def api_usuarios():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        usuario = (datos.get("usuario") or "").strip()[:64]
        password = datos.get("password") or ""
        rol = datos.get("rol") or "tecnico"
        if not usuario or rol not in core_db.ROLES_USUARIO:
            return jsonify({"error": "usuario o rol no válidos"}), 400
        if len(password) < config.LONGITUD_MINIMA_PASSWORD:
            return jsonify({"error": f"la contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
        if core_db.usuario_por_nombre(con, usuario):
            return jsonify({"error": "ese usuario ya existe"}), 400
        uid = core_db.crear_usuario(con, usuario, password, rol, datos.get("nombre") or None,
                                    datos.get("email") or None, empresa_id=session["empresa_id"])
        return jsonify({"ok": True, "id": uid}), 201
    roles = dict(core_db.ROLES_USUARIO)
    if _es_superadmin():
        roles[core_db.ROL_SUPERADMIN] = "Superadministrador"
    return jsonify({"lista": core_db.usuarios(con, session["empresa_id"]), "roles": roles})


@app.route("/api/usuarios/<int:id_>", methods=["PUT", "DELETE"])
@superadmin_requerido
def api_usuario(id_):
    con = get_con()
    # Sólo se tocan cuentas de la empresa en la que se está trabajando.
    fila = con.execute("SELECT * FROM usuarios WHERE id=? AND empresa_id=?", (id_, session["empresa_id"])).fetchone()
    if not fila:
        return jsonify({"error": "no existe"}), 404
    if fila["rol"] == core_db.ROL_SUPERADMIN and not _es_superadmin():
        return jsonify({"error": "esa cuenta la gestiona el superadministrador"}), 403
    propio = fila["usuario"] == session["usuario"]
    if request.method == "DELETE":
        if propio:
            return jsonify({"error": "no puedes borrar tu propio usuario"}), 400
        con.execute("DELETE FROM usuarios WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})
    datos = request.get_json(force=True) or {}
    if "rol" in datos:
        roles_validos = set(core_db.ROLES_USUARIO) | ({core_db.ROL_SUPERADMIN} if _es_superadmin() else set())
        if datos["rol"] not in roles_validos:
            return jsonify({"error": "rol no válido"}), 400
        if propio and datos["rol"] not in ("admin", core_db.ROL_SUPERADMIN):
            return jsonify({"error": "no puedes quitarte el rol de administrador"}), 400
        con.execute("UPDATE usuarios SET rol=? WHERE id=?", (datos["rol"], id_))
    if "activo" in datos:
        if propio and not datos["activo"]:
            return jsonify({"error": "no puedes desactivar tu propio usuario"}), 400
        con.execute("UPDATE usuarios SET activo=? WHERE id=?", (1 if datos["activo"] else 0, id_))
    for campo in ("nombre", "email"):
        if campo in datos:
            con.execute(f"UPDATE usuarios SET {campo}=? WHERE id=?", (datos[campo] or None, id_))
    if datos.get("password"):
        if len(datos["password"]) < config.LONGITUD_MINIMA_PASSWORD:
            return jsonify({"error": f"la contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
        core_db.cambiar_password(con, fila["usuario"], datos["password"])
    con.commit()
    return jsonify({"ok": True})


# ---------- API: empresas (sólo superadministrador) ----------

@app.route("/api/empresas", methods=["GET", "POST"])
@superadmin_requerido
def api_empresas():
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        if request.method == "POST":
            datos = request.get_json(force=True) or {}
            nombre = (datos.get("nombre") or "").strip()
            if not nombre:
                return jsonify({"error": "falta el nombre de la empresa"}), 400
            empresa_id = core_db.crear_empresa(admin_con, nombre, datos.get("nit") or None,
                                               datos.get("contacto") or None, datos.get("email") or None,
                                               datos.get("telefono") or None, datos.get("nota") or None)
            # Opcional: el primer administrador de la empresa nueva, en la misma operación.
            admin_usuario = (datos.get("admin_usuario") or "").strip()[:64]
            if admin_usuario:
                clave = datos.get("admin_password") or ""
                if len(clave) < config.LONGITUD_MINIMA_PASSWORD:
                    return jsonify({"error": f"la contraseña del administrador necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
                if core_db.usuario_por_nombre(admin_con, admin_usuario):
                    return jsonify({"error": "ese nombre de usuario ya existe"}), 400
                core_db.crear_usuario(admin_con, admin_usuario, clave, "admin", empresa_id=empresa_id)
            return jsonify({"ok": True, "id": empresa_id}), 201
        return jsonify({"lista": core_db.empresas(admin_con), "actual": session.get("empresa_id"),
                        "totales": core_db.totales_plataforma(admin_con),
                        "series": core_db.series_plataforma(admin_con)})
    finally:
        admin_con.close()


@app.route("/api/empresas/<int:id_>/usuarios", methods=["GET", "POST"])
@superadmin_requerido
def api_empresa_usuarios(id_):
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        if not core_db.empresa(admin_con, id_):
            return jsonify({"error": "no existe"}), 404
        if request.method == "POST":
            datos = request.get_json(force=True) or {}
            usuario = (datos.get("usuario") or "").strip()[:64]
            password = datos.get("password") or ""
            rol = datos.get("rol") or "admin"
            if not usuario or rol not in core_db.ROLES_USUARIO:
                return jsonify({"error": "usuario o rol no válidos"}), 400
            if len(password) < config.LONGITUD_MINIMA_PASSWORD:
                return jsonify({"error": f"la contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
            if core_db.usuario_por_nombre(admin_con, usuario):
                return jsonify({"error": "ese nombre de usuario ya existe (es único en toda la plataforma)"}), 400
            uid = core_db.crear_usuario(admin_con, usuario, password, rol, datos.get("nombre") or None,
                                        datos.get("email") or None, empresa_id=id_)
            return jsonify({"ok": True, "id": uid}), 201
        return jsonify({"lista": core_db.usuarios(admin_con, id_), "roles": core_db.ROLES_USUARIO})
    finally:
        admin_con.close()


@app.route("/api/admin/usuarios/<int:id_>", methods=["PUT", "DELETE"])
@superadmin_requerido
def api_admin_usuario(id_):
    """Cuentas de cualquier empresa, desde el panel. La propia cuenta no se toca desde aquí."""
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        fila = admin_con.execute("SELECT * FROM usuarios WHERE id=?", (id_,)).fetchone()
        if not fila:
            return jsonify({"error": "no existe"}), 404
        if fila["usuario"] == session["usuario"]:
            return jsonify({"error": "tu propia cuenta se cambia desde Ajustes"}), 400
        if request.method == "DELETE":
            admin_con.execute("DELETE FROM usuarios WHERE id=?", (id_,))
            admin_con.commit()
            return jsonify({"ok": True})
        datos = request.get_json(force=True) or {}
        if "rol" in datos:
            if datos["rol"] not in core_db.ROLES_USUARIO and datos["rol"] != core_db.ROL_SUPERADMIN:
                return jsonify({"error": "rol no válido"}), 400
            admin_con.execute("UPDATE usuarios SET rol=? WHERE id=?", (datos["rol"], id_))
        if "activo" in datos:
            admin_con.execute("UPDATE usuarios SET activo=? WHERE id=?", (1 if datos["activo"] else 0, id_))
        for campo in ("nombre", "email"):
            if campo in datos:
                admin_con.execute(f"UPDATE usuarios SET {campo}=? WHERE id=?", (datos[campo] or None, id_))
        if datos.get("password"):
            if len(datos["password"]) < config.LONGITUD_MINIMA_PASSWORD:
                return jsonify({"error": f"la contraseña necesita al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"}), 400
            core_db.cambiar_password(admin_con, fila["usuario"], datos["password"])
        admin_con.commit()
        return jsonify({"ok": True})
    finally:
        admin_con.close()


@app.route("/api/admin/salir-empresa", methods=["POST"])
@superadmin_requerido
def api_admin_salir_empresa():
    """Vuelve al panel: la sesión deja de tener empresa activa."""
    _fijar_empresa_sesion(get_con(), None)
    return jsonify({"ok": True})


@app.route("/api/empresas/<int:id_>", methods=["PUT"])
@superadmin_requerido
def api_empresa(id_):
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        if not core_db.empresa(admin_con, id_):
            return jsonify({"error": "no existe"}), 404
        datos = request.get_json(force=True) or {}
        for campo in ("nombre", "nit", "contacto", "email", "telefono", "nota"):
            if campo in datos:
                admin_con.execute(f"UPDATE empresas SET {campo}=? WHERE id=?", (datos[campo] or None, id_))
        if "activa" in datos:
            admin_con.execute("UPDATE empresas SET activa=? WHERE id=?", (1 if datos["activa"] else 0, id_))
        admin_con.commit()
        return jsonify({"ok": True})
    finally:
        admin_con.close()


@app.route("/api/empresas/<int:id_>/entrar", methods=["POST"])
@superadmin_requerido
def api_empresa_entrar(id_):
    """El superadministrador cambia la empresa con la que trabaja (soporte, revisión)."""
    admin_con = core_db.conectar(core_db.TODAS)
    existe = core_db.empresa(admin_con, id_)
    admin_con.close()
    if not existe:
        return jsonify({"error": "no existe"}), 404
    _fijar_empresa_sesion(get_con(), id_)
    return jsonify({"ok": True, "empresa": existe["nombre"]})


# ---------- API: buscador de piezas del catálogo ----------

@app.route("/api/piezas/buscar")
@login_requerido
def api_piezas_buscar():
    """Autocompletado del catálogo. Desde 3 letras para no devolver el catálogo entero en cada
    pulsación; con menos se responde vacío y la interfaz sigue pidiendo texto."""
    equipo_id = request.args.get("equipo_id", type=int)
    texto = (request.args.get("q") or "").strip()
    limite = request.args.get("limite", default=25, type=int)
    if not equipo_id or len(texto) < 3:
        return jsonify([])
    return jsonify(core_db.buscar_piezas(get_con(), equipo_id, texto, limite))


@app.route("/api/piezas/conteo")
@login_requerido
def api_piezas_conteo():
    con = get_con()
    return jsonify(core_db.contar_piezas(con, _modelo_pedido(con)))


# ---------- API: bitácora de reparaciones ----------

@app.route("/api/bitacora")
@login_requerido
def api_bitacora():
    con = get_con()
    filas = core_db.bitacora(
        con,
        equipo_id=request.args.get("equipo_id", type=int),
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        motivo=request.args.get("motivo") or None,
        solo_piezas=request.args.get("solo_piezas") == "1",
    )
    return jsonify({"lista": filas,
                    "resumen": core_db.resumen_bitacora(con, request.args.get("equipo_id", type=int)),
                    "motivos": core_db.MOTIVOS})


# ---------- API: personal ----------

@app.route("/api/personal", methods=["GET", "POST"])
@login_requerido
def api_personal():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"error": "falta el nombre"}), 400
        # Los valores por defecto se ponen aquí y no en el esquema: al insertar la columna con
        # NULL explícito el DEFAULT de SQLite no se aplica, y los contactos nacían inactivos.
        POR_DEFECTO = {"rol": "tecnico", "activo": 1}
        campos = [c for c in core_db.CAMPOS_PERSONA if c != "nombre"]
        valores = []
        for campo in campos:
            v = datos.get(campo)
            if v in (None, ""):
                v = POR_DEFECTO.get(campo)
            valores.append(v)
        cur = con.execute(
            f"INSERT INTO personal(nombre, {', '.join(campos)}) "
            f"VALUES(?, {', '.join('?' * len(campos))})", (nombre, *valores))
        con.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201
    # `?rol=` filtra y `?operativos=1` deja sólo a quien se le puede asignar trabajo: es lo que
    # necesitan los desplegables de las órdenes.
    lista = core_db.contactos(con, request.args.get("rol") or None,
                              incluir_inactivos=request.args.get("inactivos") != "0")
    if request.args.get("operativos") == "1":
        lista = [c for c in lista if c["operativo"] and c["activo"]]
    return jsonify(lista)


@app.route("/api/personal/plantilla.xlsx")
@app.route("/api/personal/exportar.xlsx")
@login_requerido
def api_personal_excel():
    """Directorio completo en Excel, siempre con los contactos al día.

    Es el mismo archivo que se rellena, se vuelve a subir y se guarda en Drive.
    """
    con = get_con()
    libro = core_excel.libro_contactos(con)
    from datetime import date as _date
    nombre = f"Contactos {_date.today().isoformat()} - Hangar.xlsx"
    return send_file(libro, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/personal/importar", methods=["POST"])
@login_requerido
def api_personal_importar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "error": "No llegó ningún archivo."}), 400
    if not archivo.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"ok": False, "error": "El archivo debe ser .xlsx (el que descarga la app)."}), 400
    import io as _io
    contenido = _io.BytesIO(archivo.read())
    try:
        informe = core_excel.procesar_importacion_contactos(get_con(), contenido)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"No pude leer el archivo: {exc}"}), 400
    return jsonify(informe), (200 if informe.get("ok") else 400)


@app.route("/api/contactos")
@login_requerido
def api_contactos():
    con = get_con()
    return jsonify({"lista": core_db.contactos(con, request.args.get("rol") or None),
                    "resumen": core_db.resumen_contactos(con)})


@app.route("/api/personal/<int:id_>", methods=["GET", "PUT", "DELETE"])
@login_requerido
def api_persona(id_):
    con = get_con()
    if request.method == "DELETE":
        con.execute("DELETE FROM personal WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})
    if request.method == "GET":
        fila = con.execute("SELECT * FROM personal WHERE id=?", (id_,)).fetchone()
        if not fila:
            return jsonify({"error": "no existe"}), 404
        d = dict(fila)
        d["rol_txt"] = core_db.ROLES.get(d["rol"], d["rol"])
        # El trabajo de una persona se enlaza por su nombre, que es lo que guardan las órdenes.
        d["ordenes_trabajo"] = core_ordenes.listar_ot(con)
        d["ordenes_trabajo"] = [o for o in d["ordenes_trabajo"] if o["asignado_a"] == d["nombre"]][:20]
        d["ordenes_servicio"] = [o for o in core_ordenes.listar_os(con) if o["piloto"] == d["nombre"]][:20]
        return jsonify(d)
    datos = request.get_json(force=True) or {}
    campos, valores = [], []
    for campo in core_db.CAMPOS_PERSONA:
        if campo in datos:
            campos.append(f"{campo}=?")
            valores.append(datos[campo] if datos[campo] != "" else None)
    if campos:
        campos.append("actualizado=datetime('now')")
        valores.append(id_)
        con.execute(f"UPDATE personal SET {', '.join(campos)} WHERE id=?", valores)
        con.commit()
    return jsonify({"ok": True})


# ---------- API: órdenes de trabajo ----------

@app.route("/api/ot/sugerencias")
@login_requerido
def api_ot_sugerencias():
    equipo_id = request.args.get("equipo_id", type=int)
    horizonte = request.args.get("horizonte", default=60, type=int)
    if not equipo_id:
        return jsonify([])
    return jsonify(core_ordenes.tareas_sugeridas(get_con(), equipo_id, horizonte))


@app.route("/api/ot", methods=["GET", "POST"])
@login_requerido
def api_ot():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        if not datos.get("equipo_id"):
            return jsonify({"error": "falta el equipo"}), 400
        if not _equipo_valido(con, datos.get("equipo_id")):
            return jsonify({"error": "el equipo no existe"}), 404
        orden_id = core_ordenes.crear_ot(con, datos, session.get("usuario"))
        resultado = {"ok": True, "id": orden_id, "orden": core_ordenes.ot_completa(con, orden_id)}
        if datos.get("enviar"):
            resultado["correo"] = core_ordenes.enviar_ot(con, orden_id)
            resultado["orden"] = core_ordenes.ot_completa(con, orden_id)
        return jsonify(resultado), 201
    return jsonify(core_ordenes.listar_ot(con, request.args.get("estado") or None,
                                          request.args.get("equipo_id", type=int)))


@app.route("/api/ot/<int:id_>", methods=["GET", "PUT", "DELETE"])
@login_requerido
def api_ot_detalle(id_):
    con = get_con()
    if request.method == "DELETE":
        # Los repuestos que ya salieron de bodega con esta orden vuelven a la bodega.
        core_bodega.revertir_ot(con, id_, session.get("usuario"), "orden de trabajo borrada")
        con.execute("DELETE FROM ordenes_trabajo WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})
    if request.method == "PUT":
        datos = request.get_json(force=True) or {}
        previa = con.execute("SELECT o.estado, o.aprobado_por, e.tipo_activo FROM ordenes_trabajo o "
                             "JOIN equipos e ON e.id=o.equipo_id WHERE o.id=?", (id_,)).fetchone()
        nuevo = datos.get("estado")
        if nuevo and nuevo not in core_ordenes.ESTADOS_OT:
            return jsonify({"error": "estado no válido"}), 400
        # Aviación tripulada: el trabajo no empieza sin la aprobación del jefe técnico.
        if (previa and nuevo == "en_proceso" and previa["tipo_activo"] == "avion"
                and not previa["aprobado_por"]):
            return jsonify({"error": "una orden de avión necesita la aprobación del jefe técnico antes de empezar"}), 409
        # Diferir un trabajo exige plazo y motivo; pasado el plazo el activo no vuela.
        if nuevo == "diferida" and not (datos.get("diferida_hasta") and (datos.get("diferida_motivo") or "").strip()):
            return jsonify({"error": "para diferir el trabajo indica hasta cuándo y por qué"}), 400
        if previa and previa["estado"] == "completada" and datos.get("estado") not in (None, "completada"):
            core_bodega.revertir_ot(con, id_, session.get("usuario"), "orden de trabajo reabierta")
        campos, valores = [], []
        for campo in ("titulo", "tipo", "prioridad", "estado", "asignado_a", "asignado_email",
                      "fecha_programada", "hora_programada", "lugar", "observaciones", "equipo_id",
                      "diferida_hasta", "diferida_motivo", "taller_externo", "taller_certificado"):
            if campo in datos:
                campos.append(f"{campo}=?")
                valores.append(datos[campo] or None)
        if "horas_hombre" in datos:
            campos.append("horas_hombre=?")
            valores.append(core_flota._num(datos["horas_hombre"]))
        if campos:
            campos.append("actualizado=datetime('now')")
            valores.append(id_)
            con.execute(f"UPDATE ordenes_trabajo SET {', '.join(campos)} WHERE id=?", valores)
            con.commit()
    orden = core_ordenes.ot_completa(con, id_)
    return (jsonify(orden), 200) if orden else (jsonify({"error": "no existe"}), 404)


@app.route("/api/ot/<int:id_>/aprobar", methods=["POST"])
@login_requerido
def api_ot_aprobar(id_):
    """Aprobación del jefe técnico antes de empezar (lo pide la aviación tripulada)."""
    if session.get("rol") not in ("admin", core_db.ROL_SUPERADMIN, "certificador"):
        return jsonify({"error": "aprueba el jefe técnico: un administrador o un mecánico certificador"}), 403
    con = get_con()
    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("aprobado_por") or "").strip() or session.get("usuario")
    con.execute("UPDATE ordenes_trabajo SET aprobado_por=?, aprobado_en=datetime('now'), actualizado=datetime('now') "
                "WHERE id=?", (nombre, id_))
    con.commit()
    orden = core_ordenes.ot_completa(con, id_)
    return (jsonify(orden), 200) if orden else (jsonify({"error": "no existe"}), 404)


@app.route("/api/ot/<int:id_>/tareas", methods=["POST"])
@login_requerido
def api_ot_tareas(id_):
    con = get_con()
    datos = request.get_json(force=True) or {}
    descripcion = (datos.get("descripcion") or "").strip()
    if not descripcion:
        return jsonify({"error": "falta la descripción"}), 400
    n = con.execute("SELECT COALESCE(MAX(orden_n),0)+1 n FROM ot_tareas WHERE orden_id=?", (id_,)).fetchone()["n"]
    cur = con.execute(
        "INSERT INTO ot_tareas(orden_id, descripcion, origen, pieza_clave, componente_id, nivel, nota, "
        "                      motivo, codigo_pieza, nombre_pieza, orden_n, costo_repuesto, costo_mano_obra, "
        "                      horas_mano_obra) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (id_, descripcion, datos.get("origen") or "manual", datos.get("pieza_clave"),
         datos.get("componente_id"), datos.get("nivel"), datos.get("nota"), datos.get("motivo"),
         datos.get("codigo_pieza"), datos.get("nombre_pieza"), n, core_flota._num(datos.get("costo_repuesto")),
         core_flota._num(datos.get("costo_mano_obra")), core_flota._num(datos.get("horas_mano_obra"))))
    con.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@app.route("/api/ot/tareas/<int:id_>", methods=["PUT", "DELETE"])
@login_requerido
def api_ot_tarea(id_):
    con = get_con()
    if request.method == "DELETE":
        con.execute("DELETE FROM ot_tareas WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})
    datos = request.get_json(force=True) or {}
    campos, valores = [], []
    for campo in ("descripcion", "estado", "nota", "motivo"):
        if campo in datos:
            campos.append(f"{campo}=?")
            valores.append(datos[campo])
    for campo in ("costo_repuesto", "costo_mano_obra", "horas_mano_obra"):
        if campo in datos:
            campos.append(f"{campo}=?")
            valores.append(core_flota._num(datos[campo]))
    if campos:
        valores.append(id_)
        con.execute(f"UPDATE ot_tareas SET {', '.join(campos)} WHERE id=?", valores)
        con.commit()
    return jsonify({"ok": True})


@app.route("/api/ot/<int:id_>/enviar", methods=["POST"])
@login_requerido
def api_ot_enviar(id_):
    con = get_con()
    destino = (request.get_json(silent=True) or {}).get("destino")
    resultado = core_ordenes.enviar_ot(con, id_, destino)
    resultado["orden"] = core_ordenes.ot_completa(con, id_)
    return jsonify(resultado)


@app.route("/api/ot/<int:id_>/completar", methods=["POST"])
@login_requerido
def api_ot_completar(id_):
    con = get_con()
    datos = request.get_json(silent=True) or {}
    ot = core_ordenes.ot_completa(con, id_)
    if not ot:
        return jsonify({"error": "no existe"}), 404
    tipo = con.execute("SELECT tipo_activo FROM equipos WHERE id=?", (ot["equipo_id"],)).fetchone()["tipo_activo"]
    firmado_por = (datos.get("firmado_por") or "").strip() or None
    licencia = (datos.get("licencia") or "").strip() or None
    inspector = (datos.get("inspector") or "").strip() or None
    inspector_lic = (datos.get("inspector_licencia") or "").strip() or None
    # Inspección independiente (doble firma): la hace otra persona, con su licencia.
    if inspector and firmado_por and inspector.lower() == firmado_por.lower():
        return jsonify({"error": "la inspección independiente la firma una persona distinta de quien hizo el trabajo"}), 400
    if inspector and tipo == "avion" and not inspector_lic:
        return jsonify({"error": "la inspección independiente lleva la licencia del inspector"}), 400
    # Un avión sólo lo libera un mecánico certificador (o el administrador), con nombre y licencia.
    if tipo == "avion":
        if session.get("rol") not in ("admin", core_db.ROL_SUPERADMIN, "certificador"):
            return jsonify({"error": "una orden de avión la cierra un mecánico certificador"}), 403
        if not firmado_por or not licencia:
            return jsonify({"error": "para liberar un avión se requiere nombre y número de licencia de quien firma"}), 400
    r = core_ordenes.cerrar_ot_registrando_mantenimientos(
        con, id_, datos.get("realizado_por"), firmado_por, licencia, datos.get("fecha") or None,
        core_flota._num(core_db.meta_get(con, "costo_hora_mano_obra")), usuario=session.get("usuario"),
        inspector=inspector, inspector_licencia=inspector_lic, horas_hombre=core_flota._num(datos.get("horas_hombre")))
    r["orden"] = core_ordenes.ot_completa(con, id_)
    return jsonify(r)


# ---------- API: órdenes de servicio ----------

@app.route("/api/os", methods=["GET", "POST"])
@login_requerido
def api_os():
    con = get_con()
    if request.method == "POST":
        datos = request.get_json(force=True) or {}
        if datos.get("equipo_id") and not _equipo_valido(con, datos.get("equipo_id")):
            return jsonify({"error": "el equipo no existe"}), 404
        if datos.get("equipo_id") and not datos.get("forzar"):
            est = core_alertas.estado_flota(con).get(int(datos["equipo_id"]))
            if est and est["estado"] == "no_apto":
                return jsonify({"error": "no recomendamos volar este activo", "motivos": est["motivos"][:6],
                                "puede_forzar": _es_admin()}), 409
        if datos.get("forzar") and not _es_admin():
            return jsonify({"error": "sólo el administrador asigna un activo que no recomendamos volar"}), 403
        orden_id = core_ordenes.crear_os(con, datos, session.get("usuario"))
        resultado = {"ok": True, "id": orden_id}
        if datos.get("enviar"):
            resultado["correo"] = core_ordenes.enviar_os(con, orden_id, usuario=session.get("usuario"))
        resultado["orden"] = core_ordenes.os_completa(con, orden_id)
        return jsonify(resultado), 201
    return jsonify(core_ordenes.listar_os(con, request.args.get("estado") or None,
                                          request.args.get("equipo_id", type=int)))


@app.route("/api/os/<int:id_>", methods=["GET", "PUT", "DELETE"])
@login_requerido
def api_os_detalle(id_):
    con = get_con()
    if request.method == "DELETE":
        con.execute("DELETE FROM ordenes_servicio WHERE id=?", (id_,))
        con.commit()
        return jsonify({"ok": True})
    if request.method == "PUT":
        datos = request.get_json(force=True) or {}
        campos, valores = [], []
        for campo in ("piloto", "piloto_email", "cliente", "finca", "zona", "productos", "fecha",
                      "hora", "equipo_id", "hectareas", "dosis", "observaciones", "condiciones_tiempo",
                      "zonas_evitar", "mapa_url"):
            if campo in datos:
                campos.append(f"{campo}=?")
                valores.append(core_ordenes.url_mapa(datos[campo]) if campo == "mapa_url" else (datos[campo] or None))
        if campos:
            campos.append("actualizado=datetime('now')")
            valores.append(id_)
            con.execute(f"UPDATE ordenes_servicio SET {', '.join(campos)} WHERE id=?", valores)
            con.commit()
        # La lista de productos se guarda aparte y reescribe el resumen de texto de la orden.
        if "productos_lista" in datos:
            core_ordenes.guardar_productos_os(con, id_, datos["productos_lista"])
    orden = core_ordenes.os_completa(con, id_)
    return (jsonify(orden), 200) if orden else (jsonify({"error": "no existe"}), 404)


@app.route("/api/os/<int:id_>/estado", methods=["POST"])
@login_requerido
def api_os_estado(id_):
    datos = request.get_json(force=True) or {}
    estado = datos.get("estado")
    if estado not in core_ordenes.ESTADOS_OS:
        return jsonify({"error": "estado no válido"}), 400
    con = get_con()
    core_ordenes.registrar_evento_os(con, id_, estado, datos.get("nota"), session.get("usuario"))
    return jsonify({"ok": True, "orden": core_ordenes.os_completa(con, id_)})


@app.route("/api/os/<int:id_>/enviar", methods=["POST"])
@login_requerido
def api_os_enviar(id_):
    con = get_con()
    destino = (request.get_json(silent=True) or {}).get("destino")
    resultado = core_ordenes.enviar_os(con, id_, destino, session.get("usuario"))
    resultado["orden"] = core_ordenes.os_completa(con, id_)
    return jsonify(resultado)


# ---------- API: correo ----------

@app.route("/api/correo/config", methods=["GET", "PUT"])
@superadmin_requerido
def api_correo_config():
    con = get_con()
    if request.method == "PUT":
        core_correo.guardar_config(con, request.get_json(force=True) or {})
    return jsonify(core_correo.config_publica(con))


@app.route("/api/correo/probar", methods=["POST"])
@superadmin_requerido
def api_correo_probar():
    destino = (request.get_json(force=True) or {}).get("destino")
    if not destino:
        return jsonify({"ok": False, "motivo": "Indica un correo de destino."}), 400
    return jsonify(core_correo.probar(get_con(), destino))


@app.route("/api/correo/cola")
@superadmin_requerido
def api_correo_cola():
    filas = get_con().execute(
        "SELECT id, para, asunto, referencia, estado, error, intentos, creado, enviado "
        "FROM correo_cola ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(f) for f in filas])


@app.route("/api/correo/reintentar", methods=["POST"])
@superadmin_requerido
def api_correo_reintentar():
    return jsonify(core_correo.reintentar_pendientes(get_con()))



# ---------- Correo de cada empresa (panel del superadministrador) ----------
# El correo saliente, los usuarios y sus permisos los gestiona la plataforma, no la empresa
# cliente: desde el panel se abre cada empresa sin «entrar» en su operación.

def _con_empresa(id_):
    admin_con = core_db.conectar(core_db.TODAS)
    try:
        existe = core_db.empresa(admin_con, id_)
    finally:
        admin_con.close()
    if not existe:
        abort(404)
    return core_db.conectar(id_)


@app.route("/api/empresas/<int:id_>/correo", methods=["GET", "PUT"])
@superadmin_requerido
def api_empresa_correo(id_):
    con = _con_empresa(id_)
    try:
        if request.method == "PUT":
            core_correo.guardar_config(con, request.get_json(force=True) or {})
        return jsonify(core_correo.config_publica(con))
    finally:
        con.close()


@app.route("/api/empresas/<int:id_>/correo/probar", methods=["POST"])
@superadmin_requerido
def api_empresa_correo_probar(id_):
    destino = (request.get_json(force=True) or {}).get("destino")
    if not destino:
        return jsonify({"ok": False, "motivo": "Indica un correo de destino."}), 400
    con = _con_empresa(id_)
    try:
        return jsonify(core_correo.probar(con, destino))
    finally:
        con.close()


@app.route("/api/empresas/<int:id_>/correo/cola")
@superadmin_requerido
def api_empresa_correo_cola(id_):
    con = _con_empresa(id_)
    try:
        return jsonify([dict(f) for f in con.execute(
            "SELECT id, para, asunto, referencia, estado, error, intentos, creado, enviado "
            "FROM correo_cola ORDER BY id DESC LIMIT 100").fetchall()])
    finally:
        con.close()


@app.route("/api/empresas/<int:id_>/correo/reintentar", methods=["POST"])
@superadmin_requerido
def api_empresa_correo_reintentar(id_):
    con = _con_empresa(id_)
    try:
        return jsonify(core_correo.reintentar_pendientes(con))
    finally:
        con.close()


# ---------- API: detalle de una gráfica (clic en una barra, sector o fila) ----------

# Cada dimensión dice con qué expresión SQL se agrupa y cómo se compara el valor pinchado.
DIMENSIONES_REPORTE = {
    "equipo":   ("e.nombre",                        "Equipo"),
    "producto": ("COALESCE(o.producto,'Sin especificar')", "Producto"),
    "piloto":   ("COALESCE(o.piloto,'Sin piloto')", "Piloto"),
    "cliente":  ("COALESCE(o.cliente,'Sin cliente')", "Cliente"),
    "zona":     ("COALESCE(o.zona,'Sin zona')",     "Zona"),
    "finca":    ("COALESCE(o.lote,'Sin finca')",    "Finca"),
    "mes":      ("substr(o.fecha,1,7)",             "Mes"),
    "dia":      ("o.fecha",                         "Día"),
}


@app.route("/api/reportes/detalle")
@login_requerido
def api_reportes_detalle():
    con = get_con()
    dim = request.args.get("dim")
    valor = request.args.get("valor")
    if dim not in DIMENSIONES_REPORTE:
        return jsonify({"error": "dimensión no válida"}), 400

    expr, etiqueta = DIMENSIONES_REPORTE[dim]
    equipo_id = request.args.get("equipo_id", type=int)
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None

    cond, params = [f"{expr} = ?"], [valor]
    if equipo_id:
        cond.append("o.equipo_id=?"); params.append(equipo_id)
    if desde:
        cond.append("o.fecha>=?"); params.append(desde)
    if hasta:
        cond.append("o.fecha<=?"); params.append(hasta)
    where = " AND ".join(cond)
    base = f"FROM operaciones o JOIN equipos e ON e.id=o.equipo_id WHERE {where}"

    def q(sql, extra=()):
        return [dict(f) for f in con.execute(sql, (*params, *extra)).fetchall()]

    totales = q(f"""SELECT COUNT(*) n, ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas,
                    ROUND(COALESCE(SUM(o.tiempo_total),0),1) tiempo_total,
                    ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas,
                    ROUND(COALESCE(SUM(o.litros),0),0) litros,
                    COALESCE(SUM(COALESCE(o.despegues, o.aterrizajes)),0) despegues,
                    MIN(o.fecha) primera, MAX(o.fecha) ultima,
                    COUNT(DISTINCT o.fecha) dias, COUNT(DISTINCT o.equipo_id) equipos
                    {base}""")[0]

    def desglose(campo, alias, limite=8):
        return q(f"""SELECT {campo} {alias}, COUNT(*) n, ROUND(SUM(o.horas_vuelo),1) horas,
                     ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas,
                     ROUND(COALESCE(SUM(o.litros),0),0) litros
                     {base} GROUP BY {alias} ORDER BY horas DESC LIMIT {limite}""")

    operaciones = q(f"""SELECT o.id, o.fecha, e.nombre equipo, o.horas_vuelo, o.tiempo_total, COALESCE(o.despegues, o.aterrizajes) despegues,
                        o.hectareas, o.litros, o.producto, o.piloto, o.cliente, o.zona, o.lote, o.nota
                        {base} ORDER BY o.fecha DESC, o.id DESC LIMIT 300""")

    return jsonify({
        "dimension": dim, "etiqueta": etiqueta, "valor": valor,
        "totales": totales,
        "por_mes": q(f"""SELECT substr(o.fecha,1,7) mes, COUNT(*) n, ROUND(SUM(o.horas_vuelo),1) horas,
                         ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas, ROUND(COALESCE(SUM(o.litros),0),0) litros
                         {base} GROUP BY mes ORDER BY mes"""),
        "por_equipo":   desglose("e.nombre", "equipo"),
        "por_producto": desglose("COALESCE(o.producto,'Sin especificar')", "producto"),
        "por_piloto":   desglose("COALESCE(o.piloto,'Sin piloto')", "piloto"),
        "por_cliente":  desglose("COALESCE(o.cliente,'Sin cliente')", "cliente"),
        "por_finca":    desglose("COALESCE(o.lote,'Sin finca')", "finca"),
        "operaciones": operaciones,
    })


@app.route("/api/reportes/piezas")
@login_requerido
def api_reportes_piezas():
    """Detalle del sector de «estado de la flota»: qué piezas están en ese nivel de desgaste."""
    con = get_con()
    nivel = request.args.get("nivel")
    equipo_id = request.args.get("equipo_id", type=int)
    comps = [c for c in core_alertas.componentes_con_estado(con, equipo_id) if c["equipo_estado"] != "baja"]
    if nivel:
        comps = [c for c in comps if c["nivel"] == nivel]
    proy = {(p["equipo_id"], p["clave"]): p for p in core_proyeccion.proximos_repuestos(con, equipo_id, limite=10 ** 6)}
    for c in comps:
        p = proy.get((c["equipo_id"], c["clave"]))
        c["dias_estimados"] = p["dias_estimados"] if p else None
        c["fecha_estimada"] = p["fecha_estimada"] if p else None
    comps.sort(key=lambda c: -c["pct"])
    return jsonify({"nivel": nivel, "piezas": comps[:200], "total": len(comps)})


# En local (flask run --reload) el código se actualiza sin volver a correr `manage.py init`:
# se aplica aquí el esquema pendiente para que una columna o tabla nueva no deje la app en error 500.
# En el servidor lo hace entrypoint.sh antes de arrancar Gunicorn.
if config.ENTORNO == "desarrollo" and not app.config.get("TESTING"):
    try:
        core_db.inicializar()
    except Exception as e:  # sin base disponible la app arranca igual y lo avisa en el log
        app.logger.warning("No pude actualizar el esquema al arrancar: %s", e)


# ---------- Flota mixta (drones y aviones) ----------
import web_flota  # noqa: E402
web_flota.registrar(app, get_con, login_requerido, admin_requerido)
import web_combustible  # noqa: E402
web_combustible.registrar(app, get_con, login_requerido, admin_requerido)
# web_bodega: se registra aquí debajo
import web_bodega  # noqa: E402
web_bodega.registrar(app, get_con, login_requerido, admin_requerido)
# web_informes: se registra aquí debajo
import web_informes  # noqa: E402
web_informes.registrar(app, get_con, login_requerido, admin_requerido)


if __name__ == "__main__":
    # Sólo para desarrollo local. En el servidor arranca Gunicorn (ver Dockerfile).
    core_db.inicializar()
    app.run(host=config.HOST, port=config.PUERTO, debug=config.DEPURAR, use_reloader=config.DEPURAR)
