"""Rutas de la estación de combustible (core/combustible.py) y del marco normativo RAC
(core/rac.py). Se registran desde app.py igual que web_flota.
"""
from flask import jsonify, render_template, request, session

from core import combustible as core_comb
from core import flota as core_flota
from core import indicadores as core_ind
from core import rac as core_rac


def registrar(app, get_con, login_requerido, admin_requerido):

    def _datos():
        return request.get_json(silent=True) or {}

    def _rango():
        desde, hasta = request.args.get("desde") or None, request.args.get("hasta") or None
        if not desde and not hasta:
            desde, hasta = core_ind.periodo(request.args.get("periodo") or "90d")
        return desde, hasta

    # ------------------------------------------------------------------ páginas

    @app.route("/combustible")
    @login_requerido
    def pagina_combustible():
        return render_template("combustible.html", activo="combustible")

    @app.route("/normativa")
    @login_requerido
    def pagina_normativa():
        return render_template("normativa.html", activo="normativa")

    # ------------------------------------------------------------------ combustible

    @app.route("/api/combustible", methods=["GET", "POST"])
    @login_requerido
    def api_combustible():
        con = get_con()
        if request.method == "POST":
            c, error = core_comb.validar(con, _datos())
            if error:
                return jsonify({"error": error}), 400
            obligatorio = core_rac.faltantes_tanqueo(c)
            if obligatorio and not _datos().get("forzar"):
                return jsonify({"error": "falta el chequeo de seguridad: " + "; ".join(obligatorio),
                                "faltan": obligatorio}), 400
            id_ = core_comb.guardar(con, c, usuario=session.get("usuario"))
            con.commit()
            return jsonify({"ok": True, "id": id_}), 201
        desde, hasta = _rango()
        tipo = request.args.get("tipo") or None
        equipo_id = request.args.get("equipo_id", type=int)
        r = core_comb.resumen(con, desde, hasta, equipo_id)
        r["depositos"] = core_comb.depositos(con)
        for x in r["consumo"]:
            x["carga_actual"] = core_comb.carga_actual(con, x["equipo_id"])
        r["alertas"] = core_comb.alertas(con, desde, hasta)
        r["filtros"] = {"desde": desde, "hasta": hasta}
        return jsonify(r)

    @app.route("/api/combustible/config")
    @login_requerido
    def api_combustible_config():
        """Todo lo que el formulario de tanqueo necesita para guiar al usuario."""
        con = get_con()
        equipos = []
        for e in con.execute("SELECT * FROM equipos WHERE estado!='baja' AND tipo_activo='avion' ORDER BY nombre").fetchall():
            e = dict(e)
            esp = core_comb.espec_equipo(con, e)
            ult = con.execute("""SELECT fecha, galones, lectura, lleno FROM combustible_movimientos
                                 WHERE equipo_id=? AND tipo='tanqueo' ORDER BY fecha DESC, id DESC LIMIT 1""",
                              (e["id"],)).fetchone()
            lect = core_flota.lecturas(con, [e["id"]]).get(e["id"], {})
            equipos.append({"id": e["id"], "nombre": e["nombre"], "modelo": e["modelo"],
                            "tipo_activo": e["tipo_activo"], "matricula": e.get("matricula"),
                            "espec": esp, "ultimo": dict(ult) if ult else None,
                            "lectura_actual": lect.get("hobbs", lect.get("horas_vuelo"))})
        precios = {k: core_comb.ultimo_precio(con, k) for k in core_comb.COMBUSTIBLES}
        proveedores = [f["proveedor"] for f in con.execute(
            """SELECT proveedor, MAX(fecha) f FROM combustible_movimientos WHERE proveedor IS NOT NULL
               GROUP BY proveedor ORDER BY f DESC LIMIT 12""").fetchall()]
        return jsonify({
            "tipos": core_comb.TIPOS, "combustibles": core_comb.COMBUSTIBLES, "destinos": core_comb.DESTINOS,
            "chequeo_aeronave": [{"clave": k, "texto": t, "obligatorio": o, "rac": core_rac.norma_chequeo(k)}
                                 for k, t, o in core_comb.CHEQUEO_AERONAVE],
            "chequeo_apoyo": [{"clave": k, "texto": t, "obligatorio": o} for k, t, o in core_comb.CHEQUEO_APOYO],
            "equipos": equipos, "depositos": core_comb.depositos(con), "precios": precios,
            "proveedores": proveedores, "reservas": core_rac.RESERVAS_COMBUSTIBLE,
        })

    @app.route("/api/combustible/<int:id_>", methods=["GET", "PUT", "DELETE"])
    @login_requerido
    def api_combustible_mov(id_):
        con = get_con()
        fila = con.execute("SELECT * FROM combustible_movimientos WHERE id=?", (id_,)).fetchone()
        if not fila:
            return jsonify({"error": "no existe"}), 404
        if request.method == "DELETE":
            core_flota.auditar(con, "combustible_movimientos", id_, "borrado",
                               f"{fila['tipo']} {fila['galones']} gal {fila['fecha']}", None, session.get("usuario"))
            con.execute("DELETE FROM combustible_movimientos WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        if request.method == "PUT":
            datos = _datos()
            base = dict(fila)
            base.update(datos)
            # El total y el precio se derivan: si cambian galones, precio u origen y no llegan
            # explícitos, se recalculan (un tanqueo de depósito se revalora al costo del depósito).
            if {"galones", "precio_gal"} & datos.keys() and "total" not in datos:
                base["total"] = None
            if "deposito_id" in datos and fila["tipo"] == "tanqueo" and "precio_gal" not in datos:
                base["precio_gal"] = base["total"] = None
            if base.get("deposito_id") and fila["tipo"] == "tanqueo" and "combustible" not in datos:
                base["combustible"] = None
            c, error = core_comb.validar(con, base)
            if error:
                return jsonify({"error": error}), 400
            if c["tipo"] != fila["tipo"]:
                return jsonify({"error": "no se puede cambiar el tipo de movimiento"}), 400
            for k in core_comb.CAMPOS:
                antes, despues = fila[k], c[k]
                if k != "galones" or c["tipo"] != "medicion":
                    if (antes if antes not in ("",) else None) != despues and str(antes) != str(despues):
                        core_flota.auditar(con, "combustible_movimientos", id_, k, antes, despues, session.get("usuario"))
            core_comb.guardar(con, c, id_=id_)
            con.commit()
            return jsonify({"ok": True})
        m = [x for x in core_comb._movs(con) if x["id"] == id_][0]
        m["seguimiento"] = core_comb.seguimiento_tanqueo(con, id_)
        return jsonify(m)

    @app.route("/api/combustible/depositos", methods=["POST"])
    @login_requerido
    def api_combustible_depositos():
        con = get_con()
        d = _datos()
        nombre = (d.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"error": "falta el nombre"}), 400
        comb = d.get("combustible") if d.get("combustible") in core_comb.COMBUSTIBLES else "avgas_100ll"
        cur = con.execute("""INSERT INTO combustible_depositos(nombre, combustible, capacidad_gal, nivel_inicial_gal,
                                 fecha_inicial, ubicacion, nota) VALUES(?,?,?,?,?,?,?)""",
                          (nombre, comb, core_comb._num(d.get("capacidad_gal")) or 0,
                           core_comb._num(d.get("nivel_inicial_gal")) or 0, d.get("fecha_inicial") or None,
                           d.get("ubicacion") or None, d.get("nota") or None))
        con.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.route("/api/combustible/depositos/<int:id_>", methods=["GET", "PUT", "DELETE"])
    @login_requerido
    def api_combustible_deposito(id_):
        con = get_con()
        dep = con.execute("SELECT * FROM combustible_depositos WHERE id=?", (id_,)).fetchone()
        if not dep:
            return jsonify({"error": "no existe"}), 404
        if request.method == "DELETE":
            con.execute("DELETE FROM combustible_depositos WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        if request.method == "PUT":
            d = _datos()
            campos = {"nombre": d.get("nombre"), "capacidad_gal": core_comb._num(d.get("capacidad_gal")),
                      "nivel_inicial_gal": core_comb._num(d.get("nivel_inicial_gal")),
                      "fecha_inicial": d.get("fecha_inicial"), "ubicacion": d.get("ubicacion"),
                      "nota": d.get("nota"), "activo": d.get("activo")}
            if d.get("combustible") in core_comb.COMBUSTIBLES:
                campos["combustible"] = d["combustible"]
            campos = {k: v for k, v in campos.items() if k in d}
            if campos:
                con.execute(f"UPDATE combustible_depositos SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                            list(campos.values()) + [id_])
                con.commit()
            return jsonify({"ok": True})
        info = [x for x in core_comb.depositos(con) if x["id"] == id_][0]
        info["serie"] = core_comb.serie_deposito(con, id_)
        info["movimientos"] = core_comb._movs(con, deposito_id=id_)[:200]
        return jsonify(info)

    @app.route("/api/combustible/equipo/<int:id_>", methods=["GET", "PUT"])
    @login_requerido
    def api_combustible_equipo(id_):
        con = get_con()
        eq = con.execute("SELECT * FROM equipos WHERE id=?", (id_,)).fetchone()
        if not eq:
            return jsonify({"error": "no existe"}), 404
        if request.method == "PUT":
            core_comb.guardar_espec(con, id_, _datos())
            con.commit()
            return jsonify({"ok": True})
        desde, hasta = _rango()
        c = core_comb.consumo_equipos(con, desde, hasta, id_)[0]
        c["movimientos"] = core_comb._movs(con, desde, hasta, equipo_id=id_)
        cargas = core_comb.cargas_equipo(con, id_)
        c["carga_actual"] = cargas[-1] if cargas else None
        c["cargas"] = [{k: v for k, v in x.items() if k != "vuelos"} for x in reversed(cargas)
                       if (not desde or x["fecha"] >= desde) and (not hasta or x["fecha"] <= hasta)]
        c["por_mes"] = [dict(f) for f in con.execute(
            """SELECT substr(o.fecha,1,7) mes, SUM(o.horas_vuelo) horas, SUM(o.combustible_gal) reportado,
                      (SELECT SUM(galones) FROM combustible_movimientos m WHERE m.equipo_id=o.equipo_id
                         AND m.tipo='tanqueo' AND substr(m.fecha,1,7)=substr(o.fecha,1,7)) tanqueado
               FROM operaciones o WHERE o.equipo_id=? AND o.fecha>=COALESCE(?, '0000') AND o.fecha<=COALESCE(?, '9999')
               GROUP BY substr(o.fecha,1,7) ORDER BY 1""", (id_, desde, hasta)).fetchall()]
        return jsonify(c)

    # ------------------------------------------------------------------ normativa RAC

    @app.route("/api/normativa")
    @login_requerido
    def api_normativa():
        return jsonify(core_rac.estado_cumplimiento(get_con()))
