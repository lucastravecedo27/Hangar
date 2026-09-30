"""Rutas del módulo de Informes (core/informes.py y core/informes_salida.py). Se registran desde
app.py igual que web_flota y web_combustible.

    /informes                            catálogo y vista previa (?informe=<clave> abre uno directo)
    /api/informes                        catálogo que el rol puede ver, con los fijados del usuario
    /api/informes/<clave>?filtros        el informe en JSON (vista previa en vivo)
    /informes/<clave>/excel?filtros      descarga .xlsx
    /informes/<clave>/pdf?filtros        descarga .pdf (o la hoja de impresión si no hay ReportLab)
    /informes/<clave>/imprimir?filtros   hoja de impresión HTML con @page
    /api/cuenta/informes-fijados         fijar o quitar un informe (PUT)

Las descargas son GET: no necesitan token CSRF, pero sí sesión y permiso sobre el informe.
Cada petición vuelve a consultar la base: los informes nunca se guardan precalculados.
"""
from flask import abort, jsonify, redirect, render_template, request, send_file, session, url_for

from core import informes as core_inf
from core import informes_salida as core_sal

# La vista previa no pinta tablas infinitas: con esto basta para revisar; el Excel lleva todo.
FILAS_VISTA = 1500


def registrar(app, get_con, login_requerido, admin_requerido):

    def _rol():
        return session.get("rol", "admin")

    def _definicion(clave):
        """Definición del informe si existe, está disponible y el rol lo puede ver; si no, 404/403."""
        defn = core_inf.REGISTRO.get(clave)
        if not defn or not core_inf.disponible(defn):
            abort(404)
        if not core_inf.puede(defn, _rol()):
            abort(403)
        return defn

    def _generar(clave):
        defn = _definicion(clave)
        con = get_con()
        p = core_inf.parametros(defn, request.args, rol=_rol(), empresa=session.get("empresa_nombre"),
                                usuario=session.get("usuario"))
        return core_inf.generar(con, clave, p)

    # ------------------------------------------------------------------ página

    @app.route("/informes")
    @login_requerido
    def pagina_informes():
        return render_template("informes.html", activo="informes", hay_pdf=core_sal.HAY_PDF)

    # ------------------------------------------------------------------ catálogo y vista previa

    @app.route("/api/informes")
    @login_requerido
    def api_informes_catalogo():
        con = get_con()
        equipos = [dict(e) for e in con.execute(
            "SELECT id, nombre, modelo, tipo_activo, matricula FROM equipos WHERE estado != 'baja' "
            "ORDER BY tipo_activo DESC, nombre").fetchall()]
        clientes = [f["c"] for f in con.execute(
            "SELECT DISTINCT cliente c FROM operaciones WHERE cliente IS NOT NULL AND cliente != '' ORDER BY 1").fetchall()]
        pilotos = [f["p"] for f in con.execute(
            "SELECT DISTINCT piloto p FROM operaciones WHERE piloto IS NOT NULL AND piloto != '' ORDER BY 1").fetchall()]
        return jsonify({
            "informes": core_inf.catalogo(_rol()),
            "categorias": [{"clave": c, "nombre": n, "descripcion": d} for c, n, d in core_inf.CATEGORIAS],
            "periodos": [{"clave": c, "nombre": n} for c, n in core_inf.PERIODOS],
            "fijados": core_inf.fijados(con, session.get("usuario_id")),
            "opciones": {"equipos": equipos, "clientes": clientes, "pilotos": pilotos},
            "nota_rac": core_inf.NOTA_RAC, "hay_pdf": core_sal.HAY_PDF,
        })

    @app.route("/api/informes/<clave>")
    @login_requerido
    def api_informe(clave):
        r = _generar(clave)
        # Sólo se recorta lo que viaja a la pantalla; el Excel y el PDF llevan todas las filas.
        for s in r["secciones"]:
            s["total_filas"] = len(s["filas"])
            if len(s["filas"]) > FILAS_VISTA:
                s["filas"] = s["filas"][:FILAS_VISTA]
                s["recortada"] = True
        return jsonify(r)

    # ------------------------------------------------------------------ descargas

    @app.route("/informes/<clave>/excel")
    @login_requerido
    def informe_excel(clave):
        r = _generar(clave)
        return send_file(core_sal.excel(r), as_attachment=True, download_name=core_sal.nombre_archivo(r, "xlsx"),
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", max_age=0)

    @app.route("/informes/<clave>/pdf")
    @login_requerido
    def informe_pdf(clave):
        if not core_sal.HAY_PDF:
            # Sin ReportLab en esta instalación: la hoja de impresión, que el navegador guarda como PDF.
            return redirect(url_for("informe_imprimir", clave=clave, auto=1, **request.args.to_dict()))
        r = _generar(clave)
        return send_file(core_sal.pdf(r), as_attachment=request.args.get("ver") != "1",
                         download_name=core_sal.nombre_archivo(r, "pdf"), mimetype="application/pdf", max_age=0)

    @app.route("/informes/<clave>/imprimir")
    @login_requerido
    def informe_imprimir(clave):
        r = _generar(clave)
        return render_template("informe_imprimir.html", r=core_sal.para_imprimir(r),
                               auto=request.args.get("auto") == "1")

    # ------------------------------------------------------------------ fijados por usuario

    @app.route("/api/cuenta/informes-fijados", methods=["GET", "PUT"])
    @login_requerido
    def api_informes_fijados():
        # Va bajo /api/cuenta/ porque es una preferencia personal: todos los roles pueden guardarla.
        con = get_con()
        uid = session.get("usuario_id")
        if request.method == "PUT":
            d = request.get_json(silent=True) or {}
            clave = d.get("clave")
            defn = core_inf.REGISTRO.get(clave)
            if not defn or not core_inf.puede(defn, _rol()):
                return jsonify({"error": "informe no válido"}), 400
            return jsonify({"fijados": core_inf.fijar(con, uid, clave, bool(d.get("fijado", True)))})
        return jsonify({"fijados": core_inf.fijados(con, uid)})
