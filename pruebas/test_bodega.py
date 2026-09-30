"""Pruebas de la bodega (core/bodega.py, web_bodega.py): existencias y costo promedio, tanques,
traslados, conteos, lotes, permisos por rol, repuestos en órdenes de trabajo y consumo de
insumos cruzado con las operaciones. Reutilizan la sesión de pruebas de test_app.py.

    DATABASE_URL=sqlite:///ruta/copia.db python -m pytest pruebas/test_bodega.py -q
"""
from datetime import date, timedelta

import pytest

from test_app import cliente, entrar  # noqa: F401  (fixture y ayuda compartidas)
import test_app
from core import bodega as core_bod
from core import db as core_db

HOY = date.today()
PREFIJO = "PRUEBA-BOD"


def _dias(n):
    return (HOY + timedelta(days=n)).isoformat()


def _con():
    return core_db.conectar(test_app.EMPRESA_A)


def _h(c, usuario="prueba_admin", clave="clave-segura-1"):
    return {"X-CSRF-Token": entrar(c, usuario, clave)}


def _limpiar():
    con = _con()
    ids = [f["id"] for f in con.execute("SELECT id FROM bodega_items WHERE nombre LIKE ?", (PREFIJO + "%",)).fetchall()]
    for i in ids:
        con.execute("DELETE FROM bodega_movimientos WHERE item_id=?", (i,))
        con.execute("DELETE FROM bodega_ot_lineas WHERE item_id=?", (i,))
        con.execute("DELETE FROM bodega_aplicaciones WHERE item_id=?", (i,))
    con.execute("DELETE FROM bodega_tanques WHERE nombre LIKE ?", (PREFIJO + "%",))
    con.execute("DELETE FROM bodega_items WHERE nombre LIKE ?", (PREFIJO + "%",))
    con.execute("DELETE FROM bodega_ubicaciones WHERE nombre LIKE ?", (PREFIJO + "%",))
    con.execute("DELETE FROM ordenes_trabajo WHERE titulo LIKE ?", (PREFIJO + "%",))
    con.execute("DELETE FROM equipos WHERE nombre LIKE ?", (PREFIJO + "%",))
    con.commit()
    con.close()


@pytest.fixture()
def bodega(cliente):
    """Dos ubicaciones limpias; al terminar se borra todo lo creado."""
    _limpiar()
    h = _h(cliente)
    a = cliente.post("/api/bodega/ubicaciones", json={"nombre": PREFIJO + " Hangar", "tipo": "hangar"}, headers=h).get_json()["id"]
    b = cliente.post("/api/bodega/ubicaciones", json={"nombre": PREFIJO + " Pista", "tipo": "pista"}, headers=h).get_json()["id"]
    yield {"h": h, "hangar": a, "pista": b}
    _limpiar()


def _item(c, h, **campos):
    datos = {"clase": "insumo", "categoria": "fungicida", "unidad": "L", **campos}
    datos["nombre"] = PREFIJO + " " + datos["nombre"]
    r = c.post("/api/bodega/items", json=datos, headers=h)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def _mov(c, h, **datos):
    return c.post("/api/bodega/movimientos", json=datos, headers=h)


def _inv(item_id):
    return next(i for i in core_bod.inventario(_con()) if i["id"] == item_id)


# ---------------------------------------------------------------- páginas y lectura

def test_pagina_y_apis_cargan(cliente):
    _h(cliente)
    assert cliente.get("/bodega").status_code == 200
    for url in ("/api/bodega", "/api/bodega/config", "/api/bodega/items", "/api/bodega/tanques",
                "/api/bodega/movimientos?periodo=90d", "/api/bodega/control?periodo=todo", "/api/bodega/compras",
                "/api/bodega/conciliar?periodo=30d", "/api/bodega/ubicaciones"):
        r = cliente.get(url)
        assert r.status_code == 200, (url, r.data[:200])
    k = cliente.get("/api/bodega").get_json()["kpis"]
    assert {"valor_total", "comprar_costo", "vencen_n", "posibles_perdidas", "costo_ha", "bajo_minimo"} <= set(k)


# ---------------------------------------------------------------- existencias y costo promedio

def test_costo_promedio_y_existencia_inicial(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Fungicida A", inicial=10, ubicacion_id=bodega["hangar"], costo_referencia=50000)
    assert _mov(cliente, h, tipo="entrada", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=10,
                costo_unitario=60000).status_code == 201
    i = _inv(iid)
    assert i["saldo"] == pytest.approx(20)
    assert i["costo_prom"] == pytest.approx(55000)
    assert i["valor"] == pytest.approx(1100000)
    # La salida no cambia el promedio y sale valorada a él.
    assert _mov(cliente, h, tipo="salida", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=4).status_code == 201
    i = _inv(iid)
    assert i["saldo"] == pytest.approx(16) and i["costo_prom"] == pytest.approx(55000)
    m = core_bod.movimientos(_con(), item_id=iid)[0]
    assert m["tipo"] == "salida" and m["valor"] == pytest.approx(220000)


def test_salida_no_puede_superar_existencias(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Herbicida B", categoria="herbicida", inicial=5, ubicacion_id=bodega["hangar"])
    r = _mov(cliente, h, tipo="salida", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=6)
    assert r.status_code == 400 and "no hay suficiente" in r.get_json()["error"]
    # En otra ubicación no hay nada.
    r = _mov(cliente, h, tipo="salida", item_id=iid, ubicacion_id=bodega["pista"], cantidad=1)
    assert r.status_code == 400


def test_traslado_y_ajuste_por_conteo(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Coadyuvante C", categoria="coadyuvante", inicial=30, ubicacion_id=bodega["hangar"],
                costo_referencia=1000)
    assert _mov(cliente, h, tipo="traslado", item_id=iid, ubicacion_id=bodega["hangar"], destino_id=bodega["pista"],
                cantidad=12).status_code == 201
    i = _inv(iid)
    ex = {e["ubicacion_id"]: e["cantidad"] for e in i["existencias"]}
    assert ex[bodega["hangar"]] == pytest.approx(18) and ex[bodega["pista"]] == pytest.approx(12)
    assert i["saldo"] == pytest.approx(30)
    # Conteo en la pista: hay 10, el sistema espera 12 → descuadre −2.
    r = _mov(cliente, h, tipo="ajuste", item_id=iid, ubicacion_id=bodega["pista"], conteo=10)
    assert r.status_code == 201 and r.get_json()["cantidad"] == pytest.approx(-2)
    assert _inv(iid)["saldo"] == pytest.approx(28)


def test_lotes_fefo_y_vencimientos(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Insecticida D", categoria="insecticida")
    _mov(cliente, h, tipo="entrada", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=10, costo_unitario=10,
         lote="L-TARDE", vence=_dias(300))
    _mov(cliente, h, tipo="entrada", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=10, costo_unitario=10,
         lote="L-PRONTO", vence=_dias(20))
    # Sin lote: sale primero el que vence antes.
    _mov(cliente, h, tipo="salida", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=4)
    lotes = {l["lote"]: l["cant"] for l in _inv(iid)["lotes"]}
    assert lotes == {"L-PRONTO": pytest.approx(6), "L-TARDE": pytest.approx(10)}
    i = _inv(iid)
    assert i["por_vencer"] == pytest.approx(6) and i["nivel"] == "proximo"
    assert any(v["item_id"] == iid and v["lote"] == "L-PRONTO" for v in core_bod.resumen(_con())["vencen"])


def test_tanque_capacidad_y_cambio_de_producto(cliente, bodega):
    h = bodega["h"]
    banole = _item(cliente, h, nombre="Banole", categoria="aceite_agricola", color="#e3c77c", costo_referencia=9000)
    otro = _item(cliente, h, nombre="Aceite X", categoria="aceite_agricola")
    r = cliente.post("/api/bodega/tanques", json={"nombre": PREFIJO + " Tanque Banole", "item_id": banole,
                                                  "ubicacion_id": bodega["pista"], "capacidad": 1000, "forma": "tanque"},
                     headers=h)
    assert r.status_code == 201
    tid = r.get_json()["id"]
    assert _mov(cliente, h, tipo="entrada", item_id=banole, tanque_id=tid, cantidad=200, costo_unitario=10000).status_code == 201
    r = _mov(cliente, h, tipo="entrada", item_id=banole, tanque_id=tid, cantidad=900, costo_unitario=10000)
    assert r.status_code == 400 and "no cabe" in r.get_json()["error"]
    # Un tanque sólo recibe el producto que tiene configurado.
    assert _mov(cliente, h, tipo="entrada", item_id=otro, tanque_id=tid, cantidad=1).status_code == 400
    assert _mov(cliente, h, tipo="salida", item_id=banole, tanque_id=tid, cantidad=30).status_code == 201
    t = cliente.get(f"/api/bodega/tanques/{tid}").get_json()
    assert t["nivel"] == pytest.approx(170) and t["pct"] == pytest.approx(17) and t["color_final"] == "#e3c77c"
    assert t["ubicacion_id"] == bodega["pista"]
    # Con líquido no se puede cambiar lo que contiene; vacío sí.
    assert cliente.put(f"/api/bodega/tanques/{tid}", json={"item_id": otro}, headers=h).status_code == 409
    _mov(cliente, h, tipo="baja", item_id=banole, tanque_id=tid, cantidad=170, motivo="derrame")
    assert cliente.put(f"/api/bodega/tanques/{tid}", json={"item_id": otro}, headers=h).status_code == 200


# ---------------------------------------------------------------- permisos

def test_permisos_por_rol(cliente, bodega):
    iid = _item(cliente, bodega["h"], nombre="Fertilizante E", categoria="fertilizante", inicial=10,
                ubicacion_id=bodega["hangar"])
    ht = _h(cliente, "prueba_tecnico", "clave-segura-2")
    assert cliente.post("/api/bodega/items", json={"nombre": PREFIJO + " x"}, headers=ht).status_code == 403
    assert _mov(cliente, ht, tipo="entrada", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=1).status_code == 201
    r = _mov(cliente, ht, tipo="ajuste", item_id=iid, ubicacion_id=bodega["hangar"], conteo=3)
    assert r.status_code == 400 and "rol" in r.get_json()["error"]
    hp = _h(cliente, "prueba_piloto", "clave-segura-3")
    assert _mov(cliente, hp, tipo="salida", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=1).status_code == 201
    assert _mov(cliente, hp, tipo="entrada", item_id=iid, ubicacion_id=bodega["hangar"], cantidad=1).status_code == 400
    mov = core_bod.movimientos(_con(), item_id=iid)[0]["id"]
    assert cliente.delete(f"/api/bodega/movimientos/{mov}", json={}, headers=hp).status_code == 403
    assert cliente.post("/api/bodega/tanques", json={"nombre": "x", "capacidad": 1}, headers=hp).status_code == 403


# ---------------------------------------------------------------- órdenes de trabajo

def _dron(con):
    con.execute("DELETE FROM equipos WHERE nombre=?", (PREFIJO + " DRON",))
    con.commit()
    return core_db.crear_equipo(con, PREFIJO + " DRON", "T50", "SN-BOD")


def test_ot_descuenta_al_completar_y_revierte(cliente, bodega):
    h = bodega["h"]
    rep = _item(cliente, h, nombre="Hélice", clase="repuesto", unidad="und", inicial=5,
                ubicacion_id=bodega["hangar"], costo_referencia=100)
    con = _con()
    eid = _dron(con)
    r = cliente.post("/api/ot", json={"equipo_id": eid, "titulo": PREFIJO + " OT",
                                      "tareas": [{"descripcion": "Cambiar hélice"}]}, headers=h).get_json()
    oid, tarea = r["id"], r["orden"]["tareas"][0]["id"]
    r = cliente.post("/api/bodega/ot-lineas", json={"orden_id": oid, "tarea_id": tarea, "item_id": rep,
                                                    "ubicacion_id": bodega["hangar"], "cantidad": 2}, headers=h)
    assert r.status_code == 201 and r.get_json()["linea"]["alcanza"]
    assert _inv(rep)["reservado"] == pytest.approx(2) and _inv(rep)["disponible"] == pytest.approx(3)
    cliente.put(f"/api/ot/tareas/{tarea}", json={"estado": "hecho"}, headers=h)
    r = cliente.post(f"/api/ot/{oid}/completar", json={}, headers=h).get_json()
    assert r["ok"] and r["bodega"]["n"] == 1 and r["costo"] == pytest.approx(200)
    assert _inv(rep)["saldo"] == pytest.approx(3)
    assert con.execute("SELECT costo_repuesto FROM ot_tareas WHERE id=?", (tarea,)).fetchone()["costo_repuesto"] == pytest.approx(200)
    # Reabrir la orden devuelve los repuestos a la bodega (y quedan apartados otra vez).
    cliente.put(f"/api/ot/{oid}", json={"estado": "en_proceso"}, headers=h)
    assert _inv(rep)["saldo"] == pytest.approx(5) and _inv(rep)["reservado"] == pytest.approx(2)
    # Completar otra vez y borrar la orden: también vuelven.
    cliente.post(f"/api/ot/{oid}/completar", json={}, headers=h)
    assert _inv(rep)["saldo"] == pytest.approx(3)
    assert cliente.delete(f"/api/ot/{oid}", headers=h).status_code == 200
    assert _inv(rep)["saldo"] == pytest.approx(5)
    assert con.execute("SELECT COUNT(*) n FROM auditoria WHERE tabla='bodega_movimientos' AND campo='borrado'").fetchone()["n"] >= 2
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_ot_sin_bodega_sigue_igual_y_tareas_no_hechas_liberan(cliente, bodega):
    h = bodega["h"]
    rep = _item(cliente, h, nombre="Filtro", clase="repuesto", unidad="und", inicial=1, ubicacion_id=bodega["hangar"])
    con = _con()
    eid = _dron(con)
    r = cliente.post("/api/ot", json={"equipo_id": eid, "titulo": PREFIJO + " OT2",
                                      "tareas": [{"descripcion": "Limpieza", "costo_repuesto": 50},
                                                 {"descripcion": "Cambiar filtro"}]}, headers=h).get_json()
    oid, t1, t2 = r["id"], r["orden"]["tareas"][0]["id"], r["orden"]["tareas"][1]["id"]
    cliente.post("/api/bodega/ot-lineas", json={"orden_id": oid, "tarea_id": t2, "item_id": rep, "cantidad": 3}, headers=h)
    cliente.put(f"/api/ot/tareas/{t1}", json={"estado": "hecho"}, headers=h)
    r = cliente.post(f"/api/ot/{oid}/completar", json={}, headers=h).get_json()
    # La tarea con repuesto no se hizo: no se descuenta y la reserva se libera; el costo manual se respeta.
    assert r["ok"] and r["bodega"]["n"] == 0 and r["costo"] == pytest.approx(50)
    assert _inv(rep)["saldo"] == pytest.approx(1) and _inv(rep)["reservado"] == 0
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_ot_sin_existencias_avisa_y_descuenta(cliente, bodega):
    h = bodega["h"]
    rep = _item(cliente, h, nombre="Motor", clase="repuesto", unidad="und", inicial=1, ubicacion_id=bodega["hangar"],
                costo_referencia=1000)
    con = _con()
    eid = _dron(con)
    r = cliente.post("/api/ot", json={"equipo_id": eid, "titulo": PREFIJO + " OT3",
                                      "tareas": [{"descripcion": "Cambiar motores"}]}, headers=h).get_json()
    oid, t = r["id"], r["orden"]["tareas"][0]["id"]
    linea = cliente.post("/api/bodega/ot-lineas", json={"orden_id": oid, "tarea_id": t, "item_id": rep,
                                                        "ubicacion_id": bodega["hangar"], "cantidad": 2}, headers=h).get_json()
    assert linea["linea"]["alcanza"] is False
    compra = next(c for c in core_bod.compras(_con())["lista"] if c["item_id"] == rep)
    assert compra["necesita"] == pytest.approx(2) and compra["pedir"] == pytest.approx(1)
    cliente.put(f"/api/ot/tareas/{t}", json={"estado": "hecho"}, headers=h)
    r = cliente.post(f"/api/ot/{oid}/completar", json={}, headers=h).get_json()
    assert r["ok"] and r["bodega"]["faltantes"] and "sin existencias" in r["motivo"]
    assert _inv(rep)["saldo"] == pytest.approx(-1) and _inv(rep)["nivel"] == "critico"
    cliente.delete(f"/api/ot/{oid}", headers=h)
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


# ---------------------------------------------------------------- insumos en la operación

def test_aplicaciones_descuentan_y_control_de_consumo(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Dithane", categoria="fungicida", inicial=100, ubicacion_id=bodega["pista"],
                costo_referencia=20000, dosis_ha=1.5)
    con = _con()
    eid = _dron(con)
    op = core_db.registrar_operacion(con, eid, 2.0, fecha=HOY.isoformat(), hectareas=20, litros=400,
                                     producto=PREFIJO + " Dithane", dosis_objetivo=20)
    r = cliente.post("/api/bodega/aplicaciones", json={"operacion_id": op, "productos": [
        {"item_id": iid, "dosis_ha": 1.5, "descontar": True, "ubicacion_id": bodega["pista"]}]}, headers=h)
    assert r.status_code == 201 and r.get_json()["descontados"] == 1
    assert _inv(iid)["saldo"] == pytest.approx(70)
    # Salida suelta de 5 L sin operación: es el descuadre que el control debe mostrar.
    _mov(cliente, h, tipo="salida", item_id=iid, ubicacion_id=bodega["pista"], cantidad=5)
    f = next(x for x in core_bod.control_consumo(_con(), HOY.isoformat(), HOY.isoformat())["filas"] if x["item_id"] == iid)
    assert f["teorico"] == pytest.approx(30) and f["salidas"] == pytest.approx(35)
    assert f["diferencia"] == pytest.approx(5) and f["nivel"] == "critico"
    assert f["dosis_real"] == pytest.approx(1.5) and f["caldo_real"] == pytest.approx(20)
    assert f["costo_ha"] == pytest.approx(30000)
    # Corregir los productos de la operación deshace la salida anterior (no se duplica).
    cliente.post("/api/bodega/aplicaciones", json={"operacion_id": op, "productos": [
        {"item_id": iid, "dosis_ha": 1.0, "descontar": True, "ubicacion_id": bodega["pista"]}]}, headers=h)
    assert _inv(iid)["saldo"] == pytest.approx(75)
    # Registro RAC 137 en CSV.
    csv = cliente.get(f"/api/bodega/registro-aplicaciones.csv?desde={HOY.isoformat()}&hasta={HOY.isoformat()}")
    assert csv.status_code == 200 and "Dithane" in csv.data.decode("utf-8-sig")
    # El piloto también puede descontar lo que aplicó.
    hp = _h(cliente, "prueba_piloto", "clave-segura-3")
    assert cliente.post("/api/bodega/aplicaciones", json={"operacion_id": op, "productos": [
        {"item_id": iid, "dosis_ha": 1.0, "descontar": True, "ubicacion_id": bodega["pista"]}]}, headers=hp).status_code == 201
    con.execute("DELETE FROM bodega_aplicaciones WHERE operacion_id=?", (op,))
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()


def test_conciliar_sugiere_productos_por_nombre(cliente, bodega):
    h = bodega["h"]
    iid = _item(cliente, h, nombre="Seeker", categoria="fungicida")
    insumos = [i for i in core_bod.items(_con(), "insumo") if i["id"] == iid]
    assert [x["id"] for x in core_bod.sugerir_items(f"{PREFIJO} SEEKER + DITHANE", insumos)] == [iid]


def test_compras_cruza_proyeccion_de_repuestos(cliente, bodega):
    """Una pieza con vida útil vencida en un dron pide su repuesto: necesitas X, tienes Y, pide Z."""
    h = bodega["h"]
    con = _con()
    eid = _dron(con)
    core_db.registrar_operacion(con, eid, 800.0, fecha=(HOY - timedelta(days=5)).isoformat())
    motor = con.execute("SELECT p.clave, p.modelo FROM componentes c JOIN catalogo_piezas p ON p.id=c.pieza_id "
                        "WHERE c.equipo_id=? AND p.vida_util_horas>0 AND p.vida_util_horas<800 LIMIT 1", (eid,)).fetchone()
    assert motor, "el T50 debe tener alguna pieza con vida útil menor de 800 h"
    rep = _item(cliente, h, nombre="Pieza proyectada", clase="repuesto", unidad="und", catalogo="pieza",
                catalogo_ref=motor["clave"], modelo=motor["modelo"], cantidad_cambio=2, stock_minimo=1,
                inicial=1, ubicacion_id=bodega["hangar"], costo_referencia=500)
    c = next(x for x in core_bod.compras(_con())["lista"] if x["item_id"] == rep)
    assert c["prevista"] >= 2 and c["tiene"] == pytest.approx(1)
    assert c["pedir"] == pytest.approx(c["necesita"] + 1 - 1) and c["costo"] == pytest.approx(c["pedir"] * 500)
    assert any(e["equipo_id"] == eid for e in c["eventos"])
    con.execute("DELETE FROM equipos WHERE id=?", (eid,)); con.commit()
