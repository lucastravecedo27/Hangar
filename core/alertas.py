"""Estado de desgaste de cada componente frente a sus límites.

Una pieza (o una inspección periódica) puede tener hasta tres límites y manda el que se cumpla
primero, que es como redactan sus tablas DJI y los fabricantes de aviones:

  · uso en su contador base (horas de vuelo, Hobbs o Tach) frente a `vida_util_horas`
  · ciclos (despegues, aterrizajes, arranques) frente a `limite_ciclos`
  · tiempo en servicio desde que se montó frente a `vida_util_meses`

Del T50 hay vida útil en horas de vuelo y del T100 sólo plazos en meses; de un motor de avión,
TBO en horas de Tach y en años. La `tolerancia` (en unidades del contador base) permite cumplir
una inspección un poco después del límite sin que el activo quede como vencido.
"""
from datetime import date

from core import flota as core_flota

UMBRAL_PROXIMO = 0.75
UMBRAL_CRITICO = 0.90
ORDEN_NIVEL = {"vencido": 0, "critico": 1, "proximo": 2, "ok": 3}
DIAS_POR_MES = 30.44


def _nivel_de_fraccion(pct):
    if pct >= 1:
        return "vencido"
    if pct >= UMBRAL_CRITICO:
        return "critico"
    if pct >= UMBRAL_PROXIMO:
        return "proximo"
    return "ok"


def nivel_de(horas_uso, vida_util):
    return _nivel_de_fraccion(horas_uso / vida_util if vida_util > 0 else 0)


def _meses_desde(texto):
    """Meses transcurridos desde una fecha ISO. None si no hay fecha utilizable."""
    if not texto:
        return None
    try:
        desde = date.fromisoformat(str(texto)[:10])
    except ValueError:
        return None
    return max((date.today() - desde).days, 0) / DIAS_POR_MES


def componentes_con_estado(con, equipo_id=None):
    """Componentes con su estado. Se memoriza en la conexión mientras no haya escrituras
    (Resumen y Reportes lo pedían varias veces por petición)."""
    clave = ("componentes_con_estado", equipo_id)
    cache = getattr(con, "cache", None)
    if cache is not None and clave in cache:
        return [dict(d) for d in cache[clave]]
    salida = _calcular(con, equipo_id)
    if cache is not None:
        cache[clave] = salida
    return [dict(d) for d in salida]


def _calcular(con, equipo_id=None):
    filtro = "WHERE c.equipo_id=?" if equipo_id else ""
    params = (equipo_id,) if equipo_id else ()
    filas = con.execute(
        f"""SELECT c.id, c.equipo_id, c.horas_uso, c.fecha_instalado, c.fecha_ultimo_cambio,
                   c.ciclos_uso, c.pieza_serie_id,
                   p.id AS pieza_id, p.clave, p.modulo, p.zona, p.nombre, p.vida_util_horas,
                   p.vida_util_meses, p.nota, p.mesh, p.tipo_item, p.contador_base, p.contador_ciclos,
                   p.limite_ciclos, p.tolerancia, p.serializada, p.referencia, p.precio,
                   e.nombre AS equipo, e.modelo, e.estado AS equipo_estado, e.tipo_activo, e.matricula,
                   s.serial
            FROM componentes c
            JOIN catalogo_piezas p ON p.id = c.pieza_id
            JOIN equipos e ON e.id = c.equipo_id
            LEFT JOIN piezas_serie s ON s.id = c.pieza_serie_id
            {filtro} ORDER BY p.modulo, p.nombre""",
        params,
    ).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        vida = d["vida_util_horas"] or 0
        meses = d["vida_util_meses"] or 0
        ciclos_lim = d["limite_ciclos"] or 0
        tol = d["tolerancia"] or 0
        d["contador_base"] = d["contador_base"] or "horas_vuelo"
        d["unidad"] = core_flota.unidad(d["contador_base"])
        d["contador_txt"] = core_flota.nombre_contador(d["contador_base"])
        d["horas_uso"] = round(d["horas_uso"] or 0, 1)
        d["ciclos_uso"] = round(d["ciclos_uso"] or 0)
        d["restante"] = round(vida - d["horas_uso"], 1) if vida else None
        d["restante_ciclos"] = round(ciclos_lim - d["ciclos_uso"]) if ciclos_lim else None
        d["unidad_ciclos"] = core_flota.unidad(d["contador_ciclos"]) if d["contador_ciclos"] else None

        # Gasto por contador base y por ciclos.
        pct_horas = min(d["horas_uso"] / vida, 1.5) if vida else 0
        pct_ciclos = min(d["ciclos_uso"] / ciclos_lim, 1.5) if ciclos_lim else 0

        # Gasto por calendario: desde el último cambio, o desde que se instaló si nunca se cambió.
        transcurridos = _meses_desde(d["fecha_ultimo_cambio"] or d["fecha_instalado"])
        d["meses_en_servicio"] = round(transcurridos, 1) if transcurridos is not None else None
        d["meses_restantes"] = (round(meses - transcurridos, 1)
                                if meses and transcurridos is not None else None)
        pct_meses = min(transcurridos / meses, 1.5) if meses and transcurridos is not None else 0

        # Manda el plazo que va más avanzado: salta con el que se cumpla primero.
        peor = max(pct_horas, pct_ciclos, pct_meses)
        d["pct"] = round(peor * 100, 1)
        d["pct_horas"] = round(pct_horas * 100, 1)
        d["pct_ciclos"] = round(pct_ciclos * 100, 1)
        d["pct_meses"] = round(pct_meses * 100, 1)
        d["nivel"] = _nivel_de_fraccion(peor)
        d["motivo_alerta"] = ("calendario" if pct_meses > max(pct_horas, pct_ciclos) else
                              "ciclos" if pct_ciclos > pct_horas else "horas" if pct_horas else None)
        # Tolerancia: pasado el límite de horas pero dentro del margen, se marca crítica, no vencida.
        d["en_tolerancia"] = False
        if (d["nivel"] == "vencido" and tol and d["motivo_alerta"] == "horas" and vida
                and d["horas_uso"] <= vida + tol and max(pct_ciclos, pct_meses) < 1):
            d["nivel"] = "critico"
            d["en_tolerancia"] = True
        # Sin ningún plazo publicado no hay nada que cronometrar: se revisa a diario.
        d["sin_plazo"] = not vida and not meses and not ciclos_lim
        d["plazo_txt"] = _texto_plazo(d)
        salida.append(d)
    return salida


def _c(x, dec=1):
    """Número con coma decimal, como se escribe en Colombia."""
    return f"{x:.{dec}f}".replace(".", ",")


def _texto_plazo(d):
    """«quedan 12 h de Tach», «vencida hace 3 meses», «quedan 40 aterr.»… según lo que manda."""
    m = d["motivo_alerta"]
    if d["sin_plazo"]:
        return "sin plazo publicado"
    if m == "calendario" and d["meses_restantes"] is not None:
        r = d["meses_restantes"]
        return f"vencida hace {_c(abs(r))} meses" if r < 0 else f"quedan {_c(r)} meses"
    if m == "ciclos" and d["restante_ciclos"] is not None:
        r = d["restante_ciclos"]
        return f"vencida hace {abs(r)} {d['unidad_ciclos']}" if r < 0 else f"quedan {r} {d['unidad_ciclos']}"
    if d["restante"] is not None:
        r = d["restante"]
        sufijo = f" de {d['contador_txt']}" if d["contador_base"] not in ("horas_vuelo",) else ""
        if r < 0:
            return f"pasada {abs(r):.0f} {d['unidad']}{sufijo}" + (" (en tolerancia)" if d["en_tolerancia"] else "")
        return f"quedan {r:.0f} {d['unidad']}{sufijo}"
    if d["meses_restantes"] is not None:
        r = d["meses_restantes"]
        return f"vencida hace {_c(abs(r))} meses" if r < 0 else f"quedan {_c(r)} meses"
    return ""


def alertas(con, tipo_activo=None):
    activas = [c for c in componentes_con_estado(con) if c["nivel"] != "ok" and c["equipo_estado"] != "baja"
               and (not tipo_activo or c["tipo_activo"] == tipo_activo)]
    activas.sort(key=lambda c: (ORDEN_NIVEL[c["nivel"]], -c["pct"]))
    return activas


def resumen_alertas(con):
    conteo = {"vencido": 0, "critico": 0, "proximo": 0}
    for a in alertas(con):
        conteo[a["nivel"]] += 1
    conteo["total"] = sum(conteo.values())
    return conteo


def alertas_todas(con, tipo_activo=None, equipo_id=None):
    """Piezas, inspecciones, directivas y documentos en una sola lista con la misma forma
    (fuente, nombre, equipo, nivel, pct, plazo_txt), ordenada por gravedad."""
    salida = []
    for c in componentes_con_estado(con, equipo_id):
        if c["nivel"] == "ok" or c["equipo_estado"] == "baja" or (tipo_activo and c["tipo_activo"] != tipo_activo):
            continue
        salida.append({"fuente": "inspeccion" if c["tipo_item"] == "inspeccion" else "pieza",
                       "id": c["id"], "nombre": c["nombre"], "modulo": c["modulo"], "equipo": c["equipo"],
                       "equipo_id": c["equipo_id"], "tipo_activo": c["tipo_activo"], "nivel": c["nivel"],
                       "pct": c["pct"], "plazo_txt": c["plazo_txt"], "en_tolerancia": c["en_tolerancia"]})
    tipos = {e["id"]: e["tipo_activo"] for e in con.execute("SELECT id, tipo_activo FROM equipos").fetchall()}
    for d in core_flota.directivas_con_estado(con, equipo_id):
        if d["nivel"] == "ok" or (tipo_activo and tipos.get(d["equipo_id"]) != tipo_activo):
            continue
        plazo = (f"vence {d['limite_fecha']}" if d["estado"] == "pendiente" and d["limite_fecha"] else
                 f"próxima {d['proxima']}" if d.get("proxima") else d["estado_txt"])
        salida.append({"fuente": "directiva", "id": d["id"], "nombre": f"{d['tipo']} {d['numero']} · {d['titulo']}",
                       "modulo": "Directivas", "equipo": d["equipo"], "equipo_id": d["equipo_id"],
                       "tipo_activo": tipos.get(d["equipo_id"]), "nivel": d["nivel"], "pct": d["pct"],
                       "plazo_txt": plazo})
    for d in core_flota.documentos_con_estado(con, equipo_id):
        if d["nivel"] == "ok":
            continue
        if tipo_activo and d["equipo_id"] and tipos.get(d["equipo_id"]) != tipo_activo:
            continue
        dr = d["dias_restantes"]
        salida.append({"fuente": "documento", "id": d["id"], "nombre": d["tipo_txt"] + (f" {d['numero']}" if d["numero"] else ""),
                       "modulo": "Documentos", "equipo": d["equipo"] or d["persona"], "equipo_id": d["equipo_id"],
                       "tipo_activo": tipos.get(d["equipo_id"]), "nivel": d["nivel"], "pct": None,
                       "plazo_txt": (f"vencido hace {-dr} días" if dr is not None and dr < 0 else f"vence en {dr} días")})
    salida.sort(key=lambda a: (ORDEN_NIVEL[a["nivel"]], -(a["pct"] or 0)))
    return salida


def estado_flota(con, equipos=None):
    """Estado de aeronavegabilidad de cada activo {equipo_id: {estado, estado_txt, motivos}}."""
    if equipos is None:
        equipos = [dict(e) for e in con.execute("SELECT id, estado FROM equipos WHERE estado != 'baja'").fetchall()]
    comps = {}
    for c in componentes_con_estado(con):
        comps.setdefault(c["equipo_id"], []).append(c)
    return core_flota.estado_aeronavegable(con, comps, core_flota.directivas_con_estado(con),
                                           core_flota.documentos_con_estado(con), equipos)
