"""Órdenes de trabajo (mantenimiento) y órdenes de servicio (aplicación).

Órdenes de trabajo
  1. Identificación del equipo.
  2. Trabajos a ejecutar: el cronograma se genera solo a partir del desgaste de las piezas y el
     personal puede añadir los que considere pertinentes al ver el uso real.
  3. Programación por el administrador y notificación por correo al personal asignado.

Órdenes de servicio
  El administrador programa la aplicación (piloto, cliente, finca, productos, fecha, dron y
  observaciones), se avisa al piloto por correo y se sigue el estado hasta finalizar.
"""
from html import escape

from core import correo as core_correo
from core import db as core_db
from core import proyeccion as core_proyeccion

ESTADOS_OT = ["borrador", "programada", "enviada", "en_proceso", "diferida", "completada", "cancelada"]
ESTADOS_OS = ["programada", "enviada", "en_ruta", "en_ejecucion", "finalizada", "cancelada"]
ETIQUETA_OT = {"borrador": "Borrador", "programada": "Programada", "enviada": "Enviada",
               "en_proceso": "En proceso", "diferida": "Diferida", "completada": "Completada",
               "cancelada": "Cancelada"}
ETIQUETA_OS = {"programada": "Programada", "enviada": "Enviada", "en_ruta": "En ruta",
               "en_ejecucion": "En ejecución", "finalizada": "Finalizada", "cancelada": "Cancelada"}


# ===================== Órdenes de trabajo =====================

def tareas_sugeridas(con, equipo_id, horizonte_dias=60):
    """Cronograma automático: lo vencido/crítico/próximo más lo que caerá dentro del horizonte."""
    sugeridas = []
    for p in core_proyeccion.proximos_repuestos(con, equipo_id, limite=200):
        dentro = p["dias_estimados"] is not None and p["dias_estimados"] <= horizonte_dias
        if p["nivel"] == "ok" and not dentro:
            continue
        inspeccion = p.get("tipo_item") == "inspeccion"
        if inspeccion:
            accion = "Realizar" if p["nivel"] in ("vencido", "critico") else "Programar"
        else:
            accion = "Cambiar" if p["nivel"] in ("vencido", "critico") else "Revisar y preparar cambio de"
        # El texto dice el límite que manda: horas (o Hobbs/Tach), ciclos o calendario. Antes se
        # asumía siempre horas y fallaba con los modelos que sólo tienen plazos en meses.
        uso = ""
        if p["motivo_alerta"] == "calendario" and p.get("meses_en_servicio") is not None:
            uso = f"{p['meses_en_servicio']:.1f} de {p['vida_util_meses']:.0f} meses".replace(".", ",")
        elif p["motivo_alerta"] == "ciclos" and p.get("limite_ciclos"):
            uso = f"{p['ciclos_uso']:.0f} de {p['limite_ciclos']:.0f} {p['unidad_ciclos']}"
        elif p.get("vida_util_horas"):
            uso = f"{p['horas_uso']:.0f} de {p['vida_util_horas']:.0f} {p['unidad']}"
        elif p.get("meses_en_servicio") is not None and p.get("vida_util_meses"):
            uso = f"{p['meses_en_servicio']:.1f} de {p['vida_util_meses']:.0f} meses".replace(".", ",")
        plazo = p.get("plazo_txt") or ""
        if p["dias_estimados"] is not None and p["nivel"] != "vencido":
            plazo += f" · ~{p['dias_estimados']} días"
        sugeridas.append({
            "descripcion": f"{accion} {p['nombre']} ({p['modulo']})" + (f" — {uso}" if uso else "") + (f" · {plazo}" if plazo else ""),
            "origen": "cronograma",
            "pieza_clave": p["clave"],
            "componente_id": p["id"],
            "motivo": "inspeccion" if inspeccion else "desgaste",
            "nivel": p["nivel"],
            "nota": p["nota"],
            "dias_estimados": p["dias_estimados"],
        })
    return sugeridas


def crear_ot(con, datos, usuario=None):
    codigo = core_db.siguiente_codigo(con, "ordenes_trabajo", "OT")
    equipo_id = int(datos["equipo_id"])
    horas = con.execute("SELECT horas_totales FROM equipos WHERE id=?", (equipo_id,)).fetchone()["horas_totales"]
    cur = con.execute(
        """INSERT INTO ordenes_trabajo(codigo, equipo_id, titulo, tipo, prioridad, estado, asignado_a,
                                       asignado_email, fecha_programada, hora_programada, lugar,
                                       horas_equipo, observaciones, creado_por)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (codigo, equipo_id, (datos.get("titulo") or "Mantenimiento programado").strip(),
         datos.get("tipo") or "preventivo", datos.get("prioridad") or "normal",
         datos.get("estado") or "programada", datos.get("asignado_a") or None,
         datos.get("asignado_email") or None, datos.get("fecha_programada") or None,
         datos.get("hora_programada") or None, datos.get("lugar") or None,
         horas, datos.get("observaciones") or None, usuario),
    )
    orden_id = cur.lastrowid
    for i, t in enumerate(datos.get("tareas") or []):
        descripcion = (t.get("descripcion") or "").strip()
        if not descripcion:
            continue
        con.execute(
            "INSERT INTO ot_tareas(orden_id, descripcion, origen, pieza_clave, componente_id, nivel, nota, "
            "                      motivo, codigo_pieza, nombre_pieza, orden_n, costo_repuesto, costo_mano_obra, "
            "                      horas_mano_obra) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (orden_id, descripcion, t.get("origen") or "manual", t.get("pieza_clave"),
             t.get("componente_id"), t.get("nivel"), t.get("nota"), t.get("motivo"),
             t.get("codigo_pieza"), t.get("nombre_pieza"), i, _num(t.get("costo_repuesto")),
             _num(t.get("costo_mano_obra")), _num(t.get("horas_mano_obra"))),
        )
    con.commit()
    return orden_id


def ot_completa(con, orden_id):
    fila = con.execute(
        """SELECT o.*, e.nombre AS equipo, e.modelo, e.numero_serie, e.horas_totales
           FROM ordenes_trabajo o JOIN equipos e ON e.id=o.equipo_id WHERE o.id=?""", (orden_id,)).fetchone()
    if not fila:
        return None
    d = dict(fila)
    d["estado_txt"] = ETIQUETA_OT.get(d["estado"], d["estado"])
    d["tareas"] = [dict(t) for t in con.execute(
        "SELECT * FROM ot_tareas WHERE orden_id=? ORDER BY orden_n, id", (orden_id,)).fetchall()]
    d["n_tareas"] = len(d["tareas"])
    d["n_hechas"] = sum(1 for t in d["tareas"] if t["estado"] == "hecho")
    return d


def listar_ot(con, estado=None, equipo_id=None):
    cond, params = ["1=1"], []
    if estado:
        cond.append("o.estado=?"); params.append(estado)
    if equipo_id:
        cond.append("o.equipo_id=?"); params.append(equipo_id)
    filas = con.execute(
        f"""SELECT o.*, e.nombre AS equipo, e.modelo,
                   (SELECT COUNT(*) FROM ot_tareas t WHERE t.orden_id=o.id) n_tareas,
                   (SELECT COUNT(*) FROM ot_tareas t WHERE t.orden_id=o.id AND t.estado='hecho') n_hechas
            FROM ordenes_trabajo o JOIN equipos e ON e.id=o.equipo_id
            WHERE {' AND '.join(cond)}
            ORDER BY o.estado IN ('completada','cancelada'), o.fecha_programada IS NULL,
                     o.fecha_programada, o.id DESC""", params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["estado_txt"] = ETIQUETA_OT.get(d["estado"], d["estado"])
        salida.append(d)
    return salida


def diferidas(con):
    """Órdenes diferidas con su plazo: vencida si ya pasó la fecha límite."""
    from datetime import date
    hoy = date.today().isoformat()
    salida = []
    for f in con.execute("SELECT id, codigo, equipo_id, titulo, diferida_hasta, diferida_motivo FROM ordenes_trabajo "
                         "WHERE estado='diferida'").fetchall():
        d = dict(f)
        d["vencida"] = bool(d["diferida_hasta"] and d["diferida_hasta"] < hoy)
        salida.append(d)
    return salida


def cerrar_ot_registrando_mantenimientos(con, orden_id, realizado_por=None, firmado_por=None, licencia=None,
                                         fecha=None, costo_hora=None, usuario=None, inspector=None,
                                         inspector_licencia=None, horas_hombre=None):
    """Al completar la orden, cada tarea hecha se anota en la bitácora de reparaciones y las que
    van contra una pieza concreta (o una inspección) vuelven a cero desde la fecha de cierre.

    Cada tarea lleva su costo de repuesto y de mano de obra; si sólo se anotaron horas de mano
    de obra, se valoran con el costo por hora de Ajustes. Antes el costo se guardaba siempre
    vacío y el indicador de costo de mantenimiento daba cero.

    Sólo cierra una vez: volver a completar una orden ya cerrada duplicaría los apuntes y
    reiniciaría por segunda vez piezas que no se han vuelto a tocar.

    Los repuestos apartados de la bodega (core/bodega.py) para las tareas hechas salen del
    inventario y su costo promedio pasa a ser el costo de repuesto de la tarea. Una orden sin
    repuestos de bodega se cierra exactamente igual que antes.
    """
    from core import bodega as core_bodega
    ot = ot_completa(con, orden_id)
    if not ot:
        return {"ok": False, "motivo": "La orden no existe.", "mantenimientos": 0, "piezas": 0}
    if ot["estado"] == "completada":
        return {"ok": False, "motivo": f'{ot["codigo"]} ya estaba completada; no se repiten los apuntes.',
                "mantenimientos": 0, "piezas": 0}
    bodega = core_bodega.consumir_ot(con, orden_id, fecha, usuario or realizado_por)
    if bodega["n"]:
        ot = ot_completa(con, orden_id)   # las tareas traen ya el costo de repuesto de la bodega
    hechas = [t for t in ot["tareas"] if t["estado"] == "hecho"]
    piezas, costo_total = 0, 0.0
    for t in hechas:
        mano = t.get("costo_mano_obra")
        if mano is None and t.get("horas_mano_obra") and costo_hora:
            mano = round(t["horas_mano_obra"] * costo_hora, 2)
        rep = t.get("costo_repuesto")
        core_db.registrar_mantenimiento(
            con, ot["equipo_id"], t["componente_id"], ot["tipo"] or "preventivo",
            t["descripcion"], None, realizado_por or ot["asignado_a"], fecha,
            motivo=t["motivo"] or ("desgaste" if t["componente_id"] else "otro"),
            codigo_pieza=t["codigo_pieza"], nombre_pieza=t["nombre_pieza"],
            orden_id=orden_id, orden_codigo=ot["codigo"], commit=False,
            costo_repuesto=rep, costo_mano_obra=mano, firmado_por=firmado_por, licencia_firma=licencia)
        costo_total += (rep or 0) + (mano or 0)
        if t["componente_id"]:
            piezas += 1
    if horas_hombre is None:
        horas_hombre = sum(t.get("horas_mano_obra") or 0 for t in hechas) or None
    con.execute("UPDATE ordenes_trabajo SET estado='completada', cerrado_en=datetime('now'), "
                "actualizado=datetime('now'), firmado_por=?, licencia_firma=?, inspector=?, "
                "inspector_licencia=?, horas_hombre=? WHERE id=?",
                (firmado_por, licencia, inspector, inspector_licencia, horas_hombre, orden_id))
    con.commit()
    return {"ok": True, "mantenimientos": len(hechas), "piezas": piezas, "costo": round(costo_total, 2),
            "bodega": bodega,
            "motivo": f'{len(hechas)} trabajo(s) en la bitácora · {piezas} pieza(s) a cero'
                      + (f' · costo {costo_total:,.0f}' if costo_total else '')
                      + (f' · {bodega["n"]} repuesto(s) descontados de bodega' if bodega["n"] else '')
                      + (' · sin existencias suficientes: ' + '; '.join(bodega["faltantes"]) if bodega["faltantes"] else '')}


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


# ===================== Órdenes de servicio =====================

UNIDADES = ("L", "kg", "g", "mL", "L/ha", "kg/ha")


def guardar_productos_os(con, orden_id, productos):
    """Reemplaza la lista de productos de la orden y deja el resumen de texto al día.

    El campo `productos` de la orden se sigue manteniendo porque es lo que va en el correo, en la
    hoja impresa y en las búsquedas; la tabla es la fuente de la verdad para editar uno a uno.
    """
    con.execute("DELETE FROM os_productos WHERE orden_id=?", (orden_id,))
    limpios = []
    for i, pr in enumerate(productos or []):
        nombre = (pr.get("nombre") or "").strip()
        if not nombre:
            continue
        try:
            cantidad = float(str(pr.get("cantidad")).replace(",", ".")) if pr.get("cantidad") not in (None, "") else None
        except ValueError:
            cantidad = None
        unidad = (pr.get("unidad") or "L").strip()
        con.execute(
            "INSERT INTO os_productos(orden_id, nombre, dosis, cantidad, unidad, nota, orden_n) "
            "VALUES(?,?,?,?,?,?,?)",
            (orden_id, nombre, (pr.get("dosis") or "").strip() or None, cantidad, unidad,
             (pr.get("nota") or "").strip() or None, i))
        partes = [nombre]
        if cantidad is not None:
            partes.append(f"{cantidad:g} {unidad}")
        if pr.get("dosis"):
            partes.append(str(pr["dosis"]).strip())
        limpios.append(" · ".join(partes))
    resumen = " | ".join(limpios) or None
    con.execute("UPDATE ordenes_servicio SET productos=?, actualizado=datetime('now') WHERE id=?",
                (resumen, orden_id))
    con.commit()
    return resumen


def productos_os(con, orden_id):
    return [dict(f) for f in con.execute(
        "SELECT * FROM os_productos WHERE orden_id=? ORDER BY orden_n, id", (orden_id,)).fetchall()]


def url_mapa(v):
    """Enlace al mapa o polígono del lote (Google Maps, KML compartido…). Sólo http(s)."""
    v = (v or "").strip()
    return v if v.lower().startswith(("https://", "http://")) else None


def crear_os(con, datos, usuario=None):
    codigo = core_db.siguiente_codigo(con, "ordenes_servicio", "OS")
    try:
        hectareas = float(datos.get("hectareas")) if datos.get("hectareas") not in (None, "") else None
    except (TypeError, ValueError):
        hectareas = None
    cur = con.execute(
        """INSERT INTO ordenes_servicio(codigo, piloto, piloto_email, cliente, finca, zona, productos,
                                        fecha, hora, equipo_id, hectareas, dosis, observaciones,
                                        estado, creado_por, condiciones_tiempo, zonas_evitar, mapa_url)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (codigo, datos.get("piloto") or None, datos.get("piloto_email") or None,
         datos.get("cliente") or None, datos.get("finca") or None, datos.get("zona") or None,
         datos.get("productos") or None, datos.get("fecha") or None, datos.get("hora") or None,
         datos.get("equipo_id") or None, hectareas, datos.get("dosis") or None,
         datos.get("observaciones") or None, datos.get("estado") or "programada", usuario,
         (datos.get("condiciones_tiempo") or "").strip() or None, (datos.get("zonas_evitar") or "").strip() or None,
         url_mapa(datos.get("mapa_url"))),
    )
    orden_id = cur.lastrowid
    if datos.get("productos_lista"):
        guardar_productos_os(con, orden_id, datos["productos_lista"])
    registrar_evento_os(con, orden_id, "programada", "Orden de servicio creada.", usuario)
    return orden_id


def registrar_evento_os(con, orden_id, estado, nota=None, usuario=None):
    con.execute("INSERT INTO os_eventos(orden_id, estado, nota, usuario) VALUES(?,?,?,?)",
                (orden_id, estado, nota, usuario))
    con.execute("UPDATE ordenes_servicio SET estado=?, actualizado=datetime('now') WHERE id=?", (estado, orden_id))
    if estado == "finalizada":
        con.execute("UPDATE ordenes_servicio SET finalizado_en=datetime('now') WHERE id=?", (orden_id,))
    con.commit()


def os_completa(con, orden_id):
    fila = con.execute(
        """SELECT s.*, e.nombre AS equipo, e.modelo FROM ordenes_servicio s
           LEFT JOIN equipos e ON e.id=s.equipo_id WHERE s.id=?""", (orden_id,)).fetchone()
    if not fila:
        return None
    d = dict(fila)
    d["estado_txt"] = ETIQUETA_OS.get(d["estado"], d["estado"])
    d["productos_lista"] = productos_os(con, orden_id)
    d["eventos"] = [dict(f) for f in con.execute(
        "SELECT * FROM os_eventos WHERE orden_id=? ORDER BY id", (orden_id,)).fetchall()]
    return d


def listar_os(con, estado=None, equipo_id=None):
    """Las tarjetas del listado necesitan cuántos productos lleva cada orden, no cuáles."""
    cond, params = ["1=1"], []
    if estado:
        cond.append("s.estado=?"); params.append(estado)
    if equipo_id:
        cond.append("s.equipo_id=?"); params.append(equipo_id)
    filas = con.execute(
        f"""SELECT s.*, e.nombre AS equipo, e.modelo,
                   (SELECT COUNT(*) FROM os_eventos v WHERE v.orden_id=s.id) n_eventos,
                   (SELECT COUNT(*) FROM os_productos pr WHERE pr.orden_id=s.id) n_productos
            FROM ordenes_servicio s LEFT JOIN equipos e ON e.id=s.equipo_id
            WHERE {' AND '.join(cond)}
            ORDER BY s.estado IN ('finalizada','cancelada'), s.fecha IS NULL, s.fecha, s.id DESC""",
        params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["estado_txt"] = ETIQUETA_OS.get(d["estado"], d["estado"])
        salida.append(d)
    return salida


# ===================== Correo =====================

_ESTILO = ("font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
           "color:#141a24;line-height:1.55;font-size:14px")


def _tabla(pares):
    filas = "".join(
        f'<tr><td style="padding:6px 14px 6px 0;color:#6b7f99;white-space:nowrap">{escape(str(k))}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(str(v))}</td></tr>'
        for k, v in pares if v not in (None, "", "None"))
    return f'<table style="border-collapse:collapse;margin:14px 0">{filas}</table>'


def _envoltura(titulo, subtitulo, cuerpo, pie):
    return (f'<div style="{_ESTILO};max-width:640px">'
            f'<div style="background:#0f3d80;color:#fff;padding:18px 22px;border-radius:14px 14px 0 0">'
            f'<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.8">Hangar · Control de flota aérea agrícola</div>'
            f'<div style="font-size:20px;font-weight:700;margin-top:4px">{escape(titulo)}</div>'
            f'<div style="font-size:13px;opacity:.85;margin-top:2px">{escape(subtitulo)}</div></div>'
            f'<div style="border:1px solid #dfe7f1;border-top:0;border-radius:0 0 14px 14px;padding:20px 22px">{cuerpo}'
            f'<div style="margin-top:20px;padding-top:14px;border-top:1px solid #dfe7f1;color:#6b7f99;font-size:12px">{pie}</div>'
            f'</div></div>')


def cuerpo_ot(ot):
    tareas = "".join(
        f'<li style="margin:6px 0">{escape(t["descripcion"])}'
        + (f'<div style="color:#6b7f99;font-size:12.5px">{escape(t["nota"])}</div>' if t.get("nota") else "")
        + (' <span style="background:#fff3d1;color:#7a5400;border-radius:20px;padding:1px 8px;font-size:11px">añadido por el personal</span>'
           if t.get("origen") == "manual" else "")
        + "</li>"
        for t in ot["tareas"]) or "<li>Sin trabajos detallados.</li>"
    cuerpo = (
        "<p>Se te ha asignado la siguiente orden de trabajo.</p>"
        + _tabla([
            ("Orden", ot["codigo"]),
            ("Equipo", f'{ot["equipo"]} · {ot["modelo"]}' + (f' · S/N {ot["numero_serie"]}' if ot.get("numero_serie") else "")),
            ("Horas del equipo", f'{(ot.get("horas_equipo") or 0):.1f} h'),
            ("Tipo", (ot.get("tipo") or "").capitalize()),
            ("Prioridad", (ot.get("prioridad") or "").capitalize()),
            ("Fecha programada", " ".join(x for x in [ot.get("fecha_programada"), ot.get("hora_programada")] if x)),
            ("Lugar", ot.get("lugar")),
        ])
        + '<div style="font-weight:700;margin-top:6px">Trabajos a ejecutar</div>'
        + f'<ol style="padding-left:20px;margin:8px 0">{tareas}</ol>'
        + (f'<div style="background:#f3f7fc;border-radius:10px;padding:12px 14px;margin-top:14px">'
           f'<b>Observaciones</b><br>{escape(ot["observaciones"])}</div>' if ot.get("observaciones") else ""))
    return _envoltura(f'Orden de trabajo {ot["codigo"]}',
                      f'{ot["equipo"]} · {ot.get("titulo") or ""}', cuerpo,
                      "Al terminar, reporta los trabajos ejecutados al administrador para cerrar la orden "
                      "y reiniciar la vida útil de las piezas cambiadas.")


def _lista_productos_html(productos):
    filas = "".join(
        f'<li style="margin:5px 0"><b>{escape(pr["nombre"])}</b>'
        + (f' — {pr["cantidad"]:g} {escape(pr["unidad"] or "L")}' if pr.get("cantidad") is not None else "")
        + (f' · {escape(pr["dosis"])}' if pr.get("dosis") else "")
        + (f'<div style="color:#6b7f99;font-size:12.5px">{escape(pr["nota"])}</div>' if pr.get("nota") else "")
        + "</li>"
        for pr in productos)
    return ('<div style="font-weight:700;margin-top:6px">Productos a aplicar</div>'
            f'<ul style="padding-left:20px;margin:8px 0">{filas}</ul>')


def cuerpo_os(os_):
    productos = os_.get("productos_lista") or []
    cuerpo = (
        "<p>Se te ha programado la siguiente orden de servicio.</p>"
        + _tabla([
            ("Orden", os_["codigo"]),
            ("Piloto", os_.get("piloto")),
            ("Cliente", os_.get("cliente")),
            ("Finca", os_.get("finca")),
            ("Zona", os_.get("zona")),
            ("Productos", None if productos else os_.get("productos")),
            ("Fecha", " ".join(x for x in [os_.get("fecha"), os_.get("hora")] if x)),
            ("Aeronave asignada", f'{os_.get("equipo") or "—"}' + (f' · {os_["modelo"]}' if os_.get("modelo") else "")),
            ("Hectáreas previstas", f'{os_["hectareas"]:.1f} ha' if os_.get("hectareas") else None),
            ("Dosis", os_.get("dosis")),
            ("Condiciones del tiempo", os_.get("condiciones_tiempo")),
            ("Zonas a evitar", os_.get("zonas_evitar")),
        ])
        + (f'<p><a href="{escape(os_["mapa_url"])}">Ver el mapa del lote</a></p>' if os_.get("mapa_url") else "")
        + (_lista_productos_html(productos) if productos else "")
        + (f'<div style="background:#f3f7fc;border-radius:10px;padding:12px 14px;margin-top:8px">'
           f'<b>Observaciones adicionales</b><br>{escape(os_["observaciones"])}</div>' if os_.get("observaciones") else ""))
    return _envoltura(f'Orden de servicio {os_["codigo"]}',
                      f'{os_.get("cliente") or ""} · {os_.get("finca") or ""}'.strip(" ·"), cuerpo,
                      "Avisa al administrador cuando salgas a ruta y cuando termines la aplicación "
                      "para que la orden quede cerrada.")


def enviar_ot(con, orden_id, destino=None):
    ot = ot_completa(con, orden_id)
    if not ot:
        return {"ok": False, "motivo": "La orden no existe."}
    para = destino or ot.get("asignado_email")
    if not para:
        return {"ok": False, "motivo": "La orden no tiene correo del personal asignado."}
    r = core_correo.enviar(con, para, f'Orden de trabajo {ot["codigo"]} · {ot["equipo"]}',
                           cuerpo_ot(ot), referencia=f"ot:{orden_id}")
    # Sólo pasa a «enviada» si el correo salió de verdad. Sin servidor configurado queda en la
    # bandeja de salida, y marcarla igualmente hacía creer que el técnico ya tenía la orden.
    if r.get("ok"):
        if ot["estado"] in ("borrador", "programada"):
            con.execute("UPDATE ordenes_trabajo SET estado='enviada', actualizado=datetime('now') WHERE id=?", (orden_id,))
        con.execute("UPDATE ordenes_trabajo SET enviado_en=datetime('now') WHERE id=?", (orden_id,))
        con.commit()
    return r


def enviar_os(con, orden_id, destino=None, usuario=None):
    os_ = os_completa(con, orden_id)
    if not os_:
        return {"ok": False, "motivo": "La orden no existe."}
    para = destino or os_.get("piloto_email")
    if not para:
        return {"ok": False, "motivo": "La orden no tiene correo del piloto."}
    r = core_correo.enviar(con, para, f'Orden de servicio {os_["codigo"]} · {os_.get("finca") or ""}',
                           cuerpo_os(os_), referencia=f"os:{orden_id}")
    con.execute("UPDATE ordenes_servicio SET enviado_en=datetime('now') WHERE id=?", (orden_id,))
    if os_["estado"] == "programada":
        registrar_evento_os(con, orden_id, "enviada",
                            f'Enviada a {para}. {r.get("motivo","")}'.strip(), usuario)
    con.commit()
    return r
