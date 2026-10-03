"""Incidentes: golpes, caídas, aterrizajes duros, colisiones.

Un incidente abierto deja el activo «No recomendado volar» hasta que alguien cierra su inspección
con nombre y firma. Así lo pidió el ingeniero aeronáutico de la encuesta de validación: «inspección
obligatoria antes de volver a volar».

Quién firma la inspección no es igual en los dos mundos:
  · Avión (aviación tripulada): el inspector o mecánico certificador, con su número de licencia
    (RAC 43 / RAC 145). En la app, el rol «certificador» o el administrador.
  · Dron (UAS, RAC 100): la norma no fija el paso a paso; firma el técnico asignado a la tarea o
    el representante del fabricante, con su nombre y cargo.

Reportar un incidente abre sola una orden de trabajo de inspección, como hace el chequeo
pre-vuelo con una falla.
"""
from datetime import date

from core import ordenes as core_ordenes

TIPOS = {"golpe": "Golpe", "caida": "Caída", "aterrizaje_duro": "Aterrizaje duro",
         "colision": "Colisión con obstáculo", "falla_vuelo": "Falla en vuelo", "otro": "Otro"}
RESULTADOS = {"apto": "Apto para volver a volar", "no_apto": "No apto: requiere reparación"}
ROLES_FIRMA_AVION = ("admin", "superadmin", "certificador")


def abiertos(con, equipo_id=None):
    """Incidentes sin inspección cerrada, por activo."""
    filas = con.execute(
        "SELECT * FROM incidentes WHERE estado='abierto'" + (" AND equipo_id=?" if equipo_id else "")
        + " ORDER BY fecha", (equipo_id,) if equipo_id else ()).fetchall()
    salida = {}
    for f in filas:
        salida.setdefault(f["equipo_id"], []).append(dict(f))
    return salida


def listar(con, equipo_id=None, estado=None, limite=200):
    cond, params = ["1=1"], []
    if equipo_id:
        cond.append("i.equipo_id=?"); params.append(equipo_id)
    if estado:
        cond.append("i.estado=?"); params.append(estado)
    filas = con.execute(
        f"""SELECT i.*, e.nombre equipo, e.tipo_activo, e.matricula, t.codigo orden_codigo, t.estado orden_estado
            FROM incidentes i JOIN equipos e ON e.id=i.equipo_id
            LEFT JOIN ordenes_trabajo t ON t.id=i.orden_id
            WHERE {' AND '.join(cond)} ORDER BY i.estado='abierto' DESC, i.fecha DESC, i.id DESC LIMIT ?""",
        params + [limite]).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["tipo_txt"] = TIPOS.get(d["tipo"], d["tipo"])
        d["resultado_txt"] = RESULTADOS.get(d["inspeccion_resultado"] or "", "")
        salida.append(d)
    return salida


def reportar(con, datos, usuario=None):
    """Registra el incidente y abre la OT de inspección. Devuelve (id, orden_id)."""
    equipo_id = int(datos["equipo_id"])
    eq = con.execute("SELECT id, nombre, tipo_activo FROM equipos WHERE id=?", (equipo_id,)).fetchone()
    if not eq:
        raise ValueError("el activo no existe")
    descripcion = (datos.get("descripcion") or "").strip()
    if not descripcion:
        raise ValueError("describe qué pasó")
    tipo = datos.get("tipo") or "otro"
    if tipo not in TIPOS:
        raise ValueError("tipo de incidente no válido")
    fecha = datos.get("fecha") or date.today().isoformat()
    danos = (datos.get("danos") or "").strip() or None
    orden_id = core_ordenes.crear_ot(con, {
        "equipo_id": equipo_id, "titulo": f"Inspección por incidente · {TIPOS[tipo].lower()} · {eq['nombre']}",
        "tipo": "correctivo", "prioridad": "alta", "estado": "borrador", "fecha_programada": fecha,
        "observaciones": f"{TIPOS[tipo]} el {fecha}: {descripcion}" + (f" Daños vistos: {danos}" if danos else ""),
        "tareas": [{"descripcion": f"Inspección posterior al incidente ({TIPOS[tipo].lower()}): {descripcion}",
                    "origen": "incidente", "motivo": "daño"}]}, usuario)
    cur = con.execute(
        """INSERT INTO incidentes(equipo_id, fecha, tipo, descripcion, danos, lugar, piloto, operacion_id,
                                  orden_id, usuario) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (equipo_id, fecha, tipo, descripcion, danos, (datos.get("lugar") or "").strip() or None,
         (datos.get("piloto") or "").strip() or None, datos.get("operacion_id") or None, orden_id, usuario))
    con.commit()
    return cur.lastrowid, orden_id


def cerrar_inspeccion(con, incidente_id, datos, rol, usuario=None):
    """Cierra la inspección. En un avión exige certificador con licencia; en un dron, nombre y
    cargo de quien firma (técnico asignado o representante del fabricante)."""
    inc = con.execute("SELECT i.*, e.tipo_activo FROM incidentes i JOIN equipos e ON e.id=i.equipo_id "
                      "WHERE i.id=?", (incidente_id,)).fetchone()
    if not inc:
        raise LookupError("el incidente no existe")
    if inc["estado"] != "abierto":
        raise ValueError("la inspección de este incidente ya está cerrada")
    resultado = datos.get("resultado") or "apto"
    if resultado not in RESULTADOS:
        raise ValueError("resultado no válido")
    firmado = (datos.get("firmado_por") or "").strip()
    licencia = (datos.get("licencia") or "").strip() or None
    cargo = (datos.get("cargo") or "").strip() or None
    if not firmado:
        raise ValueError("la inspección lleva el nombre de quien la firma")
    if inc["tipo_activo"] == "avion":
        if rol not in ROLES_FIRMA_AVION:
            raise PermissionError("la inspección de un avión la firma un inspector o mecánico certificador")
        if not licencia:
            raise ValueError("en un avión la firma lleva el número de licencia del inspector")
    elif not cargo:
        raise ValueError("indica si firma el técnico asignado o el representante del fabricante")
    con.execute(
        """UPDATE incidentes SET estado='cerrado', inspeccion_fecha=?, inspeccion_resultado=?,
               inspeccion_firmado_por=?, inspeccion_cargo=?, inspeccion_licencia=?, inspeccion_nota=?,
               inspeccion_usuario=? WHERE id=?""",
        (datos.get("fecha") or date.today().isoformat(), resultado, firmado, cargo, licencia,
         (datos.get("nota") or "").strip() or None, usuario, incidente_id))
    # Si la inspección dice «no apto», el activo pasa a taller hasta que se repare.
    if resultado == "no_apto":
        con.execute("UPDATE equipos SET estado='taller' WHERE id=?", (inc["equipo_id"],))
    con.commit()
