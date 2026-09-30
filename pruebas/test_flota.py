"""Pruebas de la flota mixta (drones + aviones), de los 8 errores corregidos y de las pantallas
nuevas. Corren contra la misma base que test_app.py y reutilizan su sesión de pruebas.

    DATABASE_URL=postgresql://hangar:hangar@localhost:5432/hangar_pruebas python -m pytest pruebas -q
"""
from datetime import date, timedelta

import pytest

from test_app import cliente, entrar  # noqa: F401  (fixture y ayuda compartidas)
import test_app
from core import alertas as core_alertas
from core import db as core_db
from core import flota as core_flota
from core import ordenes as core_ordenes

HOY = date.today()


def _dias(n):
    return (HOY - timedelta(days=n)).isoformat()


def _con():
    return core_db.conectar(test_app.EMPRESA_A)


def _admin(c):
    return {"X-CSRF-Token": entrar(c, "prueba_admin", "clave-segura-1")}


def _dron_nuevo(con, nombre="DRON-PRUEBA-FLOTA", modelo="T50"):
    con.execute("DELETE FROM equipos WHERE nombre=?", (nombre,))
    con.commit()
    return core_db.crear_equipo(con, nombre, modelo, "SN-" + nombre, fecha_alta=_dias(60))


def _comp(con, equipo_id, clave):
    return con.execute("SELECT c.* FROM componentes c JOIN catalogo_piezas p ON p.id=c.pieza_id "
                       "WHERE c.equipo_id=? AND p.clave=?", (equipo_id, clave)).fetchone()


# ---------------------------------------------------------------- núcleo y migración

def test_recalcular_no_cambia_lo_ya_calculado(cliente):
    """Recalcular desde las operaciones da exactamente el uso guardado (la migración es idéntica)."""
    con = _con()
    antes = {c["id"]: c["horas_uso"] for c in con.execute("SELECT id, horas_uso FROM componentes").fetchall()}
    for e in con.execute("SELECT id FROM equipos").fetchall():
        core_flota.recalcular_equipo(con, e["id"])
    despues = {c["id"]: c["horas_uso"] for c in con.execute("SELECT id, horas_uso FROM componentes").fetchall()}
    con.rollback()
    assert antes.keys() == despues.keys()
    assert all(abs((antes[k] or 0) - (despues[k] or 0)) < 1e-6 for k in antes)


def test_b1_borrar_operacion_vieja_no_toca_pieza_nueva(cliente):
    con = _con()
    eid = _dron_nuevo(con)
    op_vieja = core_db.registrar_operacion(con, eid, 2.0, fecha=_dias(20))
    helice = _comp(con, eid, "propellers")
    core_db.registrar_mantenimiento(con, eid, helice["id"], "correctivo", "Cambio", None, "t", fecha=_dias(10), motivo="daño")
    core_db.registrar_operacion(con, eid, 3.0, fecha=_dias(5))
    assert _comp(con, eid, "propellers")["horas_uso"] == pytest.approx(3.0)
    core_db.eliminar_operacion(con, op_vieja)
    # La hélice nueva conserva sus 3 h; antes perdía las 2 h de la operación borrada.
    assert _comp(con, eid, "propellers")["horas_uso"] == pytest.approx(3.0)
    assert _comp(con, eid, "motor")["horas_uso"] == pytest.approx(3.0)
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_b2_mantenimiento_con_fecha_pasada(cliente):
    con = _con()
    eid = _dron_nuevo(con)
    core_db.registrar_operacion(con, eid, 4.0, fecha=_dias(30))
    core_db.registrar_operacion(con, eid, 1.5, fecha=_dias(8))
    hose = _comp(con, eid, "hose")
    core_db.registrar_mantenimiento(con, eid, hose["id"], "preventivo", "Cambio", None, "t", fecha=_dias(10))
    c = _comp(con, eid, "hose")
    assert c["fecha_ultimo_cambio"] == _dias(10)            # antes quedaba con fecha de hoy
    assert c["horas_uso"] == pytest.approx(1.5)             # lo volado desde el cambio real
    m = con.execute("SELECT horas_pieza FROM mantenimientos WHERE componente_id=?", (hose["id"],)).fetchone()
    assert m["horas_pieza"] == pytest.approx(4.0)           # lo que llevaba el día del cambio
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_b3_sugerencias_con_plazos_en_meses(cliente):
    h = _admin(cliente)
    con = _con()
    t70 = con.execute("SELECT id FROM equipos WHERE modelo='T70P' LIMIT 1").fetchone()
    eid = t70["id"] if t70 else _dron_nuevo(con, "T70P-PRUEBA", "T70P")
    r = cliente.get(f"/api/ot/sugerencias?equipo_id={eid}", headers=h)
    assert r.status_code == 200
    for s in r.get_json():
        assert "0 h de 0 h" not in s["descripcion"]


def test_b4_cerrar_ot_guarda_costos(cliente):
    con = _con()
    eid = _dron_nuevo(con)
    comp = _comp(con, eid, "hose")
    oid = core_ordenes.crear_ot(con, {"equipo_id": eid, "titulo": "OT costos", "tareas": [
        {"descripcion": "Cambiar manguera", "componente_id": comp["id"], "costo_repuesto": "120000", "horas_mano_obra": 2}]})
    con.execute("UPDATE ot_tareas SET estado='hecho' WHERE orden_id=?", (oid,))
    r = core_ordenes.cerrar_ot_registrando_mantenimientos(con, oid, "Técnico", costo_hora=50000)
    assert r["ok"] and r["costo"] == pytest.approx(220000)
    m = con.execute("SELECT costo, costo_repuesto, costo_mano_obra FROM mantenimientos WHERE orden_id=?", (oid,)).fetchone()
    assert (m["costo"], m["costo_repuesto"], m["costo_mano_obra"]) == (220000, 120000, 100000)
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_b5_pieza_nueva_del_catalogo_llega_a_equipos_existentes(cliente):
    con = core_db.conectar(core_db.TODAS)
    n_antes = con.execute("SELECT COUNT(*) n FROM componentes c JOIN equipos e ON e.id=c.equipo_id WHERE e.modelo='T50'").fetchone()["n"]
    con.execute("INSERT INTO catalogo_piezas(modelo, clave, modulo, nombre, vida_util_horas) "
                "VALUES('T50','prueba_b5','Prueba','Pieza de prueba B5',100)")
    creados = core_flota.completar_componentes(con, "T50")
    n_t50 = con.execute("SELECT COUNT(*) n FROM equipos WHERE modelo='T50' AND estado!='baja'").fetchone()["n"]
    assert creados == n_t50
    con.execute("DELETE FROM catalogo_piezas WHERE modelo='T50' AND clave='prueba_b5'")
    con.commit()
    assert con.execute("SELECT COUNT(*) n FROM componentes c JOIN equipos e ON e.id=c.equipo_id "
                       "WHERE e.modelo='T50'").fetchone()["n"] == n_antes
    con.close()


def test_b6_correccion_manual_queda_auditada(cliente):
    h = _admin(cliente)
    con = _con()
    eid = _dron_nuevo(con)
    core_db.registrar_operacion(con, eid, 2.0, fecha=_dias(3))
    comp = _comp(con, eid, "motor")
    r = cliente.put(f"/api/componentes/{comp['id']}", json={"horas_uso": 50, "motivo": "Lectura del taller"}, headers=h)
    assert r.status_code == 200
    assert _comp(con, eid, "motor")["horas_uso"] == pytest.approx(50)
    a = con.execute("SELECT * FROM auditoria WHERE tabla='componentes' AND fila_id=? ORDER BY id DESC", (comp["id"],)).fetchone()
    assert a and a["motivo"] == "Lectura del taller" and a["usuario"] == "prueba_admin"
    # La corrección sobrevive a nuevas operaciones: sigue sumando desde ahí.
    core_db.registrar_operacion(con, eid, 1.0, fecha=_dias(1))
    assert _comp(con, eid, "motor")["horas_uso"] == pytest.approx(51)
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_b7_borrar_mantenimiento_restaura_la_pieza(cliente):
    con = _con()
    eid = _dron_nuevo(con)
    core_db.registrar_operacion(con, eid, 6.0, fecha=_dias(20))
    comp = _comp(con, eid, "hose")
    mid = core_db.registrar_mantenimiento(con, eid, comp["id"], "preventivo", "Cambio", None, "t", fecha=_dias(5))
    assert _comp(con, eid, "hose")["horas_uso"] == 0
    core_db.eliminar_mantenimiento(con, mid)
    assert _comp(con, eid, "hose")["horas_uso"] == pytest.approx(6.0)
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_b8_estado_de_flota_se_calcula_una_vez_por_peticion(cliente):
    con = _con()
    llamadas = []
    original = core_alertas._calcular
    core_alertas._calcular = lambda c, e=None: (llamadas.append(e), original(c, e))[1]
    try:
        core_alertas.componentes_con_estado(con)
        core_alertas.componentes_con_estado(con)
        core_alertas.alertas(con)
        assert llamadas == [None]
        con.execute("UPDATE equipos SET nota=nota WHERE id=-1")     # una escritura invalida la memoria
        core_alertas.componentes_con_estado(con)
        assert llamadas == [None, None]
    finally:
        core_alertas._calcular = original
        con.rollback()


# ---------------------------------------------------------------- aviones

def _avion(cliente, h, matricula="HK-7777"):
    con = _con()
    con.execute("DELETE FROM equipos WHERE matricula=?", (matricula,)); con.commit()
    r = cliente.post("/api/equipos", json={"nombre": f"Avión {matricula}", "modelo": "C188A", "matricula": matricula,
                                           "fecha_alta": _dias(100),
                                           "contadores": {"hobbs": 1000, "tach": 800, "aterrizajes": 2000, "arranques": 900}},
                     headers=h)
    assert r.status_code == 201, r.data
    return r.get_json()["id"]


def test_avion_requiere_matricula_y_usa_modelo_propio(cliente):
    h = _admin(cliente)
    r = cliente.post("/api/equipos", json={"nombre": "Sin matrícula", "modelo": "C188A"}, headers=h)
    assert r.status_code == 400
    eid = _avion(cliente, h)
    d = cliente.get(f"/api/equipos/{eid}").get_json()
    assert d["tipo_activo"] == "avion" and d["matricula"] == "HK-7777"
    assert d["modelo_info"]["propio"] and d["modelo_info"]["plantilla"] == "C188A"
    assert d["contadores"] == {"horas_vuelo": 1000, "hobbs": 1000, "tach": 800, "aterrizajes": 2000, "arranques": 900}
    assert any(c["clave"] == "insp_100h" and c["tipo_item"] == "inspeccion" for c in d["componentes"])
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_operacion_de_avion_desgasta_por_su_contador(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    r = cliente.post("/api/operaciones", json={"equipo_id": eid, "fecha": _dias(2), "hobbs_ini": 1000, "hobbs_fin": 1002.5,
                                               "tach_ini": 800, "tach_fin": 802.1, "aterrizajes": 6, "arranques": 3,
                                               "combustible_gal": 34, "hectareas": 140}, headers=h)
    assert r.status_code == 201, r.data
    d = cliente.get(f"/api/equipos/{eid}").get_json()
    assert d["horas_totales"] == pytest.approx(1002.5)
    assert d["contadores"]["tach"] == pytest.approx(802.1) and d["contadores"]["aterrizajes"] == 2006
    comps = {c["clave"]: c for c in d["componentes"]}
    assert comps["motor"]["horas_uso"] == pytest.approx(2.1)             # motor por Tach
    assert comps["insp_100h"]["horas_uso"] == pytest.approx(2.5)         # inspección por Hobbs
    assert comps["tren_principal"]["ciclos_uso"] == 6                     # tren por aterrizajes
    # Lectura final menor que la inicial y fecha futura: rechazadas.
    assert cliente.post("/api/operaciones", json={"equipo_id": eid, "hobbs_ini": 5, "hobbs_fin": 4}, headers=h).status_code == 400
    assert cliente.post("/api/operaciones", json={"equipo_id": eid, "horas_vuelo": 1,
                                                  "fecha": (HOY + timedelta(days=3)).isoformat()}, headers=h).status_code == 400
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_validacion_de_rangos(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h, "HK-7100")
    malos = [{"horas_vuelo": 30}, {"horas_vuelo": 2, "temperatura": 92}, {"horas_vuelo": 2, "humedad": 140},
             {"horas_vuelo": 5, "tiempo_total": 3}, {"horas_vuelo": 2, "hectareas": -1}]
    for m in malos:
        r = cliente.post("/api/operaciones", json={"equipo_id": eid, "fecha": _dias(1), **m}, headers=h)
        assert r.status_code == 400 and r.get_json()["errores"], m
    r = cliente.post("/api/operaciones", json={"equipo_id": eid, "fecha": _dias(1), "horas_vuelo": 2, "tiempo_total": 3,
                                               "temperatura": 31, "humedad": 70, "viento": 8}, headers=h)
    assert r.status_code == 201
    oid = r.get_json()["id"]
    # editar un solo campo se compara con lo guardado: 4 h de vuelo no caben en 3 h de jornada
    assert cliente.put(f"/api/operaciones/{oid}", json={"horas_vuelo": 4}, headers=h).status_code == 400
    assert cliente.put(f"/api/operaciones/{oid}", json={"viento": 200}, headers=h).status_code == 400
    assert cliente.put(f"/api/operaciones/{oid}", json={"viento": 12}, headers=h).status_code == 200
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_tolerancia_y_ciclos(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    # 105 h de Hobbs y 520 aterrizajes repartidos en 7 jornadas (15 h y ~75 aterrizajes cada una).
    for i in range(7):
        r = cliente.post("/api/operaciones", json={"equipo_id": eid, "fecha": _dias(1 + i), "hobbs_ini": 1000 + 15 * i,
                                                   "hobbs_fin": 1015 + 15 * i, "aterrizajes": 75 if i < 6 else 70}, headers=h)
        assert r.status_code == 201, r.data
    comps = {c["clave"]: c for c in cliente.get(f"/api/equipos/{eid}").get_json()["componentes"]}
    assert comps["insp_100h"]["nivel"] == "critico" and comps["insp_100h"]["en_tolerancia"]   # 105 h, tolerancia 10
    assert comps["tren_principal"]["nivel"] == "vencido" and comps["tren_principal"]["motivo_alerta"] == "ciclos"
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_pieza_con_serial_viaja_con_su_tso(cliente):
    h = _admin(cliente)
    a1, a2 = _avion(cliente, h, "HK-7001"), _avion(cliente, h, "HK-7002")
    motor1 = next(c for c in cliente.get(f"/api/equipos/{a1}").get_json()["componentes"] if c["clave"] == "motor")
    r = cliente.post("/api/piezas-serie", json={"serial": "TEST-MOTOR-1", "uso_acumulado": 500, "pieza_clave": "motor",
                                                "componente_id": motor1["id"], "fecha": _dias(10)}, headers=h)
    assert r.status_code == 201
    sid = r.get_json()["id"]
    cliente.post("/api/operaciones", json={"equipo_id": a1, "fecha": _dias(5), "horas_vuelo": 3, "tach_ini": 800,
                                           "tach_fin": 803}, headers=h)
    assert next(c for c in cliente.get(f"/api/equipos/{a1}").get_json()["componentes"] if c["clave"] == "motor")["horas_uso"] == pytest.approx(503)
    assert cliente.post(f"/api/piezas-serie/{sid}/desmontar", json={"fecha": _dias(2), "motivo": "Traslado"}, headers=h).status_code == 200
    motor2 = next(c for c in cliente.get(f"/api/equipos/{a2}").get_json()["componentes"] if c["clave"] == "motor")
    assert cliente.post(f"/api/piezas-serie/{sid}/instalar", json={"componente_id": motor2["id"], "fecha": _dias(1)}, headers=h).status_code == 200
    s = cliente.get(f"/api/piezas-serie/{sid}").get_json()
    assert s["equipo_id"] == a2 and s["uso_actual"] == pytest.approx(503) and len(s["instalaciones"]) == 2
    for a in (a1, a2):
        cliente.delete(f"/api/equipos/{a}", headers=h)
    con = _con(); con.execute("DELETE FROM piezas_serie WHERE serial='TEST-MOTOR-1'"); con.commit()


def test_cerrar_ot_de_avion_exige_certificador_y_firma(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    oid = cliente.post("/api/ot", json={"equipo_id": eid, "titulo": "OT avión"}, headers=h).get_json()["id"]
    assert cliente.post(f"/api/ot/{oid}/completar", json={}, headers=h).status_code == 400
    ht = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    assert cliente.post(f"/api/ot/{oid}/completar", json={"firmado_por": "X", "licencia": "1"}, headers=ht).status_code == 403
    h = _admin(cliente)
    r = cliente.post(f"/api/ot/{oid}/completar", json={"firmado_por": "Luis M.", "licencia": "TLA-1"}, headers=h)
    assert r.status_code == 200 and r.get_json()["orden"]["firmado_por"] == "Luis M."
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_directiva_y_documento_vuelven_no_apto(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    modelo = cliente.get(f"/api/equipos/{eid}").get_json()["modelo"]
    did = cliente.post("/api/directivas", json={"modelo": modelo, "numero": "TEST-AD-1", "titulo": "Prueba",
                                                "limite_fecha": _dias(3)}, headers=h).get_json()["id"]
    est = cliente.get("/api/aeronavegabilidad").get_json()
    mio = next(e for e in est["equipos"] if e["id"] == eid)
    assert mio["estado"] == "no_apto" and any("TEST-AD-1" in m for m in mio["motivos"])
    # Cumplir sin firma: 400. Con firma: la directiva sale de los pendientes.
    assert cliente.post(f"/api/directivas/{did}/cumplir", json={"equipo_id": eid}, headers=h).status_code == 400
    assert cliente.post(f"/api/directivas/{did}/cumplir", json={"equipo_id": eid, "firmado_por": "L", "licencia": "1"},
                        headers=h).status_code == 200
    estado = [d for d in cliente.get(f"/api/directivas?equipo_id={eid}").get_json()["estado"] if d["numero"] == "TEST-AD-1"]
    assert estado[0]["estado"] == "cumplida" and estado[0]["nivel"] == "ok"
    r = cliente.post("/api/documentos", json={"equipo_id": eid, "tipo": "seguro", "vence": _dias(1)}, headers=h)
    assert r.status_code == 201
    mio = next(e for e in cliente.get("/api/aeronavegabilidad").get_json()["equipos"] if e["id"] == eid)
    assert mio["estado"] == "no_apto" and any("seguro" in m.lower() for m in mio["motivos"])
    cliente.delete(f"/api/directivas/{did}", headers=h)
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_os_sobre_activo_no_apto_pide_forzar(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    cliente.post("/api/documentos", json={"equipo_id": eid, "tipo": "aeronavegabilidad", "vence": _dias(1)}, headers=h)
    r = cliente.post("/api/os", json={"equipo_id": eid, "cliente": "X", "fecha": HOY.isoformat()}, headers=h)
    assert r.status_code == 409 and r.get_json()["motivos"]
    r = cliente.post("/api/os", json={"equipo_id": eid, "cliente": "X", "fecha": HOY.isoformat(), "forzar": True}, headers=h)
    assert r.status_code == 201
    cliente.delete(f"/api/os/{r.get_json()['id']}", headers=h)
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_checklist_con_falla_abre_ot(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    plantilla = cliente.get("/api/checklists/plantilla?tipo=avion").get_json()
    items = [{"clave": p["clave"], "ok": True} for p in plantilla]
    items[0] = {"clave": plantilla[0]["clave"], "ok": False}
    assert cliente.post("/api/checklists", json={"equipo_id": eid, "items": items}, headers=h).status_code == 400
    items[0]["nota"] = "Falta el seguro a bordo"
    r = cliente.post("/api/checklists", json={"equipo_id": eid, "items": items}, headers=h)
    assert r.status_code == 201 and r.get_json()["resultado"] == "no_apto" and r.get_json()["orden_id"]
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_indicadores(cliente):
    _admin(cliente)
    r = cliente.get("/api/indicadores?periodo=todo&tipo=dron").get_json()["indicadores"]
    assert r["operaciones"]["valor"] > 0 and r["rendimiento"]["valor"] > 0
    assert "traslado" not in r                                   # sólo aplica a aviones
    r = cliente.get("/api/indicadores?agrupar=tipo&claves=horas,rendimiento&periodo=todo").get_json()
    assert set(r["por_tipo"]) == {"dron", "avion"}
    s = cliente.get("/api/indicadores?claves=horas&series=horas").get_json()["series"]["horas"]
    assert len(s) == 12


@test_app.SOLO_SERVIDOR
def test_rls_tablas_nuevas(cliente):
    """Una empresa no ve los modelos propios, directivas, piezas con serial ni documentos de otra."""
    h = _admin(cliente)
    eid = _avion(cliente, h, "HK-7090")
    modelo = cliente.get(f"/api/equipos/{eid}").get_json()["modelo"]
    cliente.post("/api/directivas", json={"modelo": modelo, "numero": "TEST-RLS", "titulo": "x"}, headers=h)
    cliente.post("/api/piezas-serie", json={"serial": "TEST-RLS-SERIAL"}, headers=h)
    entrar(cliente, "admin_b", "clave-segura-4")
    assert all(m["clave"] != modelo for m in cliente.get("/api/modelos-activo").get_json()["modelos"])
    assert any(m["clave"] == "C188A" for m in cliente.get("/api/modelos-activo").get_json()["modelos"])  # plantilla global
    assert not [d for d in cliente.get("/api/directivas").get_json()["directivas"] if d["numero"] == "TEST-RLS"]
    assert not [p for p in cliente.get("/api/piezas-serie").get_json() if p["serial"] == "TEST-RLS-SERIAL"]
    assert cliente.get(f"/api/catalogo/items?modelo={modelo}").get_json() == []
    h = _admin(cliente)
    con = _con()
    con.execute("DELETE FROM directivas WHERE numero='TEST-RLS'")
    con.execute("DELETE FROM piezas_serie WHERE serial='TEST-RLS-SERIAL'")
    con.commit()
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_tecnico_ve_catalogo_pero_no_lo_edita(cliente):
    ht = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    assert cliente.get("/api/modelos-activo").status_code == 200
    assert cliente.post("/api/modelos-activo", json={"nombre": "x", "tipo_activo": "avion"}, headers=ht).status_code == 403
    assert cliente.get("/api/rentabilidad").status_code in (302, 403)


@pytest.mark.parametrize("ruta", ["/flota", "/aeronavegabilidad", "/planificador", "/rentabilidad", "/catalogo",
                                  "/checklist"])
def test_pantallas_nuevas(cliente, ruta):
    _admin(cliente)
    assert cliente.get(ruta).status_code == 200


def test_ficha_y_diagrama_de_avion(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h)
    assert cliente.get(f"/flota/{eid}").status_code == 200
    assert cliente.get(f"/flota/{eid}/diagrama").status_code == 200
    for api in ("/api/planificador", "/api/rentabilidad", f"/api/equipos/{eid}/contadores", "/api/baterias",
                "/api/documentos", "/api/checklists", "/api/auditoria"):
        assert cliente.get(api).status_code == 200, api
    cliente.delete(f"/api/equipos/{eid}", headers=h)


def test_dar_de_baja_conserva_toda_la_informacion(cliente):
    h = _admin(cliente)
    con = _con()
    eid = _dron_nuevo(con, "DRON-BAJA")
    core_db.registrar_operacion(con, eid, 2.0, fecha=_dias(3))
    n_comp = con.execute("SELECT COUNT(*) n FROM componentes WHERE equipo_id=?", (eid,)).fetchone()["n"]
    r = cliente.delete(f"/api/equipos/{eid}", json={"motivo": "Vendido"}, headers=h)
    assert r.status_code == 200 and r.get_json()["estado"] == "baja"
    e = con.execute("SELECT estado, motivo_baja, fecha_baja FROM equipos WHERE id=?", (eid,)).fetchone()
    assert e["estado"] == "baja" and e["motivo_baja"] == "Vendido" and e["fecha_baja"] == HOY.isoformat()
    assert con.execute("SELECT COUNT(*) n FROM operaciones WHERE equipo_id=?", (eid,)).fetchone()["n"] == 1
    assert con.execute("SELECT COUNT(*) n FROM componentes WHERE equipo_id=?", (eid,)).fetchone()["n"] == n_comp
    # Reactivar lo devuelve al servicio y limpia la baja.
    assert cliente.put(f"/api/equipos/{eid}", json={"estado": "activo"}, headers=h).status_code == 200
    e = con.execute("SELECT estado, motivo_baja FROM equipos WHERE id=?", (eid,)).fetchone()
    assert e["estado"] == "activo" and e["motivo_baja"] is None
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_chequeo_ok_con_mantenimiento_vencido_no_recomienda_volar(cliente):
    h = _admin(cliente)
    eid = _avion(cliente, h, "HK-7333")
    cliente.post("/api/documentos", json={"equipo_id": eid, "tipo": "seguro", "vence": _dias(2)}, headers=h)
    plantilla = cliente.get("/api/checklists/plantilla?tipo=avion").get_json()
    r = cliente.post("/api/checklists", json={"equipo_id": eid, "items": [{"clave": p["clave"], "ok": True} for p in plantilla]},
                     headers=h)
    d = r.get_json()
    assert r.status_code == 201 and d["resultado"] == "no_recomendado" and d["motivos"] and not d["orden_id"]
    con = _con(); con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


# ---------------------------------------------------------------- disponibilidad, indicadores por activo y panel

def test_api_disponibilidad_por_activo(cliente):
    _admin(cliente)
    r = cliente.get("/api/disponibilidad").get_json()
    for k in ("activos", "total", "primer_dia", "mttr", "desde", "hasta"):
        assert k in r, k
    assert set(r["mttr"]) >= {"n", "dias"}
    assert r["activos"], "la empresa de pruebas tiene activos"
    for a in r["activos"]:
        for k in ("id", "nombre", "tipo_activo", "dias", "dias_registrados", "dias_disponible",
                  "dias_no_recomendado", "dias_taller", "disponibilidad"):
            assert k in a, k
    r = cliente.get("/api/disponibilidad?tipo=avion&periodo=30d").get_json()
    assert all(a["tipo_activo"] == "avion" for a in r["activos"])


def test_api_indicadores_de_un_avion(cliente):
    _admin(cliente)
    r = cliente.get("/api/indicadores?equipo_id=7&tipo=avion&periodo=todo"
                    "&claves=ha_galon,gal_ha,disponibilidad,mttr&series=rendimiento")
    assert r.status_code == 200
    d = r.get_json()
    assert set(d["indicadores"]) == {"ha_galon", "gal_ha", "disponibilidad", "mttr"}
    for i in d["indicadores"].values():
        assert {"valor", "unidad", "nombre", "formula", "decimales"} <= set(i)
    assert len(d["series"]["rendimiento"]) == 12
    # En un dron no aplican los de combustible.
    r = cliente.get("/api/indicadores?equipo_id=7&tipo=dron&claves=ha_galon,gal_ha,disponibilidad").get_json()
    assert "ha_galon" not in r["indicadores"] and "disponibilidad" in r["indicadores"]


def test_pantallas_con_secciones_nuevas(cliente):
    _admin(cliente)
    html = cliente.get("/flota/7").get_data(as_text=True)
    assert 'id="cardIndicadores"' in html and "segIndPeriodo" in html
    html = cliente.get("/aeronavegabilidad").get_data(as_text=True)
    assert 'id="tabDisponibilidad"' in html and 'data-t="disponibilidad"' in html
    html = cliente.get("/").get_data(as_text=True)
    assert "disponibilidad" in html
    # entrar() busca el token en «/», que al superadministrador lo redirige al panel.
    cliente.get("/salir")
    cliente.post("/login", data={"usuario": "prueba_super", "password": "clave-segura-0",
                                 "csrf_token": test_app._token(cliente)})
    r = cliente.get("/admin")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "data-correo" in html and "certificador" in html and "/correo/cola" in html
