"""Pruebas de humo y de seguridad de Hangar contra una base PostgreSQL real.

    DATABASE_URL=postgresql://hangar:hangar@localhost:5432/hangar_pruebas python -m pytest pruebas -q

Cubre: acceso, CSRF, permisos por rol, cabeceras de seguridad, límite de intentos de login,
todas las pantallas y los endpoints principales de la API con los datos migrados.
"""
import os
import re
import sys
from pathlib import Path

import pytest

from core import conexion as core_conexion

# Multi-empresa y RLS sólo existen en el servidor (PostgreSQL); el escritorio es de una sola empresa.
SOLO_SERVIDOR = pytest.mark.skipif(core_conexion.ES_SQLITE, reason="multi-empresa/RLS: sólo servidor")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("HANGAR_ENTORNO", "desarrollo")
os.environ.setdefault("COOKIE_SEGURA", "0")

import app as modulo_app  # noqa: E402
from core import db as core_db  # noqa: E402

PAGINAS = ["/", "/inventario", "/operaciones", "/mantenimiento", "/actividades", "/reportes",
           "/despiece", "/vista3d", "/ordenes-trabajo", "/ordenes-servicio", "/contactos",
           "/bitacora", "/ajustes"]
APIS = ["/api/modelos", "/api/equipos", "/api/componentes", "/api/catalogo", "/api/operaciones",
        "/api/mantenimientos", "/api/alertas", "/api/resumen", "/api/reportes", "/api/registros",
        "/api/repuestos", "/api/bitacora", "/api/personal", "/api/contactos", "/api/ot", "/api/os",
        "/api/piezas/conteo", "/api/diagramas?modelo=T50",
        "/api/reportes/detalle?dim=piloto&valor=MANUEL%20ALVAREZ", "/api/reportes/piezas?nivel=ok",
        "/api/ot/sugerencias?equipo_id=1", "/api/piezas/buscar?equipo_id=1&q=helice",
        "/api/operaciones/exportar.xlsx", "/api/personal/exportar.xlsx", "/api/cuenta/tema"]

# Correo, usuarios y permisos se gestionan desde el panel de la plataforma, no desde la empresa.
SOLO_PLATAFORMA = ["/api/correo/cola", "/api/correo/config", "/api/usuarios"]


EMPRESA_A = EMPRESA_B = None


@pytest.fixture(scope="session")
def cliente():
    global EMPRESA_A, EMPRESA_B
    modulo_app.app.config["TESTING"] = True
    core_db.inicializar()
    con = core_db.conectar(core_db.TODAS)
    con.execute("DELETE FROM usuarios WHERE usuario IN ('prueba_admin','prueba_tecnico','prueba_piloto','bruto',"
                "'prueba_super','admin_b','nuevo_u')")
    con.execute("DELETE FROM login_intentos")
    con.commit()
    # Empresa A: la que ya tiene los datos migrados (la primera). Empresa B: otra, para el aislamiento.
    EMPRESA_A = con.execute("SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()["id"]
    b = con.execute("SELECT id FROM empresas WHERE nombre='Empresa B (pruebas)'").fetchone()
    EMPRESA_B = b["id"] if b else core_db.crear_empresa(con, "Empresa B (pruebas)")
    core_db.crear_usuario(con, "prueba_super", "clave-segura-0", core_db.ROL_SUPERADMIN, empresa_id=EMPRESA_A)
    core_db.crear_usuario(con, "prueba_admin", "clave-segura-1", "admin", empresa_id=EMPRESA_A)
    core_db.crear_usuario(con, "prueba_tecnico", "clave-segura-2", "tecnico", empresa_id=EMPRESA_A)
    core_db.crear_usuario(con, "prueba_piloto", "clave-segura-3", "piloto", empresa_id=EMPRESA_A)
    core_db.crear_usuario(con, "admin_b", "clave-segura-4", "admin", empresa_id=EMPRESA_B)
    con.close()
    # La empresa B arranca con un dron propio y una operación.
    cb = core_db.conectar(EMPRESA_B)
    if not cb.execute("SELECT 1 FROM equipos").fetchone():
        eid = core_db.crear_equipo(cb, "DRON-B", "T50", "SNB")
        core_db.registrar_operacion(cb, eid, 3.0, piloto="Piloto B")
    cb.close()
    return modulo_app.app.test_client()


def _token(c):
    html = c.get("/login").data.decode()
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def entrar(c, usuario, clave):
    c.get("/salir")
    tok = _token(c)
    r = c.post("/login", data={"usuario": usuario, "password": clave, "csrf_token": tok})
    assert r.status_code == 302, r.data[:300]
    html = c.get("/").data.decode()
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


# ---------- acceso ----------

def test_sin_sesion_redirige(cliente):
    cliente.get("/salir")
    assert cliente.get("/").status_code == 302
    assert cliente.get("/api/equipos").status_code == 401


def test_login_incorrecto(cliente):
    cliente.get("/salir")
    r = cliente.post("/login", data={"usuario": "prueba_admin", "password": "mala", "csrf_token": _token(cliente)})
    assert r.status_code == 401


def test_bloqueo_por_intentos(cliente):
    cliente.get("/salir")
    for _ in range(9):
        r = cliente.post("/login", data={"usuario": "bruto", "password": "x", "csrf_token": _token(cliente)})
    assert r.status_code == 429
    con = core_db.conectar(core_db.TODAS); con.execute("DELETE FROM login_intentos"); con.commit(); con.close()


def test_login_correcto_y_cookie(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.get("/")
    assert r.status_code == 200
    # La cookie de sesión lleva HttpOnly y SameSite.
    cliente.get("/salir")
    r = cliente.post("/login", data={"usuario": "prueba_admin", "password": "clave-segura-1", "csrf_token": _token(cliente)})
    galleta = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in galleta and "SameSite=Lax" in galleta


# ---------- CSRF ----------

def test_csrf_sin_token_rechaza(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.post("/api/registros", json={"titulo": "x"})
    assert r.status_code == 403
    r = cliente.delete("/api/equipos/1")
    assert r.status_code == 403


def test_csrf_origen_ajeno_rechaza(cliente):
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.post("/api/registros", json={"titulo": "x"},
                     headers={"X-CSRF-Token": tok, "Origin": "https://malo.example"})
    assert r.status_code == 403


def test_csrf_con_token_acepta(cliente):
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.post("/api/registros", json={"titulo": "Prueba CSRF"}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 201


# ---------- cabeceras ----------

def test_cabeceras_seguridad(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.get("/")
    h = r.headers
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert cliente.get("/api/equipos").headers["Cache-Control"] == "no-store"


# ---------- pantallas y API con datos migrados ----------

@pytest.mark.parametrize("ruta", PAGINAS)
def test_pantallas(cliente, ruta):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    assert cliente.get(ruta).status_code == 200


@pytest.mark.parametrize("ruta", APIS)
def test_apis_admin(cliente, ruta):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.get(ruta)
    assert r.status_code == 200, r.data[:300]


def test_datos_migrados(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    equipos = cliente.get("/api/equipos").get_json()
    assert {e["nombre"] for e in equipos} >= {"SMR 1", "SMR 2", "SMR 4", "SMR 5"}
    r = cliente.get("/api/resumen").get_json()
    assert r["totales"]["operaciones"] >= 1038
    rep = cliente.get("/api/reportes").get_json()
    assert rep["por_dia_semana"] and rep["por_mes"] and rep["repuestos"]
    assert cliente.get("/api/repuestos").get_json()["ritmo"]


def test_flujo_operacion(cliente):
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    h = {"X-CSRF-Token": tok}
    antes = cliente.get("/api/equipos/1").get_json()["horas_totales"]
    r = cliente.post("/api/operaciones", json={"equipo_id": 1, "horas_vuelo": 1.5, "piloto": "Prueba <b>x</b>",
                                               "fecha": "2026-09-08"}, headers=h)
    assert r.status_code == 201
    despues = cliente.get("/api/equipos/1").get_json()["horas_totales"]
    assert round(despues - antes, 1) == 1.5
    op = cliente.get("/api/operaciones?equipo_id=1&limite=1").get_json()[0]
    r = cliente.put(f"/api/operaciones/{op['id']}", json={"horas_vuelo": "2,5"}, headers=h)
    assert r.status_code == 200 and r.get_json()["horas_equipo"] == round(antes + 2.5, 1)
    r = cliente.delete(f"/api/operaciones/{op['id']}", headers=h)
    assert r.status_code == 200
    assert round(cliente.get("/api/equipos/1").get_json()["horas_totales"], 1) == round(antes, 1)


def test_flujo_orden_trabajo(cliente):
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    h = {"X-CSRF-Token": tok}
    r = cliente.post("/api/ot", json={"equipo_id": 1, "titulo": "OT de prueba", "asignado_a": "Técnico"}, headers=h)
    assert r.status_code == 201
    oid = r.get_json()["id"]
    r = cliente.post(f"/api/ot/{oid}/tareas", json={"descripcion": "Revisar hélices"}, headers=h)
    assert r.status_code == 201
    assert cliente.get(f"/api/ot/{oid}").status_code == 200
    assert cliente.get(f"/imprimir/orden-trabajo/{oid}").status_code == 200
    r = cliente.post(f"/api/ot/{oid}/enviar", json={"destino": "prueba@example.com"}, headers=h)
    assert r.status_code == 200 and r.get_json()["estado"] in ("pendiente", "error")
    assert cliente.delete(f"/api/ot/{oid}", headers=h).status_code == 200


def test_flujo_orden_servicio(cliente):
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    h = {"X-CSRF-Token": tok}
    r = cliente.post("/api/os", json={"piloto": "Piloto P", "cliente": "Cliente C", "finca": "F", "equipo_id": 1,
                                      "fecha": "2026-09-10", "productos_lista": [{"nombre": "Opus", "dosis": "1 L/ha"}]}, headers=h)
    assert r.status_code == 201
    oid = r.get_json()["id"]
    r = cliente.post(f"/api/os/{oid}/estado", json={"estado": "en_ruta"}, headers=h)
    assert r.status_code == 200 and r.get_json()["orden"]["estado"] == "en_ruta"
    assert cliente.get(f"/imprimir/orden-servicio/{oid}").status_code == 200
    assert cliente.delete(f"/api/os/{oid}", headers=h).status_code == 200


def test_importar_excel_ida_y_vuelta(cliente):
    import io
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    xlsx = cliente.get("/api/operaciones/exportar.xlsx").data
    r = cliente.post("/api/operaciones/importar", data={"archivo": (io.BytesIO(xlsx), "ops.xlsx")},
                     headers={"X-CSRF-Token": tok}, content_type="multipart/form-data")
    assert r.status_code == 200, r.data[:400]
    assert r.get_json()["ok"]


# ---------- roles ----------

def test_piloto_no_borra_ni_administra(cliente):
    tok = entrar(cliente, "prueba_piloto", "clave-segura-3")
    h = {"X-CSRF-Token": tok}
    assert cliente.get("/api/equipos").status_code == 200          # leer sí
    assert cliente.delete("/api/equipos/1", headers=h).status_code == 403
    assert cliente.post("/api/ot", json={"equipo_id": 1, "titulo": "x"}, headers=h).status_code == 403
    assert cliente.get("/api/usuarios").status_code == 403
    assert cliente.put("/api/correo/config", json={"servidor": "x"}, headers=h).status_code == 403
    assert cliente.post("/api/operaciones", json={"equipo_id": 1, "horas_vuelo": 0.1}, headers=h).status_code == 201
    op = cliente.get("/api/operaciones?equipo_id=1&limite=1").get_json()[0]
    assert cliente.delete(f"/api/operaciones/{op['id']}", headers=h).status_code == 403
    # el admin limpia la operación de prueba
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    assert cliente.delete(f"/api/operaciones/{op['id']}", headers={"X-CSRF-Token": tok}).status_code == 200


def test_tecnico_gestiona_mantenimiento_pero_no_usuarios(cliente):
    tok = entrar(cliente, "prueba_tecnico", "clave-segura-2")
    h = {"X-CSRF-Token": tok}
    r = cliente.post("/api/mantenimientos", json={"equipo_id": 1, "tipo": "inspeccion", "descripcion": "prueba"}, headers=h)
    assert r.status_code == 201
    assert cliente.post("/api/usuarios", json={"usuario": "x", "password": "12345678"}, headers=h).status_code == 403
    assert cliente.delete("/api/equipos/1", headers=h).status_code == 403
    m = cliente.get("/api/mantenimientos?equipo_id=1").get_json()[0]
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    assert cliente.delete(f"/api/mantenimientos/{m['id']}", headers={"X-CSRF-Token": tok}).status_code == 200


def test_gestion_usuarios_y_password(cliente):
    # El administrador de la empresa ya no gestiona usuarios ni correo: lo hace la plataforma.
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    h = {"X-CSRF-Token": tok}
    for ruta in SOLO_PLATAFORMA:
        assert cliente.get(ruta).status_code == 403, ruta
    assert cliente.post("/api/usuarios", json={"usuario": "nuevo_u", "password": "clave-larga-9", "rol": "piloto"}, headers=h).status_code == 403
    assert "Usuarios de la app" not in cliente.get("/ajustes").data.decode()
    # cambio de contraseña propio sigue en Ajustes
    r = cliente.post("/api/cuenta/password", json={"actual": "mala", "nueva": "otra-clave-99"}, headers=h)
    assert r.status_code == 400
    # desde el panel: crear (incluido mecánico certificador), desactivar y borrar
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    h = {"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', cliente.get("/admin").data.decode()).group(1)}
    base = f"/api/empresas/{EMPRESA_A}/usuarios"
    assert cliente.post(base, json={"usuario": "nuevo_u", "password": "corta", "rol": "piloto"}, headers=h).status_code == 400
    r = cliente.post(base, json={"usuario": "nuevo_u", "password": "clave-larga-9", "rol": "certificador"}, headers=h)
    assert r.status_code == 201
    uid = r.get_json()["id"]
    assert cliente.get(base).get_json()["roles"]["certificador"] == "Mecánico certificador"
    assert cliente.put(f"/api/admin/usuarios/{uid}", json={"activo": 0}, headers=h).status_code == 200
    cliente.get("/salir")
    r = cliente.post("/login", data={"usuario": "nuevo_u", "password": "clave-larga-9", "csrf_token": _token(cliente)})
    assert r.status_code == 401   # inactivo no entra
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    h = {"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', cliente.get("/admin").data.decode()).group(1)}
    assert cliente.delete(f"/api/admin/usuarios/{uid}", headers=h).status_code == 200


@SOLO_SERVIDOR
def test_correo_por_empresa_desde_el_panel(cliente):
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    h = {"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', cliente.get("/admin").data.decode()).group(1)}
    r = cliente.put(f"/api/empresas/{EMPRESA_B}/correo", json={"servidor": "smtp.b.test", "remitente": "b@b.test",
                                                               "password": "secreta"}, headers=h)
    assert r.status_code == 200 and r.get_json()["password"] == "" and r.get_json()["tiene_password"]
    assert cliente.get(f"/api/empresas/{EMPRESA_B}/correo").get_json()["servidor"] == "smtp.b.test"
    # la de A no cambia
    assert cliente.get(f"/api/empresas/{EMPRESA_A}/correo").get_json().get("servidor") != "smtp.b.test"
    assert cliente.get(f"/api/empresas/{EMPRESA_B}/correo/cola").status_code == 200
    assert cliente.get("/api/empresas/999999/correo").status_code == 404


def test_tema_claro_oscuro_por_usuario(cliente):
    tok = entrar(cliente, "prueba_piloto", "clave-segura-3")
    h = {"X-CSRF-Token": tok}
    assert cliente.put("/api/cuenta/tema", json={"tema": "rosado"}, headers=h).status_code == 400
    assert cliente.put("/api/cuenta/tema", json={"tema": "oscuro"}, headers=h).get_json()["tema"] == "oscuro"
    assert 'data-tema="oscuro"' in cliente.get("/").data.decode()
    # se conserva al volver a entrar
    entrar(cliente, "prueba_piloto", "clave-segura-3")
    assert 'data-tema="oscuro"' in cliente.get("/").data.decode()
    cliente.put("/api/cuenta/tema", json={"tema": "sistema"}, headers=h)


# ---------- inyección ----------

def test_inyeccion_sql_en_filtros(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    for ruta in ["/api/reportes?desde=2025-01-01'%20OR%201=1--", "/api/reportes/detalle?dim=piloto&valor='%3B%20DROP%20TABLE%20equipos%3B--",
                 "/api/reportes/detalle?dim=fecha;drop&valor=x", "/api/piezas/buscar?equipo_id=1&q='%3B--",
                 "/api/bitacora?motivo='%20OR%201=1--"]:
        r = cliente.get(ruta)
        assert r.status_code in (200, 400), ruta
    assert cliente.get("/api/equipos").status_code == 200   # la tabla sigue ahí


# ---------- multi-empresa: aislamiento ----------

def _ids_equipos(c):
    return {e["id"] for e in c.get("/api/equipos").get_json()}


@SOLO_SERVIDOR
def test_cada_empresa_ve_solo_sus_drones(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    de_a = _ids_equipos(cliente)
    nombres_a = {e["nombre"] for e in cliente.get("/api/equipos").get_json()}
    entrar(cliente, "admin_b", "clave-segura-4")
    de_b = _ids_equipos(cliente)
    nombres_b = {e["nombre"] for e in cliente.get("/api/equipos").get_json()}
    assert de_a and de_b and not (de_a & de_b)
    assert "DRON-B" in nombres_b and "DRON-B" not in nombres_a
    assert "SMR 1" in nombres_a and "SMR 1" not in nombres_b
    # Resumen, operaciones, alertas y reportes de B no incluyen nada de A.
    r = cliente.get("/api/resumen").get_json()
    assert r["totales"]["operaciones"] == 1
    assert all(o["equipo"] == "DRON-B" for o in cliente.get("/api/operaciones").get_json())
    assert cliente.get("/api/reportes").get_json()["totales"]["n"] == 1
    assert all(c["equipo"] == "DRON-B" for c in cliente.get("/api/componentes").get_json())


@SOLO_SERVIDOR
def test_no_se_accede_por_id_a_otra_empresa(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    equipo_a = min(_ids_equipos(cliente))
    op_a = cliente.get("/api/operaciones?limite=1").get_json()[0]["id"]
    tok = entrar(cliente, "admin_b", "clave-segura-4")
    h = {"X-CSRF-Token": tok}
    assert cliente.get(f"/api/equipos/{equipo_a}").status_code == 404
    assert cliente.put(f"/api/equipos/{equipo_a}", json={"nombre": "hackeado"}, headers=h).status_code == 404
    assert cliente.delete(f"/api/equipos/{equipo_a}", headers=h).status_code == 404
    assert cliente.put(f"/api/operaciones/{op_a}", json={"nota": "x"}, headers=h).status_code == 404
    assert cliente.delete(f"/api/operaciones/{op_a}", headers=h).status_code == 404
    assert cliente.get(f"/api/componentes?equipo_id={equipo_a}").get_json() == []
    assert cliente.get(f"/api/operaciones?equipo_id={equipo_a}").get_json() == []
    # Tampoco se puede crear algo de B que apunte a un dron de A (lo rechaza la propia base).
    r = cliente.post("/api/operaciones", json={"equipo_id": equipo_a, "horas_vuelo": 1}, headers=h)
    assert r.status_code == 404
    r = cliente.post("/api/ot", json={"equipo_id": equipo_a, "titulo": "x"}, headers=h)
    assert r.status_code == 404
    # Y si algo saltara la validación de la app, la base lo rechaza (clave foránea compuesta).
    cb = core_db.conectar(EMPRESA_B)
    with pytest.raises(Exception):
        cb.execute("INSERT INTO operaciones(equipo_id, horas_vuelo) VALUES(?, 1)", (equipo_a,))
    cb.close()
    # El dron de A sigue intacto.
    entrar(cliente, "prueba_admin", "clave-segura-1")
    assert cliente.get(f"/api/equipos/{equipo_a}").get_json()["nombre"] != "hackeado"


@SOLO_SERVIDOR
def test_usuarios_y_contactos_por_empresa(cliente):
    # Las cuentas de cada empresa, vistas desde el panel, no se mezclan.
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    usuarios_b = {u["usuario"] for u in cliente.get(f"/api/empresas/{EMPRESA_B}/usuarios").get_json()["lista"]}
    assert "admin_b" in usuarios_b and "prueba_admin" not in usuarios_b
    id_a = [u["id"] for u in cliente.get(f"/api/empresas/{EMPRESA_A}/usuarios").get_json()["lista"]
            if u["usuario"] == "prueba_tecnico"][0]
    tok = entrar(cliente, "admin_b", "clave-segura-4")
    h = {"X-CSRF-Token": tok}
    cb = core_db.conectar(EMPRESA_B); cb.execute("DELETE FROM personal"); cb.commit(); cb.close()
    assert cliente.get("/api/personal").get_json() == []
    assert cliente.post("/api/personal", json={"nombre": "Contacto B"}, headers=h).status_code == 201
    # el admin de B no puede tocar cuentas (ni de A ni propias) ni gestionar empresas
    entrar(cliente, "prueba_admin", "clave-segura-1")
    assert "Contacto B" not in {p["nombre"] for p in cliente.get("/api/personal").get_json()}
    tok = entrar(cliente, "admin_b", "clave-segura-4")
    assert cliente.put(f"/api/usuarios/{id_a}", json={"activo": 0}, headers={"X-CSRF-Token": tok}).status_code == 403
    assert cliente.put(f"/api/admin/usuarios/{id_a}", json={"activo": 0}, headers={"X-CSRF-Token": tok}).status_code == 403
    assert cliente.get("/api/empresas").status_code == 403
    assert cliente.post("/api/empresas", json={"nombre": "X"}, headers={"X-CSRF-Token": tok}).status_code == 403


@SOLO_SERVIDOR
def test_codigos_de_orden_por_empresa(cliente):
    tok = entrar(cliente, "admin_b", "clave-segura-4")
    eq_b = min(_ids_equipos(cliente))
    r = cliente.post("/api/ot", json={"equipo_id": eq_b, "titulo": "OT B"}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 201
    ot_b = r.get_json()["orden"]
    assert ot_b["codigo"].startswith("OT-")          # numeración propia de B, empieza en 001
    tok = entrar(cliente, "prueba_admin", "clave-segura-1")
    ids_a = {o["id"] for o in cliente.get("/api/ot").get_json()}
    assert ot_b["id"] not in ids_a                     # la OT de B no aparece en A
    assert cliente.get(f"/api/ot/{ot_b['id']}").status_code == 404


@SOLO_SERVIDOR
def test_superadmin_gestiona_empresas_y_cambia(cliente):
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    tok = re.search(r'name="csrf-token" content="([^"]+)"', cliente.get("/admin").data.decode()).group(1)
    h = {"X-CSRF-Token": tok}
    lista = cliente.get("/api/empresas").get_json()
    assert {e["id"] for e in lista["lista"]} >= {EMPRESA_A, EMPRESA_B} and lista["actual"] is None
    r = cliente.post("/api/empresas", json={"nombre": "Empresa C", "admin_usuario": "admin_c_tmp", "admin_password": "clave-larga-9"}, headers=h)
    assert r.status_code == 201
    cid = r.get_json()["id"]
    # entra a B y ve lo de B
    assert cliente.post(f"/api/empresas/{EMPRESA_B}/entrar", json={}, headers=h).status_code == 200
    assert {e["nombre"] for e in cliente.get("/api/equipos").get_json()} == {"DRON-B"}
    # desactiva C: su admin ya no puede entrar
    assert cliente.put(f"/api/empresas/{cid}", json={"activa": 0}, headers=h).status_code == 200
    cliente.get("/salir")
    r = cliente.post("/login", data={"usuario": "admin_c_tmp", "password": "clave-larga-9", "csrf_token": _token(cliente)})
    assert r.status_code == 403
    con = core_db.conectar(core_db.TODAS); con.execute("DELETE FROM empresas WHERE id=?", (cid,)); con.commit(); con.close()


@SOLO_SERVIDOR
def test_rls_en_la_base_sin_empresa_no_devuelve_nada():
    con = core_db.conectar(None)
    assert con.execute("SELECT COUNT(*) n FROM operaciones").fetchone()["n"] == 0
    with pytest.raises(Exception):
        con.execute("INSERT INTO registros(titulo) VALUES('x')")
    con.close()


# ---------- panel del superadministrador ----------

def test_superadmin_entra_al_panel_y_no_a_la_operacion(cliente):
    cliente.get("/salir")
    r = cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
    assert cliente.get("/admin").status_code == 200
    # sin empresa elegida, las pantallas operativas lo devuelven al panel y la API lo avisa
    r = cliente.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
    assert cliente.get("/api/equipos").status_code == 409
    # un admin normal no puede ver el panel
    entrar(cliente, "prueba_admin", "clave-segura-1")
    assert cliente.get("/admin").status_code == 403


def test_panel_gestiona_empresas_y_usuarios(cliente):
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0", "csrf_token": _token(cliente)})
    tok = re.search(r'name="csrf-token" content="([^"]+)"', cliente.get("/admin").data.decode()).group(1)
    h = {"X-CSRF-Token": tok}
    r = cliente.get("/api/empresas").get_json()
    assert r["totales"]["empresas"] >= 2 and all("n_operaciones" in e for e in r["lista"])
    # crear empresa con su admin, y un usuario más desde el panel
    r = cliente.post("/api/empresas", json={"nombre": "Cliente Panel", "nit": "900.1", "contacto": "Ana",
                                            "admin_usuario": "ana_panel", "admin_password": "clave-larga-9"}, headers=h)
    assert r.status_code == 201
    cid = r.get_json()["id"]
    r = cliente.post(f"/api/empresas/{cid}/usuarios", json={"usuario": "piloto_panel", "password": "clave-larga-9", "rol": "piloto"}, headers=h)
    assert r.status_code == 201
    uid = r.get_json()["id"]
    lista = cliente.get(f"/api/empresas/{cid}/usuarios").get_json()["lista"]
    assert {u["usuario"] for u in lista} == {"ana_panel", "piloto_panel"}
    # el nombre de usuario es único en la plataforma
    assert cliente.post(f"/api/empresas/{cid}/usuarios", json={"usuario": "prueba_admin", "password": "clave-larga-9"}, headers=h).status_code == 400
    # editar, desactivar y restablecer clave desde el panel
    assert cliente.put(f"/api/admin/usuarios/{uid}", json={"rol": "tecnico", "activo": 0, "password": "otra-clave-99"}, headers=h).status_code == 200
    assert cliente.put(f"/api/empresas/{cid}", json={"contacto": "Ana María", "activa": 0}, headers=h).status_code == 200
    # entrar a la empresa y volver al panel
    assert cliente.post(f"/api/empresas/{cid}/entrar", json={}, headers=h).status_code == 200
    assert cliente.get("/api/equipos").status_code == 200
    assert cliente.post("/api/admin/salir-empresa", json={}, headers=h).status_code == 200
    assert cliente.get("/api/equipos").status_code == 409
    # el superadmin no puede tocar su propia cuenta desde el panel
    yo = core_db.usuario_por_nombre(core_db.conectar(core_db.TODAS), "prueba_super")
    assert cliente.put(f"/api/admin/usuarios/{yo['id']}", json={"activo": 0}, headers=h).status_code == 400
    con = core_db.conectar(core_db.TODAS); con.execute("DELETE FROM empresas WHERE id=?", (cid,)); con.commit(); con.close()


def test_primer_arranque_crea_solo_superadmin():
    """Con la base sin usuarios, el primer formulario crea un superadministrador sin empresa."""
    import app as m
    con = core_db.conectar(core_db.TODAS)
    respaldo = [dict(u) for u in con.execute("SELECT * FROM usuarios").fetchall()]
    con.execute("DELETE FROM usuarios"); con.commit()
    try:
        c = m.app.test_client()
        html = c.get("/login").data.decode()
        assert "superadministrador" in html and 'name="empresa"' not in html
        tok = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = c.post("/login", data={"usuario": "primer_super", "password": "clave-larga-9", "password2": "clave-larga-9", "csrf_token": tok})
        assert r.status_code == 302 and r.headers["Location"].endswith("/admin")
        u = core_db.usuario_por_nombre(con, "primer_super")
        assert u["rol"] == "superadmin" and u["empresa_id"] is None
        assert c.get("/admin").status_code == 200
    finally:
        con.execute("DELETE FROM usuarios")
        cols = [k for k in respaldo[0].keys()] if respaldo else []
        for u in respaldo:
            con.execute(f"INSERT INTO usuarios({', '.join(cols)}) VALUES({', '.join('?'*len(cols))})", tuple(u[k] for k in cols))
        if not core_conexion.ES_SQLITE:
            con.execute("SELECT setval(pg_get_serial_sequence('usuarios','id'), COALESCE((SELECT MAX(id) FROM usuarios),0)+1, false)")
        con.commit(); con.close()
