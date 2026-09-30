"""Importa la bitácora de operaciones (Excel) a la base. Se corre a mano:

    python manage.py importar-bitacora "ruta/Datos de Bitacora.xlsx"

Sólo se importa una vez por serial (queda anotado en `meta`); en el servidor la app nunca lo
hace sola al arrancar.
"""
from datetime import date, datetime

from core import db as core_db
from core import flota as core_flota

# Qué dron es cada serial de la bitácora. El modelo no está en el Excel: lo dice la operación,
# y de él dependen el catálogo de piezas que se le crea al equipo y sus alertas.
# SMR 3 se queda fuera hasta saber de qué modelo es.
MODELO_POR_SERIAL = {
    "SMR 1": "T50",
    "SMR 2": "T50",
    "SMR 4": "T50",
    "SMR 5": "T70P",
}
SERIALES = list(MODELO_POR_SERIAL)

COL = dict(fecha=0, zona=5, cliente=6, finca=7, serial=8, ha_programadas=9, piloto=10, tiempo_total=13,
           despegues=14, dosis_objetivo=16, litros=17, mezcla=18, hectareas=19, temperatura=20, viento=21,
           humedad=22, velocidad=24, altura=25, horas_vuelo=29)


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _texto(v):
    return str(v).strip() if v not in (None, "") else None


def _fecha(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return None


def importar(con, ruta):
    from pathlib import Path
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(ruta)
    pendientes = [s for s in SERIALES if not core_db.meta_get(con, f"bitacora_importada:{s}")]
    if not pendientes:
        return 0
    importadas = 0

    import openpyxl
    ws = openpyxl.load_workbook(ruta, data_only=True, read_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))[1:]

    for serial in pendientes:
        clave = serial.replace(" ", "").upper()
        propias = [f for f in filas if _texto(f[COL["serial"]]) and f[COL["serial"]].replace(" ", "").upper() == clave]
        propias.sort(key=lambda f: (f[COL["fecha"]] or datetime.min))

        equipo = con.execute("SELECT id FROM equipos WHERE nombre=?", (serial,)).fetchone()
        equipo_id = equipo["id"] if equipo else core_db.crear_equipo(
            con, serial, MODELO_POR_SERIAL[serial], serial,
            "Importado desde la bitácora de operaciones."
        )

        for f in propias:
            fecha = _fecha(f[COL["fecha"]])
            horas = _num(f[COL["horas_vuelo"]])
            if not fecha or horas is None:
                continue
            importadas += 1
            core_db.registrar_operacion(
                con, equipo_id, horas, fecha=fecha, commit=False,
                tiempo_total=_num(f[COL["tiempo_total"]]),
                despegues=int(_num(f[COL["despegues"]]) or 0) or None,
                hectareas=_num(f[COL["hectareas"]]),
                producto=_texto(f[COL["mezcla"]]),
                litros=_num(f[COL["litros"]]),
                piloto=_texto(f[COL["piloto"]]),
                cliente=_texto(f[COL["cliente"]]),
                zona=_texto(f[COL["zona"]]),
                lote=_texto(f[COL["finca"]]),
                ha_programadas=_num(f[COL["ha_programadas"]]),
                dosis_objetivo=_num(f[COL["dosis_objetivo"]]),
                temperatura=_num(f[COL["temperatura"]]),
                viento=_num(f[COL["viento"]]),
                humedad=_num(f[COL["humedad"]]),
                velocidad=_num(f[COL["velocidad"]]),
                altura=_num(f[COL["altura"]]),
                recalcular=False,
            )
        if propias:
            primera = _fecha(propias[0][COL["fecha"]])
            if primera:
                con.execute("UPDATE equipos SET fecha_alta=? WHERE id=?", (primera, equipo_id))
                # Las piezas se dan de alta hoy, pero el dron lleva volando desde su primera
                # operación. Sin corregirlo, un modelo con plazos de calendario (T70P, T100)
                # aparecería con cero meses en servicio el día que se importa su historial.
                con.execute(
                    "UPDATE componentes SET fecha_instalado=? "
                    "WHERE equipo_id=? AND fecha_ultimo_cambio IS NULL",
                    (primera, equipo_id))
        # El uso de cada pieza se calcula una vez, con la fecha de instalación ya corregida.
        core_flota.recalcular_equipo(con, equipo_id)
        con.commit()
        core_db.meta_set(con, f"bitacora_importada:{serial}", f"{len(propias)} filas · {ruta.name}")
    return importadas


CAMPOS_COMPLETAR = ("ha_programadas", "dosis_objetivo", "temperatura", "humedad", "viento", "velocidad", "altura")


def completar(con, ruta):
    """Rellena en las operaciones ya importadas los datos de aplicación y clima que la bitácora
    tiene y que la primera importación no traía (ha programadas, dosis, temperatura, humedad,
    viento, velocidad y altura).

    Sólo escribe campos vacíos, así que se puede correr cuantas veces se quiera sin pisar lo que
    alguien haya corregido a mano. Empareja cada fila por equipo, fecha y horas de vuelo (y lote o
    piloto si hay empate). Un valor fuera de rango (una temperatura de 92 °C, por ejemplo) se
    deja vacío. Devuelve {"actualizadas", "campos", "descartados", "sin_pareja"}.
    """
    from pathlib import Path
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(ruta)
    import openpyxl
    ws = openpyxl.load_workbook(ruta, data_only=True, read_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))[1:]

    equipos = {e["nombre"].replace(" ", "").upper(): e["id"]
               for e in con.execute("SELECT id, nombre FROM equipos").fetchall()}
    # Índice de operaciones por (equipo, fecha, horas redondeadas).
    indice = {}
    for o in con.execute(f"SELECT id, equipo_id, fecha, horas_vuelo, lote, piloto, {', '.join(CAMPOS_COMPLETAR)} "
                         "FROM operaciones").fetchall():
        o = dict(o)
        indice.setdefault((o["equipo_id"], str(o["fecha"])[:10], round(o["horas_vuelo"] or 0, 2)), []).append(o)

    informe = {"actualizadas": 0, "campos": 0, "descartados": 0, "sin_pareja": 0}
    usadas = set()
    for f in filas:
        if len(f) <= COL["horas_vuelo"]:
            continue
        serial = _texto(f[COL["serial"]])
        eid = equipos.get(serial.replace(" ", "").upper()) if serial else None
        fecha, horas = _fecha(f[COL["fecha"]]), _num(f[COL["horas_vuelo"]])
        if not eid or not fecha or horas is None:
            continue
        candidatas = [o for o in indice.get((eid, fecha, round(horas, 2)), []) if o["id"] not in usadas]
        if len(candidatas) > 1:
            lote, piloto = _texto(f[COL["finca"]]), _texto(f[COL["piloto"]])
            mejor = [o for o in candidatas if o["lote"] == lote and o["piloto"] == piloto] or \
                    [o for o in candidatas if o["lote"] == lote] or candidatas
            candidatas = mejor
        if not candidatas:
            informe["sin_pareja"] += 1
            continue
        op = candidatas[0]
        usadas.add(op["id"])
        cambios = {}
        for c in CAMPOS_COMPLETAR:
            v = _num(f[COL[c]])
            if v is None or op[c] is not None:
                continue
            lo, hi, _ = core_db.RANGOS_OPERACION[c]
            if not lo <= v <= hi:
                informe["descartados"] += 1
                continue
            cambios[c] = v
        if cambios:
            con.execute(f"UPDATE operaciones SET {', '.join(f'{c}=?' for c in cambios)} WHERE id=?",
                        (*cambios.values(), op["id"]))
            informe["actualizadas"] += 1
            informe["campos"] += len(cambios)
    con.commit()
    return informe
