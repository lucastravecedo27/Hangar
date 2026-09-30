"""Rutas de la bodega (core/bodega.py): repuestos, insumos de operación, tanques, kardex,
repuestos en órdenes de trabajo y consumo de fitosanitarios cruzado con las operaciones.
Se registran desde app.py igual que web_flota y web_combustible.

Permisos (ver PERMISOS/SOLO_ADMIN en app.py): leer, todos; registrar salidas y consumos, técnico
y piloto (el técnico también entradas y traslados); crear o cambiar artículos, ubicaciones y
tanques, ajustar por conteo, dar de baja y borrar, sólo el administrador.
"""
import csv
import io

from flask import Response, jsonify, render_template, request, session

from core import bodega as core_bod
from core import db as core_db
from core import flota as core_flota
from core import indicadores as core_ind


def registrar(app, get_con, login_requerido, admin_requerido):

    def _datos():
        return request.get_json(silent=True) or {}

    def _rol():
        rol = session.get("rol", "admin")
        return "admin" if rol in ("admin", core_db.ROL_SUPERADMIN) else rol

    def _rango():
        desde, hasta = request.args.get("desde") or None, request.args.get("hasta") or None
        if not desde and not hasta:
            desde, hasta = core_ind.periodo(request.args.get("periodo") or "90d")
        return desde, hasta

    def _no_existe():
        return jsonify({"error": "no existe"}), 404

    # ------------------------------------------------------------------ página

    @app.route("/bodega")
    @login_requerido
    def pagina_bodega():
        return render_template("bodega.html", activo="bodega")

    # ------------------------------------------------------------------ resumen y configuración

    @app.route("/api/bodega")
    @login_requerido
    def api_bodega():
        desde, hasta = _rango()
        r = core_bod.resumen(get_con(), desde, hasta)
        r["filtros"] = {"desde": desde, "hasta": hasta}
        return jsonify(r)

    @app.route("/api/bodega/config")
    @login_requerido
    def api_bodega_config():
        """Todo lo que los asistentes necesitan para guiar al usuario."""
        con = get_con()
        equipos = [dict(e) for e in con.execute(
            "SELECT id, nombre, modelo, tipo_activo, matricula FROM equipos WHERE estado!='baja' "
            "ORDER BY tipo_activo DESC, nombre").fetchall()]
        proveedores = [f["proveedor"] for f in con.execute(
            """SELECT proveedor, MAX(fecha) f FROM bodega_movimientos WHERE proveedor IS NOT NULL
               GROUP BY proveedor ORDER BY f DESC LIMIT 15""").fetchall()]
        return jsonify({
            "clases": core_bod.CLASES, "tipos": core_bod.TIPOS, "tipos_rol": core_bod.TIPOS_POR_ROL.get(_rol()),
            "motivos_salida": core_bod.MOTIVOS_SALIDA, "motivos_baja": core_bod.MOTIVOS_BAJA,
            "tipos_ubicacion": core_bod.TIPOS_UBICACION, "categorias": core_bod.CATEGORIAS_INSUMO,
            "sugeridos": core_bod.PRODUCTOS_SUGERIDOS,
            "tox": core_bod.CATEGORIAS_TOX, "unidades": core_bod.UNIDADES, "formas": core_bod.FORMAS_TANQUE,
            "ubicaciones": core_bod.ubicaciones(get_con()), "equipos": equipos, "proveedores": proveedores,
            "rol": _rol(), "dias_por_vencer": core_bod.DIAS_POR_VENCER, "horizonte": core_bod.HORIZONTE_COMPRA,
        })

    # ------------------------------------------------------------------ artículos

    @app.route("/api/bodega/items", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_items():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            campos, error = core_bod.limpiar_item(d)
            if error:
                return jsonify({"error": error}), 400
            id_ = core_bod.guardar_item(con, campos)
            core_flota.auditar(con, "bodega_items", id_, "alta", None, campos["nombre"], session.get("usuario"))
            # Existencia inicial: entra como una compra con su costo (así arranca el promedio).
            inicial = core_flota._num(d.get("inicial"))
            if inicial and inicial > 0:
                m, error, _ = core_bod.validar_mov(con, {"tipo": "entrada", "item_id": id_, "cantidad": inicial,
                                                         "ubicacion_id": d.get("ubicacion_id"),
                                                         "tanque_id": d.get("tanque_id"),
                                                         "costo_unitario": d.get("costo_referencia"),
                                                         "lote": d.get("lote"), "vence": d.get("vence"),
                                                         "proveedor": d.get("proveedor"),
                                                         "nota": "Existencia inicial"})
                if error:
                    con.rollback()
                    return jsonify({"error": "existencia inicial: " + error}), 400
                core_bod.guardar_mov(con, m, session.get("usuario"))
            con.commit()
            return jsonify({"ok": True, "id": id_}), 201
        return jsonify(core_bod.inventario(con, request.args.get("clase") or None))

    @app.route("/api/bodega/items/<int:id_>", methods=["GET", "PUT", "DELETE"])
    @login_requerido
    def api_bodega_item(id_):
        con = get_con()
        fila = con.execute("SELECT * FROM bodega_items WHERE id=?", (id_,)).fetchone()
        if not fila:
            return _no_existe()
        if request.method == "DELETE":
            n = con.execute("SELECT COUNT(*) n FROM bodega_movimientos WHERE item_id=?", (id_,)).fetchone()["n"]
            if n and not _datos().get("forzar"):
                # Con historial se desactiva: el kardex y el registro RAC deben conservarse.
                con.execute("UPDATE bodega_items SET activo=0 WHERE id=?", (id_,))
                core_flota.auditar(con, "bodega_items", id_, "activo", 1, 0, session.get("usuario"), "tiene movimientos")
                con.commit()
                return jsonify({"ok": True, "desactivado": True})
            core_flota.auditar(con, "bodega_items", id_, "borrado", fila["nombre"], None, session.get("usuario"))
            con.execute("DELETE FROM bodega_items WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        if request.method == "PUT":
            campos, error = core_bod.limpiar_item(_datos(), dict(fila))
            if error:
                return jsonify({"error": error}), 400
            for k in ("nombre", "stock_minimo", "costo_referencia", "categoria", "activo"):
                if campos.get(k) != fila[k]:
                    core_flota.auditar(con, "bodega_items", id_, k, fila[k], campos.get(k), session.get("usuario"))
            core_bod.guardar_item(con, campos, id_)
            con.commit()
            return jsonify({"ok": True})
        info = next((i for i in core_bod.inventario(con) if i["id"] == id_), None)
        info["movimientos"] = core_bod.movimientos(con, item_id=id_, limite=400)
        info["reservas"] = [dict(f) for f in con.execute(
            """SELECT l.*, o.codigo, o.estado AS orden_estado, e.nombre AS equipo FROM bodega_ot_lineas l
               JOIN ordenes_trabajo o ON o.id=l.orden_id JOIN equipos e ON e.id=o.equipo_id
               WHERE l.item_id=? ORDER BY l.id DESC LIMIT 50""", (id_,)).fetchall()]
        info["tanques"] = [t for t in core_bod.estado_tanques(con) if t["item_id"] == id_]
        comp = core_bod.compras(con)
        info["compra"] = next((c for c in comp["lista"] if c["item_id"] == id_), None)
        return jsonify(info)

    @app.route("/api/bodega/stock")
    @login_requerido
    def api_bodega_stock():
        """Repuestos que casan con una pieza (código, clave o texto) y dónde hay existencias."""
        return jsonify(core_bod.buscar_stock(get_con(), request.args.get("q"), request.args.get("codigo"),
                                             request.args.get("clave"), request.args.get("modelo"),
                                             request.args.get("clase") or "repuesto",
                                             request.args.get("limite", default=12, type=int)))

    # ------------------------------------------------------------------ ubicaciones

    @app.route("/api/bodega/ubicaciones", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_ubicaciones():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            nombre = (d.get("nombre") or "").strip()
            if not nombre:
                return jsonify({"error": "falta el nombre de la ubicación"}), 400
            tipo = d.get("tipo") if d.get("tipo") in core_bod.TIPOS_UBICACION else "hangar"
            cur = con.execute("INSERT INTO bodega_ubicaciones(nombre, tipo, detalle) VALUES(?,?,?)",
                              (nombre, tipo, (d.get("detalle") or "").strip() or None))
            core_flota.auditar(con, "bodega_ubicaciones", cur.lastrowid, "alta", None, nombre, session.get("usuario"))
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        return jsonify(core_bod.ubicaciones(con))

    @app.route("/api/bodega/ubicaciones/<int:id_>", methods=["GET", "PUT", "DELETE"])
    @login_requerido
    def api_bodega_ubicacion(id_):
        con = get_con()
        u = con.execute("SELECT * FROM bodega_ubicaciones WHERE id=?", (id_,)).fetchone()
        if not u:
            return _no_existe()
        if request.method == "DELETE":
            inv = core_bod.inventario(con)
            con_existencias = [i["nombre"] for i in inv
                               if any(e["ubicacion_id"] == id_ and abs(e["cantidad"]) > 1e-9 for e in i["existencias"])]
            if con_existencias:
                return jsonify({"error": "aún guarda existencias (" + ", ".join(con_existencias[:4])
                                         + "): trasládalas antes de quitarla"}), 409
            con.execute("UPDATE bodega_ubicaciones SET activo=0 WHERE id=?", (id_,))
            core_flota.auditar(con, "bodega_ubicaciones", id_, "activo", 1, 0, session.get("usuario"))
            con.commit()
            return jsonify({"ok": True})
        if request.method == "PUT":
            d = _datos()
            campos = {k: d[k] for k in ("nombre", "tipo", "detalle", "activo") if k in d}
            if "tipo" in campos and campos["tipo"] not in core_bod.TIPOS_UBICACION:
                campos.pop("tipo")
            if campos:
                con.execute(f"UPDATE bodega_ubicaciones SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                            list(campos.values()) + [id_])
                con.commit()
            return jsonify({"ok": True})
        d = dict(u)
        d["articulos"] = []
        for i in core_bod.inventario(con):
            e = next((x for x in i["existencias"] if x["ubicacion_id"] == id_), None)
            if e:
                d["articulos"].append({"id": i["id"], "nombre": i["nombre"], "clase": i["clase"], "unidad": i["unidad"],
                                       "cantidad": e["cantidad"], "valor": round(e["cantidad"] * (i["costo"] or 0)),
                                       "codigo": i["codigo"], "nivel": i["nivel"]})
        d["articulos"].sort(key=lambda x: -x["valor"])
        d["tanques"] = [t for t in core_bod.estado_tanques(con) if t["ubicacion_id"] == id_]
        d["movimientos"] = core_bod.movimientos(con, ubicacion_id=id_, limite=100)
        return jsonify(d)

    # ------------------------------------------------------------------ tanques

    def _limpiar_tanque(d, previo=None):
        t = dict(previo or {})
        for k in ("nombre", "forma", "color", "nota"):
            if k in d:
                t[k] = (str(d[k]).strip() or None) if d[k] not in (None, "") else None
        for k in ("item_id", "ubicacion_id"):
            if k in d:
                t[k] = int(d[k]) if str(d[k] or "").isdigit() else None
        if "capacidad" in d:
            t["capacidad"] = core_flota._num(d["capacidad"])
        if "activo" in d:
            t["activo"] = 1 if d["activo"] in (1, True, "1") else 0
        if not t.get("nombre"):
            return None, "ponle un nombre al tanque"
        if not t.get("capacidad") or t["capacidad"] <= 0:
            return None, "la capacidad debe ser mayor que cero"
        if t.get("forma") not in core_bod.FORMAS_TANQUE:
            t["forma"] = "tanque"
        if t.get("color") and not (len(t["color"]) == 7 and t["color"].startswith("#")):
            t["color"] = None
        return t, None

    @app.route("/api/bodega/tanques", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_tanques():
        con = get_con()
        if request.method == "POST":
            t, error = _limpiar_tanque(_datos())
            if error:
                return jsonify({"error": error}), 400
            campos = [k for k in ("nombre", "item_id", "ubicacion_id", "capacidad", "forma", "color", "nota") if k in t]
            cur = con.execute(f"INSERT INTO bodega_tanques({', '.join(campos)}) VALUES({', '.join('?' * len(campos))})",
                              [t[k] for k in campos])
            core_flota.auditar(con, "bodega_tanques", cur.lastrowid, "alta", None, t["nombre"], session.get("usuario"))
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        return jsonify(core_bod.estado_tanques(con))

    @app.route("/api/bodega/tanques/<int:id_>", methods=["GET", "PUT", "DELETE"])
    @login_requerido
    def api_bodega_tanque(id_):
        con = get_con()
        fila = con.execute("SELECT * FROM bodega_tanques WHERE id=?", (id_,)).fetchone()
        if not fila:
            return _no_existe()
        estado = next((t for t in core_bod.estado_tanques(con) if t["id"] == id_), None)
        if request.method == "DELETE":
            if not estado["vacio"]:
                return jsonify({"error": f"el tanque tiene {estado['nivel']:g} {estado['unidad']}: vacíalo "
                                         "(traslado o baja) antes de quitarlo"}), 409
            core_flota.auditar(con, "bodega_tanques", id_, "borrado", fila["nombre"], None, session.get("usuario"))
            con.execute("DELETE FROM bodega_tanques WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        if request.method == "PUT":
            t, error = _limpiar_tanque(_datos(), dict(fila))
            if error:
                return jsonify({"error": error}), 400
            # Cambiar lo que contiene (o dónde está) un tanque con líquido dejaría ese líquido
            # contado como otro producto: primero se vacía.
            for k, txt in (("item_id", "el producto"), ("ubicacion_id", "la ubicación")):
                if t.get(k) != fila[k] and not estado["vacio"]:
                    return jsonify({"error": f"para cambiar {txt} del tanque primero vacíalo: tiene "
                                             f"{estado['nivel']:g} {estado['unidad']} de {estado['item']}"}), 409
            if t["capacidad"] + 1e-9 < max(estado["nivel"], 0):
                return jsonify({"error": f"la capacidad no puede ser menor que lo que tiene ({estado['nivel']:g})"}), 400
            for k in ("item_id", "capacidad", "ubicacion_id", "color", "nombre"):
                if t.get(k) != fila[k]:
                    core_flota.auditar(con, "bodega_tanques", id_, k, fila[k], t.get(k), session.get("usuario"))
            campos = [k for k in ("nombre", "item_id", "ubicacion_id", "capacidad", "forma", "color", "nota", "activo") if k in t]
            con.execute(f"UPDATE bodega_tanques SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                        [t[k] for k in campos] + [id_])
            con.commit()
            return jsonify({"ok": True})
        estado["movimientos"] = [m for m in core_bod.movimientos(con, item_id=fila["item_id"], limite=1000)
                                 if id_ in (m["tanque_id"], m["tanque_destino_id"])][:100] if fila["item_id"] else []
        return jsonify(estado)

    # ------------------------------------------------------------------ movimientos (kardex)

    @app.route("/api/bodega/movimientos", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_movimientos():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            if d.get("forzar") and _rol() != "admin":
                d["forzar"] = False
            m, error, avisos = core_bod.validar_mov(con, d, _rol())
            if error:
                return jsonify({"error": error}), 400
            id_ = core_bod.guardar_mov(con, m, session.get("usuario"))
            con.commit()
            return jsonify({"ok": True, "id": id_, "avisos": avisos, "cantidad": m["cantidad"]}), 201
        desde, hasta = (request.args.get("desde") or None, request.args.get("hasta") or None)
        if request.args.get("periodo"):
            desde, hasta = _rango()
        return jsonify(core_bod.movimientos(con, desde, hasta, request.args.get("item_id", type=int),
                                            request.args.get("tipo") or None, request.args.get("clase") or None,
                                            request.args.get("ubicacion_id", type=int),
                                            request.args.get("limite", default=500, type=int)))

    @app.route("/api/bodega/movimientos/<int:id_>", methods=["GET", "DELETE"])
    @login_requerido
    def api_bodega_movimiento(id_):
        con = get_con()
        fila = con.execute("SELECT item_id FROM bodega_movimientos WHERE id=?", (id_,)).fetchone()
        if not fila:
            return _no_existe()
        if request.method == "DELETE":
            core_bod.borrar_mov(con, id_, session.get("usuario"), _datos().get("motivo"))
            con.commit()
            return jsonify({"ok": True})
        m = next((x for x in core_bod.movimientos(con, item_id=fila["item_id"], limite=10 ** 6) if x["id"] == id_), None)
        return jsonify(m)

    # ------------------------------------------------------------------ repuestos en órdenes de trabajo

    @app.route("/api/bodega/ot-lineas", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_ot_lineas():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            orden_id = d.get("orden_id")
            id_, error = core_bod.agregar_linea_ot(con, int(orden_id or 0), d, session.get("usuario"))
            if error:
                return jsonify({"error": error}), 400
            con.commit()
            linea = next((x for x in core_bod.lineas_ot(con, int(orden_id)) if x["id"] == id_), None)
            return jsonify({"ok": True, "id": id_, "linea": linea}), 201
        orden_id = request.args.get("orden_id", type=int)
        return jsonify(core_bod.lineas_ot(con, orden_id) if orden_id else [])

    @app.route("/api/bodega/ot-lineas/<int:id_>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_bodega_ot_linea(id_):
        con = get_con()
        l = con.execute("SELECT l.*, o.estado AS orden_estado FROM bodega_ot_lineas l "
                        "JOIN ordenes_trabajo o ON o.id=l.orden_id WHERE l.id=?", (id_,)).fetchone()
        if not l:
            return _no_existe()
        if l["estado"] == "consumido" or l["orden_estado"] in ("completada", "cancelada"):
            return jsonify({"error": "la orden ya está cerrada: reábrela para cambiar sus repuestos"}), 409
        if request.method == "DELETE":
            core_flota.auditar(con, "bodega_ot_lineas", id_, "borrado", f"{l['cantidad']:g} item {l['item_id']}",
                               None, session.get("usuario"))
            con.execute("DELETE FROM bodega_ot_lineas WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        d = _datos()
        cantidad = core_flota._num(d.get("cantidad"))
        if cantidad is not None:
            if cantidad <= 0:
                return jsonify({"error": "la cantidad debe ser mayor que cero"}), 400
            con.execute("UPDATE bodega_ot_lineas SET cantidad=? WHERE id=?", (cantidad, id_))
        if "ubicacion_id" in d:
            con.execute("UPDATE bodega_ot_lineas SET ubicacion_id=? WHERE id=?", (d.get("ubicacion_id") or None, id_))
        con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ insumos en la operación

    @app.route("/api/bodega/aplicaciones", methods=["GET", "POST"])
    @login_requerido
    def api_bodega_aplicaciones():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            try:
                operacion_id = int(d.get("operacion_id"))
            except (TypeError, ValueError):
                return jsonify({"error": "falta la operación"}), 400
            r, error = core_bod.guardar_aplicaciones(con, operacion_id, d.get("productos") or [],
                                                     session.get("usuario"),
                                                     forzar=bool(d.get("forzar")) and _rol() == "admin")
            if error:
                con.rollback()
                return jsonify({"error": error}), 400
            con.commit()
            return jsonify({"ok": True, **r}), 201
        operacion_id = request.args.get("operacion_id", type=int)
        return jsonify(core_bod.aplicaciones_de(con, operacion_id) if operacion_id else [])

    @app.route("/api/bodega/conciliar")
    @login_requerido
    def api_bodega_conciliar():
        desde, hasta = _rango()
        return jsonify(core_bod.por_conciliar(get_con(), desde, hasta))

    @app.route("/api/bodega/control")
    @login_requerido
    def api_bodega_control():
        desde, hasta = _rango()
        r = core_bod.control_consumo(get_con(), desde, hasta)
        r["filtros"] = {"desde": desde, "hasta": hasta}
        return jsonify(r)

    @app.route("/api/bodega/control/<int:item_id>")
    @login_requerido
    def api_bodega_control_item(item_id):
        desde, hasta = _rango()
        return jsonify(core_bod.detalle_consumo(get_con(), item_id, desde, hasta))

    @app.route("/api/bodega/compras")
    @login_requerido
    def api_bodega_compras():
        return jsonify(core_bod.compras(get_con(), request.args.get("horizonte", default=core_bod.HORIZONTE_COMPRA, type=int)))

    @app.route("/api/bodega/registro-aplicaciones.csv")
    @login_requerido
    def api_bodega_registro_csv():
        """Registro RAC 137.71(3) en CSV (se abre en Excel): producto y cantidad por operación."""
        desde, hasta = _rango()
        filas = core_bod.registro_aplicaciones(get_con(), desde, hasta)
        salida = io.StringIO()
        salida.write("﻿")   # BOM: Excel reconoce las tildes
        w = csv.writer(salida, delimiter=";")
        w.writerow(["Fecha", "Aeronave", "Matrícula", "Piloto", "Cliente", "Zona", "Finca / lote", "Hectáreas",
                    "Litros de mezcla", "Producto", "Ingrediente activo", "Registro ICA", "Cat. toxicológica",
                    "Dosis por ha", "Cantidad teórica", "Cantidad descontada", "Unidad", "Lote del producto"])
        for f in filas:
            w.writerow([f["fecha"], f["equipo"], f["matricula"] or "", f["piloto"] or "", f["cliente"] or "",
                        f["zona"] or "", f["finca"] or "", _coma(f["hectareas"]), _coma(f["litros"]), f["producto"],
                        f["ingrediente_activo"] or "", f["registro_ica"] or "", f["categoria_tox"] or "",
                        _coma(f["dosis_ha"]), _coma(f["cantidad_teorica"]), _coma(f["descontado"]), f["unidad"],
                        f["lote_producto"] or ""])
        nombre = f"registro-aplicaciones-{desde or 'inicio'}-a-{hasta or 'hoy'}.csv"
        return Response(salida.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _coma(v):
    return "" if v is None else f"{v:g}".replace(".", ",")
