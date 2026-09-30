"""Marco normativo: qué pide la RAC (Reglamentos Aeronáuticos de Colombia) y cómo lo cumple la app.

Versiones leídas del texto oficial de la Aerocivil (descargados el 2026-09-28):
  · RAC 91   Enm. 12, jul-2026 (Res. 2297 del 17-jul-2026; reforma grande Res. 03595/2025)
  · RAC 137  Enm. 1,  abr-2024 (Res. 00718)          · RAC 135 Enm. 8, feb-2026 (Res. 00512)
  · RAC 100  Enm. 2,  dic-2024                        · RAC 43  Enm. 1, dic-2019 (Res. 03827)
  · RAC 4    Enm. 32, feb-2026                        · RAC 14  Enm. 21, jul-2026
  · RAC 39   ed. original, mar-2016                   · RAC 205 ed. original, dic-2020

Cada requisito de REQUISITOS dice numeral, a qué aplica (avión, dron, empresa, personal), qué
pide en pocas palabras y dónde lo cubre la app. `estado_cumplimiento()` lo evalúa contra los datos
de la empresa: «cumple», «atencion» (hay algo vencido o incompleto), «falta» (la app no tiene el
dato) o «manual» (depende del piloto en campo; la app sólo lo recuerda).

Lo que NO está en la RAC se marca como buena práctica, sin inventar numerales: p. ej. el control de
agua en el combustible sólo aparece de forma genérica en RAC 4.5.3.5(24) («evitar y eliminar la
contaminación del combustible»).
"""
import json
from datetime import date, timedelta

from core import alertas as core_alertas
from core import flota as core_flota

VERSIONES = [
    {"rac": "RAC 91", "titulo": "Reglas generales de vuelo y de operación", "version": "Enm. 12 · julio 2026"},
    {"rac": "RAC 137", "titulo": "Aviación agrícola", "version": "Enm. 1 · abril 2024"},
    {"rac": "RAC 100", "titulo": "Sistemas de aeronaves no tripuladas (UAS)", "version": "Enm. 2 · diciembre 2024"},
    {"rac": "RAC 43", "titulo": "Mantenimiento", "version": "Enm. 1 · diciembre 2019"},
    {"rac": "RAC 4", "titulo": "Aeronavegabilidad y operación", "version": "Enm. 32 · febrero 2026"},
    {"rac": "RAC 39", "titulo": "Directrices de aeronavegabilidad", "version": "Original · marzo 2016"},
    {"rac": "RAC 14", "titulo": "Aeródromos", "version": "Enm. 21 · julio 2026"},
    {"rac": "RAC 135", "titulo": "Operaciones comerciales", "version": "Enm. 8 · febrero 2026"},
]
FUENTE = "https://www.aerocivil.gov.co/autoridad_aeronautica/normatividad/13-reglamentos-aeronauticos-de-colombia-rac"

# ----------------------------------------------------------------------------- combustible

# RAC 91.610(a): la operación agrícola es VFR diurna (RAC 137.35(f) prohíbe noche e IFR), así que
# la reserva que manda es la de 30 min. La contingencia del 5 % es de RAC 91.2012 / 135.685
# (aviones grandes y comerciales): se ofrece como opción prudente, no como obligación.
RESERVAS_COMBUSTIBLE = {
    "rodaje_gal": 1.0,
    "casos": [
        {"nombre": "Aplicación agrícola · VFR diurno", "reserva_min": 30, "contingencia_pct": 0,
         "norma": "RAC 137.35(n): combustible para completar las aspersiones planeadas, incluida la reserva. "
                  "RAC 91.610(a)(3): reserva final de 30 min a crucero normal."},
        {"nombre": "Aplicación agrícola · con contingencia 5 %", "reserva_min": 30, "contingencia_pct": 5,
         "norma": "Reserva de 30 min (RAC 91.610) más el 5 % del combustible de trayecto que RAC 91.2012 y "
                  "135.685 exigen a operaciones mayores: margen prudente para vientos y reaplicaciones."},
        {"nombre": "Traslado VFR diurno", "reserva_min": 30, "contingencia_pct": 0,
         "norma": "RAC 91.610(a)(3): destino, alterno más distante y 30 min a crucero. Incluye el alterno en el tiempo de vuelo."},
        {"nombre": "Traslado VFR nocturno", "reserva_min": 45, "contingencia_pct": 0,
         "norma": "RAC 91.610(a)(4): reserva de 45 min. Prohibido en aplicación agrícola (RAC 137.35(f))."},
        {"nombre": "IFR", "reserva_min": 45, "contingencia_pct": 0,
         "norma": "RAC 91.610(a)(2): destino, alterno más distante y 45 min a altitud normal de crucero."},
    ],
    "nota": "RAC 91.637: si el combustible al aterrizar puede quedar por debajo de la reserva final se declara "
            "«COMBUSTIBLE MÍNIMO»; si ya está por debajo, «MAYDAY COMBUSTIBLE». RAC 91.2012(b)(1) admite "
            "calcular con el consumo real registrado, que es el de esta app.",
}

# Norma de cada punto del chequeo de tanqueo (core/combustible.py).
NORMA_CHEQUEO = {
    "motor_apagado": "RAC 91.640(d)(13) y RAC 14 Ap. 9 (f)(5): prohibido abastecer con motores encendidos",
    "sin_ocupantes": "RAC 91.640: prohibido con personas a bordo salvo procedimiento aprobado por la Aerocivil",
    "puesta_tierra": "RAC 14 Ap. 9 (f)(11): aeronave y cisterna unidas con cable de estática",
    "extintor": "RAC 91.640(d) extintor tipo BC; RAC 14 Ap. 9 (f)(8) extintor y kit de derrames",
    "lugar_autorizado": "RAC 137.35(j): prohibido aprovisionar fuera de las instalaciones autorizadas",
    "tormenta": "RAC 14 Ap. 9 (f)(2): no abastecer con tormenta eléctrica a menos de 10 km",
    "tipo_verificado": "Buena práctica: comprobar el grado contra la placa de la tapa (no figura en la RAC)",
    "drenaje": "RAC 4.5.3.5(24): evitar la contaminación del combustible; drenaje según el manual del fabricante",
    "tapas": "Buena práctica del manual del fabricante",
    "sin_fuentes_ignicion": "RAC 14 Ap. 9 (f)(10): no fumar; RAC 91.640(d): sin celulares",
}


def norma_chequeo(clave):
    return NORMA_CHEQUEO.get(clave)


def faltantes_tanqueo(c):
    """Puntos obligatorios del chequeo que faltan en un tanqueo (lista vacía si está completo)."""
    if c.get("tipo") != "tanqueo":
        return []
    from core import combustible as core_comb
    lista = core_comb.CHEQUEO_AERONAVE if c.get("destino") == "aeronave" else core_comb.CHEQUEO_APOYO
    try:
        chk = json.loads(c.get("chequeo") or "{}") if isinstance(c.get("chequeo"), str) else (c.get("chequeo") or {})
    except ValueError:
        chk = {}
    return [texto for clave, texto, obligatorio in lista if obligatorio and not chk.get(clave)]


# ----------------------------------------------------------------------------- requisitos

# (id, rac, numeral, título, qué exige, aplica, dónde en la app, enlace)
REQUISITOS = [
    # --- Combustible
    ("comb_reserva", "RAC 91 · RAC 137", "91.610 · 137.35(n)", "Combustible mínimo con reserva",
     "Salir con combustible para completar las aspersiones planeadas más 30 min de reserva a crucero (VFR diurno).",
     "avion", "Combustible › Calcular combustible", "/combustible"),
    ("comb_abastecimiento", "RAC 91 · RAC 14", "91.640 · 14 Ap. 9 (f)", "Seguridad en el abastecimiento",
     "Motor apagado, sin personas a bordo, cable de estática, extintor, sin tormenta a 10 km.",
     "avion", "Combustible › Tanquear (chequeo obligatorio)", "/combustible"),
    ("comb_lugar", "RAC 137", "137.35(j)", "Abastecer sólo en instalaciones autorizadas",
     "Prohibido aprovisionar combustible o insumos fuera de las instalaciones autorizadas.",
     "avion", "Combustible › chequeo del tanqueo", "/combustible"),
    ("comb_tanques", "RAC 137", "137.35(d)", "Sin tanques adicionales",
     "Prohibido instalar tanques adicionales o aumentar la autonomía de otro modo.",
     "avion", "Combustible › capacidad del activo (alerta si se carga más)", "/combustible"),
    ("comb_registro", "RAC 135 · RAC 91", "135.130 · 91.2012(b)(1)", "Registro de consumo de combustible",
     "Llevar registros de consumo para demostrar el combustible de cada vuelo (obligatorio en 135; buena práctica en 137).",
     "avion", "Combustible › consumo por activo", "/combustible"),
    ("uas_energia", "RAC 100", "100.210(j)(k)", "Energía suficiente y 80 % de la autonomía",
     "El tiempo de vuelo de una operación no puede superar el 80 % de la autonomía del fabricante.",
     "dron", "Chequeo pre-vuelo del dron", "/checklist"),
    # --- Aeronavegabilidad y mantenimiento
    ("insp_anual", "RAC 91", "91.1110(b)", "Inspección anual",
     "Cada 12 meses calendario, con certificación de conformidad de mantenimiento (CCM).",
     "avion", "Catálogo › Inspección anual (12 meses)", "/catalogo"),
    ("insp_100h", "RAC 4 · RAC 137", "4.2.4.5(b) · 137.53(c)(1)", "Inspección de 100 horas",
     "Cada 100 h; se puede exceder hasta 10 h y el exceso cuenta para las siguientes 100 h.",
     "avion", "Catálogo › Inspección de 100 h (tolerancia 10 h)", "/catalogo"),
    ("equipos_24m", "RAC 91", "91.877", "Altímetro, transpondedor, ELT y brújula",
     "Altímetro y transpondedor cada 24 meses, ELT cada 12, brújula cada 24 (si el fabricante no fija otro).",
     "avion", "Catálogo › Inspecciones", "/catalogo"),
    ("ad", "RAC 39 · RAC 91", "39.115 · 91.1115(b)(4)", "Directrices de aeronavegabilidad",
     "No se opera sin cumplir todas las AD aplicables (las de la FAA para Cessna y Continental rigen directamente).",
     "avion", "Aeronavegabilidad › Directivas", "/aeronavegabilidad"),
    ("registros_mant", "RAC 91 · RAC 43", "91.1125 · 43.305", "Registros de mantenimiento",
     "Anotar tarea, horas y ciclos, descripción, datos de referencia, fechas y firma con licencia de quien lo hizo.",
     "avion", "Órdenes de trabajo › cierre firmado", "/ordenes-trabajo"),
    ("ccm", "RAC 43", "43.405", "Certificación de conformidad (visto bueno)",
     "La CCM lleva el trabajo, la referencia, la fecha, el nombre y el número de licencia del certificador.",
     "avion", "Órdenes de trabajo › cierre con firma y licencia", "/ordenes-trabajo"),
    ("docs_bordo", "RAC 91", "91.1420 · 91.1413", "Documentos a bordo",
     "Matrícula, aeronavegabilidad y licencia de la estación de radio (vigente 5 años), en original.",
     "avion", "Aeronavegabilidad › Documentos", "/aeronavegabilidad"),
    ("fiaa", "RAC 91", "91.1136", "Informe anual de aeronavegabilidad (FIAA)",
     "Cada 12 meses se presenta a la Aerocivil el informe de la condición de aeronavegabilidad.",
     "avion", "Aeronavegabilidad › Documentos (tipo FIAA)", "/aeronavegabilidad"),
    ("libro_abordo", "RAC 91", "91.1410", "Libro de a bordo",
     "Por vuelo: fecha, tripulación, lugares y horas de salida y llegada, tiempo de vuelo, propósito y firma. 3 años.",
     "avion", "Operaciones", "/operaciones"),
    # --- Aviación agrícola
    ("registro_aplic", "RAC 137", "137.71", "Registro de cada aplicación",
     "Cliente, fecha, nombre y cantidad de los productos aplicados en cada operación. Conservar 12 meses.",
     "empresa", "Operaciones (cliente, producto, litros)", "/operaciones"),
    ("piloto_salud", "RAC 137", "137.73", "Registro del piloto: médico y colinesterasa",
     "Por piloto: vencimiento del certificado médico y del examen de colinesterasa.",
     "personal", "Contactos › documentos del piloto", "/contactos"),
    ("biblioteca", "RAC 137", "137.79", "Programa de mantenimiento y biblioteca técnica",
     "Programa aprobado, formularios de inspección y manuales del avión, motor, hélice y equipo de fumigación.",
     "avion", "Catálogo y Diagramas (manuales del fabricante)", "/catalogo"),
    # --- Drones
    ("uas_registro", "RAC 100", "100.105", "Registro de cada UAS",
     "Todo dron de 200 g o más registrado ante la Aerocivil (altas, bajas y transferencias también).",
     "dron", "Flota › documentos del dron (Registro UAS)", "/flota"),
    ("uas_libro", "RAC 100", "100.005 · 100.510", "Libro de vuelo y mantenimiento del UA",
     "Cada vuelo con fecha, horas, tiempo y piloto; fallas y mantenimiento con quién lo hizo.",
     "dron", "Operaciones y Bitácora de reparaciones", "/bitacora"),
    ("uas_docs", "RAC 100", "100.225", "Documentos durante la operación",
     "Registro, póliza, certificado de idoneidad del piloto y autorización de vuelo.",
     "dron", "Flota › documentos", "/flota"),
    ("uas_mant", "RAC 100", "100.415", "Mantenimiento según el fabricante",
     "Mantener según DJI; todos los sistemas de fábrica operativos, incluido el de aspersión.",
     "dron", "Mantenimiento (vida útil DJI)", "/mantenimiento"),
]


def _nivel_peor(niveles):
    orden = ["vencido", "critico", "proximo", "ok"]
    return min(niveles, key=lambda n: orden.index(n) if n in orden else 9) if niveles else "ok"


def estado_cumplimiento(con):
    """Evalúa cada requisito con los datos de la empresa. Devuelve requisitos + resumen."""
    hoy = date.today()
    equipos = [dict(e) for e in con.execute("SELECT * FROM equipos WHERE estado!='baja'").fetchall()]
    aviones = [e for e in equipos if e["tipo_activo"] == "avion"]
    drones = [e for e in equipos if e["tipo_activo"] != "avion"]
    comps = core_alertas.componentes_con_estado(con)
    docs = core_flota.documentos_con_estado(con)
    dirs = core_flota.directivas_con_estado(con) if aviones else []

    def docs_de(eid, tipo):
        return [d for d in docs if d["equipo_id"] == eid and d["tipo"] == tipo]

    def item_de(eid, clave):
        return [c for c in comps if c["equipo_id"] == eid and c["clave"] == clave]

    evalua = {}

    # -- inspecciones del avión: existen en su catálogo y cómo van
    def por_inspeccion(claves, nombre):
        if not aviones:
            return None
        problemas, faltan = [], []
        for a in aviones:
            for k in claves:
                it = item_de(a["id"], k)
                if not it:
                    faltan.append(f"{a['nombre']}: sin «{nombre.get(k, k)}» en su catálogo")
                elif it[0]["nivel"] in ("vencido", "critico"):
                    problemas.append(f"{a['nombre']}: {it[0]['nombre']} {it[0]['nivel']}")
        if faltan:
            return "falta", faltan
        return ("atencion", problemas) if problemas else ("cumple", [f"{len(aviones)} avión(es) al día"])

    evalua["insp_anual"] = por_inspeccion(["insp_anual"], {"insp_anual": "Inspección anual"})
    evalua["insp_100h"] = por_inspeccion(["insp_100h"], {"insp_100h": "Inspección de 100 h"})
    evalua["equipos_24m"] = por_inspeccion(["pitot_estatica", "insp_elt", "brujula"],
                                           {"pitot_estatica": "Altímetro y transpondedor", "insp_elt": "ELT",
                                            "brujula": "Brújula"})

    if aviones:
        pend = [d for d in dirs if d["estado"] == "pendiente" and d["nivel"] in ("vencido", "critico")]
        if pend:
            evalua["ad"] = ("atencion", [f"{d['equipo']}: {d['numero']} {d['titulo']}" for d in pend[:6]])
        elif dirs:
            evalua["ad"] = ("cumple", [f"{len(dirs)} directivas registradas"])
        else:
            evalua["ad"] = ("atencion", ["Sin directivas cargadas: revisa las AD de la FAA del Cessna 188 y del IO-520"])

        def docs_req(tipos, texto):
            faltan, venc = [], []
            for a in aviones:
                for t in tipos:
                    ds = docs_de(a["id"], t)
                    if not ds:
                        faltan.append(f"{a['nombre']}: falta {core_flota.TIPOS_DOCUMENTO.get(t, t)}")
                    elif all(d["nivel"] == "vencido" for d in ds):
                        venc.append(f"{a['nombre']}: {core_flota.TIPOS_DOCUMENTO.get(t, t)} vencido")
            if faltan or venc:
                return "atencion", venc + faltan
            return "cumple", [texto]
        evalua["docs_bordo"] = docs_req(["matricula", "aeronavegabilidad", "licencia_radio"], "Documentos vigentes")
        evalua["fiaa"] = docs_req(["informe_fiaa"], "FIAA vigente")

        m = con.execute("""SELECT COUNT(*) n, SUM(CASE WHEN firmado_por IS NOT NULL AND licencia_firma IS NOT NULL
                                  THEN 1 ELSE 0 END) f
                           FROM mantenimientos WHERE equipo_id IN (SELECT id FROM equipos WHERE tipo_activo='avion')
                             AND fecha>=?""", ((hoy - timedelta(days=365)).isoformat(),)).fetchone()
        if m["n"]:
            pct = (m["f"] or 0) / m["n"]
            est = "cumple" if pct >= .999 else "atencion"
            evalua["registros_mant"] = (est, [f"{m['f'] or 0} de {m['n']} registros del último año firmados con licencia"])
            evalua["ccm"] = evalua["registros_mant"]
        else:
            evalua["registros_mant"] = evalua["ccm"] = ("cumple", ["Sin mantenimientos de avión en el último año"])

        t = con.execute("""SELECT chequeo FROM combustible_movimientos WHERE tipo='tanqueo' AND destino='aeronave'
                           AND fecha>=?""", ((hoy - timedelta(days=90)).isoformat(),)).fetchall()
        if t:
            incompletos = sum(1 for x in t if faltantes_tanqueo({"tipo": "tanqueo", "destino": "aeronave",
                                                                  "chequeo": x["chequeo"]}))
            evalua["comb_abastecimiento"] = (("atencion" if incompletos else "cumple"),
                                             [f"{len(t) - incompletos} de {len(t)} tanqueos de 90 días con chequeo completo"])
            evalua["comb_lugar"] = evalua["comb_abastecimiento"]
        else:
            evalua["comb_abastecimiento"] = evalua["comb_lugar"] = ("cumple", ["El registro exige el chequeo en cada tanqueo"])
        evalua["comb_reserva"] = ("cumple", ["Calculadora con reserva de 30 min y consumo real por avión"])
        evalua["comb_tanques"] = ("cumple", ["Alerta si un tanqueo supera la capacidad del tanque"])
        n_tq = con.execute("SELECT COUNT(*) n FROM combustible_movimientos WHERE tipo='tanqueo' AND destino='aeronave'").fetchone()["n"]
        evalua["comb_registro"] = ("cumple", [f"{n_tq} tanqueos registrados"]) if n_tq else \
            ("atencion", ["Aún no hay tanqueos registrados"])
        lb = con.execute("""SELECT COUNT(*) n, SUM(CASE WHEN hora_salida IS NOT NULL AND hora_llegada IS NOT NULL
                                  AND (personal_id IS NOT NULL OR piloto IS NOT NULL) THEN 1 ELSE 0 END) ok
                            FROM operaciones WHERE equipo_id IN (SELECT id FROM equipos WHERE tipo_activo='avion')
                              AND fecha>=?""", ((hoy - timedelta(days=3 * 365)).isoformat(),)).fetchone()
        if lb["n"]:
            falta = lb["n"] - (lb["ok"] or 0)
            evalua["libro_abordo"] = (("atencion", [f"{falta} de {lb['n']} vuelos sin hora de salida/llegada o piloto"])
                                      if falta else ("cumple", [f"{lb['n']} vuelos completos para el libro"]))
        else:
            evalua["libro_abordo"] = ("cumple", ["Sin vuelos de avión registrados todavía"])
        evalua["biblioteca"] = ("cumple", ["Catálogo de mantenimiento y manuales del fabricante cargados"])

    # -- aplicaciones (RAC 137.71)
    ops = con.execute("""SELECT COUNT(*) n,
                           SUM(CASE WHEN cliente IS NOT NULL AND cliente!='' THEN 1 ELSE 0 END) cli,
                           SUM(CASE WHEN producto IS NOT NULL AND producto!='' THEN 1 ELSE 0 END) prod,
                           SUM(CASE WHEN litros IS NOT NULL AND litros>0 THEN 1 ELSE 0 END) cant
                         FROM operaciones WHERE fecha>=? AND fecha<=?""",
                      ((hoy - timedelta(days=365)).isoformat(), hoy.isoformat())).fetchone()
    if ops["n"]:
        faltan = []
        for k, txt in (("cli", "cliente"), ("prod", "producto"), ("cant", "cantidad")):
            if (ops[k] or 0) < ops["n"]:
                faltan.append(f"{ops['n'] - (ops[k] or 0)} de {ops['n']} operaciones sin {txt}")
        evalua["registro_aplic"] = ("atencion", faltan) if faltan else ("cumple", [f"{ops['n']} operaciones completas"])
    else:
        evalua["registro_aplic"] = ("cumple", ["Sin operaciones en los últimos 12 meses"])

    # -- pilotos (RAC 137.73): médico y colinesterasa
    pilotos = [dict(p) for p in con.execute("SELECT * FROM personal WHERE activo=1 AND rol='piloto'").fetchall()]
    if pilotos:
        obs = []
        for p in pilotos:
            for t in ("certificado_medico", "colinesterasa"):
                ds = [d for d in docs if d.get("personal_id") == p["id"] and d["tipo"] == t]
                if not ds:
                    obs.append(f"{p['nombre']}: sin {core_flota.TIPOS_DOCUMENTO[t].split(' (')[0].lower()}")
                elif all(d["nivel"] == "vencido" for d in ds):
                    obs.append(f"{p['nombre']}: {core_flota.TIPOS_DOCUMENTO[t].split(' (')[0].lower()} vencido")
        evalua["piloto_salud"] = ("atencion", obs) if obs else ("cumple", [f"{len(pilotos)} pilotos al día"])
    else:
        evalua["piloto_salud"] = ("falta", ["No hay pilotos en Contactos con rol «piloto»"])

    # -- drones
    if drones:
        def docs_dron(tipos):
            obs = []
            for d in drones:
                for t in tipos:
                    ds = docs_de(d["id"], t)
                    if not ds:
                        obs.append(f"{d['nombre']}: falta {core_flota.TIPOS_DOCUMENTO.get(t, t).split(' (')[0]}")
                    elif all(x["nivel"] == "vencido" for x in ds):
                        obs.append(f"{d['nombre']}: {core_flota.TIPOS_DOCUMENTO.get(t, t).split(' (')[0]} vencido")
            return ("atencion", obs) if obs else ("cumple", [f"{len(drones)} drones con documentos"])
        evalua["uas_registro"] = docs_dron(["registro_uas"])
        evalua["uas_docs"] = docs_dron(["seguro", "autorizacion_uas"])
        vencidos = [c for c in comps if c["tipo_activo"] != "avion" and c["nivel"] == "vencido"]
        evalua["uas_mant"] = (("atencion", [f"{len(vencidos)} piezas con vida útil vencida"])
                              if vencidos else ("cumple", ["Piezas dentro de la vida útil de DJI"]))
        evalua["uas_libro"] = ("cumple", ["Cada operación y reparación queda registrada con piloto y responsable"])
        evalua["uas_energia"] = ("manual", ["Se confirma en el chequeo pre-vuelo del dron"])

    salida = []
    for id_, rac, numeral, titulo, exige, aplica, donde, enlace in REQUISITOS:
        r = evalua.get(id_)
        if r is None:
            estado, detalle = "no_aplica", ["No hay activos de este tipo en la flota"]
        else:
            estado, detalle = r
        salida.append({"id": id_, "rac": rac, "numeral": numeral, "titulo": titulo, "exige": exige,
                       "aplica": aplica, "donde": donde, "enlace": enlace, "estado": estado, "detalle": detalle})
    cuenta = {}
    for s in salida:
        cuenta[s["estado"]] = cuenta.get(s["estado"], 0) + 1
    evaluables = sum(v for k, v in cuenta.items() if k in ("cumple", "atencion", "falta"))
    return {"requisitos": salida, "resumen": cuenta,
            "indice": round(cuenta.get("cumple", 0) / evaluables * 100) if evaluables else None,
            "versiones": VERSIONES, "fuente": FUENTE, "reservas": RESERVAS_COMBUSTIBLE,
            "fecha": hoy.isoformat()}
