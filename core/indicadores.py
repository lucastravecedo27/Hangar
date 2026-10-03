"""Indicadores de la operación en un solo lugar.

Cada indicador es una función registrada con @indicador que recibe la conexión y unos Filtros
(tipo de activo, activo, desde, hasta) y devuelve un número. El registro sabe su nombre, unidad,
a qué tipo de activo aplica y si «más es mejor», para que la pantalla pinte la comparación con
el período anterior en el color correcto.

    GET /api/indicadores?claves=rendimiento,costo_ha&tipo=avion&periodo=90d

Antes estas cuentas estaban repetidas dentro de las rutas de app.py (resumen, reportes, detalle).
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta

from core import alertas as core_alertas
from core import conexion as core_conexion
from core import flota as core_flota

REGISTRO = {}

# Indicadores con ingreso, margen o nómina: sólo los ve la gerencia (core.db.ROLES_COSTOS).
CLAVES_GERENCIA = ("ingreso_ha", "margen", "costo_personal", "costo_ha")


def indicador(clave, nombre, unidad="", aplica=("dron", "avion"), mejor="alto", grupo="Operación",
              decimales=1, formula=""):
    def envolver(fn):
        REGISTRO[clave] = {"clave": clave, "nombre": nombre, "unidad": unidad, "aplica": aplica,
                           "mejor": mejor, "grupo": grupo, "decimales": decimales, "formula": formula, "fn": fn}
        return fn
    return envolver


@dataclass
class Filtros:
    tipo: str = None          # 'dron' | 'avion' | None (toda la flota)
    equipo_id: int = None
    desde: str = None
    hasta: str = None

    def where(self, alias="o", fecha=True):
        cond, params = ["1=1"], []
        if self.equipo_id:
            cond.append(f"{alias}.equipo_id=?"); params.append(self.equipo_id)
        if self.tipo:
            cond.append(f"{alias}.equipo_id IN (SELECT id FROM equipos WHERE tipo_activo=?)"); params.append(self.tipo)
        if fecha and self.desde:
            cond.append(f"{alias}.fecha>=?"); params.append(self.desde)
        if fecha and self.hasta:
            cond.append(f"{alias}.fecha<=?"); params.append(self.hasta)
        return " AND ".join(cond), params

    def anterior(self):
        """Período inmediatamente anterior de la misma duración."""
        if not self.desde or not self.hasta:
            return None
        d0, d1 = date.fromisoformat(self.desde), date.fromisoformat(self.hasta)
        largo = (d1 - d0).days + 1
        return replace(self, desde=(d0 - timedelta(days=largo)).isoformat(),
                       hasta=(d0 - timedelta(days=1)).isoformat())


def periodo(nombre, hoy=None):
    """('desde', 'hasta') para 'mes', '30d', '90d', 'anio', 'todo'."""
    hoy = hoy or date.today()
    if nombre == "mes":
        return hoy.replace(day=1).isoformat(), hoy.isoformat()
    if nombre == "anio":
        return hoy.replace(month=1, day=1).isoformat(), hoy.isoformat()
    if nombre == "todo":
        return None, None
    dias = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}.get(nombre, 30)
    return (hoy - timedelta(days=dias - 1)).isoformat(), hoy.isoformat()


def _uno(con, sql, params):
    fila = con.execute(sql, params).fetchone()
    return None if fila is None else list(fila.values())[0]


def _div(a, b):
    return None if a is None or not b else a / b


def _ops(con, f, expr):
    w, p = f.where()
    return _uno(con, f"SELECT {expr} FROM operaciones o WHERE {w}", p)


def _meta_num(con, clave, defecto=None):
    fila = con.execute("SELECT valor FROM meta WHERE clave=?", (clave,)).fetchone()
    try:
        return float(fila["valor"]) if fila and fila["valor"] not in (None, "") else defecto
    except ValueError:
        return defecto


# ======================= Operación =======================

@indicador("hectareas", "Hectáreas aplicadas", "ha", decimales=0, formula="Σ hectáreas")
def _hectareas(con, f):
    return _ops(con, f, "COALESCE(SUM(o.hectareas),0)")


@indicador("horas", "Horas de vuelo", "h", formula="Σ horas de vuelo")
def _horas(con, f):
    return _ops(con, f, "COALESCE(SUM(o.horas_vuelo),0)")


@indicador("operaciones", "Operaciones", "", decimales=0, formula="número de jornadas")
def _operaciones(con, f):
    return _ops(con, f, "COUNT(*)")


@indicador("litros", "Litros aplicados", "L", decimales=0, formula="Σ litros de mezcla")
def _litros(con, f):
    return _ops(con, f, "COALESCE(SUM(o.litros),0)")


@indicador("cumplimiento", "Cumplimiento de programación", "%", formula="ha aplicadas ÷ ha programadas")
def _cumplimiento(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, SUM(o.ha_programadas) prog FROM operaciones o "
                       f"WHERE {w} AND o.ha_programadas > 0", p).fetchone()
    v = _div(fila["ha"], fila["prog"])
    return None if v is None else v * 100


@indicador("rendimiento", "Rendimiento", "ha/h", formula="ha ÷ horas de vuelo")
def _rendimiento(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, SUM(o.horas_vuelo) h FROM operaciones o "
                       f"WHERE {w} AND o.hectareas IS NOT NULL", p).fetchone()
    return _div(fila["ha"], fila["h"])


@indicador("ha_dia", "Hectáreas por día operativo", "ha/día", formula="ha ÷ días con operación")
def _ha_dia(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, COUNT(DISTINCT o.fecha) d FROM operaciones o WHERE {w}", p).fetchone()
    return _div(fila["ha"], fila["d"])


@indicador("aprovechamiento", "Aprovechamiento de jornada", "%", formula="horas de vuelo ÷ tiempo total de jornada")
def _aprovechamiento(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.horas_vuelo) h, SUM(o.tiempo_total) t FROM operaciones o "
                       f"WHERE {w} AND o.tiempo_total > 0", p).fetchone()
    v = _div(fila["h"], fila["t"])
    return None if v is None else min(v, 1) * 100


@indicador("traslado", "Traslado vs aplicación", "%", aplica=("avion",), mejor="bajo",
           formula="tiempo de traslado ÷ horas de vuelo")
def _traslado(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.tiempo_traslado) t, SUM(o.horas_vuelo) h FROM operaciones o "
                       f"WHERE {w} AND o.tiempo_traslado IS NOT NULL", p).fetchone()
    v = _div(fila["t"], fila["h"])
    return None if v is None else v * 100


@indicador("dosis", "Dosis real", "L/ha", mejor=None, formula="Σ litros ÷ Σ ha")
def _dosis(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.litros) l, SUM(o.hectareas) ha FROM operaciones o "
                       f"WHERE {w} AND o.litros IS NOT NULL AND o.hectareas > 0", p).fetchone()
    return _div(fila["l"], fila["ha"])


@indicador("desvio_dosis", "Desvío de dosis vs objetivo", "%", mejor="bajo",
           formula="|dosis real − objetivo| ÷ objetivo, ponderado por ha")
def _desvio_dosis(con, f):
    w, p = f.where()
    fila = con.execute(
        f"""SELECT SUM(ABS(o.litros / o.hectareas - o.dosis_objetivo) / o.dosis_objetivo * o.hectareas) num,
                   SUM(o.hectareas) ha FROM operaciones o
            WHERE {w} AND o.dosis_objetivo > 0 AND o.hectareas > 0 AND o.litros IS NOT NULL""", p).fetchone()
    v = _div(fila["num"], fila["ha"])
    return None if v is None else v * 100


@indicador("min_salida", "Minutos por salida", "min", mejor=None, formula="horas × 60 ÷ despegues")
def _min_salida(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.horas_vuelo) h, SUM(COALESCE(o.despegues, o.aterrizajes)) n FROM operaciones o "
                       f"WHERE {w} AND COALESCE(o.despegues, o.aterrizajes) > 0", p).fetchone()
    v = _div(fila["h"], fila["n"])
    return None if v is None else v * 60


@indicador("fuera_ventana", "Operaciones fuera de ventana", "", mejor="bajo", decimales=0, grupo="Personal y seguridad",
           formula="viento, temperatura o humedad fuera de los límites de Ajustes")
def _fuera_ventana(con, f):
    w, p = f.where()
    viento = _meta_num(con, "ventana_viento_max", 15)
    temp = _meta_num(con, "ventana_temp_max", 32)
    hum = _meta_num(con, "ventana_humedad_min", 50)
    return _uno(con, f"SELECT COUNT(*) FROM operaciones o WHERE {w} AND (o.viento > ? OR o.temperatura > ? "
                     f"OR o.humedad < ?)", p + [viento, temp, hum])


# ======================= Flota y aeronavegabilidad =======================

def _equipos(con, f):
    cond, params = ["estado != 'baja'"], []
    if f.tipo:
        cond.append("tipo_activo=?"); params.append(f.tipo)
    if f.equipo_id:
        cond.append("id=?"); params.append(f.equipo_id)
    return [dict(e) for e in con.execute(f"SELECT id, estado, tipo_activo FROM equipos WHERE {' AND '.join(cond)}",
                                         params).fetchall()]


def _estados(con, f):
    clave = ("estado_flota",)
    cache = getattr(con, "cache", None)
    if cache is not None and clave in cache:
        todos = cache[clave]
    else:
        todos = core_alertas.estado_flota(con)
        if cache is not None:
            cache[clave] = todos
    ids = {e["id"] for e in _equipos(con, f)}
    return {k: v for k, v in todos.items() if k in ids}


@indicador("aptos", "Activos aptos hoy", "%", grupo="Flota y aeronavegabilidad",
           formula="activos sin nada vencido ÷ activos en servicio (hoy)")
def _aptos(con, f):
    est = _estados(con, f)
    return None if not est else sum(1 for e in est.values() if e["estado"] != "no_apto") / len(est) * 100


@indicador("no_aptos", "Activos que no recomendamos volar", "", mejor="bajo", decimales=0, grupo="Flota y aeronavegabilidad",
           formula="activos con pieza, inspección, directiva o documento vencido")
def _no_aptos(con, f):
    return sum(1 for e in _estados(con, f).values() if e["estado"] == "no_apto")


@indicador("activos", "Activos en servicio", "", mejor=None, decimales=0, grupo="Flota y aeronavegabilidad",
           formula="activos que no están de baja")
def _activos(con, f):
    return len(_equipos(con, f))


@indicador("directivas_pendientes", "Directivas pendientes", "", aplica=("avion",), mejor="bajo", decimales=0,
           grupo="Flota y aeronavegabilidad", formula="AD/SB aplicables sin cumplir o con repetición vencida")
def _directivas_pendientes(con, f):
    ids = {e["id"] for e in _equipos(con, f)}
    return sum(1 for d in core_flota.directivas_con_estado(con) if d["equipo_id"] in ids and d["nivel"] != "ok")


@indicador("documentos_vencer", "Documentos por vencer (30 días)", "", mejor="bajo", decimales=0,
           grupo="Flota y aeronavegabilidad", formula="documentos vencidos o que vencen en 30 días")
def _documentos_vencer(con, f):
    ids = {e["id"] for e in _equipos(con, f)}
    return sum(1 for d in core_flota.documentos_con_estado(con)
               if d["nivel"] != "ok" and (d["equipo_id"] in ids or (d["equipo_id"] is None and not f.equipo_id)))


@indicador("mtbf", "Horas entre fallas (MTBF)", "h", grupo="Flota y aeronavegabilidad",
           formula="horas de vuelo ÷ cambios por daño o rotura")
def _mtbf(con, f):
    horas = _horas(con, f)
    w, p = f.where("m")
    fallas = _uno(con, f"SELECT COUNT(*) FROM mantenimientos m WHERE {w} AND m.motivo='daño'", p)
    return _div(horas, fallas)


@indicador("incidentes_100h", "Daños por cada 100 h", "", mejor="bajo", grupo="Personal y seguridad",
           formula="cambios por daño ÷ horas × 100")
def _incidentes(con, f):
    horas = _horas(con, f)
    w, p = f.where("m")
    fallas = _uno(con, f"SELECT COUNT(*) FROM mantenimientos m WHERE {w} AND m.motivo='daño'", p)
    v = _div(fallas, horas)
    return None if v is None else v * 100


@indicador("incidentes", "Incidentes reportados", "", mejor="bajo", grupo="Personal y seguridad", decimales=0,
           formula="golpes, caídas, aterrizajes duros y colisiones registrados")
def _incidentes_n(con, f):
    w, p = f.where("i")
    return _uno(con, f"SELECT COUNT(*) FROM incidentes i WHERE {w}", p)


@indicador("dias_sin_datos", "Días sin registrar (peor activo)", "días", mejor="bajo", decimales=0,
           grupo="Flota y aeronavegabilidad", formula="días desde la última operación del activo más atrasado")
def _dias_sin_datos(con, f):
    cond, params = ["e.estado = 'activo'"], []
    if f.tipo:
        cond.append("e.tipo_activo=?"); params.append(f.tipo)
    if f.equipo_id:
        cond.append("e.id=?"); params.append(f.equipo_id)
    fila = con.execute(
        f"""SELECT MAX({core_conexion.sql_dias("LEAST(COALESCE(u.f, e.fecha_alta), " + core_conexion.sql_hoy() + ")", core_conexion.sql_hoy())}) d
            FROM equipos e LEFT JOIN (SELECT equipo_id, MAX(fecha) f FROM operaciones GROUP BY equipo_id) u
                 ON u.equipo_id = e.id WHERE {' AND '.join(cond)}""", params).fetchone()
    return fila["d"]


# ======================= Costos y rentabilidad =======================

def _costo_mant(con, f):
    w, p = f.where("m")
    return _uno(con, f"SELECT COALESCE(SUM(COALESCE(m.costo, COALESCE(m.costo_repuesto,0)+COALESCE(m.costo_mano_obra,0))),0) "
                     f"FROM mantenimientos m WHERE {w}", p)


def _costo_combustible(con, f):
    precio = _meta_num(con, "precio_combustible_gal")
    if not precio:
        return None
    gal = _ops(con, f, "COALESCE(SUM(o.combustible_gal),0)")
    return gal * precio


# Valor que factura una operación con la tarifa vigente de su cliente (la del tipo de activo si
# la hay, si no la general). La tarifa se cobra por hectárea o por hora de vuelo según `unidad`.
# Necesita los alias `o` (operaciones) y `e` (equipos). La usa también la ruta de rentabilidad.
SQL_INGRESO_OP = """(
    SELECT (CASE WHEN t.unidad = 'hora' THEN o.horas_vuelo ELSE o.hectareas END) * t.valor_ha FROM tarifas t
    WHERE lower(t.cliente) = lower(o.cliente)
      AND (t.tipo_activo = 'todos' OR t.tipo_activo = e.tipo_activo)
      AND (t.desde IS NULL OR t.desde <= o.fecha)
    ORDER BY (t.tipo_activo = e.tipo_activo) DESC, t.desde DESC NULLS LAST LIMIT 1)"""


def _ingreso(con, f):
    """Σ lo facturado a cada cliente: ha × tarifa o horas × tarifa, según cómo cobre."""
    w, p = f.where()
    return _uno(con, f"SELECT COALESCE(SUM({SQL_INGRESO_OP}), 0) "
                     f"FROM operaciones o JOIN equipos e ON e.id = o.equipo_id WHERE {w}", p)


def _meses_periodo(con, f):
    """Meses que cubre el período (para prorratear costos mensuales). Sin fechas, del primer al
    último día con operación."""
    d0, d1 = f.desde, f.hasta
    if not d0 or not d1:
        fila = con.execute("SELECT MIN(fecha) a, MAX(fecha) b FROM operaciones").fetchone()
        d0, d1 = d0 or fila["a"], d1 or fila["b"]
    if not d0 or not d1:
        return 0
    return ((date.fromisoformat(d1[:10]) - date.fromisoformat(d0[:10])).days + 1) / 30.4375


def nomina_hora(con, f):
    """Costo de nómina (pilotos y técnicos, con prestaciones) por hora volada de TODA la flota en
    el período: la nómina se reparte entre activos y clientes según las horas que volaron."""
    nomina = _meta_num(con, "nomina_mes")
    if not nomina:
        return None
    flota = replace(f, tipo=None, equipo_id=None)
    horas = _horas(con, flota)
    return _div(nomina * _meses_periodo(con, flota), horas)


def _costo_personal(con, f):
    por_hora = nomina_hora(con, f)
    return None if por_hora is None else por_hora * (_horas(con, f) or 0)


@indicador("costo_mant_hora", "Costo de mantenimiento por hora", "$/h", mejor="bajo", grupo="Costos y rentabilidad",
           decimales=0, formula="Σ (repuesto + mano de obra) ÷ horas de vuelo")
def _costo_mant_hora(con, f):
    return _div(_costo_mant(con, f), _horas(con, f))


@indicador("costo_mant", "Costo de mantenimiento", "$", mejor="bajo", grupo="Costos y rentabilidad", decimales=0,
           formula="Σ (repuesto + mano de obra)")
def _costo_mant_total(con, f):
    return _costo_mant(con, f)


@indicador("consumo", "Consumo de combustible", "gal/h", aplica=("avion",), mejor="bajo", grupo="Costos y rentabilidad",
           formula="galones ÷ horas de vuelo")
def _consumo(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.combustible_gal) g, SUM(o.horas_vuelo) h FROM operaciones o "
                       f"WHERE {w} AND o.combustible_gal IS NOT NULL", p).fetchone()
    return _div(fila["g"], fila["h"])


@indicador("costo_combustible_hora", "Costo de combustible por hora", "$/h", aplica=("avion",), mejor="bajo",
           grupo="Costos y rentabilidad", decimales=0, formula="galones × precio ÷ horas")
def _costo_combustible_hora(con, f):
    return _div(_costo_combustible(con, f), _horas(con, f))


@indicador("costo_ha", "Costo por hectárea", "$/ha", mejor="bajo", grupo="Costos y rentabilidad", decimales=0,
           formula="(mantenimiento + combustible + nómina) ÷ ha")
def _costo_ha(con, f):
    costo = (_costo_mant(con, f) or 0) + (_costo_combustible(con, f) or 0) + (_costo_personal(con, f) or 0)
    return _div(costo, _hectareas(con, f)) if costo else None


@indicador("ingreso_ha", "Ingreso por hectárea", "$/ha", grupo="Costos y rentabilidad", decimales=0,
           formula="lo facturado (por ha o por hora, según la tarifa del cliente) ÷ ha")
def _ingreso_ha(con, f):
    ing = _ingreso(con, f)
    return _div(ing, _hectareas(con, f)) if ing else None


@indicador("margen", "Margen de la operación", "$", grupo="Costos y rentabilidad", decimales=0,
           formula="ingreso − mantenimiento − combustible − nómina")
def _margen(con, f):
    ing = _ingreso(con, f)
    if not ing:
        return None
    return ing - (_costo_mant(con, f) or 0) - (_costo_combustible(con, f) or 0) - (_costo_personal(con, f) or 0)


@indicador("costo_personal", "Costo de nómina", "$", mejor="bajo", grupo="Costos y rentabilidad", decimales=0,
           formula="nómina mensual × meses del período, repartida por horas de vuelo")
def _costo_personal_total(con, f):
    return _costo_personal(con, f)


# ======================= Eficiencia por activo =======================

@indicador("ha_galon", "Hectáreas por galón", "ha/gal", aplica=("avion",), grupo="Operación",
           formula="Σ hectáreas ÷ Σ galones de combustible")
def _ha_galon(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, SUM(o.combustible_gal) g FROM operaciones o "
                       f"WHERE {w} AND o.combustible_gal > 0 AND o.hectareas IS NOT NULL", p).fetchone()
    return _div(fila["ha"], fila["g"])


@indicador("gal_ha", "Galones por hectárea", "gal/ha", aplica=("avion",), mejor="bajo", grupo="Operación",
           decimales=2, formula="Σ galones de combustible ÷ Σ hectáreas")
def _gal_ha(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, SUM(o.combustible_gal) g FROM operaciones o "
                       f"WHERE {w} AND o.combustible_gal > 0 AND o.hectareas > 0", p).fetchone()
    return _div(fila["g"], fila["ha"])


@indicador("ha_vuelo", "Hectáreas por vuelo", "ha/vuelo", grupo="Operación",
           formula="Σ hectáreas ÷ Σ despegues (dron) o aterrizajes (avión); en el dron ≈ ha por tanque o batería")
def _ha_vuelo(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.hectareas) ha, SUM(COALESCE(o.despegues, o.aterrizajes)) n FROM operaciones o "
                       f"WHERE {w} AND COALESCE(o.despegues, o.aterrizajes) > 0 AND o.hectareas IS NOT NULL", p).fetchone()
    return _div(fila["ha"], fila["n"])


@indicador("horas_dia", "Horas de vuelo por día operativo", "h/día", mejor=None, grupo="Operación",
           formula="Σ horas de vuelo ÷ días con operación")
def _horas_dia(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.horas_vuelo) h, COUNT(DISTINCT o.fecha) d FROM operaciones o WHERE {w}", p).fetchone()
    return _div(fila["h"], fila["d"])


@indicador("litros_hora", "Litros aplicados por hora", "L/h", mejor=None, grupo="Operación",
           decimales=0, formula="Σ litros de mezcla ÷ Σ horas de vuelo")
def _litros_hora(con, f):
    w, p = f.where()
    fila = con.execute(f"SELECT SUM(o.litros) l, SUM(o.horas_vuelo) h FROM operaciones o "
                       f"WHERE {w} AND o.litros IS NOT NULL", p).fetchone()
    return _div(fila["l"], fila["h"])


# ======================= Disponibilidad histórica =======================

@indicador("disponibilidad", "Disponibilidad", "%", grupo="Flota y aeronavegabilidad",
           formula="días apto o con observaciones ÷ días registrados (foto diaria del estado)")
def _disponibilidad(con, f):
    return core_flota.disponibilidad(con, f.desde, f.hasta, f.tipo, f.equipo_id)["total"]


@indicador("mttr", "Tiempo medio de reparación (MTTR)", "días", mejor="bajo", grupo="Flota y aeronavegabilidad",
           formula="días entre abrir y cerrar las OT correctivas o por daño cerradas en el período")
def _mttr(con, f):
    return core_flota.mttr(con, f.desde, f.hasta, f.tipo, f.equipo_id)["dias"]


# ======================= Cálculo =======================

def calcular(con, claves=None, filtros=None, comparar=True):
    filtros = filtros or Filtros()
    claves = [c for c in (claves or REGISTRO) if c in REGISTRO]
    ant = filtros.anterior() if comparar else None
    salida = {}
    for c in claves:
        r = REGISTRO[c]
        if filtros.tipo and filtros.tipo not in r["aplica"]:
            continue
        valor = r["fn"](con, filtros)
        es_de_hoy = r["clave"] in ("aptos", "no_aptos", "activos", "directivas_pendientes", "documentos_vencer", "dias_sin_datos")
        anterior = r["fn"](con, ant) if ant is not None and not es_de_hoy else None
        variacion = None
        if valor is not None and anterior:
            variacion = round((valor - anterior) / abs(anterior) * 100, 1)
        salida[c] = {k: r[k] for k in ("clave", "nombre", "unidad", "mejor", "grupo", "decimales", "formula")}
        salida[c]["aplica"] = list(r["aplica"])
        salida[c]["valor"] = None if valor is None else round(float(valor), r["decimales"])
        salida[c]["anterior"] = None if anterior is None else round(float(anterior), r["decimales"])
        salida[c]["variacion"] = variacion
    return salida


def serie_mensual(con, clave, filtros=None, meses=12):
    """Valor del indicador en cada uno de los últimos `meses` meses (para las minigráficas)."""
    filtros = filtros or Filtros()
    r = REGISTRO[clave]
    hoy = date.today().replace(day=1)
    salida = []
    for i in range(meses - 1, -1, -1):
        y, m = hoy.year, hoy.month - i
        while m <= 0:
            m += 12; y -= 1
        d0 = date(y, m, 1)
        d1 = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        v = r["fn"](con, replace(filtros, desde=d0.isoformat(), hasta=d1.isoformat()))
        salida.append({"mes": d0.isoformat()[:7], "valor": None if v is None else round(float(v), r["decimales"])})
    return salida


def por_tipo(con, claves, filtros=None):
    """Mismos indicadores para drones y para aviones, lado a lado (comparativo)."""
    filtros = filtros or Filtros()
    return {t: calcular(con, claves, replace(filtros, tipo=t), comparar=False) for t in core_flota.TIPOS_ACTIVO}


def por_activo(con, claves, filtros=None):
    filtros = filtros or Filtros()
    salida = []
    for e in con.execute("SELECT id, nombre, tipo_activo, modelo, matricula FROM equipos WHERE estado != 'baja' "
                         + ("AND tipo_activo=? " if filtros.tipo else "") + "ORDER BY nombre",
                         (filtros.tipo,) if filtros.tipo else ()).fetchall():
        d = dict(e)
        d["indicadores"] = calcular(con, claves, replace(filtros, equipo_id=e["id"], tipo=None), comparar=False)
        salida.append(d)
    return salida


def catalogo():
    return [{k: v for k, v in r.items() if k != "fn"} for r in REGISTRO.values()]
