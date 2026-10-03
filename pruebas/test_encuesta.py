"""Pruebas de los cambios que salieron de la encuesta de validación (octubre de 2026): tarifa por
hora y nómina en el margen, incidentes que dejan el activo en tierra, avisos por lo que falta,
controles separados de UAS y aviación tripulada, triple lavado, rol de gerencia.
"""
from datetime import date, timedelta

import pytest

from test_app import cliente, entrar  # noqa: F401  (fixture y ayuda compartidas)
import test_app
from core import db as core_db
from core import indicadores as core_ind

HOY = date.today()


def _dias(n):
    return (HOY - timedelta(days=n)).isoformat()


def _con():
    return core_db.conectar(test_app.EMPRESA_A)


def _dron(con, nombre="DRON-ENCUESTA"):
    con.execute("DELETE FROM equipos WHERE nombre=?", (nombre,))
    con.commit()
    return core_db.crear_equipo(con, nombre, "T50", "SN-" + nombre, fecha_alta=_dias(60))


# ---------------------------------------------------------------- tarifa por hora y nómina

def test_tarifa_por_hora_y_nomina_en_el_margen(cliente):
    con = _con()
    eid = _dron(con)
    con.execute("DELETE FROM tarifas WHERE cliente IN ('CLI-HORA','CLI-HA')")
    con.execute("INSERT INTO tarifas(cliente, tipo_activo, valor_ha, unidad) VALUES('CLI-HORA','todos',100,'hora')")
    con.execute("INSERT INTO tarifas(cliente, tipo_activo, valor_ha, unidad) VALUES('CLI-HA','todos',10,'ha')")
    core_db.registrar_operacion(con, eid, 2.0, fecha=_dias(3), hectareas=30, cliente="CLI-HORA")
    core_db.registrar_operacion(con, eid, 1.0, fecha=_dias(3), hectareas=20, cliente="CLI-HA")
    f = core_ind.Filtros(equipo_id=eid, desde=_dias(5), hasta=_dias(1))
    # 2 h × 100 + 20 ha × 10 = 400; antes la de por hora se cobraba como 30 ha × 100.
    assert core_ind._ingreso(con, f) == pytest.approx(400)

    con.execute("DELETE FROM meta WHERE clave='nomina_mes'")
    sin_nomina = core_ind._margen(con, f)
    con.execute("INSERT INTO meta(clave, valor) VALUES('nomina_mes', '3043.75')")
    nh = core_ind.nomina_hora(con, f)
    assert nh is not None and nh > 0
    con_nomina = core_ind._margen(con, f)
    assert con_nomina == pytest.approx(sin_nomina - nh * 3.0)
    con.rollback()
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_api_tarifa_valida_la_unidad(cliente):
    h = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    r = cliente.post("/api/tarifas", json={"cliente": "X", "valor_ha": 5, "unidad": "galon"}, headers=h)
    assert r.status_code == 400
    r = cliente.post("/api/tarifas", json={"cliente": "CLI-API-HORA", "valor_ha": 5, "unidad": "hora"}, headers=h)
    assert r.status_code == 201
    tid = r.get_json()["id"]
    assert any(t["id"] == tid and t["unidad"] == "hora" for t in cliente.get("/api/tarifas").get_json()["tarifas"])
    cliente.delete(f"/api/tarifas/{tid}", headers=h)


# ---------------------------------------------------------------- avisos por lo que falta

def test_avisos_por_horas_restantes(cliente):
    from core import alertas as core_alertas
    cfg = {"aviso_horas_proximo": 25, "aviso_horas_critico": 10}
    nivel = lambda usado, vida: core_alertas._nivel_de_restante(usado, vida, cfg["aviso_horas_proximo"],
                                                                 cfg["aviso_horas_critico"])
    # Vida larga: manda lo que falta, no el porcentaje (a 80 % de 1.000 h faltan 200 h: todavía bien).
    assert nivel(800, 1000) == "ok"
    assert nivel(980, 1000) == "proximo"
    assert nivel(995, 1000) == "critico"
    assert nivel(1000, 1000) == "vencido"
    # Vida corta: el aviso se acota al 25 % / 10 % de la vida.
    assert nivel(5, 20) == "ok"
    assert nivel(16, 20) == "proximo"
    assert nivel(18.5, 20) == "critico"


def test_api_avisos_solo_admin_y_nunca_al_reves(cliente):
    h = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    assert cliente.put("/api/avisos-config", json={"modo": "porcentaje"}, headers=h).status_code == 403
    h = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    base = cliente.get("/api/avisos-config").get_json()
    malo = {**{k: base[k] for k in base if k.startswith("aviso_")}, "modo": "restante",
            "aviso_horas_critico": 50, "aviso_horas_proximo": 20}
    assert cliente.put("/api/avisos-config", json=malo, headers=h).status_code == 400
    bueno = {**{k: base[k] for k in base if k.startswith("aviso_")}, "modo": "restante"}
    r = cliente.put("/api/avisos-config", json=bueno, headers=h)
    assert r.status_code == 200 and "faltan" in r.get_json()["texto"]["critico"]


# ---------------------------------------------------------------- incidentes

def _avion(con, nombre="AV-ENCUESTA"):
    con.execute("DELETE FROM equipos WHERE nombre=?", (nombre,))
    con.commit()
    return core_db.crear_equipo(con, nombre, "C188", "SN-" + nombre, fecha_alta=_dias(60),
                                tipo_activo="avion", matricula="HK-9999")


def test_incidente_deja_el_dron_en_tierra_hasta_la_inspeccion(cliente):
    from core import alertas as core_alertas
    con = _con()
    eid = _dron(con)
    assert core_alertas.estado_flota(con)[eid]["estado"] != "no_apto"
    piloto = {"X-CSRF-Token": entrar(cliente, "prueba_piloto", "clave-segura-3")}
    r = cliente.post("/api/incidentes", json={"equipo_id": eid, "tipo": "aterrizaje_duro",
                                               "descripcion": "Tocó una rama al aterrizar"}, headers=piloto)
    assert r.status_code == 201 and r.get_json()["orden_id"]
    iid = r.get_json()["id"]
    con = _con()
    est = core_alertas.estado_flota(con)[eid]
    assert est["estado"] == "no_apto" and any("Incidente" in m for m in est["motivos"])
    # El piloto no firma la inspección.
    assert cliente.post(f"/api/incidentes/{iid}/inspeccion", json={"firmado_por": "X", "cargo": "Técnico asignado"},
                        headers=piloto).status_code == 403
    tec = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    # En un dron firma el técnico asignado o el representante del fabricante: hace falta decir cuál.
    assert cliente.post(f"/api/incidentes/{iid}/inspeccion", json={"firmado_por": "Ana"}, headers=tec).status_code == 400
    r = cliente.post(f"/api/incidentes/{iid}/inspeccion",
                     json={"firmado_por": "Ana", "cargo": "Técnico asignado", "resultado": "apto"}, headers=tec)
    assert r.status_code == 200
    con = _con()
    assert core_alertas.estado_flota(con)[eid]["estado"] != "no_apto"
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_inspeccion_de_incidente_de_avion_la_firma_un_certificador(cliente):
    con = _con()
    eid = _avion(con)
    tec = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    iid = cliente.post("/api/incidentes", json={"equipo_id": eid, "tipo": "golpe", "descripcion": "Golpe en el ala"},
                       headers=tec).get_json()["id"]
    r = cliente.post(f"/api/incidentes/{iid}/inspeccion", json={"firmado_por": "Ana", "licencia": "123"}, headers=tec)
    assert r.status_code == 403
    adm = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    assert cliente.post(f"/api/incidentes/{iid}/inspeccion", json={"firmado_por": "Luis"}, headers=adm).status_code == 400
    r = cliente.post(f"/api/incidentes/{iid}/inspeccion",
                     json={"firmado_por": "Luis", "licencia": "IMA-123", "resultado": "no_apto"}, headers=adm)
    assert r.status_code == 200
    con = _con()
    assert con.execute("SELECT estado FROM equipos WHERE id=?", (eid,)).fetchone()["estado"] == "taller"
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


# ---------------------------------------------------------------- órdenes de trabajo de avión

def test_ot_de_avion_aprobacion_diferido_y_doble_firma(cliente):
    from core import alertas as core_alertas
    con = _con()
    eid = _avion(con)
    adm = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    oid = cliente.post("/api/ot", json={"equipo_id": eid, "titulo": "Cambio de neumático",
                                         "tareas": [{"descripcion": "Cambiar neumático"}]}, headers=adm).get_json()["id"]
    # Sin aprobación del jefe técnico no empieza.
    assert cliente.put(f"/api/ot/{oid}", json={"estado": "en_proceso"}, headers=adm).status_code == 409
    tec = {"X-CSRF-Token": entrar(cliente, "prueba_tecnico", "clave-segura-2")}
    assert cliente.post(f"/api/ot/{oid}/aprobar", json={}, headers=tec).status_code == 403
    adm = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    assert cliente.post(f"/api/ot/{oid}/aprobar", json={"aprobado_por": "Jefe"}, headers=adm).status_code == 200
    assert cliente.put(f"/api/ot/{oid}", json={"estado": "en_proceso"}, headers=adm).status_code == 200
    # Diferir exige plazo y motivo; vencido el plazo el avión no vuela.
    assert cliente.put(f"/api/ot/{oid}", json={"estado": "diferida"}, headers=adm).status_code == 400
    r = cliente.put(f"/api/ot/{oid}", json={"estado": "diferida", "diferida_hasta": _dias(1),
                                             "diferida_motivo": "Repuesto en camino"}, headers=adm)
    assert r.status_code == 200
    con = _con()
    est = core_alertas.estado_flota(con)[eid]
    assert est["estado"] == "no_apto" and any("diferido" in m for m in est["motivos"])
    # Doble firma: el inspector no puede ser quien firmó el trabajo.
    r = cliente.post(f"/api/ot/{oid}/completar", json={"firmado_por": "Luis", "licencia": "1",
                                                       "inspector": "luis", "inspector_licencia": "2"}, headers=adm)
    assert r.status_code == 400
    r = cliente.post(f"/api/ot/{oid}/completar", json={"firmado_por": "Luis", "licencia": "1", "horas_hombre": 3,
                                                       "inspector": "Marta", "inspector_licencia": "2"}, headers=adm)
    assert r.status_code == 200 and r.get_json()["orden"]["inspector"] == "Marta"
    assert r.get_json()["orden"]["horas_hombre"] == 3
    con = _con()
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


# ---------------------------------------------------------------- bodega: producto del cliente y envases

def test_producto_del_cliente_no_es_inventario(cliente):
    from core import bodega as core_bod
    d, err = core_bod.limpiar_item({"nombre": "Fungicida del cliente", "clase": "insumo", "propietario": "cliente",
                                    "cliente": "Finca X", "stock_minimo": 50, "costo_referencia": 1000})
    assert err is None and d["stock_minimo"] == 0 and d["costo_referencia"] is None
    _, err = core_bod.limpiar_item({"nombre": "Hélice", "clase": "repuesto", "propietario": "cliente"})
    assert err


def test_envases_triple_lavado(cliente):
    h = {"X-CSRF-Token": entrar(cliente, "prueba_piloto", "clave-segura-3")}
    # No se devuelve un envase sin triple lavado.
    r = cliente.post("/api/bodega/envases", json={"producto": "Mancozeb", "cantidad": 4, "devuelto_en": _dias(0),
                                                   "centro_acopio": "Campo Limpio"}, headers=h)
    assert r.status_code == 400
    r = cliente.post("/api/bodega/envases", json={"producto": "Mancozeb", "cantidad": 4, "triple_lavado": True,
                                                   "fecha": _dias(1)}, headers=h)
    assert r.status_code == 201
    k = cliente.get("/api/bodega/envases?periodo=7d").get_json()["kpis"]
    assert k["envases"] >= 4 and k["por_devolver"] >= 4
    adm = {"X-CSRF-Token": entrar(cliente, "prueba_admin", "clave-segura-1")}
    assert cliente.delete(f"/api/bodega/envases/{r.get_json()['id']}", headers=adm).status_code == 200


# ---------------------------------------------------------------- rol de gerencia / finanzas

def test_gerencia_ve_la_plata_y_no_cambia_nada(cliente):
    con = core_db.conectar(test_app.EMPRESA_A)
    con.execute("DELETE FROM usuarios WHERE usuario='prueba_gerencia'")
    con.commit()
    core_db.crear_usuario(con, "prueba_gerencia", "clave-segura-5", "gerencia", empresa_id=test_app.EMPRESA_A)
    con.commit()
    h = {"X-CSRF-Token": entrar(cliente, "prueba_gerencia", "clave-segura-5")}
    assert cliente.get("/rentabilidad").status_code == 200
    assert cliente.get("/api/rentabilidad").status_code == 200
    assert cliente.get("/api/tarifas").status_code == 200
    assert cliente.post("/api/tarifas", json={"cliente": "X", "valor_ha": 1}, headers=h).status_code == 403
    assert cliente.post("/api/ot", json={"equipo_id": 1}, headers=h).status_code == 403
    # El técnico ya no ve tarifas ni el margen.
    entrar(cliente, "prueba_tecnico", "clave-segura-2")
    assert cliente.get("/api/tarifas").status_code == 403
    assert cliente.get("/api/rentabilidad").status_code == 403
    ind = cliente.get("/api/indicadores?claves=margen,horas").get_json()["indicadores"]
    assert ind["margen"]["valor"] is None and ind["margen"].get("oculto")
    con.execute("DELETE FROM usuarios WHERE usuario='prueba_gerencia'"); con.commit()


# ---------------------------------------------------------------- adopción: facturación y WhatsApp

def test_facturacion_csv_y_texto_whatsapp(cliente):
    entrar(cliente, "prueba_admin", "clave-segura-1")
    r = cliente.get("/api/rentabilidad/facturacion.csv?periodo=365d")
    assert r.status_code == 200 and "Valor unitario" in r.get_data(as_text=True)
    t = cliente.get("/api/alertas/texto").get_json()["texto"]
    assert "Hangar" in t and "activos disponibles" in t
    entrar(cliente, "prueba_tecnico", "clave-segura-2")
    assert cliente.get("/api/rentabilidad/facturacion.csv").status_code == 403
