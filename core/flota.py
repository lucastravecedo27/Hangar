"""Flota mixta: drones y aviones en el mismo sistema.

Hasta ahora todo giraba alrededor de un solo contador, `horas_vuelo`, que cada operación sumaba
a todas las piezas del dron. Un avión agrícola se lleva con varios contadores a la vez —Hobbs
(tiempo de motor encendido), Tach (horas de motor), aterrizajes, arranques— y cada pieza se
desgasta con uno distinto: el motor por Tach, la célula por Hobbs, el tren por aterrizajes.

Este módulo reúne lo que eso implica:

  · CONTADORES: qué contadores existen y cómo se calcula el avance de cada uno en una operación.
  · Uso EXACTO de cada pieza: uso inicial + lo que marcó su contador en las operaciones hechas
    desde que se montó. Se recalcula al crear, editar o borrar una operación o un cambio de
    pieza, así que borrar una operación vieja ya no puede quitarle horas a una pieza montada
    después (antes se restaba a todas por igual).
  · Modelos de activo en la base (DJI sembrado desde core/modelos.py, plantillas de avión desde
    core/aeronaves.py, y modelos propios de cada empresa, editables).
  · Piezas con serial (motor, hélice, magnetos, baterías) con su historial de instalación.
  · Directivas de aeronavegabilidad (AD/SB), documentos con vencimiento y auditoría.
"""
import json
from core import conexion as core_conexion
from datetime import date, timedelta

# clave -> (nombre, unidad, expresión SQL del avance en una operación `o`)
CONTADORES = {
    "horas_vuelo": ("Horas de vuelo", "h", "COALESCE(o.horas_vuelo, 0)"),
    "despegues": ("Despegues", "desp.", "COALESCE(o.despegues, 0)"),
    "hobbs": ("Hobbs", "h", "COALESCE(o.hobbs_fin - o.hobbs_ini, o.horas_vuelo, 0)"),
    # Si no se anotó el Tach se toma el tiempo de vuelo: sobreestima un poco el desgaste del
    # motor, que es el lado seguro.
    "tach": ("Tach", "h", "COALESCE(o.tach_fin - o.tach_ini, o.horas_vuelo, 0)"),
    "aterrizajes": ("Aterrizajes", "aterr.", "COALESCE(o.aterrizajes, 0)"),
    "arranques": ("Arranques de motor", "arr.", "COALESCE(o.arranques, 0)"),
}
TIPOS_ACTIVO = {"dron": "Dron", "avion": "Avión"}
CONTADORES_POR_TIPO = {"dron": ["horas_vuelo", "despegues"],
                       "avion": ["hobbs", "tach", "aterrizajes", "arranques"]}
TIPOS_ITEM = {"pieza": "Pieza con vida útil", "inspeccion": "Inspección periódica"}
TIPOS_DOCUMENTO = {
    "aeronavegabilidad": "Certificado de aeronavegabilidad",
    "matricula": "Certificado de matrícula",
    "seguro": "Póliza de seguro",
    "registro_uas": "Registro del dron (UAS)",
    "permiso_operacion": "Permiso de operación",
    "licencia": "Licencia",
    "certificado_medico": "Certificado médico",
    # Añadidos por la RAC (ver core/rac.py).
    "licencia_radio": "Licencia de estación de radio (RAC 91.1413)",
    "informe_fiaa": "Informe anual de aeronavegabilidad FIAA (RAC 91.1136)",
    "colinesterasa": "Examen de colinesterasa (RAC 137.73)",
    "idoneidad_uas": "Certificado de idoneidad piloto UAS (RAC 100)",
    "autorizacion_uas": "Autorización de vuelo UAS (RAC 100.225)",
    "otro": "Otro",
}
ESTADOS_DIRECTIVA = {"pendiente": "Pendiente", "cumplida": "Cumplida", "no_aplica": "No aplica"}

DIAS_POR_MES = 30.44


def unidad(contador):
    return CONTADORES.get(contador, ("", "h", ""))[1]


def nombre_contador(contador):
    return CONTADORES.get(contador, (contador, "", ""))[0]


def _case(columna):
    """CASE SQL que da el avance del contador que dice `columna` en la operación `o`."""
    ramas = " ".join(f"WHEN '{k}' THEN {v[2]}" for k, v in CONTADORES.items())
    return f"(CASE {columna} {ramas} ELSE 0 END)"


def contadores_de_tipo(tipo_activo):
    return CONTADORES_POR_TIPO.get(tipo_activo or "dron", CONTADORES_POR_TIPO["dron"])


# ======================================================================
# Uso de las piezas y lecturas de contador
# ======================================================================

def recalcular_equipo(con, equipo_id):
    """Recalcula desde las operaciones el uso de cada pieza y las horas totales del equipo.

    uso = uso_inicial + Σ avance del contador de la pieza en las operaciones con fecha ≥ la
    fecha en que se montó (último cambio, o instalación). Una operación del mismo día del cambio
    cuenta para la pieza nueva: es el lado conservador.
    """
    desde = "COALESCE(c.fecha_ultimo_cambio, c.fecha_instalado, '0000-00-00')"
    con.execute(
        f"""UPDATE componentes c SET
              horas_uso = GREATEST(0, COALESCE(c.uso_inicial, 0) + COALESCE((
                  SELECT SUM({_case('p.contador_base')}) FROM operaciones o
                  WHERE o.equipo_id = c.equipo_id AND o.fecha >= {desde}), 0)),
              ciclos_uso = CASE WHEN p.contador_ciclos IS NULL OR p.contador_ciclos = '' THEN 0 ELSE
                  GREATEST(0, COALESCE(c.ciclos_inicial, 0) + COALESCE((
                  SELECT SUM({_case('p.contador_ciclos')}) FROM operaciones o
                  WHERE o.equipo_id = c.equipo_id AND o.fecha >= {desde}), 0)) END
            FROM catalogo_piezas p
            WHERE p.id = c.pieza_id AND c.equipo_id = ? AND c.uso_inicial IS NOT NULL""",
        (equipo_id,))
    con.execute(
        """UPDATE equipos e SET horas_totales = GREATEST(0,
              COALESCE((SELECT valor_inicial FROM contadores_equipo ce
                        WHERE ce.equipo_id = e.id AND ce.contador = 'horas_vuelo'), 0)
            + COALESCE((SELECT SUM(horas_vuelo) FROM operaciones o WHERE o.equipo_id = e.id), 0))
           WHERE e.id = ? AND EXISTS (SELECT 1 FROM contadores_equipo ce
                                      WHERE ce.equipo_id = e.id AND ce.contador = 'horas_vuelo')""",
        (equipo_id,))


def uso_hasta(con, componente_id, fecha):
    """Uso de una pieza justo antes de `fecha` (las operaciones de ese día ya no cuentan).
    Es lo que llevaba la pieza el día que se cambió, aunque el cambio se registre después."""
    fila = con.execute(
        f"""SELECT COALESCE(c.uso_inicial, 0) + COALESCE((
                  SELECT SUM({_case('p.contador_base')}) FROM operaciones o
                  WHERE o.equipo_id = c.equipo_id
                    AND o.fecha >= COALESCE(c.fecha_ultimo_cambio, c.fecha_instalado, '0000-00-00')
                    AND o.fecha < ?), 0) AS uso
            FROM componentes c JOIN catalogo_piezas p ON p.id = c.pieza_id WHERE c.id = ?""",
        (fecha, componente_id)).fetchone()
    return round(fila["uso"], 2) if fila else None


def avance_desde(con, componente_id):
    """Σ del contador de la pieza desde que se montó, sin el uso inicial."""
    fila = con.execute(
        f"""SELECT COALESCE((SELECT SUM({_case('p.contador_base')}) FROM operaciones o
                  WHERE o.equipo_id = c.equipo_id
                    AND o.fecha >= COALESCE(c.fecha_ultimo_cambio, c.fecha_instalado, '0000-00-00')), 0) AS s
            FROM componentes c JOIN catalogo_piezas p ON p.id = c.pieza_id WHERE c.id = ?""",
        (componente_id,)).fetchone()
    return fila["s"] if fila else 0


def lecturas(con, equipo_ids=None):
    """Valor actual de cada contador de cada equipo: {equipo_id: {contador: valor}}."""
    filtro, params = "", ()
    if equipo_ids is not None:
        if not equipo_ids:
            return {}
        filtro = f"WHERE ce.equipo_id IN ({','.join('?' * len(equipo_ids))})"
        params = tuple(equipo_ids)
    filas = con.execute(
        f"""SELECT ce.equipo_id, ce.contador, ce.valor_inicial,
                   ce.valor_inicial + COALESCE(SUM({_case('ce.contador')}), 0) AS valor
            FROM contadores_equipo ce
            LEFT JOIN operaciones o ON o.equipo_id = ce.equipo_id
            {filtro}
            GROUP BY ce.id, ce.equipo_id, ce.contador, ce.valor_inicial""", params).fetchall()
    salida = {}
    for f in filas:
        salida.setdefault(f["equipo_id"], {})[f["contador"]] = round(f["valor"] or 0, 1)
    return salida


def asegurar_contadores(con, equipo_id, tipo_activo, iniciales=None, empresa_id=None, lista=None):
    """Crea las filas de contador que le falten al equipo (con su valor inicial, si se da)."""
    iniciales = iniciales or {}
    lista = [c for c in (lista or contadores_de_tipo(tipo_activo)) if c in CONTADORES]
    # Todo activo lleva horas_vuelo: es lo que usan reportes, ritmo y horas_totales.
    if "horas_vuelo" not in lista:
        lista = ["horas_vuelo"] + lista
    for c in lista:
        valor = iniciales.get(c)
        if c == "horas_vuelo" and valor is None and "hobbs" in iniciales:
            valor = iniciales["hobbs"]
        try:
            valor = float(valor) if valor not in (None, "") else 0.0
        except (TypeError, ValueError):
            valor = 0.0
        if empresa_id is None:
            con.execute("INSERT INTO contadores_equipo(equipo_id, contador, valor_inicial) VALUES(?,?,?) "
                        "ON CONFLICT(equipo_id, contador) DO NOTHING", (equipo_id, c, valor))
        else:
            con.execute("INSERT INTO contadores_equipo(empresa_id, equipo_id, contador, valor_inicial) "
                        "VALUES(?,?,?,?) ON CONFLICT(equipo_id, contador) DO NOTHING",
                        (empresa_id, equipo_id, c, valor))


def ajustar_contador(con, equipo_id, contador, valor_actual, usuario=None, motivo=None):
    """Fija la lectura actual de un contador (p. ej. al corregir el Hobbs). Cambia el valor
    inicial para que valor_inicial + Σ operaciones = lectura indicada, y lo deja auditado."""
    actual = lecturas(con, [equipo_id]).get(equipo_id, {}).get(contador)
    fila = con.execute("SELECT valor_inicial FROM contadores_equipo WHERE equipo_id=? AND contador=?",
                       (equipo_id, contador)).fetchone()
    if fila is None:
        con.execute("INSERT INTO contadores_equipo(equipo_id, contador, valor_inicial) VALUES(?,?,0)",
                    (equipo_id, contador))
        actual, inicial = 0.0, 0.0
    else:
        inicial = fila["valor_inicial"] or 0
        actual = actual if actual is not None else inicial
    nuevo_inicial = inicial + (float(valor_actual) - actual)
    con.execute("UPDATE contadores_equipo SET valor_inicial=? WHERE equipo_id=? AND contador=?",
                (nuevo_inicial, equipo_id, contador))
    auditar(con, "contadores_equipo", equipo_id, contador, actual, valor_actual, usuario, motivo)
    recalcular_equipo(con, equipo_id)


def fijar_uso_componente(con, componente_id, uso, usuario=None, motivo=None):
    """Corrige a mano el uso de una pieza, dejando rastro (antes se sobrescribía sin más)."""
    fila = con.execute("SELECT equipo_id, horas_uso FROM componentes WHERE id=?", (componente_id,)).fetchone()
    if not fila:
        return False
    avance = avance_desde(con, componente_id)
    con.execute("UPDATE componentes SET uso_inicial=? WHERE id=?", (float(uso) - avance, componente_id))
    auditar(con, "componentes", componente_id, "horas_uso", fila["horas_uso"], uso, usuario, motivo)
    recalcular_equipo(con, fila["equipo_id"])
    return True


def conciliar(con):
    """Paso único de la migración a contadores, idempotente. Se ejecuta con conexión TODAS.

    · Cada equipo recibe sus filas de contador. El valor inicial de horas_vuelo se elige para que
      horas_totales no cambie: inicial = horas_totales − Σ horas de sus operaciones.
    · Cada componente sin uso_inicial (los de antes de esta versión) recibe el suyo con el mismo
      criterio: uso_inicial = horas_uso − Σ avance desde que se montó. Así, tras migrar, todas
      las alertas dan exactamente lo mismo que antes.
    """
    for e in con.execute(
            """SELECT e.id, e.empresa_id, e.tipo_activo, e.horas_totales,
                      COALESCE((SELECT SUM(horas_vuelo) FROM operaciones o WHERE o.equipo_id=e.id), 0) s
               FROM equipos e
               WHERE NOT EXISTS (SELECT 1 FROM contadores_equipo ce WHERE ce.equipo_id=e.id)""").fetchall():
        asegurar_contadores(con, e["id"], e["tipo_activo"],
                            {"horas_vuelo": (e["horas_totales"] or 0) - (e["s"] or 0)},
                            empresa_id=e["empresa_id"])
    desde = "COALESCE(c.fecha_ultimo_cambio, c.fecha_instalado, '0000-00-00')"
    con.execute(
        f"""UPDATE componentes c SET
              uso_inicial = COALESCE(c.horas_uso, 0) - COALESCE((
                  SELECT SUM({_case('p.contador_base')}) FROM operaciones o
                  WHERE o.equipo_id = c.equipo_id AND o.fecha >= {desde}), 0),
              ciclos_inicial = 0
            FROM catalogo_piezas p
            WHERE p.id = c.pieza_id AND c.uso_inicial IS NULL""")
    con.commit()


# ======================================================================
# Modelos de activo
# ======================================================================

def sembrar_modelos(con, modelos_dji, plantillas_avion):
    """Deja en `modelos_activo` los modelos del sistema (empresa_id nulo): DJI y plantillas."""
    for m in modelos_dji:
        con.execute(
            """INSERT INTO modelos_activo(empresa_id, clave, tipo_activo, fabricante, nombre, contadores,
                                          descripcion, es_plantilla)
               VALUES(NULL,?,?,?,?,?,?,0)
               ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, descripcion=excluded.descripcion,
                 fabricante=excluded.fabricante, contadores=excluded.contadores""",
            (m["clave"], "dron", "DJI", m["nombre"], ",".join(CONTADORES_POR_TIPO["dron"]),
             m.get("descripcion")))
    for p in plantillas_avion:
        con.execute(
            """INSERT INTO modelos_activo(empresa_id, clave, tipo_activo, fabricante, nombre, contadores,
                                          descripcion, es_plantilla)
               VALUES(NULL,?,?,?,?,?,?,1)
               ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, descripcion=excluded.descripcion,
                 fabricante=excluded.fabricante, contadores=excluded.contadores""",
            (p["clave"], p["tipo_activo"], p["fabricante"], p["nombre"], ",".join(p["contadores"]),
             p["descripcion"]))
        _sembrar_items(con, p["clave"], p["catalogo"], borrar_sobrantes=True)
    con.commit()


def _sembrar_items(con, modelo, items, borrar_sobrantes=False, empresa_id=None):
    claves = [i["clave"] for i in items]
    if borrar_sobrantes and claves:
        marcas = ",".join("?" * len(claves))
        con.execute(f"DELETE FROM catalogo_piezas WHERE modelo=? AND clave NOT IN ({marcas})", [modelo] + claves)
    for i in items:
        con.execute(
            """INSERT INTO catalogo_piezas(empresa_id, modelo, clave, modulo, nombre, vida_util_horas,
                   vida_util_meses, nota, tipo_item, contador_base, contador_ciclos, limite_ciclos,
                   tolerancia, serializada, referencia, zona, precio)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(modelo, clave) DO UPDATE SET modulo=excluded.modulo, nombre=excluded.nombre,
                 vida_util_horas=excluded.vida_util_horas, vida_util_meses=excluded.vida_util_meses,
                 nota=excluded.nota, tipo_item=excluded.tipo_item, contador_base=excluded.contador_base,
                 contador_ciclos=excluded.contador_ciclos, limite_ciclos=excluded.limite_ciclos,
                 tolerancia=excluded.tolerancia, serializada=excluded.serializada,
                 referencia=excluded.referencia, zona=excluded.zona""",
            (empresa_id, modelo, i["clave"], i["modulo"], i["nombre"], i.get("limite") or 0,
             i.get("meses") or 0, i.get("nota"), i.get("tipo_item") or "pieza",
             i.get("contador") or "horas_vuelo", i.get("contador_ciclos"), i.get("limite_ciclos") or 0,
             i.get("tolerancia") or 0, 1 if i.get("serializada") else 0,
             1 if i.get("referencia") else 0, i["modulo"], i.get("precio")))


def modelos(con, tipo_activo=None):
    cond, params = ["activo=1"], []
    if tipo_activo:
        cond.append("tipo_activo=?"); params.append(tipo_activo)
    filas = con.execute(
        f"""SELECT m.*, (SELECT COUNT(*) FROM catalogo_piezas p WHERE p.modelo=m.clave) n_items,
                   (SELECT COUNT(*) FROM equipos e WHERE e.modelo=m.clave) n_equipos
            FROM modelos_activo m WHERE {' AND '.join(cond)}
            ORDER BY m.tipo_activo, m.es_plantilla, m.nombre""", params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["contadores"] = [c for c in (d["contadores"] or "").split(",") if c]
        d["propio"] = d["empresa_id"] is not None
        salida.append(d)
    return salida


def modelo_activo(con, clave):
    fila = con.execute("SELECT * FROM modelos_activo WHERE clave=?", (clave,)).fetchone()
    if not fila:
        return None
    d = dict(fila)
    d["contadores"] = [c for c in (d["contadores"] or "").split(",") if c]
    d["propio"] = d["empresa_id"] is not None
    return d


def _clave_libre(con, base):
    base = "".join(ch for ch in base.upper() if ch.isalnum() or ch in "-_")[:24] or "MODELO"
    clave, n = base, 1
    while con.execute("SELECT 1 FROM modelos_activo WHERE clave=?", (clave,)).fetchone() or \
            con.execute("SELECT 1 FROM catalogo_piezas WHERE modelo=? LIMIT 1", (clave,)).fetchone():
        n += 1
        clave = f"{base}-{n}"
    return clave


def crear_modelo(con, nombre, tipo_activo, fabricante=None, contadores=None, descripcion=None,
                 desde_plantilla=None, empresa_id=None):
    """Modelo propio de la empresa. Si viene de una plantilla, copia su catálogo (editable)."""
    plantilla = modelo_activo(con, desde_plantilla) if desde_plantilla else None
    if plantilla:
        tipo_activo = plantilla["tipo_activo"]
        contadores = contadores or plantilla["contadores"]
        fabricante = fabricante or plantilla["fabricante"]
    contadores = [c for c in (contadores or contadores_de_tipo(tipo_activo)) if c in CONTADORES]
    clave = _clave_libre(con, f"{desde_plantilla or nombre}-E{empresa_id or con.empresa_id}")
    con.execute(
        """INSERT INTO modelos_activo(clave, tipo_activo, fabricante, nombre, contadores, descripcion,
                                      plantilla, es_plantilla) VALUES(?,?,?,?,?,?,?,0)""",
        (clave, tipo_activo, fabricante, nombre, ",".join(contadores), descripcion, desde_plantilla))
    if plantilla:
        for p in con.execute("SELECT * FROM catalogo_piezas WHERE modelo=?", (desde_plantilla,)).fetchall():
            con.execute(
                """INSERT INTO catalogo_piezas(modelo, clave, modulo, nombre, vida_util_horas, vida_util_meses,
                       nota, mesh, zona, tipo_item, contador_base, contador_ciclos, limite_ciclos, tolerancia,
                       serializada, referencia, precio)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (clave, p["clave"], p["modulo"], p["nombre"], p["vida_util_horas"], p["vida_util_meses"],
                 p["nota"], p["mesh"], p["zona"], p["tipo_item"], p["contador_base"], p["contador_ciclos"],
                 p["limite_ciclos"], p["tolerancia"], p["serializada"], p["referencia"], p["precio"]))
    return clave


def asegurar_modelo_propio(con, clave):
    """Los activos de avión se dan de alta sobre un modelo propio de la empresa (su catálogo es
    editable). Si se elige una plantilla, se reutiliza la copia que ya exista o se crea una."""
    m = modelo_activo(con, clave)
    if not m or not m["es_plantilla"]:
        return clave
    copia = con.execute("SELECT clave FROM modelos_activo WHERE plantilla=? AND empresa_id=empresa_actual() "
                        "ORDER BY id LIMIT 1", (clave,)).fetchone()
    if copia:
        return copia["clave"]
    return crear_modelo(con, m["nombre"].replace(" (plantilla)", ""), m["tipo_activo"], m["fabricante"],
                        m["contadores"], m["descripcion"], desde_plantilla=clave)


def completar_componentes(con, modelo=None, equipo_id=None):
    """Crea los componentes que le falten a cada equipo según el catálogo de su modelo.

    Antes sólo se creaban al dar de alta el equipo: una pieza añadida después al catálogo no
    llegaba nunca a los equipos existentes. La pieza nueva arranca contando desde la fecha de
    alta del equipo (lado conservador: se asume que lleva todo el uso del equipo)."""
    cond, params = ["e.estado != 'baja'"], []
    if modelo:
        cond.append("e.modelo=?"); params.append(modelo)
    if equipo_id:
        cond.append("e.id=?"); params.append(equipo_id)
    faltan = con.execute(
        f"""SELECT e.id equipo_id, e.empresa_id, e.fecha_alta, p.id pieza_id
            FROM equipos e JOIN catalogo_piezas p ON p.modelo = e.modelo
            WHERE {' AND '.join(cond)}
              AND NOT EXISTS (SELECT 1 FROM componentes c WHERE c.equipo_id=e.id AND c.pieza_id=p.id)""",
        params).fetchall()
    tocados = set()
    for f in faltan:
        con.execute("INSERT INTO componentes(empresa_id, equipo_id, pieza_id, uso_inicial, ciclos_inicial, "
                    "fecha_instalado) VALUES(?,?,?,0,0,COALESCE(?, to_char(CURRENT_DATE,'YYYY-MM-DD'))) "
                    "ON CONFLICT DO NOTHING",
                    (f["empresa_id"], f["equipo_id"], f["pieza_id"], f["fecha_alta"]))
        tocados.add(f["equipo_id"])
    for e in tocados:
        recalcular_equipo(con, e)
    return len(faltan)


# ======================================================================
# Piezas con serial e instalaciones
# ======================================================================

def piezas_serie(con, tipo=None, equipo_id=None, estado=None):
    cond, params = ["1=1"], []
    if tipo:
        cond.append("s.tipo=?"); params.append(tipo)
    else:
        cond.append("s.tipo <> 'bateria'")   # las baterías tienen su propia lista
    if equipo_id:
        cond.append("s.equipo_id=?"); params.append(equipo_id)
    if estado:
        cond.append("s.estado=?"); params.append(estado)
    filas = con.execute(
        f"""SELECT s.*, e.nombre AS equipo, e.matricula, c.horas_uso AS uso_en_equipo,
                   p.nombre AS pieza_nombre, p.vida_util_horas, p.contador_base
            FROM piezas_serie s
            LEFT JOIN equipos e ON e.id = s.equipo_id
            LEFT JOIN componentes c ON c.id = s.componente_id
            LEFT JOIN catalogo_piezas p ON p.id = c.pieza_id
            WHERE {' AND '.join(cond)} ORDER BY s.tipo, s.pieza_clave, s.serial""", params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        # TSO/uso vigente: si está montada, lo que marca el componente; si no, lo acumulado.
        d["uso_actual"] = round(d["uso_en_equipo"] if d["componente_id"] and d["uso_en_equipo"] is not None
                                else (d["uso_acumulado"] or 0), 1)
        d["tsn"] = round((d["tsn_inicial"] or 0) + (d["uso_actual"] - (d["tso_inicial"] or 0))
                         if d["tsn_inicial"] is not None else d["uso_actual"], 1)
        salida.append(d)
    return salida


def crear_pieza_serie(con, datos):
    cur = con.execute(
        """INSERT INTO piezas_serie(tipo, pieza_clave, serial, descripcion, uso_acumulado, tso_inicial,
                                    tsn_inicial, ciclos_acumulados, vida_ciclos, estado, fecha_compra, precio, nota)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datos.get("tipo") or "pieza", datos.get("pieza_clave") or None, datos["serial"].strip(),
         datos.get("descripcion") or None, _num(datos.get("uso_acumulado")) or 0,
         _num(datos.get("uso_acumulado")) or 0, _num(datos.get("tsn_inicial")),
         _num(datos.get("ciclos_acumulados")) or 0, _num(datos.get("vida_ciclos")),
         "bodega", datos.get("fecha_compra") or None, _num(datos.get("precio")), datos.get("nota") or None))
    return cur.lastrowid


def instalar(con, pieza_serie_id, componente_id, fecha=None, usuario=None, motivo=None):
    """Monta una pieza con serial en el puesto (componente) de un equipo. El componente pasa a
    contar desde la fecha de montaje con el uso que ya trae la pieza (su TSO)."""
    fecha = fecha or date.today().isoformat()
    s = con.execute("SELECT * FROM piezas_serie WHERE id=?", (pieza_serie_id,)).fetchone()
    comp = con.execute("SELECT c.*, p.clave FROM componentes c JOIN catalogo_piezas p ON p.id=c.pieza_id "
                       "WHERE c.id=?", (componente_id,)).fetchone()
    if not s or not comp:
        raise ValueError("La pieza o el puesto no existen.")
    if s["estado"] == "montada":
        raise ValueError(f"La pieza {s['serial']} ya está montada; desmóntala primero.")
    # Si el puesto tenía otra pieza con serial, se desmonta en la misma fecha.
    if comp["pieza_serie_id"]:
        desmontar(con, comp["pieza_serie_id"], fecha, usuario, "Reemplazada por " + s["serial"])
    con.execute("UPDATE componentes SET pieza_serie_id=?, fecha_ultimo_cambio=?, uso_inicial=?, ciclos_inicial=? "
                "WHERE id=?", (pieza_serie_id, fecha, s["uso_acumulado"] or 0, s["ciclos_acumulados"] or 0,
                              componente_id))
    con.execute("UPDATE piezas_serie SET estado='montada', equipo_id=?, componente_id=?, pieza_clave=COALESCE(pieza_clave, ?) "
                "WHERE id=?", (comp["equipo_id"], componente_id, comp["clave"], pieza_serie_id))
    con.execute("INSERT INTO instalaciones(pieza_serie_id, equipo_id, componente_id, desde, uso_al_montar, motivo, usuario) "
                "VALUES(?,?,?,?,?,?,?)", (pieza_serie_id, comp["equipo_id"], componente_id, fecha,
                                          s["uso_acumulado"] or 0, motivo, usuario))
    recalcular_equipo(con, comp["equipo_id"])


def desmontar(con, pieza_serie_id, fecha=None, usuario=None, motivo=None, estado="bodega"):
    fecha = fecha or date.today().isoformat()
    s = con.execute("SELECT * FROM piezas_serie WHERE id=?", (pieza_serie_id,)).fetchone()
    if not s or s["estado"] != "montada" or not s["componente_id"]:
        raise ValueError("La pieza no está montada.")
    uso = uso_hasta(con, s["componente_id"], _dia_siguiente(fecha))
    ciclos = con.execute("SELECT ciclos_uso FROM componentes WHERE id=?", (s["componente_id"],)).fetchone()
    con.execute("UPDATE piezas_serie SET estado=?, uso_acumulado=?, ciclos_acumulados=?, equipo_id=NULL, "
                "componente_id=NULL WHERE id=?",
                (estado if estado in ("bodega", "overhaul", "baja") else "bodega", uso,
                 ciclos["ciclos_uso"] if ciclos else s["ciclos_acumulados"], pieza_serie_id))
    con.execute("UPDATE instalaciones SET hasta=?, uso_al_desmontar=?, motivo=COALESCE(motivo,'') || ? "
                "WHERE pieza_serie_id=? AND hasta IS NULL",
                (fecha, uso, (" · " + motivo) if motivo else "", pieza_serie_id))
    con.execute("UPDATE componentes SET pieza_serie_id=NULL WHERE id=?", (s["componente_id"],))


def instalaciones_de(con, pieza_serie_id):
    return [dict(f) for f in con.execute(
        "SELECT i.*, e.nombre equipo, e.matricula FROM instalaciones i JOIN equipos e ON e.id=i.equipo_id "
        "WHERE i.pieza_serie_id=? ORDER BY i.desde DESC, i.id DESC", (pieza_serie_id,)).fetchall()]


def _dia_siguiente(fecha):
    try:
        return (date.fromisoformat(fecha[:10]) + timedelta(days=1)).isoformat()
    except ValueError:
        return fecha


# ======================================================================
# Baterías de dron
# ======================================================================

def baterias(con, equipo_id=None):
    """Baterías con sus ciclos. Si no se ha leído el contador de la batería, los ciclos se
    estiman repartiendo los despegues del dron desde la asignación entre las baterías que
    tiene asignadas (cada despegue es aproximadamente un ciclo de una batería)."""
    cond, params = ["s.tipo='bateria'"], []
    if equipo_id:
        cond.append("s.equipo_id=?"); params.append(equipo_id)
    filas = con.execute(
        f"""SELECT s.*, e.nombre equipo,
                   (SELECT COUNT(*) FROM piezas_serie b WHERE b.tipo='bateria' AND b.equipo_id=s.equipo_id
                      AND b.estado='montada') n_en_equipo,
                   COALESCE((SELECT SUM(COALESCE(o.despegues,0)) FROM operaciones o
                             WHERE o.equipo_id=s.equipo_id AND s.equipo_id IS NOT NULL
                               AND o.fecha > COALESCE(s.fecha_asignada, '0000-00-00')), 0) desp_desde
            FROM piezas_serie s LEFT JOIN equipos e ON e.id=s.equipo_id
            WHERE {' AND '.join(cond)} ORDER BY e.nombre NULLS LAST, s.serial""", params).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        estimados = (d["desp_desde"] / d["n_en_equipo"]) if d["equipo_id"] and d["n_en_equipo"] else 0
        d["ciclos"] = round((d["ciclos_acumulados"] or 0) + estimados)
        d["ciclos_estimados"] = bool(estimados)
        vida = d["vida_ciclos"] or 0
        d["pct"] = round(d["ciclos"] / vida * 100, 1) if vida else None
        d["nivel"] = _nivel(d["ciclos"] / vida) if vida else "ok"
        d["costo_ciclo"] = round(d["precio"] / vida, 2) if vida and d["precio"] else None
        salida.append(d)
    return salida


def asignar_bateria(con, bateria_id, equipo_id, fecha=None):
    """Cierra los ciclos estimados en el dron anterior y la asigna al nuevo (o a bodega)."""
    actual = next((b for b in baterias(con) if b["id"] == bateria_id), None)
    if not actual:
        raise ValueError("La batería no existe.")
    con.execute("UPDATE piezas_serie SET ciclos_acumulados=?, equipo_id=?, estado=?, fecha_asignada=? WHERE id=?",
                (actual["ciclos"], equipo_id, "montada" if equipo_id else "bodega",
                 fecha or date.today().isoformat(), bateria_id))


def leer_ciclos_bateria(con, bateria_id, ciclos):
    """Lectura real del contador de ciclos de la batería: reemplaza la estimación."""
    con.execute("UPDATE piezas_serie SET ciclos_acumulados=?, fecha_asignada=? WHERE id=? AND tipo='bateria'",
                (float(ciclos), date.today().isoformat(), bateria_id))


# ======================================================================
# Directivas y documentos
# ======================================================================

def _nivel(fraccion):
    if fraccion >= 1:
        return "vencido"
    if fraccion >= 0.90:
        return "critico"
    if fraccion >= 0.75:
        return "proximo"
    return "ok"


def _nivel_por_dias(dias):
    if dias is None:
        return "ok"
    if dias < 0:
        return "vencido"
    if dias <= 15:
        return "critico"
    if dias <= 45:
        return "proximo"
    return "ok"


def directivas_con_estado(con, equipo_id=None):
    """Estado de cada directiva en cada avión de su modelo (último registro de cumplimiento)."""
    cond, params = ["e.estado != 'baja'"], []
    if equipo_id:
        cond.append("e.id=?"); params.append(equipo_id)
    filas = con.execute(
        f"""SELECT d.*, e.id equipo_id, e.nombre equipo, e.matricula, e.modelo equipo_modelo,
                   c.id cumplimiento_id, c.estado estado_cumpl, c.fecha fecha_cumpl, c.valor_contador,
                   c.firmado_por, c.licencia, c.nota nota_cumpl
            FROM directivas d
            JOIN equipos e ON e.modelo = d.modelo OR (d.modelo IS NULL OR d.modelo = '')
            LEFT JOIN cumplimiento_directiva c ON c.id = (
                SELECT x.id FROM cumplimiento_directiva x
                WHERE x.directiva_id = d.id AND x.equipo_id = e.id
                ORDER BY x.fecha DESC NULLS LAST, x.id DESC LIMIT 1)
            WHERE {' AND '.join(cond)} ORDER BY d.numero, e.nombre""", params).fetchall()
    ids = list({f["equipo_id"] for f in filas})
    lect = lecturas(con, ids) if ids else {}
    hoy = date.today()
    salida = []
    for f in filas:
        d = dict(f)
        estado = d["estado_cumpl"] or "pendiente"
        d["estado"] = estado
        d["estado_txt"] = ESTADOS_DIRECTIVA.get(estado, estado)
        d["nivel"], d["pct"], d["dias_restantes"], d["restante"], d["proxima"] = "ok", 0, None, None, None
        valor_actual = lect.get(d["equipo_id"], {}).get(d["intervalo_contador"] or "horas_vuelo")
        if estado == "no_aplica":
            pass
        elif estado == "pendiente":
            if d["limite_fecha"]:
                try:
                    d["dias_restantes"] = (date.fromisoformat(d["limite_fecha"][:10]) - hoy).days
                except ValueError:
                    pass
                d["nivel"] = _nivel_por_dias(d["dias_restantes"])
            if d["limite_valor"] and valor_actual is not None:
                d["restante"] = round(d["limite_valor"] - valor_actual, 1)
                n2 = "vencido" if d["restante"] <= 0 else "critico" if d["restante"] <= 10 else "proximo"
                d["nivel"] = min(d["nivel"], n2, key=lambda n: ["vencido", "critico", "proximo", "ok"].index(n)) \
                    if d["limite_fecha"] else n2
            if not d["limite_fecha"] and not d["limite_valor"]:
                d["nivel"] = "critico"   # pendiente y sin plazo: hay que decidir ya si aplica
        elif estado == "cumplida" and d["recurrente"]:
            fr = []
            if d["intervalo_dias"] and d["fecha_cumpl"]:
                try:
                    prox = date.fromisoformat(d["fecha_cumpl"][:10]) + timedelta(days=int(d["intervalo_dias"]))
                    d["proxima"] = prox.isoformat()
                    d["dias_restantes"] = (prox - hoy).days
                    fr.append(1 - d["dias_restantes"] / d["intervalo_dias"])
                except ValueError:
                    pass
            if d["intervalo_valor"] and d["valor_contador"] is not None and valor_actual is not None:
                usado = valor_actual - d["valor_contador"]
                d["restante"] = round(d["intervalo_valor"] - usado, 1)
                fr.append(usado / d["intervalo_valor"])
            if fr:
                d["pct"] = round(max(fr) * 100, 1)
                d["nivel"] = _nivel(max(fr))
        d["unidad"] = unidad(d["intervalo_contador"] or "horas_vuelo")
        salida.append(d)
    return salida


def documentos_con_estado(con, equipo_id=None, incluir_personal=True):
    cond, params = ["1=1"], []
    if equipo_id:
        cond.append("d.equipo_id=?"); params.append(equipo_id)
    elif not incluir_personal:
        cond.append("d.equipo_id IS NOT NULL")
    filas = con.execute(
        f"""SELECT d.*, e.nombre equipo, e.matricula, p.nombre persona
            FROM documentos d LEFT JOIN equipos e ON e.id=d.equipo_id LEFT JOIN personal p ON p.id=d.personal_id
            WHERE {' AND '.join(cond)} ORDER BY d.vence NULLS LAST""", params).fetchall()
    hoy = date.today()
    salida = []
    for f in filas:
        d = dict(f)
        d["tipo_txt"] = TIPOS_DOCUMENTO.get(d["tipo"], d["tipo"])
        d["dias_restantes"] = None
        if d["vence"]:
            try:
                d["dias_restantes"] = (date.fromisoformat(d["vence"][:10]) - hoy).days
            except ValueError:
                pass
        dr = d["dias_restantes"]
        d["nivel"] = ("vencido" if dr is not None and dr < 0 else "critico" if dr is not None and dr <= 15
                      else "proximo" if dr is not None and dr <= 30 else "ok")
        salida.append(d)
    return salida


def cumplir_directiva(con, directiva_id, equipo_id, estado, fecha=None, firmado_por=None, licencia=None,
                      nota=None, orden_id=None):
    if estado not in ESTADOS_DIRECTIVA:
        raise ValueError("estado no válido")
    d = con.execute("SELECT * FROM directivas WHERE id=?", (directiva_id,)).fetchone()
    if not d:
        raise ValueError("La directiva no existe.")
    valor = lecturas(con, [equipo_id]).get(equipo_id, {}).get(d["intervalo_contador"] or "horas_vuelo")
    con.execute(
        """INSERT INTO cumplimiento_directiva(directiva_id, equipo_id, estado, fecha, valor_contador, firmado_por,
                                              licencia, nota, orden_id) VALUES(?,?,?,?,?,?,?,?,?)""",
        (directiva_id, equipo_id, estado, fecha or date.today().isoformat(), valor, firmado_por, licencia,
         nota, orden_id))


# ======================================================================
# Estado de aeronavegabilidad
# ======================================================================

ESTADOS_AERO = {"apto": "Apto", "observaciones": "Apto con observaciones",
                "no_apto": "No recomendado volar"}


def estado_aeronavegable(con, comps_por_equipo, directivas=None, documentos=None, equipos=None):
    """Estado de cada equipo a partir de lo ya calculado (no vuelve a consultar componentes).

    No apto: pieza o inspección vencida (fuera de tolerancia), directiva vencida, documento del
    activo vencido, o el activo en taller/baja. Con observaciones: algo crítico, o una directiva /
    documento por vencer. Apto: nada de lo anterior."""
    directivas = directivas or []
    documentos = documentos or []
    salida = {}
    for eq in (equipos or []):
        salida[eq["id"]] = {"estado": "apto", "motivos": []}
    def marcar(eid, nivel, texto):
        d = salida.setdefault(eid, {"estado": "apto", "motivos": []})
        if nivel == "vencido":
            d["estado"] = "no_apto"
            d["motivos"].append(texto)
        elif nivel in ("critico",) or (nivel == "proximo" and texto.startswith(("Directiva", "Documento"))):
            if d["estado"] == "apto":
                d["estado"] = "observaciones"
            d["motivos"].append(texto)
    for eid, comps in comps_por_equipo.items():
        for c in comps:
            if c.get("sin_plazo"):
                continue
            if c["nivel"] == "vencido":
                marcar(eid, "vencido", f"{c['nombre']} vencida")
            elif c["nivel"] == "critico":
                marcar(eid, "critico", f"{c['nombre']} crítica" + (" (en tolerancia)" if c.get("en_tolerancia") else ""))
    for d in directivas:
        if d["nivel"] != "ok":
            marcar(d["equipo_id"], d["nivel"], f"Directiva {d['numero']} {d['estado_txt'].lower()}")
    for d in documentos:
        if d.get("equipo_id") and d["nivel"] != "ok":
            marcar(d["equipo_id"], d["nivel"], f"Documento {d['tipo_txt'].lower()} "
                   + ("vencido" if d["nivel"] == "vencido" else f"vence en {d['dias_restantes']} días"))
    for eq in (equipos or []):
        if eq.get("estado") in ("taller", "mantenimiento"):
            salida[eq["id"]]["estado"] = "no_apto"
            salida[eq["id"]]["motivos"].insert(0, "En taller")
    for d in salida.values():
        d["estado_txt"] = ESTADOS_AERO[d["estado"]]
    return salida


# ======================================================================
# Auditoría
# ======================================================================

def auditar(con, tabla, fila_id, campo, antes, despues, usuario=None, motivo=None):
    con.execute("INSERT INTO auditoria(tabla, fila_id, campo, antes, despues, usuario, motivo) VALUES(?,?,?,?,?,?,?)",
                (tabla, fila_id, campo, None if antes is None else str(antes),
                 None if despues is None else str(despues), usuario, motivo))


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def a_json(v):
    return json.dumps(v, ensure_ascii=False)


# ======================================================================
# Disponibilidad histórica
# ======================================================================

def registrar_estado_diario(con, estados, equipos, fecha=None):
    """Guarda (o actualiza) la foto de hoy del estado de cada activo. `estados` es la salida de
    estado_aeronavegable y `equipos` las filas con id y estado (activo/mantenimiento/taller/baja).
    Un activo en taller o de baja cuenta como no disponible aunque sus piezas estén al día."""
    fecha = fecha or date.today().isoformat()
    for e in equipos:
        est = estados.get(e["id"], {"estado": "apto", "motivos": []})
        estado = est["estado"]
        if e.get("estado") in ("taller", "mantenimiento"):
            estado = "taller"
        elif e.get("estado") == "baja":
            estado = "baja"
        con.execute(
            """INSERT INTO estado_diario(equipo_id, fecha, estado, estado_equipo, motivos) VALUES(?,?,?,?,?)
               ON CONFLICT(equipo_id, fecha) DO UPDATE SET estado=excluded.estado,
                 estado_equipo=excluded.estado_equipo, motivos=excluded.motivos,
                 actualizado=to_char(now(), 'YYYY-MM-DD HH24:MI:SS')""",
            (e["id"], fecha, estado, e.get("estado"), "; ".join(est.get("motivos", [])[:6]) or None))


DISPONIBLE = ("apto", "observaciones")


def disponibilidad(con, desde=None, hasta=None, tipo=None, equipo_id=None):
    """Disponibilidad por activo en el período: días disponibles ÷ días con foto, y la franja
    diaria para pintarla. Los días sin foto (antes de empezar a registrar) no cuentan."""
    cond, params = ["e.estado != 'baja' OR d.estado IS NOT NULL"], []
    filtros = []
    if desde:
        filtros.append("d.fecha >= ?"); params.append(desde)
    if hasta:
        filtros.append("d.fecha <= ?"); params.append(hasta)
    extra = ("AND " + " AND ".join(filtros)) if filtros else ""
    where_e, pe = ["e.estado != 'baja'"], []
    if tipo:
        where_e.append("e.tipo_activo=?"); pe.append(tipo)
    if equipo_id:
        where_e.append("e.id=?"); pe.append(equipo_id)
    equipos = [dict(r) for r in con.execute(
        f"SELECT id, nombre, matricula, tipo_activo, modelo FROM equipos e WHERE {' AND '.join(where_e)} ORDER BY tipo_activo DESC, nombre",
        pe).fetchall()]
    if not equipos:
        return {"activos": [], "total": None, "primer_dia": None}
    ids = [e["id"] for e in equipos]
    filas = con.execute(
        f"""SELECT d.equipo_id, d.fecha, d.estado, d.motivos FROM estado_diario d
            WHERE d.equipo_id IN ({','.join('?' * len(ids))}) {extra} ORDER BY d.fecha""",
        ids + params).fetchall()
    por = {}
    for f in filas:
        por.setdefault(f["equipo_id"], []).append({"fecha": f["fecha"], "estado": f["estado"], "motivos": f["motivos"]})
    tot_d, tot_ok = 0, 0
    for e in equipos:
        dias = por.get(e["id"], [])
        ok = sum(1 for d in dias if d["estado"] in DISPONIBLE)
        e["dias"] = dias
        e["dias_registrados"] = len(dias)
        e["dias_disponible"] = ok
        e["dias_no_recomendado"] = sum(1 for d in dias if d["estado"] == "no_apto")
        e["dias_taller"] = sum(1 for d in dias if d["estado"] == "taller")
        e["disponibilidad"] = round(ok / len(dias) * 100, 1) if dias else None
        tot_d += len(dias); tot_ok += ok
    primero = con.execute("SELECT MIN(fecha) f FROM estado_diario").fetchone()["f"]
    return {"activos": equipos, "total": round(tot_ok / tot_d * 100, 1) if tot_d else None, "primer_dia": primero}


def mttr(con, desde=None, hasta=None, tipo=None, equipo_id=None):
    """Tiempo medio de reparación: días desde que se abre una OT correctiva (o de daño) hasta que
    se cierra, en las OT cerradas del período."""
    cond, params = ["o.estado='completada'", "o.cerrado_en IS NOT NULL",
                    "(o.tipo='correctivo' OR EXISTS (SELECT 1 FROM ot_tareas t WHERE t.orden_id=o.id AND t.motivo='daño'))"], []
    if desde:
        cond.append("LEFT(o.cerrado_en,10) >= ?"); params.append(desde)
    if hasta:
        cond.append("LEFT(o.cerrado_en,10) <= ?"); params.append(hasta)
    if tipo:
        cond.append("o.equipo_id IN (SELECT id FROM equipos WHERE tipo_activo=?)"); params.append(tipo)
    if equipo_id:
        cond.append("o.equipo_id=?"); params.append(equipo_id)
    f = con.execute(f"""SELECT COUNT(*) n, AVG({core_conexion.sql_dias('o.creado', 'o.cerrado_en')}) dias
                        FROM ordenes_trabajo o WHERE {' AND '.join(cond)}""", params).fetchone()
    return {"n": f["n"], "dias": round(float(f["dias"]), 1) if f["dias"] is not None else None}
