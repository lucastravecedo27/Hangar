"""Rutas de la flota mixta: modelos y catálogo, contadores, piezas con serial, baterías,
directivas, documentos, aeronavegabilidad, indicadores, planificador, rentabilidad, checklist
pre-vuelo y archivos adjuntos.

Se registran desde app.py con `registrar(app, get_con, login_requerido, admin_requerido)` para no
seguir engordando app.py y para que las dependencias (conexión con la empresa de la sesión,
permisos) sean exactamente las mismas que en el resto de la API.
"""
import json
import re
import secrets
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_from_directory, session

from core import alertas as core_alertas
from core import conexion as core_conexion
from core import config
from core import db as core_db
from core import flota as core_flota
from core import indicadores as core_ind
from core import ordenes as core_ordenes

DIR_ARCHIVOS = Path(config.RAIZ) / "datos" / "archivos"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}

# Puntos del chequeo pre-vuelo por tipo de activo. Cada punto puede llevar foto.
CHECKLIST = {
    "dron": [
        ("helices", "Hélices sin fisuras ni deformación"),
        ("brazos", "Brazos desplegados y bloqueados"),
        ("motores", "Motores giran libres, sin ruido"),
        ("baterias", "Baterías cargadas y sin hinchazón"),
        ("autonomia", "Vuelo planeado ≤ 80 % de la autonomía del fabricante (RAC 100.210(k))"),
        ("tanque", "Tanque, filtros y tapa en buen estado"),
        ("boquillas", "Boquillas / aspersores limpios"),
        ("mangueras", "Mangueras sin fugas"),
        ("radar", "Radar y cámaras limpios"),
        ("control", "Control remoto cargado y enlazado"),
        ("gps", "Señal GNSS/RTK correcta"),
        ("documentos_uas", "Registro, póliza y autorización de vuelo a mano (RAC 100.225)"),
    ],
    "avion": [
        ("documentos", "Documentos a bordo: matrícula, aeronavegabilidad, licencia de radio (RAC 91.1420)"),
        ("combustible", "Combustible para las aspersiones planeadas + 30 min de reserva (RAC 137.35(n), 91.610)"),
        ("drenaje", "Drenaje de sumideros: muestra sin agua ni sedimentos"),
        ("aceite", "Nivel de aceite del motor"),
        ("helice", "Hélice sin mellas ni fisuras"),
        ("capo", "Capó y fijaciones"),
        ("superficies", "Superficies de control libres y sin daños"),
        ("tren", "Tren principal, frenos y rueda de cola"),
        ("neumaticos", "Presión y estado de neumáticos"),
        ("tolva", "Tolva, compuerta y sello"),
        ("bomba", "Bomba de aspersión y molinete"),
        ("barras", "Barras, boquillas y válvula de corte"),
        ("arnes", "Arnés y cinturones"),
        ("instrumentos", "Instrumentos y GPS de guiado"),
        ("elt", "ELT armado y dentro de su inspección (RAC 91.830)"),
        ("piloto_apto", "Piloto apto: médico y colinesterasa vigentes, descansado (RAC 137.73)"),
    ],
}


def registrar(app, get_con, login_requerido, admin_requerido):

    def _usuario():
        return session.get("usuario")

    def _rol():
        return session.get("rol", "admin")

    def _datos():
        return request.get_json(silent=True) or {}

    def _num(v):
        return core_flota._num(v)

    def _filtros():
        per = request.args.get("periodo") or "30d"
        desde, hasta = request.args.get("desde") or None, request.args.get("hasta") or None
        if not desde and not hasta:
            desde, hasta = core_ind.periodo(per)
        return core_ind.Filtros(tipo=request.args.get("tipo") or None,
                                equipo_id=request.args.get("equipo_id", type=int), desde=desde, hasta=hasta)

    # ------------------------------------------------------------------ páginas

    @app.route("/flota")
    @login_requerido
    def pagina_flota():
        return render_template("inventario.html", activo="inventario")

    @app.route("/flota/<int:id_>")
    @login_requerido
    def pagina_activo(id_):
        return render_template("activo.html", activo="inventario", equipo_id=id_)

    @app.route("/flota/<int:id_>/diagrama")
    @login_requerido
    def pagina_diagrama_avion(id_):
        return render_template("avion_diagrama.html", activo="inventario", equipo_id=id_)

    @app.route("/aeronavegabilidad")
    @login_requerido
    def pagina_aeronavegabilidad():
        return render_template("aeronavegabilidad.html", activo="aeronavegabilidad")

    @app.route("/planificador")
    @login_requerido
    def pagina_planificador():
        return render_template("planificador.html", activo="planificador")

    @app.route("/rentabilidad")
    @admin_requerido
    def pagina_rentabilidad():
        return render_template("rentabilidad.html", activo="rentabilidad")

    @app.route("/catalogo")
    @login_requerido
    def pagina_catalogo():
        return render_template("catalogo.html", activo="catalogo")

    @app.route("/checklist")
    @login_requerido
    def pagina_checklist():
        return render_template("checklist.html", activo="checklist")

    # ------------------------------------------------------------------ modelos y catálogo

    @app.route("/api/modelos-activo", methods=["GET", "POST"])
    @login_requerido
    def api_modelos_activo():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            nombre = (d.get("nombre") or "").strip()
            if not nombre:
                return jsonify({"error": "falta el nombre"}), 400
            tipo = d.get("tipo_activo") or "avion"
            if tipo not in core_flota.TIPOS_ACTIVO:
                return jsonify({"error": "tipo de activo no válido"}), 400
            clave = core_flota.crear_modelo(con, nombre, tipo, d.get("fabricante"), d.get("contadores"),
                                            d.get("descripcion"), desde_plantilla=d.get("plantilla") or None)
            con.commit()
            return jsonify({"ok": True, "clave": clave, "modelo": core_flota.modelo_activo(con, clave)}), 201
        return jsonify({"modelos": core_flota.modelos(con, request.args.get("tipo") or None),
                        "contadores": {k: {"nombre": v[0], "unidad": v[1]} for k, v in core_flota.CONTADORES.items()},
                        "tipos": core_flota.TIPOS_ACTIVO, "contadores_por_tipo": core_flota.CONTADORES_POR_TIPO,
                        "tipos_item": core_flota.TIPOS_ITEM})

    @app.route("/api/modelos-activo/<clave>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_modelo_activo(clave):
        con = get_con()
        m = core_flota.modelo_activo(con, clave)
        if not m:
            return jsonify({"error": "no existe"}), 404
        if not m["propio"]:
            return jsonify({"error": "los modelos del sistema no se editan; crea uno propio desde la plantilla"}), 403
        if request.method == "DELETE":
            if con.execute("SELECT 1 FROM equipos WHERE modelo=?", (clave,)).fetchone():
                return jsonify({"error": "hay activos de este modelo; dalos de baja o cámbialos primero"}), 409
            con.execute("DELETE FROM catalogo_piezas WHERE modelo=?", (clave,))
            con.execute("DELETE FROM modelos_activo WHERE clave=?", (clave,))
            con.commit()
            return jsonify({"ok": True})
        d = _datos()
        campos, valores = [], []
        for c in ("nombre", "fabricante", "descripcion"):
            if c in d:
                campos.append(f"{c}=?"); valores.append(d[c])
        if "contadores" in d:
            campos.append("contadores=?")
            valores.append(",".join(x for x in d["contadores"] if x in core_flota.CONTADORES))
        if campos:
            con.execute(f"UPDATE modelos_activo SET {', '.join(campos)} WHERE clave=?", valores + [clave])
            con.commit()
        return jsonify({"ok": True, "modelo": core_flota.modelo_activo(con, clave)})

    CAMPOS_ITEM = ("modulo", "nombre", "tipo_item", "contador_base", "vida_util_horas", "vida_util_meses",
                   "contador_ciclos", "limite_ciclos", "tolerancia", "serializada", "nota", "precio", "referencia")

    @app.route("/api/catalogo/items", methods=["GET", "POST"])
    @login_requerido
    def api_catalogo_items():
        con = get_con()
        modelo = request.args.get("modelo") or _datos().get("modelo")
        if request.method == "POST":
            m = core_flota.modelo_activo(con, modelo)
            if not m or not m["propio"]:
                return jsonify({"error": "sólo se agregan ítems a modelos propios"}), 403
            d = _datos()
            if not (d.get("nombre") or "").strip():
                return jsonify({"error": "falta el nombre"}), 400
            clave = re.sub(r"[^a-z0-9_]+", "_", (d.get("clave") or d["nombre"]).lower()).strip("_")[:40] or "item"
            base, n = clave, 1
            while con.execute("SELECT 1 FROM catalogo_piezas WHERE modelo=? AND clave=?", (modelo, clave)).fetchone():
                n += 1; clave = f"{base}_{n}"
            core_flota._sembrar_items(con, modelo, [{
                "clave": clave, "modulo": d.get("modulo") or "General", "nombre": d["nombre"].strip(),
                "tipo_item": d.get("tipo_item") or "pieza", "contador": d.get("contador_base") or "horas_vuelo",
                "limite": _num(d.get("vida_util_horas")), "meses": _num(d.get("vida_util_meses")),
                "contador_ciclos": d.get("contador_ciclos") or None, "limite_ciclos": _num(d.get("limite_ciclos")),
                "tolerancia": _num(d.get("tolerancia")), "serializada": bool(d.get("serializada")),
                "nota": d.get("nota"), "precio": _num(d.get("precio"))}], empresa_id=con.empresa_id)
            core_flota.completar_componentes(con, modelo)
            con.commit()
            return jsonify({"ok": True, "clave": clave}), 201
        filas = con.execute("SELECT * FROM catalogo_piezas WHERE modelo=? ORDER BY tipo_item DESC, modulo, nombre",
                            (modelo,)).fetchall()
        return jsonify([dict(f) for f in filas])

    @app.route("/api/catalogo/items/<int:id_>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_catalogo_item(id_):
        con = get_con()
        it = con.execute("SELECT * FROM catalogo_piezas WHERE id=?", (id_,)).fetchone()
        if not it:
            return jsonify({"error": "no existe"}), 404
        if it["empresa_id"] is None:
            return jsonify({"error": "los ítems del sistema no se editan"}), 403
        if request.method == "DELETE":
            con.execute("DELETE FROM catalogo_piezas WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        d = _datos()
        campos, valores = [], []
        for c in CAMPOS_ITEM:
            if c in d:
                v = d[c]
                if c in ("vida_util_horas", "vida_util_meses", "limite_ciclos", "tolerancia", "precio"):
                    v = _num(v) or 0 if c != "precio" else _num(v)
                if c in ("serializada", "referencia"):
                    v = 1 if v else 0
                if c in ("contador_base", "contador_ciclos") and v and v not in core_flota.CONTADORES:
                    return jsonify({"error": f"contador no válido: {v}"}), 400
                campos.append(f"{c}=?"); valores.append(v or None if c == "contador_ciclos" else v)
        if campos:
            con.execute(f"UPDATE catalogo_piezas SET {', '.join(campos)} WHERE id=?", valores + [id_])
            core_flota.auditar(con, "catalogo_piezas", id_, ",".join(c for c in CAMPOS_ITEM if c in d),
                               None, json.dumps({c: d[c] for c in CAMPOS_ITEM if c in d}, ensure_ascii=False),
                               _usuario(), "Edición de catálogo")
            for e in con.execute("SELECT DISTINCT equipo_id FROM componentes WHERE pieza_id=?", (id_,)).fetchall():
                core_flota.recalcular_equipo(con, e["equipo_id"])
            con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ contadores

    @app.route("/api/equipos/<int:id_>/contadores", methods=["GET", "PUT"])
    @login_requerido
    def api_contadores(id_):
        con = get_con()
        if not con.execute("SELECT 1 FROM equipos WHERE id=?", (id_,)).fetchone():
            return jsonify({"error": "no existe"}), 404
        if request.method == "PUT":
            d = _datos()
            contador, valor = d.get("contador"), _num(d.get("valor"))
            if contador not in core_flota.CONTADORES or valor is None:
                return jsonify({"error": "contador o valor no válido"}), 400
            core_flota.ajustar_contador(con, id_, contador, valor, _usuario(), (d.get("motivo") or "Ajuste de lectura"))
            con.commit()
        return jsonify(core_flota.lecturas(con, [id_]).get(id_, {}))

    # ------------------------------------------------------------------ piezas con serial

    @app.route("/api/piezas-serie", methods=["GET", "POST"])
    @login_requerido
    def api_piezas_serie():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            if not (d.get("serial") or "").strip():
                return jsonify({"error": "falta el serial"}), 400
            pid = core_flota.crear_pieza_serie(con, d)
            if d.get("componente_id"):
                try:
                    core_flota.instalar(con, pid, int(d["componente_id"]), d.get("fecha"), _usuario(), "Alta")
                except ValueError as e:
                    con.rollback()
                    return jsonify({"error": str(e)}), 400
            con.commit()
            return jsonify({"ok": True, "id": pid}), 201
        return jsonify(core_flota.piezas_serie(con, request.args.get("tipo") or None,
                                               request.args.get("equipo_id", type=int), request.args.get("estado") or None))

    @app.route("/api/piezas-serie/<int:id_>", methods=["GET", "PUT"])
    @login_requerido
    def api_pieza_serie(id_):
        con = get_con()
        if request.method == "PUT":
            d = _datos()
            campos, valores = [], []
            for c in ("descripcion", "fecha_compra", "nota", "pieza_clave"):
                if c in d:
                    campos.append(f"{c}=?"); valores.append(d[c] or None)
            for c in ("precio", "vida_ciclos", "tsn_inicial"):
                if c in d:
                    campos.append(f"{c}=?"); valores.append(_num(d[c]))
            if campos:
                con.execute(f"UPDATE piezas_serie SET {', '.join(campos)} WHERE id=?", valores + [id_])
                con.commit()
        fila = next((p for p in core_flota.piezas_serie(con) if p["id"] == id_), None)
        if not fila:
            return jsonify({"error": "no existe"}), 404
        fila["instalaciones"] = core_flota.instalaciones_de(con, id_)
        return jsonify(fila)

    @app.route("/api/piezas-serie/<int:id_>/instalar", methods=["POST"])
    @login_requerido
    def api_pieza_instalar(id_):
        con = get_con()
        d = _datos()
        try:
            core_flota.instalar(con, id_, int(d.get("componente_id")), d.get("fecha"), _usuario(), d.get("motivo"))
        except (TypeError, ValueError) as e:
            con.rollback()
            return jsonify({"error": str(e) or "datos no válidos"}), 400
        con.commit()
        return jsonify({"ok": True})

    @app.route("/api/piezas-serie/<int:id_>/desmontar", methods=["POST"])
    @login_requerido
    def api_pieza_desmontar(id_):
        con = get_con()
        d = _datos()
        try:
            core_flota.desmontar(con, id_, d.get("fecha"), _usuario(), d.get("motivo"), d.get("estado") or "bodega")
        except ValueError as e:
            con.rollback()
            return jsonify({"error": str(e)}), 400
        con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ baterías

    @app.route("/api/baterias", methods=["GET", "POST"])
    @login_requerido
    def api_baterias():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            if not (d.get("serial") or "").strip():
                return jsonify({"error": "falta el serial"}), 400
            d["tipo"] = "bateria"
            bid = core_flota.crear_pieza_serie(con, d)
            if d.get("equipo_id"):
                core_flota.asignar_bateria(con, bid, int(d["equipo_id"]), d.get("fecha"))
            con.commit()
            return jsonify({"ok": True, "id": bid}), 201
        return jsonify(core_flota.baterias(con, request.args.get("equipo_id", type=int)))

    @app.route("/api/baterias/<int:id_>", methods=["PUT"])
    @login_requerido
    def api_bateria(id_):
        con = get_con()
        d = _datos()
        try:
            if "equipo_id" in d:
                core_flota.asignar_bateria(con, id_, int(d["equipo_id"]) if d["equipo_id"] else None, d.get("fecha"))
            if d.get("ciclos") not in (None, ""):
                core_flota.leer_ciclos_bateria(con, id_, _num(d["ciclos"]))
            for c in ("vida_ciclos", "precio"):
                if c in d:
                    con.execute(f"UPDATE piezas_serie SET {c}=? WHERE id=? AND tipo='bateria'", (_num(d[c]), id_))
            if d.get("baja"):
                con.execute("UPDATE piezas_serie SET estado='baja', equipo_id=NULL WHERE id=?", (id_,))
        except ValueError as e:
            con.rollback()
            return jsonify({"error": str(e)}), 400
        con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ directivas

    CAMPOS_DIRECTIVA = ("modelo", "numero", "tipo", "titulo", "descripcion", "aplica_a", "recurrente",
                        "intervalo_valor", "intervalo_contador", "intervalo_dias", "limite_fecha", "limite_valor",
                        "fuente", "url")

    def _valor_directiva(c, v):
        if c in ("intervalo_valor", "limite_valor"):
            return _num(v)
        if c == "intervalo_dias":
            n = _num(v)
            return int(n) if n else None
        if c == "recurrente":
            return 1 if v else 0
        return (str(v).strip() or None) if v is not None else None

    @app.route("/api/directivas", methods=["GET", "POST"])
    @login_requerido
    def api_directivas():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            if not (d.get("numero") or "").strip() or not (d.get("titulo") or "").strip():
                return jsonify({"error": "número y título son obligatorios"}), 400
            cols = [c for c in CAMPOS_DIRECTIVA if c in d]
            cur = con.execute(f"INSERT INTO directivas({', '.join(cols)}) VALUES({','.join('?' * len(cols))})",
                              [_valor_directiva(c, d[c]) for c in cols])
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        directivas = [dict(f) for f in con.execute("SELECT * FROM directivas ORDER BY modelo, numero").fetchall()]
        return jsonify({"directivas": directivas,
                        "estado": core_flota.directivas_con_estado(con, request.args.get("equipo_id", type=int))})

    @app.route("/api/directivas/<int:id_>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_directiva(id_):
        con = get_con()
        if request.method == "DELETE":
            con.execute("DELETE FROM cumplimiento_directiva WHERE directiva_id=?", (id_,))
            con.execute("DELETE FROM directivas WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        d = _datos()
        cols = [c for c in CAMPOS_DIRECTIVA if c in d]
        if cols:
            con.execute(f"UPDATE directivas SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                        [_valor_directiva(c, d[c]) for c in cols] + [id_])
            con.commit()
        return jsonify({"ok": True})

    @app.route("/api/directivas/<int:id_>/cumplir", methods=["POST"])
    @login_requerido
    def api_directiva_cumplir(id_):
        con = get_con()
        d = _datos()
        estado = d.get("estado") or "cumplida"
        if estado == "cumplida" and _rol() not in ("admin", core_db.ROL_SUPERADMIN, "certificador"):
            return jsonify({"error": "sólo un mecánico certificador o un administrador registra el cumplimiento"}), 403
        if estado == "cumplida" and not (d.get("firmado_por") and d.get("licencia")):
            return jsonify({"error": "el cumplimiento lleva nombre y licencia de quien firma"}), 400
        try:
            core_flota.cumplir_directiva(con, id_, int(d.get("equipo_id")), estado, d.get("fecha"),
                                         d.get("firmado_por"), d.get("licencia"), d.get("nota"), d.get("orden_id"))
        except (TypeError, ValueError) as e:
            con.rollback()
            return jsonify({"error": str(e) or "datos no válidos"}), 400
        con.commit()
        return jsonify({"ok": True})

    @app.route("/api/directivas/<int:id_>/historial")
    @login_requerido
    def api_directiva_historial(id_):
        con = get_con()
        return jsonify([dict(f) for f in con.execute(
            "SELECT c.*, e.nombre equipo, e.matricula FROM cumplimiento_directiva c JOIN equipos e ON e.id=c.equipo_id "
            "WHERE c.directiva_id=? ORDER BY c.fecha DESC, c.id DESC", (id_,)).fetchall()])

    # ------------------------------------------------------------------ documentos

    CAMPOS_DOC = ("equipo_id", "personal_id", "tipo", "numero", "emitido", "vence", "nota", "archivo")

    @app.route("/api/documentos", methods=["GET", "POST"])
    @login_requerido
    def api_documentos():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            if not d.get("tipo"):
                return jsonify({"error": "falta el tipo de documento"}), 400
            if not d.get("equipo_id") and not d.get("personal_id"):
                return jsonify({"error": "el documento es de un activo o de una persona"}), 400
            cols = [c for c in CAMPOS_DOC if c in d]
            cur = con.execute(f"INSERT INTO documentos({', '.join(cols)}) VALUES({','.join('?' * len(cols))})",
                              [d[c] or None for c in cols])
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        return jsonify({"documentos": core_flota.documentos_con_estado(con, request.args.get("equipo_id", type=int)),
                        "tipos": core_flota.TIPOS_DOCUMENTO})

    @app.route("/api/documentos/<int:id_>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_documento(id_):
        con = get_con()
        if request.method == "DELETE":
            con.execute("DELETE FROM documentos WHERE id=?", (id_,))
            con.commit()
            return jsonify({"ok": True})
        d = _datos()
        cols = [c for c in CAMPOS_DOC if c in d]
        if cols:
            con.execute(f"UPDATE documentos SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                        [d[c] or None for c in cols] + [id_])
            con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ aeronavegabilidad

    @app.route("/api/aeronavegabilidad")
    @login_requerido
    def api_aeronavegabilidad():
        con = get_con()
        tipo = request.args.get("tipo") or None
        equipos = [dict(e) for e in con.execute(
            "SELECT id, nombre, modelo, matricula, tipo_activo, estado, horas_totales FROM equipos "
            "WHERE estado != 'baja'" + (" AND tipo_activo=?" if tipo else "") + " ORDER BY tipo_activo DESC, nombre",
            (tipo,) if tipo else ()).fetchall()]
        estados = core_alertas.estado_flota(con, equipos)
        # Foto del día para la disponibilidad histórica (antes de pisar `estado` con el de aeronavegabilidad).
        try:
            core_flota.registrar_estado_diario(con, estados, [{"id": e["id"], "estado": e["estado"]} for e in equipos])
            con.commit()
        except Exception:
            con.rollback()
        lect = core_flota.lecturas(con, [e["id"] for e in equipos])
        for e in equipos:
            e["estado_equipo"] = e["estado"]
            e.update(estados.get(e["id"], {"estado": "apto", "estado_txt": "Apto", "motivos": []}))
            e["contadores"] = lect.get(e["id"], {})
        conteo = {k: sum(1 for e in equipos if e["estado"] == k) for k in core_flota.ESTADOS_AERO}
        return jsonify({"equipos": equipos, "conteo": conteo,
                        "alertas": core_alertas.alertas_todas(con, tipo)[:200]})

    # ------------------------------------------------------------------ disponibilidad histórica

    @app.route("/api/disponibilidad")
    @login_requerido
    def api_disponibilidad():
        con = get_con()
        f = _filtros()
        if not request.args.get("periodo") and not request.args.get("desde"):
            f = replace(f, desde=(date.today() - timedelta(days=89)).isoformat(), hasta=date.today().isoformat())
        d = core_flota.disponibilidad(con, f.desde, f.hasta, f.tipo, f.equipo_id)
        d["mttr"] = core_flota.mttr(con, f.desde, f.hasta, f.tipo, f.equipo_id)
        d["desde"], d["hasta"] = f.desde, f.hasta
        return jsonify(d)

    # ------------------------------------------------------------------ indicadores

    @app.route("/api/indicadores")
    @login_requerido
    def api_indicadores():
        con = get_con()
        f = _filtros()
        claves = [c for c in (request.args.get("claves") or "").split(",") if c] or None
        agrupar = request.args.get("agrupar")
        salida = {"filtros": {"tipo": f.tipo, "equipo_id": f.equipo_id, "desde": f.desde, "hasta": f.hasta}}
        if agrupar == "tipo":
            salida["por_tipo"] = core_ind.por_tipo(con, claves, f)
        elif agrupar == "activo":
            salida["por_activo"] = core_ind.por_activo(con, claves, f)
        else:
            salida["indicadores"] = core_ind.calcular(con, claves, f)
        series = [c for c in (request.args.get("series") or "").split(",") if c in core_ind.REGISTRO]
        if series:
            salida["series"] = {c: core_ind.serie_mensual(con, c, replace(f, desde=None, hasta=None)) for c in series}
        return jsonify(salida)

    @app.route("/api/indicadores/catalogo")
    @login_requerido
    def api_indicadores_catalogo():
        return jsonify(core_ind.catalogo())

    # ------------------------------------------------------------------ planificador

    @app.route("/api/planificador")
    @login_requerido
    def api_planificador():
        """Semana (o rango) de la flota: por activo, sus OS de vuelo, OT de mantenimiento y
        operaciones hechas; con su estado de aeronavegabilidad y la carga de cada piloto."""
        con = get_con()
        hoy = date.today()
        desde = request.args.get("desde") or (hoy - timedelta(days=hoy.weekday())).isoformat()
        try:
            d0 = date.fromisoformat(desde)
        except ValueError:
            return jsonify({"error": "fecha no válida"}), 400
        dias = min(max(request.args.get("dias", default=7, type=int), 1), 42)
        hasta = (d0 + timedelta(days=dias - 1)).isoformat()
        tipo = request.args.get("tipo") or None
        equipos = [dict(e) for e in con.execute(
            "SELECT id, nombre, modelo, matricula, tipo_activo, estado FROM equipos WHERE estado != 'baja'"
            + (" AND tipo_activo=?" if tipo else "") + " ORDER BY tipo_activo DESC, nombre",
            (tipo,) if tipo else ()).fetchall()]
        estados = core_alertas.estado_flota(con, equipos)
        os_ = [dict(f) for f in con.execute(
            "SELECT id, codigo, equipo_id, piloto, cliente, finca, fecha, hora, hectareas, estado FROM ordenes_servicio "
            "WHERE fecha BETWEEN ? AND ? AND estado != 'cancelada'", (desde, hasta)).fetchall()]
        ot = [dict(f) for f in con.execute(
            "SELECT id, codigo, equipo_id, titulo, asignado_a, fecha_programada fecha, estado, prioridad "
            "FROM ordenes_trabajo WHERE fecha_programada BETWEEN ? AND ? AND estado != 'cancelada'",
            (desde, hasta)).fetchall()]
        ops = [dict(f) for f in con.execute(
            "SELECT equipo_id, fecha, COUNT(*) n, ROUND(SUM(horas_vuelo),1) horas, ROUND(COALESCE(SUM(hectareas),0),1) ha, "
            + ("group_concat(DISTINCT piloto) pilotos" if core_conexion.ES_SQLITE else "string_agg(DISTINCT piloto, ', ') pilotos")
            + " FROM operaciones WHERE fecha BETWEEN ? AND ? "
            "GROUP BY equipo_id, fecha", (desde, hasta)).fetchall()]
        pilotos = [dict(f) for f in con.execute(
            "SELECT piloto, fecha, ROUND(SUM(horas_vuelo),1) horas FROM operaciones "
            "WHERE fecha BETWEEN ? AND ? AND piloto IS NOT NULL GROUP BY piloto, fecha ORDER BY piloto, fecha",
            (desde, hasta)).fetchall()]
        # Avisos: OS sobre activo no apto, piloto con licencia vencida, OS sin activo.
        licencias = {p["nombre"]: p for p in core_db.contactos(con, "piloto")}
        avisos = []
        for o in os_:
            est = estados.get(o["equipo_id"])
            if o["equipo_id"] and est and est["estado"] == "no_apto" and o["estado"] not in ("finalizada",):
                avisos.append({"tipo": "no_apto", "os": o["codigo"], "texto": f"{o['codigo']}: no recomendamos volar el activo ({'; '.join(est['motivos'][:2])})"})
            p = licencias.get(o["piloto"] or "")
            if p and p.get("licencia_vencida"):
                avisos.append({"tipo": "licencia", "os": o["codigo"], "texto": f"{o['codigo']}: la licencia de {o['piloto']} está vencida"})
            if not o["equipo_id"]:
                avisos.append({"tipo": "sin_activo", "os": o["codigo"], "texto": f"{o['codigo']}: sin activo asignado"})
        limite_piloto = core_ind._meta_num(con, "horas_max_piloto_dia", 8)
        for p in pilotos:
            if p["horas"] and p["horas"] > limite_piloto:
                avisos.append({"tipo": "carga", "texto": f"{p['piloto']} voló {p['horas']} h el {p['fecha']} (límite {limite_piloto:g} h)"})
        for e in equipos:
            e.update(estados.get(e["id"], {}))
        return jsonify({"desde": desde, "hasta": hasta, "dias": dias, "equipos": equipos, "os": os_, "ot": ot,
                        "operaciones": ops, "pilotos": pilotos, "avisos": avisos})

    # ------------------------------------------------------------------ rentabilidad y costos

    @app.route("/api/rentabilidad")
    @admin_requerido
    def api_rentabilidad():
        con = get_con()
        f = _filtros()
        claves = ["hectareas", "horas", "costo_mant", "costo_mant_hora", "costo_combustible_hora", "costo_ha",
                  "ingreso_ha", "margen", "consumo"]
        total = core_ind.calcular(con, claves, f)
        activos = core_ind.por_activo(con, ["hectareas", "horas", "costo_mant", "costo_ha", "ingreso_ha", "margen"], f)
        w, p = f.where()
        precio = core_ind._meta_num(con, "precio_combustible_gal") or 0
        clientes = [dict(r) for r in con.execute(f"""
            SELECT COALESCE(o.cliente,'Sin cliente') cliente, COALESCE(o.lote,'') finca, e.tipo_activo,
                   ROUND(COALESCE(SUM(o.hectareas),0),1) ha, ROUND(SUM(o.horas_vuelo),1) horas,
                   ROUND(COALESCE(SUM(o.combustible_gal),0) * ?, 0) combustible,
                   ROUND(COALESCE(SUM(o.hectareas * (
                        SELECT t.valor_ha FROM tarifas t WHERE lower(t.cliente)=lower(o.cliente)
                          AND (t.tipo_activo='todos' OR t.tipo_activo=e.tipo_activo)
                          AND (t.desde IS NULL OR t.desde <= o.fecha)
                        ORDER BY (t.tipo_activo=e.tipo_activo) DESC, t.desde DESC NULLS LAST LIMIT 1)),0), 0) ingreso
            FROM operaciones o JOIN equipos e ON e.id=o.equipo_id WHERE {w}
            GROUP BY 1, 2, 3 ORDER BY ingreso DESC, ha DESC LIMIT 60""", [precio] + p).fetchall()]
        # Costo de mantenimiento repartido por hora de vuelo del activo en el período.
        mant_hora = {a["id"]: a["indicadores"].get("costo_mant", {}).get("valor") for a in activos}
        horas_act = {a["id"]: a["indicadores"].get("horas", {}).get("valor") for a in activos}
        por_cliente_activo = [dict(r) for r in con.execute(f"""
            SELECT COALESCE(o.cliente,'Sin cliente') cliente, COALESCE(o.lote,'') finca, o.equipo_id, SUM(o.horas_vuelo) h
            FROM operaciones o WHERE {w} GROUP BY 1, 2, 3""", p).fetchall()]
        mant_cf = {}
        for r in por_cliente_activo:
            if mant_hora.get(r["equipo_id"]) and horas_act.get(r["equipo_id"]):
                k = (r["cliente"], r["finca"])
                mant_cf[k] = mant_cf.get(k, 0) + mant_hora[r["equipo_id"]] * (r["h"] or 0) / horas_act[r["equipo_id"]]
        for c in clientes:
            c["mantenimiento"] = round(mant_cf.get((c["cliente"], c["finca"]), 0))
            c["margen"] = round((c["ingreso"] or 0) - (c["combustible"] or 0) - c["mantenimiento"]) if c["ingreso"] else None
            c["margen_ha"] = round(c["margen"] / c["ha"]) if c["margen"] is not None and c["ha"] else None
        return jsonify({"total": total, "activos": activos, "clientes": clientes,
                        "config": _config_costos(con), "tarifas": _tarifas(con),
                        "filtros": {"tipo": f.tipo, "desde": f.desde, "hasta": f.hasta}})

    CLAVES_CONFIG = ("precio_combustible_gal", "costo_hora_mano_obra", "moneda", "ventana_viento_max",
                     "ventana_temp_max", "ventana_humedad_min", "horas_max_piloto_dia", "meta_ha_mes")

    def _config_costos(con):
        return {c: core_db.meta_get(con, c) for c in CLAVES_CONFIG}

    def _tarifas(con):
        return [dict(t) for t in con.execute("SELECT * FROM tarifas ORDER BY cliente, tipo_activo, desde DESC").fetchall()]

    @app.route("/api/costos/config", methods=["GET", "PUT"])
    @login_requerido
    def api_costos_config():
        con = get_con()
        if request.method == "PUT":
            if _rol() not in ("admin", core_db.ROL_SUPERADMIN):
                return jsonify({"error": "tu rol no permite esta acción"}), 403
            d = _datos()
            for c in CLAVES_CONFIG:
                if c in d:
                    v = d[c]
                    if c != "moneda" and v not in (None, "") and _num(v) is None:
                        return jsonify({"error": f"{c} debe ser numérico"}), 400
                    con.execute("INSERT INTO meta(clave, valor) VALUES(?,?) ON CONFLICT(empresa_id, clave) "
                                "DO UPDATE SET valor=excluded.valor", (c, None if v in (None, "") else str(v)))
            con.commit()
        return jsonify(_config_costos(con))

    @app.route("/api/tarifas", methods=["GET", "POST"])
    @login_requerido
    def api_tarifas():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            valor = _num(d.get("valor_ha"))
            if not (d.get("cliente") or "").strip() or valor is None:
                return jsonify({"error": "cliente y valor por hectárea son obligatorios"}), 400
            tipo = d.get("tipo_activo") or "todos"
            if tipo not in ("todos", *core_flota.TIPOS_ACTIVO):
                return jsonify({"error": "tipo no válido"}), 400
            cur = con.execute("INSERT INTO tarifas(cliente, tipo_activo, valor_ha, desde, nota) VALUES(?,?,?,?,?)",
                              (d["cliente"].strip(), tipo, valor, d.get("desde") or None, d.get("nota") or None))
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid}), 201
        clientes = [r["cliente"] for r in con.execute(
            "SELECT DISTINCT cliente FROM operaciones WHERE cliente IS NOT NULL ORDER BY 1").fetchall()]
        return jsonify({"tarifas": _tarifas(con), "clientes": clientes})

    @app.route("/api/tarifas/<int:id_>", methods=["PUT", "DELETE"])
    @login_requerido
    def api_tarifa(id_):
        con = get_con()
        if request.method == "DELETE":
            con.execute("DELETE FROM tarifas WHERE id=?", (id_,))
        else:
            d = _datos()
            for c in ("cliente", "tipo_activo", "desde", "nota"):
                if c in d:
                    con.execute(f"UPDATE tarifas SET {c}=? WHERE id=?", (d[c] or None, id_))
            if "valor_ha" in d:
                con.execute("UPDATE tarifas SET valor_ha=? WHERE id=?", (_num(d["valor_ha"]), id_))
        con.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ checklist pre-vuelo

    @app.route("/api/checklists", methods=["GET", "POST"])
    @login_requerido
    def api_checklists():
        con = get_con()
        if request.method == "POST":
            d = _datos()
            try:
                equipo_id = int(d.get("equipo_id"))
            except (TypeError, ValueError):
                return jsonify({"error": "falta el activo"}), 400
            eq = con.execute("SELECT id, nombre, tipo_activo FROM equipos WHERE id=?", (equipo_id,)).fetchone()
            if not eq:
                return jsonify({"error": "el activo no existe"}), 404
            plantilla = dict(CHECKLIST.get(eq["tipo_activo"], CHECKLIST["dron"]))
            items = []
            for it in d.get("items") or []:
                if it.get("clave") not in plantilla:
                    continue
                ok = bool(it.get("ok"))
                items.append({"clave": it["clave"], "texto": plantilla[it["clave"]], "ok": ok,
                              "nota": (it.get("nota") or "").strip() or None, "foto": it.get("foto") or None})
            faltan = [k for k in plantilla if k not in {i["clave"] for i in items}]
            if faltan:
                return jsonify({"error": "faltan puntos por revisar", "faltan": faltan}), 400
            fallas = [i for i in items if not i["ok"]]
            if any(not i["nota"] and not i["foto"] for i in fallas):
                return jsonify({"error": "cada punto con falla lleva una nota o una foto"}), 400
            # El resultado combina lo que vio el piloto con el estado de mantenimiento: aunque la
            # revisión visual salga bien, si hay algo vencido recomendamos no volar.
            mant = core_alertas.estado_flota(con).get(equipo_id) or {"estado": "apto", "motivos": []}
            if fallas:
                resultado = "no_apto"
            elif mant["estado"] == "no_apto":
                resultado = "no_recomendado"
            elif mant["estado"] == "observaciones":
                resultado = "observaciones"
            else:
                resultado = "apto"
            orden_id = None
            if fallas:
                # Lo que falla en el chequeo abre una orden de trabajo sola, para el técnico.
                orden_id = core_ordenes.crear_ot(con, {
                    "equipo_id": equipo_id, "titulo": f"Falla en chequeo pre-vuelo · {eq['nombre']}",
                    "tipo": "correctivo", "prioridad": "alta", "estado": "borrador",
                    "fecha_programada": date.today().isoformat(),
                    "observaciones": f"Reportado por {d.get('piloto') or _usuario()} en el chequeo pre-vuelo.",
                    "tareas": [{"descripcion": f"{i['texto']}: {i['nota'] or 'ver foto'}", "origen": "checklist",
                                "motivo": "daño"} for i in fallas]}, _usuario())
            cur = con.execute("INSERT INTO checklists(equipo_id, fecha, piloto, resultado, items, nota, orden_id, usuario) "
                              "VALUES(?,?,?,?,?,?,?,?)",
                              (equipo_id, d.get("fecha") or date.today().isoformat(), d.get("piloto") or None,
                               resultado, json.dumps(items, ensure_ascii=False), d.get("nota") or None, orden_id,
                               _usuario()))
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid, "resultado": resultado, "orden_id": orden_id,
                            "mantenimiento": mant["estado"], "motivos": mant["motivos"][:6]}), 201
        equipo_id = request.args.get("equipo_id", type=int)
        filas = con.execute(
            "SELECT c.*, e.nombre equipo, e.tipo_activo, t.codigo orden_codigo FROM checklists c "
            "JOIN equipos e ON e.id=c.equipo_id LEFT JOIN ordenes_trabajo t ON t.id=c.orden_id "
            + ("WHERE c.equipo_id=? " if equipo_id else "") + "ORDER BY c.fecha DESC, c.id DESC LIMIT 100",
            (equipo_id,) if equipo_id else ()).fetchall()
        salida = []
        for f in filas:
            d = dict(f)
            d["items"] = json.loads(d["items"] or "[]")
            salida.append(d)
        return jsonify(salida)

    @app.route("/api/checklists/plantilla")
    @login_requerido
    def api_checklist_plantilla():
        tipo = request.args.get("tipo") or "dron"
        return jsonify([{"clave": k, "texto": t} for k, t in CHECKLIST.get(tipo, CHECKLIST["dron"])])

    # ------------------------------------------------------------------ archivos adjuntos

    @app.route("/api/archivos", methods=["POST"])
    @login_requerido
    def api_archivos():
        """Sube una foto o un PDF (chequeo, soporte de directiva, documento). Se guarda en
        datos/archivos/<empresa>/ con nombre aleatorio; sólo lo sirve la misma empresa."""
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            return jsonify({"error": "no llegó ningún archivo"}), 400
        ext = Path(archivo.filename).suffix.lower()
        if ext not in EXTENSIONES:
            return jsonify({"error": "sólo imágenes (jpg, png, webp, heic) o PDF"}), 400
        empresa = session.get("empresa_id")
        if not empresa:
            return jsonify({"error": "sin empresa"}), 403
        carpeta = DIR_ARCHIVOS / str(int(empresa))
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"{date.today().isoformat()}_{secrets.token_hex(8)}{ext}"
        archivo.save(carpeta / nombre)
        return jsonify({"ok": True, "archivo": nombre, "url": f"/archivos/{nombre}"}), 201

    @app.route("/archivos/<nombre>")
    @login_requerido
    def servir_archivo(nombre):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9a-f]{16}\.[a-z0-9]{3,4}", nombre):
            abort(404)
        empresa = session.get("empresa_id")
        if not empresa:
            abort(404)
        return send_from_directory(DIR_ARCHIVOS / str(int(empresa)), nombre, max_age=3600)

    # ------------------------------------------------------------------ auditoría

    @app.route("/api/auditoria")
    @admin_requerido
    def api_auditoria():
        con = get_con()
        return jsonify([dict(f) for f in con.execute(
            "SELECT * FROM auditoria ORDER BY id DESC LIMIT 300").fetchall()])
