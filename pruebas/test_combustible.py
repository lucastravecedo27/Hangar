"""Pruebas de la estación de combustible (core/combustible.py) y del marco RAC (core/rac.py)."""
from datetime import date, timedelta

from test_app import cliente, entrar  # noqa: F401  (fixture y ayuda compartidas)
import test_app
from core import combustible as core_comb
from core import db as core_db
from core import rac as core_rac

HOY = date.today()


def _dias(n):
    return (HOY - timedelta(days=n)).isoformat()


def _con():
    return core_db.conectar(test_app.EMPRESA_A)


def _cab(c):
    return {"X-CSRF-Token": entrar(c, "prueba_admin", "clave-segura-1")}


CHEQUEO_OK = {k: True for k, _t, _o in core_comb.CHEQUEO_AERONAVE}


def _avion(con, nombre="AVION-PRUEBA-COMB"):
    con.execute("DELETE FROM equipos WHERE nombre=?", (nombre,))
    con.execute("DELETE FROM combustible_movimientos")
    con.execute("DELETE FROM combustible_depositos")
    con.commit()
    eid = core_db.crear_equipo(con, nombre, "C188A", "SN-" + nombre, matricula="HK-PRB", fecha_alta=_dias(90))
    con.commit()
    return eid


def _deposito(c, h, nivel=200):
    r = c.post("/api/combustible/depositos", json={"nombre": "Cisterna prueba", "combustible": "avgas_100ll",
                                                   "capacidad_gal": 1000, "nivel_inicial_gal": nivel,
                                                   "fecha_inicial": _dias(60)}, headers=h)
    assert r.status_code == 201
    return r.get_json()["id"]


def test_tanqueo_exige_chequeo_rac(cliente):
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    base = {"tipo": "tanqueo", "equipo_id": eid, "galones": 30, "precio_gal": 30000, "fecha": _dias(5)}
    r = cliente.post("/api/combustible", json=base, headers=h)
    assert r.status_code == 400 and "chequeo" in r.get_json()["error"]
    r = cliente.post("/api/combustible", json={**base, "chequeo": CHEQUEO_OK}, headers=h)
    assert r.status_code == 201


def test_tanqueo_solo_aviones(cliente):
    con = _con(); _avion(con)
    dron = con.execute("SELECT id FROM equipos WHERE tipo_activo!='avion' LIMIT 1").fetchone()
    if not dron:
        dron_id = core_db.crear_equipo(con, "DRON-COMB", "T50", "SN-DRON-COMB"); con.commit()
    else:
        dron_id = dron["id"]
    r = cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": dron_id, "galones": 5,
                                               "chequeo": CHEQUEO_OK}, headers=_cab(cliente))
    assert r.status_code == 400 and "aviones" in r.get_json()["error"]


def test_nivel_y_descuadre_del_deposito(cliente):
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    dep = _deposito(cliente, h, nivel=200)
    cliente.post("/api/combustible", json={"tipo": "compra", "deposito_id": dep, "galones": 500,
                                           "precio_gal": 32000, "fecha": _dias(20)}, headers=h)
    cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "deposito_id": dep,
                                           "galones": 40, "fecha": _dias(10), "chequeo": CHEQUEO_OK}, headers=h)
    con = _con()
    assert core_comb.nivel_deposito(con, dep) == 660
    # El tanqueo desde depósito propio se valora al costo medio del depósito.
    t = con.execute("SELECT precio_gal FROM combustible_movimientos WHERE tipo='tanqueo'").fetchone()
    assert t["precio_gal"] == 32000
    cliente.post("/api/combustible", json={"tipo": "medicion", "deposito_id": dep, "nivel_medido": 600,
                                           "fecha": _dias(1)}, headers=h)
    con = _con()
    m = con.execute("SELECT galones FROM combustible_movimientos WHERE tipo='medicion'").fetchone()
    assert m["galones"] == -60
    assert core_comb.nivel_deposito(con, dep) == 600
    assert any("descuadre" in a["titulo"] for a in core_comb.alertas(con))


def test_alertas_combustible_equivocado_y_capacidad(cliente):
    con = _con(); eid = _avion(con)
    cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "galones": 60, "combustible": "jet_a1",
                                           "precio_gal": 30000, "fecha": _dias(3), "chequeo": CHEQUEO_OK},
                 headers=_cab(cliente))
    titulos = [a["titulo"] for a in core_comb.alertas(_con())]
    assert any("combustible equivocado" in t for t in titulos)
    assert any("mayor que el tanque" in t for t in titulos)


def test_consumo_de_lleno_a_lleno(cliente):
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    for dias, gal, lect in ((10, 40, 100.0), (5, 32, 102.0)):
        r = cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "galones": gal, "precio_gal": 1,
                                                   "fecha": _dias(dias), "lleno": True, "lectura": lect,
                                                   "chequeo": CHEQUEO_OK}, headers=h)
        assert r.status_code == 201
    tramos = core_comb.tramos_lleno(_con(), eid)
    assert len(tramos) == 1 and tramos[0]["fuente"] == "lectura" and tramos[0]["gal_h"] == 16.0


def test_normativa_evalua_requisitos(cliente):
    _cab(cliente)
    r = cliente.get("/api/normativa")
    assert r.status_code == 200
    d = r.get_json()
    ids = {q["id"] for q in d["requisitos"]}
    assert {"insp_anual", "registro_aplic", "comb_reserva", "uas_registro"} <= ids
    assert all(q["estado"] in ("cumple", "atencion", "falta", "manual", "no_aplica") for q in d["requisitos"])
    assert core_rac.RESERVAS_COMBUSTIBLE["casos"][0]["reserva_min"] == 30
    for pagina in ("/combustible", "/normativa"):
        assert cliente.get(pagina).status_code == 200


def test_seguimiento_de_cada_tanqueo(cliente):
    """Cada carga se sigue vuelo a vuelo hasta el siguiente tanqueo; al volver a llenar se cierra
    con el consumo real (lo que se repuso) y se compara con lo que explican los vuelos."""
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    ids = []
    for dias, gal in ((10, 52), (5, 50)):
        r = cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "galones": gal, "lleno": True,
                                                   "precio_gal": 30000, "fecha": _dias(dias), "hora": "06:00",
                                                   "chequeo": CHEQUEO_OK}, headers=h)
        ids.append(r.get_json()["id"])
    con = _con()
    vuelos = ((9, "07:00", 1.0, 15), (8, None, 1.0, 15), (7, "08:00", 1.0, None),   # de la 1.ª carga
              (5, "05:00", 0.5, None),                                              # antes del 2.º tanqueo ese día
              (4, "09:00", 1.0, 16))                                                # de la carga abierta
    for dias, hora, horas, gal in vuelos:
        core_db.registrar_operacion(con, eid, horas, fecha=_dias(dias), hora_salida=hora, combustible_gal=gal)

    cargas = core_comb.cargas_equipo(_con(), eid)
    assert [c["n_vuelos"] for c in cargas] == [4, 1]
    primera, abierta = cargas
    # 52 usables; el lleno siguiente repuso 50 → se gastaron 50 de verdad.
    assert primera["estado"] == "cerrado" and primera["real"] == 50.0 and primera["restante"] == 2.0
    tasa = primera["tasa"]                       # 50 gal ÷ 3,5 h de lleno a lleno
    assert abs(tasa - 50 / 3.5) < 0.01
    assert abs(primera["consumido"] - (30 + 1.5 * tasa)) < 0.1
    assert primera["diferencia"] is not None
    # La carga en el tanque: 52 − 16 anotados.
    assert abierta["estado"] == "en_uso" and abierta["restante"] == 36.0
    assert abierta["horas_restantes"] > 0 and not abierta["bajo_reserva"]

    r = cliente.get(f"/api/combustible/{ids[0]}", headers=h).get_json()
    assert r["seguimiento"]["real"] == 50.0
    r = cliente.get(f"/api/combustible/equipo/{eid}", headers=h).get_json()
    assert r["carga_actual"]["id"] == ids[1] and len(r["cargas"]) == 2


def test_carga_bajo_reserva_alerta(cliente):
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    for dias, gal in ((10, 52), (6, 40)):
        cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "galones": gal, "lleno": True,
                                               "fecha": _dias(dias), "chequeo": CHEQUEO_OK}, headers=h)
    con = _con()
    core_db.registrar_operacion(con, eid, 2.5, fecha=_dias(8))
    core_db.registrar_operacion(con, eid, 3.0, fecha=_dias(3), combustible_gal=46)
    actual = core_comb.carga_actual(_con(), eid)
    assert actual["restante"] == 6.0 and actual["bajo_reserva"]
    assert any("bajo la reserva" in a["titulo"] for a in core_comb.alertas(_con()))
    con = _con(); con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_editar_tanqueo_recalcula_y_audita(cliente):
    con = _con(); eid = _avion(con)
    h = _cab(cliente)
    dep = _deposito(cliente, h, nivel=300)
    cliente.post("/api/combustible", json={"tipo": "compra", "deposito_id": dep, "galones": 100, "precio_gal": 30000,
                                           "fecha": _dias(20)}, headers=h)
    r = cliente.post("/api/combustible", json={"tipo": "tanqueo", "equipo_id": eid, "deposito_id": dep, "galones": 40,
                                               "fecha": _dias(5), "chequeo": CHEQUEO_OK}, headers=h)
    mid = r.get_json()["id"]
    # Más galones: el total se recalcula al costo del depósito y el nivel baja.
    assert cliente.put(f"/api/combustible/{mid}", json={"galones": 45, "lleno": True}, headers=h).status_code == 200
    m = cliente.get(f"/api/combustible/{mid}", headers=h).get_json()
    assert m["galones"] == 45 and m["total"] == 45 * 30000 and m["lleno"] == 1
    assert core_comb.nivel_deposito(_con(), dep) == 355
    # Pasa a proveedor externo con su precio: el depósito recupera los galones.
    r = cliente.put(f"/api/combustible/{mid}", json={"deposito_id": None, "precio_gal": 33000, "proveedor": "Aeródromo"}, headers=h)
    assert r.status_code == 200
    m = cliente.get(f"/api/combustible/{mid}", headers=h).get_json()
    assert m["deposito_id"] is None and m["total"] == 45 * 33000
    assert core_comb.nivel_deposito(_con(), dep) == 400
    campos = {f["campo"] for f in _con().execute(
        "SELECT campo FROM auditoria WHERE tabla='combustible_movimientos' AND fila_id=?", (mid,)).fetchall()}
    assert {"galones", "lleno", "deposito_id", "precio_gal", "proveedor"} <= campos
    assert cliente.put(f"/api/combustible/{mid}", json={"tipo": "compra"}, headers=h).status_code == 400
