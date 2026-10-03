"""Informes: todo lo que vive en la app, listo para ver, imprimir o bajar en PDF y Excel.

Cada informe es una función registrada con @informe (igual que los indicadores de
core/indicadores.py). El registro sabe su título, su categoría, qué filtros acepta y quién lo puede
ver; la función recibe la conexión y unos Parametros y devuelve una ESTRUCTURA COMÚN:

    {"titulo", "subtitulo", "encabezado": [(etiqueta, valor)], "avisos": [...], "kpis": [...],
     "graficas": [...], "secciones": [{"titulo", "columnas": [...], "filas": [...]}], "firmas": [...]}

De esa única estructura salen las tres salidas: la vista en pantalla (templates/informes.html),
el Excel y el PDF (core/informes_salida.py). Nada se guarda precalculado: cada vez que se abre o
se descarga un informe se consulta la base en ese momento, así que siempre refleja lo último que
se registró en la app.

Los informes reutilizan los cálculos que ya existen (indicadores, estado de la flota, proyección
de repuestos, combustible, directivas, bitácora…); aquí sólo se ordenan para leerlos de corrido.

Los «Entregables RAC» son los registros que la norma obliga a llevar y presentar a la Aerocivil,
con los campos que pide el texto vigente de cada numeral. La RAC define el contenido pero no un
formato de archivo de carga: se generan listos para imprimir, firmar o adjuntar en el trámite.
"""
import importlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from core import alertas as core_alertas
from core import db as core_db
from core import flota as core_flota
from core import indicadores as core_ind
from core import ordenes as core_ordenes
from core import proyeccion as core_proyeccion

# (clave, nombre, descripción). El orden es el del catálogo en pantalla.
CATEGORIAS = [
    ("rac", "Entregables RAC",
     "Registros que exige la Aerocivil, con los campos de cada numeral. Listos para firmar y entregar."),
    ("operacion", "Operación", "Qué se voló, dónde, para quién y con qué rendimiento."),
    ("mantenimiento", "Mantenimiento y aeronavegabilidad", "Estado de la flota, vencimientos, órdenes y directivas."),
    ("combustible", "Combustible", "Tanqueos, consumo por hora y conciliación de lo cargado con lo reportado."),
    ("bodega", "Bodega e insumos", "Existencias, kardex y consumo de fitosanitarios."),
    ("costos", "Costos y rentabilidad", "Ingreso, costos y margen por activo y por cliente."),
    ("normativa", "Normativa RAC", "Cumplimiento de los requisitos de la RAC con los datos de la empresa."),
    ("personal", "Personal", "Horas de los pilotos, licencias y documentos del personal."),
]
NOMBRE_CATEGORIA = {c[0]: c[1] for c in CATEGORIAS}

PERIODOS = [("mes", "Este mes"), ("30d", "Últimos 30 días"), ("90d", "Últimos 90 días"),
            ("anio", "Este año"), ("anio_anterior", "Año anterior"), ("365d", "Últimos 12 meses"),
            ("todo", "Todo el historial")]
NOMBRE_PERIODO = dict(PERIODOS)

# Roles de la app (ver PERMISOS en app.py). El piloto no ve costos ni márgenes.
TODOS = ("admin", "superadmin", "tecnico", "certificador", "piloto", "gerencia")
SIN_PILOTO = ("admin", "superadmin", "tecnico", "certificador", "gerencia")
ADMIN = ("admin", "superadmin", "gerencia")   # costos y rentabilidad: también la gerencia (sólo lectura)

# Estados que se pintan como semáforo: (texto, clase). La clase es la del semáforo de la app
# (ok verde, proximo ámbar, critico/vencido rojo) o «gris» si no es bueno ni malo.
ESTADOS = {
    "vencido": ("Vencido", "vencido"), "critico": ("Crítico", "critico"), "proximo": ("Próximo", "proximo"),
    "ok": ("Al día", "ok"),
    "no_apto": ("No recomendado volar", "vencido"), "observaciones": ("Con observaciones", "proximo"),
    "apto": ("Apto", "ok"), "taller": ("En taller", "critico"),
    "cumple": ("Cumple", "ok"), "atencion": ("Atención", "proximo"), "falta": ("Falta", "vencido"),
    "manual": ("Verificación manual", "gris"), "no_aplica": ("No aplica", "gris"),
    "info": ("Informativo", "gris"), "incompleto": ("Incompleto", "proximo"), "completo": ("Completo", "ok"),
    "pendiente": ("Pendiente", "proximo"), "cumplida": ("Cumplida", "ok"),
    "bajo": ("Bajo mínimo", "critico"), "agotado": ("Agotado", "vencido"),
}

REGISTRO = {}


def informe(clave, titulo, categoria, descripcion, filtros=("periodo", "tipo", "equipo"), roles=TODOS,
            periodo="90d", tipo_fijo=None, norma=None, conservar=None, disponible=None, destacado=False,
            palabras="", para=None, exige=None):
    """Registra un informe.

    filtros:    cuáles acepta ('periodo', 'tipo', 'equipo', 'cliente', 'piloto').
    roles:      quién lo puede abrir y descargar.
    periodo:    período con que se abre.
    tipo_fijo:  'avion' o 'dron' si sólo tiene sentido para ese tipo de activo.
    norma:      numeral RAC que lo exige (se imprime en la cabecera).
    conservar:  cuánto tiempo exige la norma conservar el registro.
    disponible: función sin argumentos; si devuelve False el informe no aparece (módulos que
                todavía no existen en esta instalación).
    para:       «para qué sirve / quién lo pide», en una línea (se muestra en la tarjeta y la cabecera).
    exige:      en los entregables RAC, qué exige el numeral, con sus palabras.
    """
    def envolver(fn):
        REGISTRO[clave] = {"clave": clave, "titulo": titulo, "categoria": categoria, "descripcion": descripcion,
                           "filtros": tuple(filtros), "roles": tuple(roles), "periodo": periodo,
                           "tipo_fijo": tipo_fijo, "norma": norma, "conservar": conservar,
                           "disponible": disponible, "destacado": destacado, "palabras": palabras,
                           "para": para, "exige": exige, "fn": fn}
        return fn
    return envolver


def _modulo(nombre, funcion=None):
    """El módulo (o None) si existe en esta instalación y, si se pide, tiene esa función.
    Import perezoso: un módulo a medio construir no tumba el registro de informes."""
    try:
        mod = importlib.import_module(nombre)
    except Exception:
        return None
    if funcion and not callable(getattr(mod, funcion, None)):
        return None
    return mod


# ======================================================================
# Parámetros (filtros) de un informe
# ======================================================================

@dataclass
class Parametros:
    periodo: str = "90d"
    desde: str = None
    hasta: str = None
    tipo: str = None          # 'dron' | 'avion' | None
    equipo_id: int = None
    cliente: str = None
    piloto: str = None
    rol: str = "admin"
    empresa: str = None       # nombre de la empresa, para las cabeceras
    usuario: str = None

    @property
    def es_admin(self):
        return self.rol in ADMIN

    def filtros(self):
        return core_ind.Filtros(tipo=self.tipo, equipo_id=self.equipo_id, desde=self.desde, hasta=self.hasta)

    def where(self, alias="o", fecha=True, operaciones=True):
        """WHERE de las consultas: los mismos filtros que los indicadores, más cliente y piloto
        cuando la tabla es la de operaciones."""
        w, p = self.filtros().where(alias, fecha)
        if operaciones and self.cliente:
            w += f" AND lower(COALESCE({alias}.cliente,'')) = lower(?)"; p.append(self.cliente)
        if operaciones and self.piloto:
            w += f" AND lower(COALESCE({alias}.piloto,'')) = lower(?)"; p.append(self.piloto)
        return w, p


def _fecha_valida(v):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat() if v else None
    except ValueError:
        return None


def rango_periodo(nombre, hoy=None):
    hoy = hoy or date.today()
    if nombre == "anio_anterior":
        return date(hoy.year - 1, 1, 1).isoformat(), date(hoy.year - 1, 12, 31).isoformat()
    return core_ind.periodo(nombre, hoy)


def parametros(defn, args, rol="admin", empresa=None, usuario=None):
    """Parametros a partir de los argumentos de la petición (sólo los filtros que el informe acepta)."""
    args = args or {}
    acepta = set(defn["filtros"])
    p = Parametros(rol=rol or "admin", empresa=empresa, usuario=usuario, periodo=None)
    if "periodo" in acepta:
        desde, hasta = _fecha_valida(args.get("desde")), _fecha_valida(args.get("hasta"))
        if desde or hasta:
            if desde and hasta and desde > hasta:
                desde, hasta = hasta, desde
            p.periodo, p.desde, p.hasta = "personalizado", desde, hasta
        else:
            per = args.get("periodo") if args.get("periodo") in NOMBRE_PERIODO else defn["periodo"]
            p.periodo = per
            p.desde, p.hasta = rango_periodo(per)
    if "tipo" in acepta and args.get("tipo") in core_flota.TIPOS_ACTIVO:
        p.tipo = args.get("tipo")
    if defn["tipo_fijo"]:
        p.tipo = defn["tipo_fijo"]
    if "equipo" in acepta and str(args.get("equipo_id") or "").isdigit():
        p.equipo_id = int(args["equipo_id"])
    if "cliente" in acepta and (args.get("cliente") or "").strip():
        p.cliente = args["cliente"].strip()[:120]
    if "piloto" in acepta and (args.get("piloto") or "").strip():
        p.piloto = args["piloto"].strip()[:120]
    return p


def _dmy(iso):
    if not iso:
        return ""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def describir_filtros(con, p):
    """Texto de los filtros aplicados, para la cabecera: «Período: 01/07/2026 – 28/09/2026 · Drones»."""
    partes = []
    if p.periodo:
        if p.desde or p.hasta:
            rango = f"{_dmy(p.desde) or 'el inicio'} – {_dmy(p.hasta) or 'hoy'}"
            nombre = NOMBRE_PERIODO.get(p.periodo)
            partes.append(f"{nombre} ({rango})" if nombre else f"Período {rango}")
        else:
            partes.append("Todo el historial")
    if p.tipo:
        partes.append({"dron": "Drones", "avion": "Aviones"}[p.tipo])
    if p.equipo_id:
        e = con.execute("SELECT nombre, matricula FROM equipos WHERE id=?", (p.equipo_id,)).fetchone()
        partes.append("Activo: " + (e["nombre"] if e else f"#{p.equipo_id}"))
    if p.cliente:
        partes.append(f"Cliente: {p.cliente}")
    if p.piloto:
        partes.append(f"Piloto: {p.piloto}")
    return " · ".join(partes) or "Toda la flota"


# ======================================================================
# Piezas de la estructura común
# ======================================================================
# Tipos de columna: texto, entero, numero, dinero, pct, horas, fecha, estado, firma.

def col(clave, titulo, tipo="texto", dec=None, ancho=None, total=False):
    if dec is None:
        dec = {"entero": 0, "dinero": 0, "pct": 1, "horas": 1, "numero": 1}.get(tipo, 0)
    return {"clave": clave, "titulo": titulo, "tipo": tipo, "dec": dec, "ancho": ancho, "total": total}


def kpi(etiqueta, valor, tipo="numero", dec=0, unidad="", nota=None, estado=None, variacion=None, mejor=None):
    return {"etiqueta": etiqueta, "valor": valor, "tipo": tipo, "dec": dec, "unidad": unidad, "nota": nota,
            "estado": estado, "variacion": variacion, "mejor": mejor}


def seccion(titulo, columnas, filas, descripcion=None, encabezado=None, firmas=None, vacio=None, clave=None):
    return {"titulo": titulo, "descripcion": descripcion, "columnas": columnas, "filas": filas,
            "encabezado": encabezado or [], "firmas": firmas or [], "clave": clave,
            "vacio": vacio or "Sin registros con estos filtros."}


def grafica(tipo, titulo, etiquetas, series, seccion=None, campo=None, unidad="", colores=None):
    """tipo: barras | linea | ranking | dona. `seccion` (índice) y `campo` dicen qué filas de qué
    tabla se muestran al pinchar una barra: las que tienen ese valor en ese campo."""
    return {"tipo": tipo, "titulo": titulo, "etiquetas": etiquetas, "series": series, "seccion": seccion,
            "campo": campo, "unidad": unidad, "colores": colores}


def _r(v, n=1):
    return None if v is None else round(float(v), n)


def _div(a, b):
    return None if a is None or not b else a / b


def _filas(con, sql, params=()):
    return [dict(f) for f in con.execute(sql, params).fetchall()]


# ======================================================================
# Generación
# ======================================================================

def puede(defn, rol):
    return (rol or "admin") in defn["roles"]


def disponible(defn):
    return defn["disponible"] is None or bool(defn["disponible"]())


def catalogo(rol="admin"):
    salida = []
    for d in REGISTRO.values():
        if not puede(d, rol) or not disponible(d):
            continue
        salida.append({k: d[k] for k in ("clave", "titulo", "categoria", "descripcion", "filtros", "periodo",
                                         "tipo_fijo", "norma", "conservar", "destacado", "palabras", "para",
                                         "exige")}
                      | {"categoria_txt": NOMBRE_CATEGORIA.get(d["categoria"], d["categoria"]),
                         "filtros": list(d["filtros"])})
    orden = {c[0]: i for i, c in enumerate(CATEGORIAS)}
    salida.sort(key=lambda d: (orden.get(d["categoria"], 99), not d["destacado"]))
    return salida


def generar(con, clave, p):
    """Ejecuta el informe con los parámetros y completa la cabecera común."""
    defn = REGISTRO[clave]
    r = defn["fn"](con, p) or {}
    r.setdefault("titulo", defn["titulo"])
    r.setdefault("subtitulo", defn["descripcion"])
    for k in ("encabezado", "avisos", "kpis", "graficas", "secciones", "firmas"):
        r.setdefault(k, [])
    for s in r["secciones"]:
        s.setdefault("encabezado", []); s.setdefault("firmas", [])
        s.setdefault("vacio", "Sin registros con estos filtros.")
        s["totales"] = _totales(s)
    r.update({
        "clave": clave, "categoria": defn["categoria"],
        "categoria_txt": NOMBRE_CATEGORIA.get(defn["categoria"], defn["categoria"]),
        "norma": defn["norma"], "conservar": defn["conservar"], "para": defn["para"], "exige": defn["exige"],
        "filtros_txt": describir_filtros(con, p),
        "filtros": {"periodo": p.periodo, "desde": p.desde, "hasta": p.hasta, "tipo": p.tipo,
                    "equipo_id": p.equipo_id, "cliente": p.cliente, "piloto": p.piloto},
        "empresa": p.empresa, "usuario": p.usuario,
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "estados": {k: {"texto": v[0], "clase": v[1]} for k, v in ESTADOS.items()},
    })
    if defn["categoria"] == "rac":
        r.setdefault("nota_rac", NOTA_RAC)
    return r


NOTA_RAC = ("La RAC define qué datos debe contener este registro, pero no un formato de archivo de carga. "
            "Se genera con los campos exigidos por la norma, listo para imprimir, firmar o adjuntar en el "
            "trámite ante la Aerocivil.")


def _totales(s):
    """Fila de totales: suma las columnas marcadas `total`. Nada si no hay ninguna."""
    cols = [c for c in s["columnas"] if c.get("total")]
    if not cols or not s["filas"]:
        return None
    t = {}
    for c in cols:
        vals = [f.get(c["clave"]) for f in s["filas"] if isinstance(f.get(c["clave"]), (int, float))]
        t[c["clave"]] = round(sum(vals), max(c["dec"], 0)) if vals else None
    return t


# ======================================================================
# Ayudas compartidas por varios informes
# ======================================================================

def _equipos(con, p, tipo=None):
    cond, prm = ["estado != 'baja'"], []
    tipo = tipo or p.tipo
    if tipo:
        cond.append("tipo_activo=?"); prm.append(tipo)
    if p.equipo_id:
        cond.append("id=?"); prm.append(p.equipo_id)
    return _filas(con, f"SELECT * FROM equipos WHERE {' AND '.join(cond)} ORDER BY tipo_activo DESC, nombre", prm)


def _operaciones(con, p, orden="o.fecha, COALESCE(o.hora_salida,''), o.id"):
    w, prm = p.where()
    return _filas(con, f"""SELECT o.*, e.nombre equipo, e.modelo, e.tipo_activo, e.matricula
                           FROM operaciones o JOIN equipos e ON e.id=o.equipo_id
                           WHERE {w} ORDER BY {orden}""", prm)


class _Personas:
    """Directorio de personal para enlazar el piloto de cada operación con su licencia y sus
    documentos (por `personal_id` o, en registros viejos, por el nombre escrito)."""

    def __init__(self, con):
        self.por_id, self.por_nombre = {}, {}
        for f in _filas(con, "SELECT * FROM personal"):
            self.por_id[f["id"]] = f
            self.por_nombre.setdefault((f["nombre"] or "").strip().lower(), f)
        self.docs = {}
        for d in core_flota.documentos_con_estado(con):
            if d.get("personal_id"):
                self.docs.setdefault(d["personal_id"], []).append(d)

    def de(self, op):
        if op.get("personal_id") and op["personal_id"] in self.por_id:
            return self.por_id[op["personal_id"]]
        return self.por_nombre.get((op.get("piloto") or "").strip().lower())

    def documento(self, persona, tipo):
        """El documento más reciente de ese tipo (el de vencimiento más lejano)."""
        if not persona:
            return None
        ds = [d for d in self.docs.get(persona["id"], []) if d["tipo"] == tipo]
        ds.sort(key=lambda d: d.get("vence") or "", reverse=True)
        return ds[0] if ds else None

    def licencia(self, persona, tipo_doc=None):
        """Número de licencia o certificado: el del documento pedido si existe, si no el de la ficha."""
        if not persona:
            return None
        d = self.documento(persona, tipo_doc) if tipo_doc else None
        return (d or {}).get("numero") or persona.get("licencia")


def _num_txt(v, dec=2):
    """1234.5 -> «1.234,5» (sin ceros de sobra)."""
    t = f"{float(v):,.{dec}f}".rstrip("0").rstrip(".")
    return t.replace(",", "§").replace(".", ",").replace("§", ".")


def _minutos(hhmm):
    try:
        h, m = str(hhmm).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _horas_entre(salida, llegada):
    a, b = _minutos(salida), _minutos(llegada)
    if a is None or b is None:
        return None
    return round(((b - a) % (24 * 60)) / 60, 2)


def _incompletos_aviso(n, total, que, enlace="/operaciones"):
    if not n:
        return []
    return [{"nivel": "proximo", "enlace": enlace,
             "texto": f"{n} de {total} registros incompletos: falta {que}. Complétalos antes de entregar."}]


def _faltan_txt(faltas):
    """«hora de salida (4), licencia del piloto (2)» a partir de un contador de campos."""
    return ", ".join(f"{k} ({v})" for k, v in sorted(faltas.items(), key=lambda x: -x[1]))


def _nacionalidad(e):
    mat = (e.get("matricula") or e.get("nombre") or "").upper()
    return "Colombia (HK)" if mat.startswith("HK") else ""


def _fabricante(con, e):
    if e.get("fabricante"):
        return e["fabricante"]
    m = core_flota.modelo_activo(con, e.get("modelo"))
    if m and m.get("fabricante"):
        return m["fabricante"]
    return "DJI" if e.get("tipo_activo") == "dron" else ""


def _serie_mes(filas, campo_mes="mes", series=()):
    etiquetas = [f[campo_mes] for f in filas]
    return etiquetas, [{"nombre": n, "datos": [f.get(k) or 0 for f in filas], "unidad": u} for k, n, u in series]


def _pct_var(ind):
    return ind.get("variacion") if ind else None


def _kpi_ind(ind, clave, etiqueta=None, tipo="numero"):
    """KPI a partir de un indicador calculado por core/indicadores.py (con su comparación)."""
    i = ind.get(clave)
    if not i:
        return None
    t = "dinero" if i["unidad"].startswith("$") else ("pct" if i["unidad"] == "%" else tipo)
    return kpi(etiqueta or i["nombre"], i["valor"], t, i["decimales"],
               "" if t in ("dinero", "pct") else i["unidad"],
               nota=i["formula"], variacion=i["variacion"], mejor=i["mejor"])


# ======================================================================
# ENTREGABLES RAC
# ======================================================================

@informe("rac_libro_abordo", "Libro de a bordo del avión", "rac",
         "Registro de cada vuelo del avión: tripulación, lugares y horas de salida y llegada, tiempo de vuelo, "
         "horas bloque, propósito y anotaciones técnicas, con espacio para la firma del piloto al mando.",
         filtros=("periodo", "equipo"), tipo_fijo="avion", periodo="mes", norma="RAC 91.1410",
         conservar="3 años", destacado=True, palabras="bitacora vuelo cessna aeronave diario de vuelo",
         para='Lo lleva el piloto al mando y lo revisa la Aerocivil en inspecciones de rampa y auditorías; se conserva 3 años.',
         exige='Por cada vuelo: fecha, tripulación con licencia, lugar y hora de salida y de llegada, tiempo de vuelo y horas bloque, propósito, observaciones, anotaciones técnicas y firma del piloto al mando. Encabezado con nacionalidad y matrícula.')
def _rac_libro_abordo(con, p):
    personas = _Personas(con)
    aviones = _equipos(con, p, "avion")
    ops = _operaciones(con, p)
    mant = {}
    for m in core_db.bitacora(con, p.equipo_id, p.desde, p.hasta, limite=10 ** 6):
        mant.setdefault((m["equipo_id"], m["fecha"]), []).append(m)
    secciones, incompletos, faltas, total = [], 0, {}, 0
    for a in aviones:
        filas = []
        for o in [x for x in ops if x["equipo_id"] == a["id"]]:
            per = personas.de(o)
            lic = personas.licencia(per)
            tecnicas = []
            if o.get("hobbs_ini") is not None and o.get("hobbs_fin") is not None:
                tecnicas.append(f"Hobbs {o['hobbs_ini']:.1f}–{o['hobbs_fin']:.1f}")
            if o.get("tach_ini") is not None and o.get("tach_fin") is not None:
                tecnicas.append(f"Tach {o['tach_ini']:.1f}–{o['tach_fin']:.1f}")
            if o.get("combustible_gal"):
                tecnicas.append(f"Combustible {o['combustible_gal']:.1f} gal")
            for m in mant.get((a["id"], o["fecha"]), []):
                tecnicas.append((m.get("descripcion") or m.get("pieza") or "Mantenimiento")[:120])
            bloque = _horas_entre(o.get("hora_salida"), o.get("hora_llegada"))
            if bloque is None and o.get("hobbs_ini") is not None and o.get("hobbs_fin") is not None:
                bloque = round(o["hobbs_fin"] - o["hobbs_ini"], 2)
            f = {"fecha": o["fecha"], "piloto": (per or {}).get("nombre") or o.get("piloto"), "licencia": lic,
                 "origen": o.get("origen"), "hora_salida": o.get("hora_salida"), "destino": o.get("destino"),
                 "hora_llegada": o.get("hora_llegada"), "tiempo_vuelo": _r(o.get("horas_vuelo"), 2),
                 "horas_bloque": bloque, "aterrizajes": o.get("aterrizajes"),
                 "proposito": o.get("proposito") or "Aplicación aérea", "observaciones": o.get("nota"),
                 "tecnicas": " · ".join(tecnicas) or None, "firma": None, "_enlace": "/operaciones"}
            falta = [n for k, n in (("piloto", "piloto"), ("licencia", "licencia del piloto"),
                                    ("origen", "punto de salida"), ("hora_salida", "hora de salida"),
                                    ("destino", "punto de llegada"), ("hora_llegada", "hora de llegada")) if not f[k]]
            if falta:
                incompletos += 1
                f["_incompleto"] = [k for k in ("piloto", "licencia", "origen", "hora_salida", "destino", "hora_llegada")
                                    if not f[k]]
                for n in falta:
                    faltas[n] = faltas.get(n, 0) + 1
            filas.append(f)
        total += len(filas)
        secciones.append(seccion(
            f"Libro de a bordo · {a.get('matricula') or a['nombre']}",
            [col("fecha", "Fecha", "fecha"), col("piloto", "Piloto al mando", ancho=22),
             col("licencia", "Licencia N.º", ancho=13), col("origen", "Salida (lugar)", ancho=16),
             col("hora_salida", "Hora salida", ancho=8), col("destino", "Llegada (lugar)", ancho=16),
             col("hora_llegada", "Hora llegada", ancho=8),
             col("tiempo_vuelo", "Tiempo de vuelo (h)", "horas", 2, total=True),
             col("horas_bloque", "Horas bloque", "horas", 2, total=True),
             col("aterrizajes", "Aterr.", "entero", total=True),
             col("proposito", "Propósito", ancho=16), col("observaciones", "Observaciones", ancho=24),
             col("tecnicas", "Anotaciones técnicas", ancho=30), col("firma", "Firma piloto al mando", "firma", ancho=22)],
            filas,
            encabezado=[("Nacionalidad", _nacionalidad(a) or "—"), ("Matrícula", a.get("matricula") or a["nombre"]),
                        ("Aeronave", f"{_fabricante(con, a) or ''} {a['modelo']}".strip()),
                        ("N.º de serie", a.get("numero_serie") or "—"), ("Explotador", p.empresa or "—")],
            vacio="Sin vuelos registrados para este avión en el período."))
    horas = sum(f["tiempo_vuelo"] or 0 for s in secciones for f in s["filas"])
    return {
        "subtitulo": "Registro de vuelos por aeronave (RAC 91.1410). Horas bloque: de la hora de salida a la de "
                     "llegada; si no están, la diferencia de Hobbs.",
        "kpis": [kpi("Vuelos", total, "entero", nota="Operaciones del avión registradas en el período."),
                 kpi("Tiempo de vuelo", horas, "horas", 1, "h", nota="Σ horas de vuelo de cada operación."),
                 kpi("Aviones", len(aviones), "entero", nota="Aviones en servicio incluidos en el libro."),
                 kpi("Registros incompletos", incompletos, "entero", estado="proximo" if incompletos else "ok",
                     nota="Vuelos a los que les falta piloto, licencia, lugar u hora de salida o de llegada.")],
        "avisos": _incompletos_aviso(incompletos, total, _faltan_txt(faltas)) if incompletos else
                  ([{"nivel": "info", "texto": "No hay aviones en la flota con estos filtros."}] if not aviones else []),
        "secciones": secciones,
        "firmas": ["Piloto al mando (nombre y licencia)", "Jefe de operaciones del explotador"],
    }


@informe("rac_libro_uas", "Libro de vuelo y mantenimiento del UA", "rac",
         "Por cada dron: sus vuelos con fecha, horas de despegue y aterrizaje, tiempo total y piloto con su "
         "certificado de idoneidad; y los reportes de fallas y trabajos de mantenimiento con quién los hizo.",
         filtros=("periodo", "equipo"), tipo_fijo="dron", periodo="mes", norma="RAC 100.005 · 100.510(3)",
         conservar="Vida del UAS", destacado=True, palabras="dron uas drone libro vuelo mantenimiento",
         para='El explotador del dron lo presenta a la Aerocivil cuando lo pide (inspección, renovación de la autorización o un incidente).',
         exige='Por vuelo: fecha, hora de despegue y aterrizaje, tiempo total y piloto con su certificado de idoneidad. Además, los reportes de fallas y los trabajos de mantenimiento con quién los hizo y el estado de aeronavegabilidad.')
def _rac_libro_uas(con, p):
    personas = _Personas(con)
    drones = _equipos(con, p, "dron")
    ops = _operaciones(con, p)
    estados = core_alertas.estado_flota(con)
    docs = core_flota.documentos_con_estado(con, incluir_personal=False)
    ots = core_ordenes.listar_ot(con, equipo_id=p.equipo_id)
    secciones, incompletos, faltas, total = [], 0, {}, 0
    for d in drones:
        filas = []
        for o in [x for x in ops if x["equipo_id"] == d["id"]]:
            per = personas.de(o)
            f = {"fecha": o["fecha"], "hora_despegue": o.get("hora_salida"), "hora_aterrizaje": o.get("hora_llegada"),
                 "tiempo_total": _r(o.get("horas_vuelo"), 2), "vuelos": o.get("despegues"),
                 "piloto": (per or {}).get("nombre") or o.get("piloto"),
                 "certificado": personas.licencia(per, "idoneidad_uas"), "hectareas": _r(o.get("hectareas"), 1),
                 "lugar": o.get("lote") or o.get("zona"), "observaciones": o.get("nota"), "_enlace": "/operaciones"}
            falta = [n for k, n in (("hora_despegue", "hora de despegue"), ("hora_aterrizaje", "hora de aterrizaje"),
                                    ("piloto", "piloto"), ("certificado", "certificado de idoneidad")) if not f[k]]
            if falta:
                incompletos += 1
                f["_incompleto"] = [k for k in ("hora_despegue", "hora_aterrizaje", "piloto", "certificado") if not f[k]]
                for n in falta:
                    faltas[n] = faltas.get(n, 0) + 1
            filas.append(f)
        total += len(filas)
        registro = next((x["numero"] for x in docs if x["equipo_id"] == d["id"] and x["tipo"] == "registro_uas"
                         and x.get("numero")), None)
        est = estados.get(d["id"], {"estado": "apto", "estado_txt": "Apto", "motivos": []})
        encab = [("Fabricante", _fabricante(con, d) or "—"), ("Modelo", d["modelo"]),
                 ("Serial", d.get("numero_serie") or "—"), ("Registro UAS", registro or "Sin registrar"),
                 ("Explotador", p.empresa or "—"), ("Aeronavegabilidad", est.get("estado_txt") or "Apto")]
        secciones.append(seccion(
            f"Vuelos · {d['nombre']}",
            [col("fecha", "Fecha", "fecha"), col("hora_despegue", "Hora despegue", ancho=9),
             col("hora_aterrizaje", "Hora aterrizaje", ancho=9),
             col("tiempo_total", "Tiempo total (h)", "horas", 2, total=True),
             col("vuelos", "Despegues", "entero", total=True), col("piloto", "Piloto", ancho=22),
             col("certificado", "Certificado de idoneidad N.º", ancho=16),
             col("hectareas", "Hectáreas", "numero", 1, total=True), col("lugar", "Lugar", ancho=18),
             col("observaciones", "Observaciones", ancho=26)],
            filas, encabezado=encab, vacio="Sin vuelos registrados para este dron en el período."))
        # Fallas y mantenimiento: la bitácora de reparaciones y las órdenes de trabajo del dron.
        mfilas = []
        for m in core_db.bitacora(con, d["id"], p.desde, p.hasta, limite=10 ** 6):
            mfilas.append({"fecha": m["fecha"], "registro": "Mantenimiento",
                           "tipo": "Falla / daño" if m["motivo"] == "daño" else (m.get("tipo") or "").capitalize(),
                           "descripcion": " · ".join(x for x in (m.get("pieza"), m.get("descripcion")) if x) or None,
                           "responsable": m.get("realizado_por"), "certifica": m.get("firmado_por"),
                           "estado": "Realizado", "_enlace": "/bitacora"})
        for o in ots:
            if o["equipo_id"] != d["id"]:
                continue
            fecha = (o.get("cerrado_en") or "")[:10] or o.get("fecha_programada") or (o.get("creado") or "")[:10]
            if (p.desde and fecha < p.desde) or (p.hasta and fecha > p.hasta):
                continue
            mfilas.append({"fecha": fecha, "registro": f"Orden {o['codigo']}", "tipo": (o.get("tipo") or "").capitalize(),
                           "descripcion": o.get("titulo"), "responsable": o.get("asignado_a"),
                           "certifica": o.get("firmado_por"), "estado": o["estado_txt"], "_enlace": "/ordenes-trabajo"})
        mfilas.sort(key=lambda x: x["fecha"] or "")
        secciones.append(seccion(
            f"Fallas y mantenimiento · {d['nombre']}",
            [col("fecha", "Fecha", "fecha"), col("registro", "Registro", ancho=14), col("tipo", "Tipo", ancho=14),
             col("descripcion", "Falla o trabajo realizado", ancho=40), col("responsable", "Quién lo hizo", ancho=20),
             col("certifica", "Certificó", ancho=18), col("estado", "Estado", ancho=12)],
            mfilas, encabezado=[("Estado de aeronavegabilidad", est.get("estado_txt") or "Apto"),
                                ("Motivos", "; ".join(est.get("motivos", [])[:4]) or "Sin observaciones")],
            vacio="Sin fallas ni trabajos de mantenimiento registrados en el período."))
    horas = sum(f["tiempo_total"] or 0 for s in secciones[::2] for f in s["filas"])
    return {
        "subtitulo": "Libro de vuelo y de mantenimiento de cada aeronave no tripulada (RAC 100.005 y 100.510(3)).",
        "kpis": [kpi("Vuelos (jornadas)", total, "entero", nota="Operaciones de los drones registradas en el período."),
                 kpi("Tiempo de vuelo", horas, "horas", 1, "h", nota="Σ horas de vuelo de cada operación."),
                 kpi("Drones", len(drones), "entero", nota="Drones en servicio incluidos en el libro."),
                 kpi("Registros incompletos", incompletos, "entero", estado="proximo" if incompletos else "ok",
                     nota="Vuelos sin hora de despegue o aterrizaje, sin piloto o sin su certificado de idoneidad.")],
        "avisos": _incompletos_aviso(incompletos, total, _faltan_txt(faltas)),
        "secciones": secciones,
        "firmas": ["Piloto responsable", "Explotador (representante)"],
    }


def _direcciones_clientes(con):
    """Nombre → «dirección, ciudad» de los contactos con rol cliente (por nombre o por empresa)."""
    salida = {}
    for c in _filas(con, "SELECT nombre, empresa, direccion, ciudad FROM personal WHERE rol='cliente'"):
        dire = ", ".join(x for x in (c.get("direccion"), c.get("ciudad")) if x)
        if not dire:
            continue
        for k in (c.get("nombre"), c.get("empresa")):
            if k:
                salida.setdefault(k.strip().lower(), dire)
    return salida


@informe("rac_aplicaciones", "Registro de aplicaciones aéreas", "rac",
         "Constancia de cada servicio: nombre y dirección del cliente, fecha, finca, nombre y cantidad de los "
         "productos aplicados, hectáreas, dosis y piloto.",
         filtros=("periodo", "tipo", "equipo", "cliente", "piloto"), periodo="365d", norma="RAC 137.71",
         conservar="12 meses", destacado=True, palabras="aplicacion fumigacion producto cliente constancia 137",
         para='Constancia de cada servicio de aspersión para la Aerocivil, el ICA y el propio cliente; se conserva 12 meses.',
         exige='Nombre y dirección de cada cliente, fecha de cada servicio, y nombre y cantidad de los productos aplicados en cada operación.')
def _rac_aplicaciones(con, p):
    direcciones = _direcciones_clientes(con)
    ops = _operaciones(con, p)
    # Con la bodega, cada operación puede llevar los insumos exactos que se le cargaron (nombre,
    # cantidad y registro ICA): es lo que pide el numeral. Si no, queda el producto escrito a mano.
    insumos = {}
    if _hay_bodega():
        for a in _filas(con, """SELECT a.operacion_id, i.nombre, i.unidad, i.registro_ica,
                                       COALESCE(m.cantidad, a.cantidad_teorica) cantidad
                                FROM bodega_aplicaciones a JOIN bodega_items i ON i.id=a.item_id
                                LEFT JOIN bodega_movimientos m ON m.id=a.movimiento_id ORDER BY a.id"""):
            txt = a["nombre"] + (f" {_num_txt(a['cantidad'])} {a['unidad'] or ''}".rstrip() if a["cantidad"] else "")
            insumos.setdefault(a["operacion_id"], []).append(txt + (f" (ICA {a['registro_ica']})" if a["registro_ica"] else ""))
    filas, incompletos, faltas, por_cliente = [], 0, {}, {}
    for o in ops:
        cliente = o.get("cliente")
        dire = direcciones.get((cliente or "").strip().lower())
        f = {"fecha": o["fecha"], "cliente": cliente, "direccion": dire, "finca": o.get("lote"), "zona": o.get("zona"),
             "producto": o.get("producto") or ("; ".join(insumos[o["id"]]) if o["id"] in insumos else None),
             "insumos": "; ".join(insumos.get(o["id"], [])) or None,
             "cantidad": _r(o.get("litros"), 1), "unidad": "L" if o.get("litros") else None,
             "hectareas": _r(o.get("hectareas"), 2), "dosis": _r(_div(o.get("litros"), o.get("hectareas")), 1),
             "piloto": o.get("piloto"), "equipo": o["equipo"] + (f" ({o['matricula']})" if o.get("matricula") else ""),
             "_enlace": "/operaciones"}
        falta = [n for k, n in (("cliente", "cliente"), ("direccion", "dirección del cliente"),
                                ("producto", "producto"), ("cantidad", "cantidad aplicada")) if not f[k]]
        if falta:
            incompletos += 1
            f["_incompleto"] = [k for k in ("cliente", "direccion", "producto", "cantidad") if not f[k]]
            for n in falta:
                faltas[n] = faltas.get(n, 0) + 1
        filas.append(f)
        c = por_cliente.setdefault(cliente or "Sin cliente", {"cliente": cliente or "Sin cliente", "direccion": dire,
                                                             "servicios": 0, "primera": o["fecha"], "ultima": o["fecha"],
                                                             "hectareas": 0, "litros": 0, "productos": set()})
        c["servicios"] += 1
        c["ultima"] = max(c["ultima"], o["fecha"])
        c["primera"] = min(c["primera"], o["fecha"])
        c["hectareas"] += o.get("hectareas") or 0
        c["litros"] += o.get("litros") or 0
        if o.get("producto"):
            c["productos"].add(o["producto"])
    resumen = []
    for c in sorted(por_cliente.values(), key=lambda x: -x["hectareas"]):
        c["productos"] = ", ".join(sorted(c["productos"])) or None
        c["hectareas"], c["litros"] = round(c["hectareas"], 1), round(c["litros"], 0)
        resumen.append(c)
    ha = sum(f["hectareas"] or 0 for f in filas)
    litros = sum(f["cantidad"] or 0 for f in filas)
    avisos = _incompletos_aviso(incompletos, len(filas), _faltan_txt(faltas))
    if faltas.get("dirección del cliente"):
        avisos.append({"nivel": "info", "enlace": "/contactos",
                       "texto": "La dirección sale de Contactos: registra a cada cliente con rol «Cliente», "
                                "su dirección y su ciudad, con el mismo nombre que se usa en las operaciones."})
    return {
        "subtitulo": "Registro de cada operación de aplicación aérea (RAC 137.71): se conserva al menos 12 meses.",
        "kpis": [kpi("Aplicaciones", len(filas), "entero", nota="Una por operación registrada en el período."),
                 kpi("Clientes", len(resumen), "entero", nota="Clientes distintos atendidos."),
                 kpi("Hectáreas", ha, "numero", 1, "ha", nota="Σ hectáreas aplicadas."),
                 kpi("Producto aplicado", litros, "numero", 0, "L", nota="Σ litros de mezcla anotados en las operaciones."),
                 kpi("Registros incompletos", incompletos, "entero", estado="proximo" if incompletos else "ok",
                     nota="Aplicaciones sin cliente, sin dirección del cliente, sin producto o sin cantidad.")],
        "avisos": avisos,
        "graficas": [grafica("ranking", "Hectáreas por cliente", [c["cliente"] for c in resumen[:12]],
                             [{"nombre": "Hectáreas", "datos": [c["hectareas"] for c in resumen[:12]]}],
                             seccion=0, campo="cliente", unidad="ha")],
        "secciones": [
            seccion("Aplicaciones realizadas",
                    [col("fecha", "Fecha", "fecha"), col("cliente", "Cliente", ancho=20),
                     col("direccion", "Dirección del cliente", ancho=24), col("finca", "Finca / lote", ancho=18),
                     col("producto", "Producto aplicado", ancho=22),
                     col("cantidad", "Mezcla aplicada", "numero", 1, total=True), col("unidad", "Unidad", ancho=7),
                     col("insumos", "Insumos y cantidades (bodega)", ancho=30),
                     col("hectareas", "Hectáreas", "numero", 2, total=True), col("dosis", "Dosis (L/ha)", "numero", 1),
                     col("piloto", "Piloto", ancho=18), col("equipo", "Aeronave", ancho=14)], filas),
            seccion("Resumen por cliente",
                    [col("cliente", "Cliente", ancho=22), col("direccion", "Dirección", ancho=26),
                     col("servicios", "Servicios", "entero", total=True), col("primera", "Primer servicio", "fecha"),
                     col("ultima", "Último servicio", "fecha"), col("hectareas", "Hectáreas", "numero", 1, total=True),
                     col("litros", "Litros", "numero", 0, total=True), col("productos", "Productos", ancho=36)],
                    resumen),
        ],
        "firmas": ["Responsable de operaciones del explotador"],
    }


@informe("rac_horas_pilotos", "Certificación de horas de vuelo por piloto", "rac",
         "Horas voladas por cada piloto, mes a mes y por aeronave, con el vencimiento de su certificado médico "
         "y del examen de colinesterasa, y la firma del explotador.",
         filtros=("periodo", "tipo", "piloto"), periodo="anio", norma="RAC 100.510(4)-(5) · 137.73",
         conservar="Vigencia de la licencia", destacado=True,
         palabras="piloto horas certificado medico colinesterasa licencia anual",
         para='Certificación que firma el explotador para renovar licencias y certificados de los pilotos; la Aerocivil la exige con el registro del piloto.',
         exige='Horas de vuelo de cada piloto certificadas por el explotador y, para aviación agrícola, el vencimiento del certificado médico y del examen de colinesterasa.')
def _rac_horas_pilotos(con, p):
    personas = _Personas(con)
    ops = _operaciones(con, p)
    pilotos = {}
    for o in ops:
        per = personas.de(o)
        nombre = (per or {}).get("nombre") or o.get("piloto") or "Sin piloto"
        d = pilotos.setdefault(nombre, {"persona": per, "ops": []})
        d["persona"] = d["persona"] or per
        d["ops"].append(o)
    resumen, secciones = [], []
    hoy = date.today().isoformat()

    def estado_doc(doc):
        if not doc or not doc.get("vence"):
            return "falta"
        return doc["nivel"]

    for nombre in sorted(pilotos):
        d = pilotos[nombre]
        per = d["persona"]
        medico = personas.documento(per, "certificado_medico")
        coli = personas.documento(per, "colinesterasa")
        tipos = {o["tipo_activo"] for o in d["ops"]}
        lic = personas.licencia(per, "idoneidad_uas" if tipos == {"dron"} else None)
        horas = sum(o.get("horas_vuelo") or 0 for o in d["ops"])
        peor = min((estado_doc(medico), estado_doc(coli)),
                   key=lambda n: ["vencido", "falta", "critico", "proximo", "ok"].index(n))
        resumen.append({"piloto": nombre, "documento": (per or {}).get("documento"), "licencia": lic,
                        "horas": round(horas, 1), "vuelos": len(d["ops"]),
                        "aeronaves": ", ".join(sorted({o["equipo"] for o in d["ops"]})),
                        "medico_vence": (medico or {}).get("vence"), "coli_vence": (coli or {}).get("vence"),
                        "estado": peor, "_enlace": "/contactos"})
        meses = {}
        for o in d["ops"]:
            k = (o["fecha"][:7], o["equipo"])
            m = meses.setdefault(k, {"mes": o["fecha"][:7], "equipo": o["equipo"], "tipo": core_flota.TIPOS_ACTIVO.get(o["tipo_activo"]),
                                     "horas": 0, "vuelos": 0, "salidas": 0, "hectareas": 0})
            m["horas"] += o.get("horas_vuelo") or 0
            m["vuelos"] += 1
            m["salidas"] += o.get("despegues") or o.get("aterrizajes") or 0
            m["hectareas"] += o.get("hectareas") or 0
        filas = []
        for m in sorted(meses.values(), key=lambda x: (x["mes"], x["equipo"])):
            m["horas"], m["hectareas"] = round(m["horas"], 2), round(m["hectareas"], 1)
            filas.append(m)
        secciones.append(seccion(
            f"Horas de {nombre}",
            [col("mes", "Mes", ancho=9), col("equipo", "Aeronave", ancho=16), col("tipo", "Tipo", ancho=8),
             col("vuelos", "Jornadas", "entero", total=True), col("salidas", "Despegues / aterrizajes", "entero", total=True),
             col("horas", "Horas de vuelo", "horas", 2, total=True), col("hectareas", "Hectáreas", "numero", 1, total=True)],
            filas,
            encabezado=[("Piloto", nombre), ("Documento", (per or {}).get("documento") or "—"),
                        ("Licencia / certificado", lic or "—"),
                        ("Certificado médico vence", _dmy((medico or {}).get("vence")) or "Sin registrar"),
                        ("Colinesterasa vence", _dmy((coli or {}).get("vence")) or "Sin registrar")],
            firmas=["Firma del explotador (representante)", f"Firma del piloto · {nombre}"]))
    faltan = [r for r in resumen if r["estado"] in ("falta", "vencido")]
    avisos = []
    if faltan:
        avisos.append({"nivel": "proximo", "enlace": "/contactos",
                       "texto": f"{len(faltan)} piloto(s) con el certificado médico o la colinesterasa vencidos o sin "
                                "registrar en Contactos › documentos."})
    sin_ficha = [r["piloto"] for r in resumen if not r["licencia"]]
    if sin_ficha:
        avisos.append({"nivel": "proximo", "enlace": "/contactos",
                       "texto": f"{len(sin_ficha)} piloto(s) sin número de licencia o certificado: "
                                + ", ".join(sin_ficha[:5]) + ("…" if len(sin_ficha) > 5 else "")})
    return {
        "subtitulo": f"Horas de vuelo certificadas por el explotador al {_dmy(hoy)} (RAC 100.510 y 137.73).",
        "kpis": [kpi("Pilotos", len(resumen), "entero", nota="Pilotos con al menos una operación en el período."),
                 kpi("Horas de vuelo", sum(r["horas"] for r in resumen), "horas", 1, "h",
                     nota="Σ horas de vuelo de las operaciones de cada piloto."),
                 kpi("Con documentos al día", sum(1 for r in resumen if r["estado"] in ("ok", "proximo")), "entero",
                     nota="Certificado médico y colinesterasa registrados y sin vencer."),
                 kpi("Con pendientes", len(faltan), "entero", estado="vencido" if faltan else "ok",
                     nota="Pilotos con el médico o la colinesterasa vencidos o sin registrar.")],
        "avisos": avisos,
        "graficas": [grafica("ranking", "Horas por piloto", [r["piloto"] for r in resumen],
                             [{"nombre": "Horas", "datos": [r["horas"] for r in resumen]}], seccion=0,
                             campo="piloto", unidad="h")],
        "secciones": [seccion(
            "Resumen por piloto",
            [col("piloto", "Piloto", ancho=22), col("documento", "Documento", ancho=13),
             col("licencia", "Licencia / certificado", ancho=16), col("vuelos", "Jornadas", "entero", total=True),
             col("horas", "Horas", "horas", 1, total=True), col("aeronaves", "Aeronaves", ancho=22),
             col("medico_vence", "Médico vence", "fecha"), col("coli_vence", "Colinesterasa vence", "fecha"),
             col("estado", "Documentos", "estado")], resumen)] + secciones,
        "firmas": ["Explotador (representante legal)", "Jefe de pilotos"],
    }


@informe("rac_fiaa", "Soporte del informe anual de aeronavegabilidad (FIAA)", "rac",
         "Por avión: estadística de servicios del año (horas y ciclos), estado de las directivas de "
         "aeronavegabilidad y componentes de vida limitada con su tiempo en servicio y lo que les queda.",
         filtros=("periodo", "equipo"), tipo_fijo="avion", periodo="365d", norma="RAC 91.1136",
         conservar="Anual", destacado=True, palabras="fiaa aeronavegabilidad anual directivas componentes vida limitada",
         para='Soporte para diligenciar el formulario FIAA que el explotador presenta cada 12 meses a la Aerocivil.',
         exige='Condición de aeronavegabilidad del avión: estadística de horas y ciclos del año, cumplimiento de directivas de aeronavegabilidad y componentes de vida limitada con su tiempo remanente.')
def _rac_fiaa(con, p):
    aviones = _equipos(con, p, "avion")
    ids = [a["id"] for a in aviones]
    lect = core_flota.lecturas(con, ids) if ids else {}
    estados = core_alertas.estado_flota(con)
    secciones, kpis_dir, kpis_comp = [], 0, 0
    for a in aviones:
        w, prm = replace(p, equipo_id=a["id"], tipo=None).where()
        meses = _filas(con, f"""SELECT substr(o.fecha,1,7) mes, COUNT(*) servicios,
                ROUND(COALESCE(SUM(COALESCE(o.hobbs_fin - o.hobbs_ini, o.horas_vuelo)),0),1) hobbs,
                ROUND(COALESCE(SUM(COALESCE(o.tach_fin - o.tach_ini, o.horas_vuelo)),0),1) tach,
                COALESCE(SUM(o.aterrizajes),0) aterrizajes, COALESCE(SUM(o.arranques),0) arranques,
                ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
            FROM operaciones o WHERE {w} GROUP BY substr(o.fecha,1,7) ORDER BY 1""", prm)
        l = lect.get(a["id"], {})
        est = estados.get(a["id"], {"estado_txt": "Apto", "motivos": []})
        encab = [("Matrícula", a.get("matricula") or a["nombre"]), ("Aeronave", f"{_fabricante(con, a)} {a['modelo']}".strip()),
                 ("N.º de serie", a.get("numero_serie") or "—"), ("Año", a.get("anio") or "—"),
                 ("Hobbs actual", f"{l.get('hobbs', 0):.1f} h"), ("Tach actual", f"{l.get('tach', 0):.1f} h"),
                 ("Aterrizajes totales", f"{l.get('aterrizajes', 0):.0f}"), ("Estado", est.get("estado_txt"))]
        secciones.append(seccion(f"Estadística de servicios · {a.get('matricula') or a['nombre']}",
                                 [col("mes", "Mes", ancho=9), col("servicios", "Servicios", "entero", total=True),
                                  col("hobbs", "Horas Hobbs", "horas", 1, total=True),
                                  col("tach", "Horas Tach", "horas", 1, total=True),
                                  col("aterrizajes", "Aterrizajes (ciclos)", "entero", total=True),
                                  col("arranques", "Arranques", "entero", total=True),
                                  col("hectareas", "Hectáreas", "numero", 1, total=True)],
                                 meses, encabezado=encab))
        dirs = []
        for d in core_flota.directivas_con_estado(con, a["id"]):
            plazo = (f"vence {_dmy(d['limite_fecha'])}" if d["estado"] == "pendiente" and d.get("limite_fecha") else
                     f"próxima {_dmy(d['proxima'])}" if d.get("proxima") else "")
            if d.get("restante") is not None:
                plazo = (plazo + " · " if plazo else "") + f"quedan {d['restante']:.1f} {d['unidad']}"
            dirs.append({"numero": d["numero"], "tipo": d["tipo"], "titulo": d["titulo"],
                         "recurrente": "Sí" if d.get("recurrente") else "No", "estado_txt": d["estado_txt"],
                         "fecha": d.get("fecha_cumpl"), "firmado": d.get("firmado_por"), "licencia": d.get("licencia"),
                         "plazo": plazo or None, "nivel": d["nivel"], "_enlace": "/aeronavegabilidad"})
            kpis_dir += d["nivel"] != "ok"
        secciones.append(seccion(f"Directivas de aeronavegabilidad · {a.get('matricula') or a['nombre']}",
                                 [col("numero", "Número", ancho=14), col("tipo", "Tipo", ancho=6),
                                  col("titulo", "Título", ancho=34), col("recurrente", "Repetitiva", ancho=8),
                                  col("estado_txt", "Estado", ancho=11), col("fecha", "Cumplida el", "fecha"),
                                  col("firmado", "Certificó", ancho=16), col("licencia", "Licencia", ancho=11),
                                  col("plazo", "Próximo cumplimiento", ancho=22), col("nivel", "Situación", "estado")],
                                 dirs, vacio="Sin directivas registradas para este avión."))
        comps = []
        for c in core_alertas.componentes_con_estado(con, a["id"]):
            if c.get("sin_plazo"):
                continue
            limite = " · ".join(x for x in (
                f"{c['vida_util_horas']:.0f} {c['unidad']}" if c.get("vida_util_horas") else None,
                f"{c['limite_ciclos']:.0f} {c['unidad_ciclos']}" if c.get("limite_ciclos") else None,
                f"{c['vida_util_meses']:.0f} meses" if c.get("vida_util_meses") else None) if x)
            comps.append({"nombre": c["nombre"], "modulo": c.get("modulo"),
                          "clase": "Inspección" if c.get("tipo_item") == "inspeccion" else "Componente",
                          "serial": c.get("serial"), "contador": c["contador_txt"], "uso": c["horas_uso"],
                          "ciclos": c["ciclos_uso"] if c.get("limite_ciclos") else None,
                          "meses": c.get("meses_en_servicio"), "limite": limite or None, "restante": c["plazo_txt"],
                          "pct": c["pct"], "nivel": c["nivel"], "_enlace": f"/flota/{a['id']}"})
            kpis_comp += c["nivel"] in ("vencido", "critico")
        comps.sort(key=lambda x: -x["pct"])
        secciones.append(seccion(f"Componentes de vida limitada e inspecciones · {a.get('matricula') or a['nombre']}",
                                 [col("nombre", "Componente / inspección", ancho=28), col("clase", "Clase", ancho=11),
                                  col("serial", "Serial", ancho=12), col("contador", "Contador", ancho=10),
                                  col("uso", "Tiempo en servicio", "numero", 1), col("ciclos", "Ciclos", "entero"),
                                  col("meses", "Meses en servicio", "numero", 1), col("limite", "Límite", ancho=18),
                                  col("restante", "Restante", ancho=20), col("pct", "Consumido", "pct", 0),
                                  col("nivel", "Situación", "estado")],
                                 comps, vacio="El catálogo del avión no tiene componentes con vida limitada."))
    horas = sum(f["hobbs"] or 0 for s in secciones[::3] for f in s["filas"])
    return {
        "subtitulo": "Datos de soporte para el formulario FIAA que se presenta cada 12 meses a la Aerocivil (RAC 91.1136).",
        "kpis": [kpi("Aviones", len(aviones), "entero", nota="Aviones en servicio."),
                 kpi("Horas del período", horas, "horas", 1, "h",
                     nota="Σ Hobbs final − inicial (o las horas de vuelo si no se anotó el Hobbs)."),
                 kpi("Directivas por atender", kpis_dir, "entero", estado="critico" if kpis_dir else "ok",
                     nota="Directivas pendientes o repetitivas vencidas o próximas a vencer."),
                 kpi("Componentes críticos o vencidos", kpis_comp, "entero", estado="vencido" if kpis_comp else "ok",
                     nota="Componentes o inspecciones en aviso crítico o vencidos.")],
        "avisos": [] if aviones else [{"nivel": "info", "texto": "No hay aviones en la flota con estos filtros."}],
        "secciones": secciones,
        "firmas": ["Director de mantenimiento / inspector autorizado (licencia)", "Explotador (representante legal)"],
    }


@informe("rac_registro_mant", "Registro de mantenimiento del avión", "rac",
         "Cada trabajo de mantenimiento con su alcance, horas y ciclos totales del avión, referencia, fecha, "
         "quién lo hizo y quién lo certificó con su número de licencia.",
         filtros=("periodo", "equipo"), tipo_fijo="avion", periodo="365d", norma="RAC 91.1125 · 43.305",
         conservar="Hasta reemplazar el trabajo o 1 año; los de vida limitada, permanentes", destacado=True,
         palabras="mantenimiento ccm certificacion licencia firma registro avion",
         para='Lo firma el técnico certificador y lo audita la Aerocivil; respalda cada certificación de conformidad (CCM).',
         exige='Por cada trabajo: descripción y alcance, horas y ciclos totales, datos de referencia, fechas, quién lo hizo y quién lo certificó con su número de licencia.')
def _rac_registro_mant(con, p):
    aviones = _equipos(con, p, "avion")
    ids = [a["id"] for a in aviones]
    lect = core_flota.lecturas(con, ids) if ids else {}
    secciones, incompletos, faltas, total = [], 0, {}, 0
    for a in aviones:
        l = lect.get(a["id"], {})
        # Hobbs y aterrizajes acumulados a cada fecha: lectura actual menos lo volado después.
        despues = _filas(con, """SELECT fecha, SUM(COALESCE(hobbs_fin - hobbs_ini, horas_vuelo, 0)) h,
                                        SUM(COALESCE(aterrizajes, 0)) at FROM operaciones WHERE equipo_id=?
                                 GROUP BY fecha ORDER BY fecha""", (a["id"],))

        def acumulado(fecha, campo, actual):
            return round(actual - sum((x[campo] or 0) for x in despues if x["fecha"] > fecha), 1)

        filas = []
        for m in reversed(core_db.bitacora(con, a["id"], p.desde, p.hasta, limite=10 ** 6)):
            ref = " · ".join(x for x in (m.get("codigo_pieza"), m.get("orden_codigo")) if x) or None
            f = {"fecha": m["fecha"], "tarea": (m.get("tipo") or "").capitalize() + (" · daño" if m["motivo"] == "daño" else ""),
                 "descripcion": " · ".join(x for x in (m.get("pieza"), m.get("descripcion")) if x) or None,
                 "referencia": ref,
                 "horas": _r(m.get("horas_al_momento"), 1) if m.get("horas_al_momento") else acumulado(m["fecha"], "h", l.get("hobbs", 0)),
                 "ciclos": acumulado(m["fecha"], "at", l.get("aterrizajes", 0)),
                 "horas_pieza": _r(m.get("horas_pieza"), 1), "realizado": m.get("realizado_por"),
                 "certifico": m.get("firmado_por"), "licencia": m.get("licencia_firma"), "_enlace": "/bitacora"}
            falta = [n for k, n in (("descripcion", "descripción"), ("realizado", "quién lo hizo"),
                                    ("certifico", "certificador"), ("licencia", "licencia del certificador")) if not f[k]]
            if falta:
                incompletos += 1
                f["_incompleto"] = [k for k in ("descripcion", "realizado", "certifico", "licencia") if not f[k]]
                for n in falta:
                    faltas[n] = faltas.get(n, 0) + 1
            filas.append(f)
        total += len(filas)
        secciones.append(seccion(
            f"Registro de mantenimiento · {a.get('matricula') or a['nombre']}",
            [col("fecha", "Fecha", "fecha"), col("tarea", "Tarea", ancho=14),
             col("descripcion", "Descripción y alcance del trabajo", ancho=38), col("referencia", "Referencia", ancho=16),
             col("horas", "Horas totales", "horas", 1), col("ciclos", "Ciclos totales", "entero"),
             col("horas_pieza", "Horas de la pieza", "horas", 1), col("realizado", "Realizó", ancho=16),
             col("certifico", "Certificó", ancho=16), col("licencia", "Licencia N.º", ancho=12)],
            filas,
            encabezado=[("Matrícula", a.get("matricula") or a["nombre"]), ("Aeronave", f"{_fabricante(con, a)} {a['modelo']}".strip()),
                        ("N.º de serie", a.get("numero_serie") or "—"), ("Hobbs actual", f"{l.get('hobbs', 0):.1f} h"),
                        ("Tach actual", f"{l.get('tach', 0):.1f} h"), ("Aterrizajes", f"{l.get('aterrizajes', 0):.0f}")],
            vacio="Sin trabajos de mantenimiento registrados en el período."))
    return {
        "subtitulo": "Registros de mantenimiento y de conformidad (RAC 91.1125 y 43.305). Horas y ciclos totales a la "
                     "fecha del trabajo.",
        "kpis": [kpi("Trabajos registrados", total, "entero", nota="Intervenciones de la bitácora en el período."),
                 kpi("Aviones", len(aviones), "entero", nota="Aviones en servicio."),
                 kpi("Registros incompletos", incompletos, "entero", estado="proximo" if incompletos else "ok",
                     nota="Trabajos sin descripción, sin quién lo hizo o sin certificador y su licencia.")],
        "avisos": _incompletos_aviso(incompletos, total, _faltan_txt(faltas), "/ordenes-trabajo"),
        "secciones": secciones,
        "firmas": ["Técnico certificador (nombre y licencia)", "Director de mantenimiento"],
    }


# ======================================================================
# OPERACIÓN
# ======================================================================

@informe("resumen_gerencial", "Resumen gerencial del período", "operacion",
         "La foto completa en una página: operación, disponibilidad de la flota, costos y alertas abiertas, "
         "comparada con el período anterior.",
         filtros=("periodo", "tipo", "equipo"), roles=SIN_PILOTO, periodo="mes", destacado=True,
         palabras="gerencia junta ejecutivo kpi indicadores mensual",
         para='Para la reunión de gerencia o la junta: cómo va la operación, la flota y los costos en una sola hoja.')
def _resumen_gerencial(con, p):
    f = p.filtros()
    claves = ["operaciones", "hectareas", "horas", "rendimiento", "cumplimiento", "disponibilidad", "aptos",
              "mttr", "costo_mant", "costo_mant_hora", "costo_ha"]
    if p.es_admin:
        claves += ["ingreso_ha", "margen"]
    ind = core_ind.calcular(con, claves, f)
    kpis = [k for k in (_kpi_ind(ind, c) for c in claves) if k]
    alertas = core_alertas.alertas_todas(con, p.tipo, p.equipo_id)
    conteo = {n: sum(1 for a in alertas if a["nivel"] == n) for n in ("vencido", "critico", "proximo")}
    kpis.append(kpi("Alertas abiertas", len(alertas), "entero",
                    estado="vencido" if conteo["vencido"] else "critico" if conteo["critico"] else "ok",
                    nota=f"{conteo['vencido']} vencidas · {conteo['critico']} críticas · {conteo['proximo']} próximas"))
    w, prm = p.where()
    por_mes = _filas(con, f"""SELECT substr(o.fecha,1,7) mes, COUNT(*) operaciones,
            ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas, ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas,
            ROUND(COALESCE(SUM(o.litros),0),0) litros
        FROM operaciones o WHERE {w} GROUP BY substr(o.fecha,1,7) ORDER BY 1""", prm)
    for m in por_mes:
        m["rendimiento"] = _r(_div(m["hectareas"], m["horas"]), 1)
    wm, pm = p.where("m", operaciones=False)
    costos_mes = {r["mes"]: r["costo"] for r in _filas(con, f"""SELECT substr(m.fecha,1,7) mes,
            COALESCE(SUM(COALESCE(m.costo, COALESCE(m.costo_repuesto,0)+COALESCE(m.costo_mano_obra,0))),0) costo
        FROM mantenimientos m WHERE {wm} GROUP BY substr(m.fecha,1,7)""", pm)}
    for m in por_mes:
        m["costo_mant"] = round(costos_mes.get(m["mes"], 0) or 0)
    activos = core_ind.por_activo(con, ["operaciones", "horas", "hectareas", "rendimiento", "disponibilidad",
                                        "costo_mant"], replace(f, equipo_id=None))
    estados = core_alertas.estado_flota(con)
    filas_act = []
    for a in activos:
        if p.equipo_id and a["id"] != p.equipo_id:
            continue
        i = a["indicadores"]
        est = estados.get(a["id"], {})
        filas_act.append({"equipo": a["nombre"], "tipo": core_flota.TIPOS_ACTIVO.get(a["tipo_activo"]),
                          "modelo": a["modelo"],
                          **{k: (i.get(k) or {}).get("valor") for k in ("operaciones", "horas", "hectareas",
                                                                        "rendimiento", "disponibilidad", "costo_mant")},
                          "estado": est.get("estado", "apto"), "motivos": "; ".join(est.get("motivos", [])[:3]) or None,
                          "_enlace": f"/flota/{a['id']}"})
    etq, series = _serie_mes(por_mes, series=(("hectareas", "Hectáreas", "ha"), ("horas", "Horas", "h")))
    series[1]["eje"] = "derecha"
    return {
        "subtitulo": "Operación, disponibilidad, costos y alertas del período; la flecha compara con el período "
                     "anterior de la misma duración.",
        "kpis": kpis,
        "graficas": [grafica("linea", "Hectáreas y horas por mes", etq, series, seccion=0, campo="mes"),
                     grafica("ranking", "Horas por activo", [x["equipo"] for x in filas_act],
                             [{"nombre": "Horas", "datos": [x["horas"] or 0 for x in filas_act]}], seccion=1,
                             campo="equipo", unidad="h")],
        "secciones": [
            seccion("Operación por mes",
                    [col("mes", "Mes", ancho=9), col("operaciones", "Operaciones", "entero", total=True),
                     col("horas", "Horas", "horas", 1, total=True), col("hectareas", "Hectáreas", "numero", 1, total=True),
                     col("litros", "Litros", "numero", 0, total=True), col("rendimiento", "ha/h", "numero", 1)]
                    + ([col("costo_mant", "Costo mantenimiento", "dinero", total=True)]),
                    por_mes),
            seccion("Activos",
                    [col("equipo", "Activo", ancho=14), col("tipo", "Tipo", ancho=7), col("modelo", "Modelo", ancho=10),
                     col("operaciones", "Op.", "entero", total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("hectareas", "Hectáreas", "numero", 0, total=True), col("rendimiento", "ha/h", "numero", 1),
                     col("disponibilidad", "Disponibilidad", "pct", 1), col("costo_mant", "Costo mant.", "dinero", total=True),
                     col("estado", "Estado hoy", "estado"), col("motivos", "Motivos", ancho=30)],
                    filas_act),
            seccion("Alertas abiertas",
                    [col("equipo", "Activo", ancho=14), col("fuente", "Origen", ancho=10), col("nombre", "Qué", ancho=34),
                     col("plazo_txt", "Plazo", ancho=22), col("nivel", "Nivel", "estado")],
                    [{**a, "fuente": a["fuente"].capitalize(), "_enlace": "/aeronavegabilidad"} for a in alertas[:200]]),
        ],
    }


@informe("operaciones_cliente", "Operaciones por cliente, finca y lote", "operacion",
         "Cuánto se aplicó a cada cliente y en cada finca, con el detalle de cada jornada: producto, dosis, "
         "hectáreas y fecha.",
         filtros=("periodo", "tipo", "equipo", "cliente", "piloto"), periodo="90d",
         palabras="cliente finca lote hacienda aplicacion producto dosis",
         para='Para facturar y rendir cuentas a cada cliente: qué se aplicó, dónde y cuándo.')
def _operaciones_cliente(con, p):
    ops = _operaciones(con, p, "o.fecha DESC, o.id DESC")
    grupos = {}
    for o in ops:
        k = (o.get("cliente") or "Sin cliente", o.get("lote") or "Sin finca")
        g = grupos.setdefault(k, {"cliente": k[0], "finca": k[1], "zona": o.get("zona"), "operaciones": 0,
                                  "horas": 0, "hectareas": 0, "litros": 0, "productos": set(),
                                  "primera": o["fecha"], "ultima": o["fecha"]})
        g["operaciones"] += 1
        g["horas"] += o.get("horas_vuelo") or 0
        g["hectareas"] += o.get("hectareas") or 0
        g["litros"] += o.get("litros") or 0
        g["primera"], g["ultima"] = min(g["primera"], o["fecha"]), max(g["ultima"], o["fecha"])
        if o.get("producto"):
            g["productos"].add(o["producto"])
    resumen = []
    for g in sorted(grupos.values(), key=lambda x: -x["hectareas"]):
        g.update(horas=round(g["horas"], 1), hectareas=round(g["hectareas"], 1), litros=round(g["litros"]),
                 productos=", ".join(sorted(g["productos"])) or None, dosis=_r(_div(g["litros"], g["hectareas"]), 1))
        resumen.append(g)
    por_cliente = {}
    for g in resumen:
        por_cliente[g["cliente"]] = por_cliente.get(g["cliente"], 0) + g["hectareas"]
    top = sorted(por_cliente.items(), key=lambda x: -x[1])[:12]
    detalle = [{"fecha": o["fecha"], "cliente": o.get("cliente"), "finca": o.get("lote"), "zona": o.get("zona"),
                "producto": o.get("producto"), "hectareas": _r(o.get("hectareas"), 2), "litros": _r(o.get("litros"), 0),
                "dosis": _r(_div(o.get("litros"), o.get("hectareas")), 1), "dosis_objetivo": o.get("dosis_objetivo"),
                "horas": _r(o.get("horas_vuelo"), 2), "piloto": o.get("piloto"), "equipo": o["equipo"],
                "_enlace": "/operaciones"} for o in ops]
    ha = sum(g["hectareas"] for g in resumen)
    litros = sum(g["litros"] for g in resumen)
    return {
        "kpis": [kpi("Clientes", len(por_cliente), "entero", nota="Clientes distintos con operaciones."),
                 kpi("Fincas / lotes", len(resumen), "entero", nota="Combinaciones distintas de cliente y finca."),
                 kpi("Hectáreas", ha, "numero", 1, "ha", nota="Σ hectáreas aplicadas."),
                 kpi("Litros aplicados", litros, "numero", 0, "L", nota="Σ litros de mezcla."),
                 kpi("Dosis media", _r(_div(litros, ha), 1), "numero", 1, "L/ha", nota="Σ litros ÷ Σ hectáreas.")],
        "graficas": [grafica("ranking", "Hectáreas por cliente", [t[0] for t in top],
                             [{"nombre": "Hectáreas", "datos": [round(t[1], 1) for t in top]}], seccion=0,
                             campo="cliente", unidad="ha")],
        "secciones": [
            seccion("Por cliente y finca",
                    [col("cliente", "Cliente", ancho=20), col("finca", "Finca / lote", ancho=20), col("zona", "Zona", ancho=14),
                     col("operaciones", "Jornadas", "entero", total=True), col("hectareas", "Hectáreas", "numero", 1, total=True),
                     col("litros", "Litros", "numero", 0, total=True), col("dosis", "Dosis (L/ha)", "numero", 1),
                     col("horas", "Horas", "horas", 1, total=True), col("primera", "Primera", "fecha"),
                     col("ultima", "Última", "fecha"), col("productos", "Productos", ancho=30)], resumen),
            seccion("Detalle de aplicaciones",
                    [col("fecha", "Fecha", "fecha"), col("cliente", "Cliente", ancho=18), col("finca", "Finca / lote", ancho=18),
                     col("producto", "Producto", ancho=20), col("hectareas", "Hectáreas", "numero", 2, total=True),
                     col("litros", "Litros", "numero", 0, total=True), col("dosis", "Dosis (L/ha)", "numero", 1),
                     col("dosis_objetivo", "Dosis objetivo", "numero", 1), col("horas", "Horas", "horas", 2, total=True),
                     col("piloto", "Piloto", ancho=18), col("equipo", "Activo", ancho=12)], detalle),
        ],
    }


@informe("productividad_activo", "Horas y productividad por activo", "operacion",
         "Horas de vuelo, hectáreas, rendimiento por hora y por día, minutos por salida y aprovechamiento de la "
         "jornada de cada dron y avión.",
         filtros=("periodo", "tipo", "equipo"), periodo="90d", palabras="rendimiento ha/h eficiencia dron avion horas",
         para='Para el jefe de operaciones: qué activo rinde más y dónde se pierde tiempo.')
def _productividad_activo(con, p):
    claves = ["operaciones", "horas", "hectareas", "rendimiento", "ha_dia", "horas_dia", "min_salida",
              "ha_vuelo", "litros_hora", "aprovechamiento"]
    activos = core_ind.por_activo(con, claves, replace(p.filtros(), equipo_id=None))
    filas = []
    for a in activos:
        if p.equipo_id and a["id"] != p.equipo_id:
            continue
        i = a["indicadores"]
        filas.append({"equipo": a["nombre"], "tipo": core_flota.TIPOS_ACTIVO.get(a["tipo_activo"]), "modelo": a["modelo"],
                      **{k: (i.get(k) or {}).get("valor") for k in claves}, "_enlace": f"/flota/{a['id']}"})
    w, prm = p.where()
    por_mes = _filas(con, f"""SELECT substr(o.fecha,1,7) mes, e.nombre equipo, COUNT(*) operaciones,
            ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas, ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas
        FROM operaciones o JOIN equipos e ON e.id=o.equipo_id WHERE {w}
        GROUP BY substr(o.fecha,1,7), e.nombre ORDER BY 1, 2""", prm)
    for m in por_mes:
        m["rendimiento"] = _r(_div(m["hectareas"], m["horas"]), 1)
    tot = core_ind.calcular(con, ["horas", "hectareas", "rendimiento", "ha_dia", "min_salida"], p.filtros())
    return {
        "kpis": [k for k in (_kpi_ind(tot, c) for c in ("horas", "hectareas", "rendimiento", "ha_dia", "min_salida")) if k],
        "graficas": [grafica("barras", "Horas y hectáreas por activo", [f["equipo"] for f in filas],
                             [{"nombre": "Horas", "datos": [f["horas"] or 0 for f in filas], "unidad": "h"},
                              {"nombre": "Hectáreas", "datos": [f["hectareas"] or 0 for f in filas], "unidad": "ha"}],
                             seccion=0, campo="equipo")],
        "secciones": [
            seccion("Productividad por activo",
                    [col("equipo", "Activo", ancho=14), col("tipo", "Tipo", ancho=7), col("modelo", "Modelo", ancho=10),
                     col("operaciones", "Jornadas", "entero", total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("hectareas", "Hectáreas", "numero", 0, total=True), col("rendimiento", "ha/h", "numero", 1),
                     col("ha_dia", "ha/día", "numero", 1), col("horas_dia", "h/día", "numero", 1),
                     col("min_salida", "min/salida", "numero", 1), col("ha_vuelo", "ha/vuelo", "numero", 1),
                     col("litros_hora", "L/h", "numero", 0), col("aprovechamiento", "Aprovechamiento", "pct", 0)], filas),
            seccion("Por mes y activo",
                    [col("mes", "Mes", ancho=9), col("equipo", "Activo", ancho=14),
                     col("operaciones", "Jornadas", "entero", total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("hectareas", "Hectáreas", "numero", 1, total=True), col("rendimiento", "ha/h", "numero", 1)],
                    por_mes),
        ],
    }


# ======================================================================
# PERSONAL
# ======================================================================

@informe("productividad_piloto", "Horas y productividad por piloto", "personal",
         "Jornadas, horas, hectáreas y rendimiento de cada piloto, con las operaciones fuera de la ventana "
         "de aplicación (viento, temperatura o humedad).",
         filtros=("periodo", "tipo", "equipo", "piloto"), periodo="90d", palabras="piloto carga rendimiento horas",
         para='Para planear la carga de los pilotos y detectar jornadas fuera de la ventana de aplicación.')
def _productividad_piloto(con, p):
    w, prm = p.where()
    viento = core_ind._meta_num(con, "ventana_viento_max", 15)
    temp = core_ind._meta_num(con, "ventana_temp_max", 32)
    hum = core_ind._meta_num(con, "ventana_humedad_min", 50)
    filas = _filas(con, f"""SELECT COALESCE(o.piloto,'Sin piloto') piloto, COUNT(*) operaciones,
            COUNT(DISTINCT o.fecha) dias, COUNT(DISTINCT o.equipo_id) activos,
            ROUND(COALESCE(SUM(o.horas_vuelo),0),1) horas, ROUND(COALESCE(SUM(o.hectareas),0),1) hectareas,
            ROUND(COALESCE(SUM(o.litros),0),0) litros, MAX(o.fecha) ultima,
            SUM(CASE WHEN o.viento > ? OR o.temperatura > ? OR o.humedad < ? THEN 1 ELSE 0 END) fuera_ventana
        FROM operaciones o WHERE {w} GROUP BY COALESCE(o.piloto,'Sin piloto') ORDER BY horas DESC""",
                       [viento, temp, hum] + prm)
    limite = core_ind._meta_num(con, "horas_max_piloto_dia", 8)
    excesos = _filas(con, f"""SELECT o.piloto, o.fecha, ROUND(SUM(o.horas_vuelo),1) horas FROM operaciones o
        WHERE {w} AND o.piloto IS NOT NULL GROUP BY o.piloto, o.fecha HAVING SUM(o.horas_vuelo) > ?
        ORDER BY o.fecha DESC""", prm + [limite])
    for f in filas:
        f["rendimiento"] = _r(_div(f["hectareas"], f["horas"]), 1)
        f["horas_dia"] = _r(_div(f["horas"], f["dias"]), 1)
        f["dias_exceso"] = sum(1 for x in excesos if x["piloto"] == f["piloto"])
        f["_enlace"] = "/contactos"
    return {
        "kpis": [kpi("Pilotos", len(filas), "entero", nota="Pilotos con operaciones en el período."),
                 kpi("Horas", sum(f["horas"] for f in filas), "horas", 1, "h", nota="Σ horas de vuelo."),
                 kpi("Hectáreas", sum(f["hectareas"] for f in filas), "numero", 0, "ha", nota="Σ hectáreas aplicadas."),
                 kpi("Operaciones fuera de ventana", sum(f["fuera_ventana"] or 0 for f in filas), "entero",
                     estado="proximo" if any(f["fuera_ventana"] for f in filas) else "ok",
                     nota=f"viento > {viento:g} km/h, temperatura > {temp:g} °C o humedad < {hum:g} %"),
                 kpi(f"Días con más de {limite:g} h", len(excesos), "entero", estado="critico" if excesos else "ok",
                     nota="Días en que un piloto superó las horas máximas por día de la configuración de costos.")],
        "graficas": [grafica("ranking", "Horas por piloto", [f["piloto"] for f in filas],
                             [{"nombre": "Horas", "datos": [f["horas"] for f in filas]}], seccion=0, campo="piloto",
                             unidad="h")],
        "secciones": [
            seccion("Por piloto",
                    [col("piloto", "Piloto", ancho=22), col("operaciones", "Jornadas", "entero", total=True),
                     col("dias", "Días", "entero", total=True), col("activos", "Activos", "entero"),
                     col("horas", "Horas", "horas", 1, total=True), col("hectareas", "Hectáreas", "numero", 0, total=True),
                     col("rendimiento", "ha/h", "numero", 1), col("horas_dia", "h/día", "numero", 1),
                     col("fuera_ventana", "Fuera de ventana", "entero", total=True),
                     col("dias_exceso", f"Días > {limite:g} h", "entero", total=True), col("ultima", "Última", "fecha")], filas),
            seccion(f"Días con más de {limite:g} horas de vuelo",
                    [col("fecha", "Fecha", "fecha"), col("piloto", "Piloto", ancho=22), col("horas", "Horas", "horas", 1)],
                    excesos, vacio="Ningún piloto superó el límite diario en el período."),
        ],
    }


@informe("personal_licencias", "Personal, licencias y documentos", "personal",
         "Directorio del personal operativo con su licencia, el vencimiento de licencias, certificados médicos, "
         "colinesterasa e idoneidad UAS.",
         filtros=(), roles=SIN_PILOTO, periodo=None, palabras="licencia medico colinesterasa idoneidad vencimiento personal",
         para='Para recursos humanos y el jefe de pilotos: quién puede volar hoy y qué hay que renovar.')
def _personal_licencias(con, p):
    lista = [c for c in core_db.contactos(con, incluir_inactivos=False) if c["operativo"] or c["rol"] == "operario"]
    docs = {}
    for d in core_flota.documentos_con_estado(con):
        if d.get("personal_id"):
            docs.setdefault(d["personal_id"], []).append(d)
    hoy = date.today()
    filas, doc_filas = [], []
    for c in lista:
        ds = docs.get(c["id"], [])
        niveles = [d["nivel"] for d in ds]
        lic_nivel = "ok"
        if c.get("licencia_vence"):
            try:
                dias = (date.fromisoformat(c["licencia_vence"][:10]) - hoy).days
                lic_nivel = "vencido" if dias < 0 else "critico" if dias <= 15 else "proximo" if dias <= 30 else "ok"
            except ValueError:
                pass
        niveles.append(lic_nivel)
        peor = min(niveles, key=lambda n: ["vencido", "critico", "proximo", "ok"].index(n))
        filas.append({"nombre": c["nombre"], "rol": c["rol_txt"], "cargo": c.get("cargo"),
                      "licencia": c.get("licencia"), "licencia_vence": c.get("licencia_vence"),
                      "horas": c.get("horas_vuelo"), "documentos": len(ds), "estado": peor,
                      "telefono": c.get("telefono"), "email": c.get("email"), "_enlace": "/contactos"})
        for d in ds:
            doc_filas.append({"nombre": c["nombre"], "tipo": d["tipo_txt"], "numero": d.get("numero"),
                              "emitido": d.get("emitido"), "vence": d.get("vence"), "dias": d.get("dias_restantes"),
                              "nivel": d["nivel"], "_enlace": "/contactos"})
    doc_filas.sort(key=lambda d: (d["dias"] if d["dias"] is not None else 10 ** 6))
    malos = sum(1 for f in filas if f["estado"] in ("vencido", "critico"))
    return {
        "kpis": [kpi("Personas operativas", len(filas), "entero", nota="Pilotos, técnicos y operarios activos en Contactos."),
                 kpi("Documentos registrados", len(doc_filas), "entero", nota="Licencias, certificados y exámenes cargados."),
                 kpi("Con algo vencido o por vencer", malos, "entero", estado="critico" if malos else "ok",
                     nota="Personas con una licencia o documento vencido o que vence en 15 días.")],
        "secciones": [
            seccion("Personal operativo",
                    [col("nombre", "Nombre", ancho=22), col("rol", "Rol", ancho=16), col("cargo", "Cargo", ancho=16),
                     col("licencia", "Licencia", ancho=13), col("licencia_vence", "Licencia vence", "fecha"),
                     col("horas", "Horas de vuelo", "horas", 1, total=True), col("documentos", "Documentos", "entero"),
                     col("estado", "Situación", "estado"), col("telefono", "Teléfono", ancho=13),
                     col("email", "Correo", ancho=22)], filas),
            seccion("Documentos del personal",
                    [col("nombre", "Persona", ancho=22), col("tipo", "Documento", ancho=30), col("numero", "Número", ancho=14),
                     col("emitido", "Emitido", "fecha"), col("vence", "Vence", "fecha"), col("dias", "Días restantes", "entero"),
                     col("nivel", "Situación", "estado")], doc_filas),
        ],
    }


# ======================================================================
# MANTENIMIENTO Y AERONAVEGABILIDAD
# ======================================================================

@informe("estado_mantenimiento", "Estado de mantenimiento y vencimientos", "mantenimiento",
         "Aeronavegabilidad de cada activo hoy, lo vencido o por vencer (piezas, inspecciones, directivas y "
         "documentos) y la proyección de los próximos cambios según el ritmo de vuelo.",
         filtros=("tipo", "equipo"), periodo=None, destacado=True,
         palabras="vencimiento pieza repuesto inspeccion alerta proyeccion aeronavegabilidad",
         para='Para el jefe de mantenimiento: qué hay que cambiar o inspeccionar y cuándo, antes de que pare un activo.')
def _estado_mantenimiento(con, p):
    equipos = _equipos(con, p)
    estados = core_alertas.estado_flota(con, [{"id": e["id"], "estado": e["estado"]} for e in equipos])
    lect = core_flota.lecturas(con, [e["id"] for e in equipos]) if equipos else {}
    flota = []
    for e in equipos:
        est = estados.get(e["id"], {"estado": "apto", "motivos": []})
        l = lect.get(e["id"], {})
        contador = (f"Hobbs {l.get('hobbs', 0):.1f} · Tach {l.get('tach', 0):.1f}" if e["tipo_activo"] == "avion"
                    else f"{l.get('horas_vuelo', e.get('horas_totales') or 0):.1f} h")
        flota.append({"equipo": e["nombre"], "tipo": core_flota.TIPOS_ACTIVO.get(e["tipo_activo"]), "modelo": e["modelo"],
                      "matricula": e.get("matricula"), "contadores": contador, "estado": est["estado"],
                      "motivos": "; ".join(est.get("motivos", [])[:4]) or None, "_enlace": f"/flota/{e['id']}"})
    alertas = core_alertas.alertas_todas(con, p.tipo, p.equipo_id)
    venc = [{"equipo": a["equipo"], "fuente": {"pieza": "Pieza", "inspeccion": "Inspección", "directiva": "Directiva",
                                                "documento": "Documento"}.get(a["fuente"], a["fuente"]),
             "nombre": a["nombre"], "modulo": a.get("modulo"), "pct": a.get("pct"), "plazo_txt": a["plazo_txt"],
             "nivel": a["nivel"], "_enlace": "/aeronavegabilidad" if a["fuente"] in ("directiva", "documento")
             else (f"/flota/{a['equipo_id']}" if a.get("equipo_id") else "/mantenimiento")} for a in alertas]
    proy = []
    for r in core_proyeccion.proximos_repuestos(con, p.equipo_id, limite=10 ** 6):
        if p.tipo and r["tipo_activo"] != p.tipo:
            continue
        if r["nivel"] == "ok" and (r["dias_estimados"] is None or r["dias_estimados"] > 120):
            continue
        proy.append({"equipo": r["equipo"], "nombre": r["nombre"], "modulo": r["modulo"], "uso": r["horas_uso"],
                     "unidad": r["unidad"], "plazo_txt": r["plazo_txt"], "dias": r["dias_estimados"],
                     "fecha": r["fecha_estimada"], "ritmo": r["h_dia"], "precio": r.get("precio"), "nivel": r["nivel"],
                     "_enlace": f"/flota/{r['equipo_id']}"})
    conteo_est = {k: sum(1 for f in flota if f["estado"] == k) for k in ("apto", "observaciones", "no_apto")}
    conteo = {n: sum(1 for a in venc if a["nivel"] == n) for n in ("vencido", "critico", "proximo")}
    nombres = [f["equipo"] for f in flota]
    serie = {n: [sum(1 for a in venc if a["equipo"] == eq and a["nivel"] == n) for eq in nombres]
             for n in ("vencido", "critico", "proximo")}
    avisos = core_alertas.texto_avisos(core_alertas.config_avisos(con))
    return {
        "subtitulo": "Situación de hoy. Un activo «no recomendado volar» tiene algo vencido, un incidente sin "
                     "inspeccionar o está en taller.",
        "kpis": [kpi("Aptos", conteo_est["apto"], "entero", estado="ok",
                     nota="Activos sin nada vencido ni crítico."),
                 kpi("Con observaciones", conteo_est["observaciones"], "entero",
                     estado="proximo" if conteo_est["observaciones"] else "ok",
                     nota="Algo en aviso crítico o una directiva o documento por vencer."),
                 kpi("No recomendado volar", conteo_est["no_apto"], "entero",
                     estado="vencido" if conteo_est["no_apto"] else "ok",
                     nota="Pieza, inspección, directiva o documento vencido, o el activo en taller."),
                 kpi("Vencidos", conteo["vencido"], "entero", estado="vencido" if conteo["vencido"] else "ok",
                     nota="Ítems que ya pasaron su límite de horas, ciclos o calendario."),
                 kpi("Críticos", conteo["critico"], "entero", estado="critico" if conteo["critico"] else "ok",
                     nota=f"Ítems a punto de vencer: {avisos['critico']}."),
                 kpi("Próximos", conteo["proximo"], "entero", estado="proximo" if conteo["proximo"] else "ok",
                     nota=f"Ítems por vencer: {avisos['proximo']}."),
                 kpi("Cambios en 120 días", len(proy), "entero",
                     nota="Piezas e inspecciones que caen en los próximos 120 días al ritmo de vuelo actual.")],
        "graficas": [grafica("barras", "Vencimientos por activo", nombres,
                             [{"nombre": "Vencidos", "datos": serie["vencido"], "nivel": "vencido"},
                              {"nombre": "Críticos", "datos": serie["critico"], "nivel": "critico"},
                              {"nombre": "Próximos", "datos": serie["proximo"], "nivel": "proximo"}],
                             seccion=1, campo="equipo")],
        "secciones": [
            seccion("Estado de la flota",
                    [col("equipo", "Activo", ancho=14), col("tipo", "Tipo", ancho=7), col("modelo", "Modelo", ancho=11),
                     col("matricula", "Matrícula", ancho=10), col("contadores", "Contadores", ancho=22),
                     col("estado", "Estado", "estado"), col("motivos", "Motivos", ancho=40)], flota),
            seccion("Vencido y por vencer",
                    [col("equipo", "Activo", ancho=14), col("fuente", "Origen", ancho=10), col("nombre", "Qué", ancho=36),
                     col("modulo", "Módulo", ancho=16), col("pct", "Consumido", "pct", 0), col("plazo_txt", "Plazo", ancho=24),
                     col("nivel", "Nivel", "estado")], venc, vacio="Nada vencido ni por vencer. La flota está al día."),
            seccion("Próximos cambios (120 días)",
                    [col("equipo", "Activo", ancho=14), col("nombre", "Pieza / inspección", ancho=30),
                     col("modulo", "Módulo", ancho=16), col("uso", "Uso", "numero", 1), col("unidad", "Unidad", ancho=7),
                     col("plazo_txt", "Plazo", ancho=22), col("dias", "Días estimados", "entero"),
                     col("fecha", "Fecha estimada", "fecha"), col("ritmo", "Ritmo (u/día)", "numero", 2),
                     col("nivel", "Nivel", "estado")], proy,
                    descripcion="La fecha estimada sale del ritmo de vuelo de los últimos 90 días de cada activo."),
        ],
    }


@informe("ordenes_costos", "Órdenes de trabajo y costos de mantenimiento", "mantenimiento",
         "Órdenes de trabajo del período con su avance y costo, y cada intervención de la bitácora con el "
         "repuesto y la mano de obra.",
         filtros=("periodo", "tipo", "equipo"), roles=SIN_PILOTO, periodo="90d",
         palabras="ot orden trabajo costo repuesto mano de obra mttr bitacora",
         para='Para controlar el presupuesto de mantenimiento y el avance de las órdenes de trabajo.')
def _ordenes_costos(con, p):
    equipos = {e["id"]: e for e in _equipos(con, replace(p, equipo_id=None))}
    costos_ot = {r["orden_id"]: r for r in _filas(con, """SELECT orden_id, COALESCE(SUM(costo_repuesto),0) rep,
            COALESCE(SUM(costo_mano_obra),0) mo, COALESCE(SUM(horas_mano_obra),0) hmo FROM ot_tareas GROUP BY orden_id""")}
    ots = []
    for o in core_ordenes.listar_ot(con, equipo_id=p.equipo_id):
        if o["equipo_id"] not in equipos:
            continue
        fecha = (o.get("cerrado_en") or "")[:10] or o.get("fecha_programada") or (o.get("creado") or "")[:10]
        if (p.desde and fecha < p.desde) or (p.hasta and fecha > p.hasta):
            continue
        c = costos_ot.get(o["id"], {})
        ots.append({"codigo": o["codigo"], "equipo": o["equipo"], "titulo": o["titulo"], "tipo": (o.get("tipo") or "").capitalize(),
                    "prioridad": (o.get("prioridad") or "").capitalize(), "estado_txt": o["estado_txt"],
                    "asignado": o.get("asignado_a"), "programada": o.get("fecha_programada"),
                    "cerrada": (o.get("cerrado_en") or "")[:10] or None,
                    "avance": f"{o['n_hechas']}/{o['n_tareas']}" if o["n_tareas"] else None,
                    "repuestos": _r(c.get("rep"), 0), "mano_obra": _r(c.get("mo"), 0),
                    "total": _r((c.get("rep") or 0) + (c.get("mo") or 0), 0), "_enlace": "/ordenes-trabajo"})
    mant = []
    for m in core_db.bitacora(con, p.equipo_id, p.desde, p.hasta, limite=10 ** 6):
        if m["equipo_id"] not in equipos:
            continue
        rep = m.get("costo_repuesto")
        mo = m.get("costo_mano_obra")
        total = m.get("costo") if m.get("costo") is not None else ((rep or 0) + (mo or 0) or None)
        mant.append({"fecha": m["fecha"], "equipo": m["equipo"], "tipo": (m.get("tipo") or "").capitalize(),
                     "motivo": m["motivo_txt"], "pieza": m.get("pieza"), "descripcion": m.get("descripcion"),
                     "orden": m.get("orden_codigo"), "realizado": m.get("realizado_por"),
                     "repuesto": _r(rep, 0), "mano_obra": _r(mo, 0), "total": _r(total, 0), "_enlace": "/bitacora"})
    por_mes = {}
    for m in mant:
        por_mes[m["fecha"][:7]] = por_mes.get(m["fecha"][:7], 0) + (m["total"] or 0)
    meses = sorted(por_mes)
    por_equipo = {}
    for m in mant:
        por_equipo[m["equipo"]] = por_equipo.get(m["equipo"], 0) + (m["total"] or 0)
    ind = core_ind.calcular(con, ["costo_mant", "costo_mant_hora", "mttr", "mtbf"], p.filtros())
    abiertas = sum(1 for o in ots if o["estado_txt"] not in ("Completada", "Cancelada"))
    return {
        "kpis": [kpi("Órdenes en el período", len(ots), "entero",
                     nota="Órdenes programadas, cerradas o creadas dentro del período."),
                 kpi("Abiertas", abiertas, "entero", estado="proximo" if abiertas else "ok",
                     nota="Órdenes que no están completadas ni canceladas."),
                 kpi("Intervenciones", len(mant), "entero", nota="Registros de la bitácora de reparaciones.")]
                + [k for k in (_kpi_ind(ind, c) for c in ("costo_mant", "costo_mant_hora", "mttr", "mtbf")) if k],
        "graficas": [grafica("barras", "Costo de mantenimiento por mes", meses,
                             [{"nombre": "Costo", "datos": [round(por_mes[m]) for m in meses], "unidad": "$"}],
                             seccion=1, campo="mes"),
                     grafica("ranking", "Costo por activo", list(por_equipo),
                             [{"nombre": "Costo", "datos": [round(v) for v in por_equipo.values()]}],
                             seccion=1, campo="equipo", unidad="$")],
        "secciones": [
            seccion("Órdenes de trabajo",
                    [col("codigo", "Orden", ancho=10), col("equipo", "Activo", ancho=12), col("titulo", "Título", ancho=30),
                     col("tipo", "Tipo", ancho=11), col("prioridad", "Prioridad", ancho=9), col("estado_txt", "Estado", ancho=11),
                     col("asignado", "Asignada a", ancho=18), col("programada", "Programada", "fecha"),
                     col("cerrada", "Cerrada", "fecha"), col("avance", "Tareas", ancho=7),
                     col("repuestos", "Repuestos", "dinero", total=True), col("mano_obra", "Mano de obra", "dinero", total=True),
                     col("total", "Total", "dinero", total=True)], ots),
            seccion("Intervenciones y costos (bitácora)",
                    [col("fecha", "Fecha", "fecha"), col("equipo", "Activo", ancho=12), col("tipo", "Tipo", ancho=11),
                     col("motivo", "Motivo", ancho=16), col("pieza", "Pieza", ancho=24), col("descripcion", "Descripción", ancho=30),
                     col("orden", "Orden", ancho=10), col("realizado", "Realizó", ancho=16),
                     col("repuesto", "Repuesto", "dinero", total=True), col("mano_obra", "Mano de obra", "dinero", total=True),
                     col("total", "Total", "dinero", total=True)], [dict(m, mes=m["fecha"][:7]) for m in mant]),
        ],
    }


@informe("directivas_documentos", "Directivas de aeronavegabilidad y documentos por vencer", "mantenimiento",
         "Estado de cada directiva (AD/SB) en cada avión y de los documentos de los activos y del personal, "
         "ordenados por urgencia.",
         filtros=("tipo", "equipo"), periodo=None, palabras="ad sb directiva documento seguro matricula vence",
         para='Para que ningún avión vuele con una directiva vencida ni un documento caducado.')
def _directivas_documentos(con, p):
    ids = {e["id"] for e in _equipos(con, p)}
    dirs = []
    for d in core_flota.directivas_con_estado(con, p.equipo_id):
        if d["equipo_id"] not in ids:
            continue
        plazo = (f"vence {_dmy(d['limite_fecha'])}" if d["estado"] == "pendiente" and d.get("limite_fecha") else
                 f"próxima {_dmy(d['proxima'])}" if d.get("proxima") else "")
        if d.get("restante") is not None:
            plazo = (plazo + " · " if plazo else "") + f"quedan {d['restante']:.1f} {d['unidad']}"
        dirs.append({"equipo": d["equipo"], "numero": d["numero"], "tipo": d["tipo"], "titulo": d["titulo"],
                     "estado_txt": d["estado_txt"], "fecha": d.get("fecha_cumpl"), "plazo": plazo or None,
                     "dias": d.get("dias_restantes"), "nivel": d["nivel"], "_enlace": "/aeronavegabilidad"})
    orden = {"vencido": 0, "critico": 1, "proximo": 2, "ok": 3}
    dirs.sort(key=lambda d: (orden[d["nivel"]], d["numero"]))
    docs = []
    for d in core_flota.documentos_con_estado(con, p.equipo_id, incluir_personal=not (p.equipo_id or p.tipo)):
        if d.get("equipo_id") and d["equipo_id"] not in ids:
            continue
        docs.append({"titular": d.get("equipo") or d.get("persona") or "Empresa", "tipo": d["tipo_txt"],
                     "numero": d.get("numero"), "emitido": d.get("emitido"), "vence": d.get("vence"),
                     "dias": d.get("dias_restantes"), "nivel": d["nivel"],
                     "_enlace": "/contactos" if d.get("personal_id") else "/aeronavegabilidad"})
    docs.sort(key=lambda d: (orden[d["nivel"]], d["dias"] if d["dias"] is not None else 10 ** 6))
    pend = sum(1 for d in dirs if d["nivel"] != "ok")
    dv = sum(1 for d in docs if d["nivel"] == "vencido")
    dp = sum(1 for d in docs if d["nivel"] in ("critico", "proximo"))
    return {
        "kpis": [kpi("Directivas registradas", len(dirs), "entero", nota="Una por directiva y avión al que aplica."),
                 kpi("Directivas por atender", pend, "entero", estado="critico" if pend else "ok",
                     nota="Pendientes con plazo cercano o vencido, o repetitivas próximas."),
                 kpi("Documentos vencidos", dv, "entero", estado="vencido" if dv else "ok",
                     nota="Documentos cuya fecha de vencimiento ya pasó."),
                 kpi("Documentos por vencer (30 días)", dp, "entero", estado="proximo" if dp else "ok",
                     nota="Documentos que vencen en los próximos 30 días.")],
        "secciones": [
            seccion("Directivas de aeronavegabilidad",
                    [col("equipo", "Avión", ancho=12), col("numero", "Número", ancho=14), col("tipo", "Tipo", ancho=6),
                     col("titulo", "Título", ancho=36), col("estado_txt", "Estado", ancho=11),
                     col("fecha", "Cumplida el", "fecha"), col("plazo", "Plazo", ancho=24),
                     col("dias", "Días", "entero"), col("nivel", "Situación", "estado")], dirs,
                    vacio="Sin directivas registradas."),
            seccion("Documentos",
                    [col("titular", "Activo / persona", ancho=18), col("tipo", "Documento", ancho=34),
                     col("numero", "Número", ancho=14), col("emitido", "Emitido", "fecha"), col("vence", "Vence", "fecha"),
                     col("dias", "Días restantes", "entero"), col("nivel", "Situación", "estado")], docs,
                    vacio="Sin documentos registrados."),
        ],
    }


# ======================================================================
# COMBUSTIBLE
# ======================================================================

@informe("combustible", "Combustible de los aviones: tanqueos, consumo y conciliación", "combustible",
         "Galones cargados y comprados, consumo por hora de cada avión, conciliación de lo tanqueado frente a lo "
         "que reportan los pilotos, nivel de los depósitos y alertas de control.",
         filtros=("periodo", "equipo"), tipo_fijo="avion", periodo="90d",
         disponible=lambda: _modulo("core.combustible", "resumen") is not None,
         palabras="gasolina avgas galones tanqueo deposito consumo gal/h conciliacion",
         para='Para el control del combustible de los aviones: cuánto se cargó, cuánto se consumió y si todo cuadra.')
def _combustible(con, p):
    comb = _modulo("core.combustible")
    r = comb.resumen(con, p.desde, p.hasta, p.equipo_id, p.tipo)
    k = r["kpis"]
    nombres = {c: v["nombre"] for c, v in comb.COMBUSTIBLES.items()}
    consumo = []
    for c in r["consumo"]:
        if not c["tanqueos"] and not c["horas"]:
            continue
        consumo.append({"equipo": c["equipo"], "tipo": core_flota.TIPOS_ACTIVO.get(c["tipo_activo"]),
                        "tanqueos": c["tanqueos"], "galones": c["galones"], "horas": c["horas"], "gal_h": c["gal_h"],
                        "metodo": {"lleno": "Lleno a lleno", "periodo": "Promedio del período"}.get(c["metodo"]),
                        "gal_h_reportado": c["gal_h_reportado"], "reportado": c["galones_reportados"],
                        "conciliacion": None if c["conciliacion"] is None else round(c["conciliacion"] * 100, 1),
                        "gal_ha": c["gal_ha"], "costo": c["costo"], "costo_h": c["costo_h"],
                        "_enlace": "/combustible"})
    movs = [{"fecha": m["fecha"], "hora": m.get("hora"), "tipo": comb.TIPOS.get(m["tipo"], m["tipo"]),
             "equipo": m.get("equipo") or comb.DESTINOS.get(m.get("destino") or "", None), "deposito": m.get("deposito"),
             "combustible": nombres.get(m["combustible"], m["combustible"]), "galones": _r(m["galones"], 1),
             "precio": _r(m.get("precio_gal"), 0), "total": _r(m.get("total"), 0), "proveedor": m.get("proveedor"),
             "lleno": "Sí" if m.get("lleno") else None, "lectura": m.get("lectura"), "responsable": m.get("responsable"),
             "_enlace": "/combustible"} for m in r["movimientos"]]
    deps = [{"nombre": d["nombre"], "combustible": nombres.get(d["combustible"], d["combustible"]),
             "capacidad": d["capacidad_gal"], "nivel": d["nivel_gal"], "pct": d["pct"], "salida_30d": d["salida_30d"],
             "autonomia": d["dias_autonomia"], "precio_medio": d["precio_medio"],
             "medicion": (d.get("ultima_medicion") or {}).get("fecha"), "_enlace": "/combustible"}
            for d in comb.depositos(con)]
    alertas = [{"nivel": a["nivel"] if a["nivel"] in ESTADOS else "info", "titulo": a["titulo"],
                "detalle": a["detalle"], "_enlace": "/combustible"} for a in comb.alertas(con, p.desde, p.hasta)]
    etq, series = _serie_mes(r["por_mes"], series=(("tanqueado", "Tanqueado", "gal"), ("comprado", "Comprado", "gal")))
    return {
        "kpis": [kpi("Galones tanqueados", k["galones"], "numero", 1, "gal", nota="Σ galones cargados a los aviones."),
                 kpi("Tanqueos", k["tanqueos"], "entero", nota="Cargas de combustible registradas."),
                 kpi("Galones comprados", k["comprado"], "numero", 1, "gal", nota="Σ galones que entraron a los depósitos."),
                 kpi("Consumo medio", k["gal_h"], "numero", 2, "gal/h",
                     nota="Galones cargados ÷ horas voladas por los aviones que tanquearon."),
                 kpi("Gasto en combustible", k["gasto"], "dinero",
                     nota="Compras a depósito + tanqueos pagados en el aeródromo."),
                 kpi("Precio medio", k["precio_medio"], "dinero", nota="Precio por galón ponderado por galones comprados."),
                 kpi("Alertas de control", len(alertas), "entero",
                     nota="Depósitos bajos o con descuadre, tanqueos sin chequeo, combustible sin explicar.",
                     estado="critico" if any(a["nivel"] in ("vencido", "critico") for a in alertas) else
                     "proximo" if alertas else "ok")],
        "graficas": [grafica("barras", "Galones por mes", etq, series, seccion=1, campo="mes"),
                     grafica("ranking", "Consumo por activo (gal/h)", [c["equipo"] for c in consumo if c["gal_h"]],
                             [{"nombre": "gal/h", "datos": [c["gal_h"] for c in consumo if c["gal_h"]]}],
                             seccion=0, campo="equipo", unidad="gal/h")],
        "secciones": [
            seccion("Consumo y conciliación por activo",
                    [col("equipo", "Activo", ancho=13), col("tipo", "Tipo", ancho=7), col("tanqueos", "Tanqueos", "entero", total=True),
                     col("galones", "Galones cargados", "numero", 1, total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("gal_h", "gal/h", "numero", 2), col("metodo", "Método", ancho=16),
                     col("gal_h_reportado", "gal/h reportado", "numero", 2),
                     col("reportado", "Galones reportados", "numero", 1, total=True),
                     col("conciliacion", "Diferencia", "pct", 1), col("gal_ha", "gal/ha", "numero", 3),
                     col("costo", "Costo", "dinero", total=True), col("costo_h", "Costo/h", "dinero")], consumo,
                    descripcion="Diferencia = (cargado − reportado) ÷ cargado. Más del 10 % indica combustible sin explicar."),
            seccion("Movimientos",
                    [col("fecha", "Fecha", "fecha"), col("hora", "Hora", ancho=7), col("tipo", "Tipo", ancho=12),
                     col("equipo", "Activo / destino", ancho=16), col("deposito", "Depósito", ancho=16),
                     col("combustible", "Combustible", ancho=14), col("galones", "Galones", "numero", 1, total=True),
                     col("precio", "Precio/gal", "dinero"), col("total", "Total", "dinero", total=True),
                     col("proveedor", "Proveedor", ancho=16), col("lleno", "Lleno", ancho=6),
                     col("lectura", "Lectura", "numero", 1), col("responsable", "Responsable", ancho=16)],
                    [dict(m, mes=m["fecha"][:7]) for m in movs]),
            seccion("Depósitos (hoy)",
                    [col("nombre", "Depósito", ancho=18), col("combustible", "Combustible", ancho=14),
                     col("capacidad", "Capacidad (gal)", "numero", 0), col("nivel", "Nivel (gal)", "numero", 1),
                     col("pct", "Nivel", "pct", 0), col("salida_30d", "Salida 30 días", "numero", 1),
                     col("autonomia", "Días de autonomía", "entero"), col("precio_medio", "Precio medio", "dinero"),
                     col("medicion", "Última medición", "fecha")], deps, vacio="Sin depósitos registrados."),
            seccion("Alertas de control",
                    [col("nivel", "Nivel", "estado"), col("titulo", "Alerta", ancho=34), col("detalle", "Detalle", ancho=60)],
                    alertas, vacio="Sin alertas de combustible en el período."),
        ],
    }


# ======================================================================
# COSTOS Y RENTABILIDAD (sólo administrador)
# ======================================================================

def rentabilidad_clientes(con, f, mant_por_activo=None, horas_por_activo=None):
    """Ingreso, combustible, mantenimiento y nómina prorrateados y margen por cliente y finca. Es el
    mismo cálculo de la pantalla de Rentabilidad: el mantenimiento de cada activo se reparte por sus
    horas de vuelo, y la nómina por las horas de toda la flota."""
    w, p = f.where()
    precio = core_ind._meta_num(con, "precio_combustible_gal") or 0
    clientes = _filas(con, f"""
        SELECT COALESCE(o.cliente,'Sin cliente') cliente, COALESCE(o.lote,'') finca, e.tipo_activo,
               ROUND(COALESCE(SUM(o.hectareas),0),1) ha, ROUND(SUM(o.horas_vuelo),1) horas,
               ROUND(COALESCE(SUM(o.combustible_gal),0) * ?, 0) combustible,
               ROUND(COALESCE(SUM({core_ind.SQL_INGRESO_OP}),0), 0) ingreso
        FROM operaciones o JOIN equipos e ON e.id=o.equipo_id WHERE {w}
        GROUP BY 1, 2, 3 ORDER BY ingreso DESC, ha DESC""", [precio] + p)
    reparto = _filas(con, f"""SELECT COALESCE(o.cliente,'Sin cliente') cliente, COALESCE(o.lote,'') finca,
            o.equipo_id, SUM(o.horas_vuelo) h FROM operaciones o WHERE {w} GROUP BY 1, 2, 3""", p)
    mant_cf = {}
    for r in reparto:
        m, h = (mant_por_activo or {}).get(r["equipo_id"]), (horas_por_activo or {}).get(r["equipo_id"])
        if m and h:
            k = (r["cliente"], r["finca"])
            mant_cf[k] = mant_cf.get(k, 0) + m * (r["h"] or 0) / h
    nomina_h = core_ind.nomina_hora(con, f) or 0
    for c in clientes:
        c["mantenimiento"] = round(mant_cf.get((c["cliente"], c["finca"]), 0))
        c["nomina"] = round(nomina_h * (c["horas"] or 0))
        c["margen"] = (round((c["ingreso"] or 0) - (c["combustible"] or 0) - c["mantenimiento"] - c["nomina"])
                       if c["ingreso"] else None)
        c["margen_ha"] = round(c["margen"] / c["ha"]) if c["margen"] is not None and c["ha"] else None
    return clientes


@informe("rentabilidad", "Rentabilidad por activo y por cliente", "costos",
         "Ingreso según las tarifas (por hectárea o por hora), costos de mantenimiento, combustible y nómina y margen de cada activo y de cada "
         "cliente y finca.",
         filtros=("periodo", "tipo", "equipo", "cliente"), roles=ADMIN, periodo="90d", destacado=True,
         palabras="margen ingreso tarifa costo utilidad ganancia",
         para='Para la gerencia: qué activos y qué clientes dejan margen y cuáles no.')
def _rentabilidad(con, p):
    f = p.filtros()
    claves = ["hectareas", "horas", "costo_mant", "costo_mant_hora", "costo_combustible_hora", "costo_personal",
              "costo_ha", "ingreso_ha", "margen"]
    total = core_ind.calcular(con, claves, f)
    activos = core_ind.por_activo(con, ["hectareas", "horas", "costo_mant", "costo_ha", "ingreso_ha", "margen"],
                                  replace(f, equipo_id=None))
    filas_act = []
    for a in activos:
        if p.equipo_id and a["id"] != p.equipo_id:
            continue
        i = a["indicadores"]
        filas_act.append({"equipo": a["nombre"], "tipo": core_flota.TIPOS_ACTIVO.get(a["tipo_activo"]),
                          **{k: (i.get(k) or {}).get("valor") for k in ("hectareas", "horas", "costo_mant", "costo_ha",
                                                                        "ingreso_ha", "margen")},
                          "_enlace": f"/flota/{a['id']}"})
    mant = {a["id"]: (a["indicadores"].get("costo_mant") or {}).get("valor") for a in activos}
    horas = {a["id"]: (a["indicadores"].get("horas") or {}).get("valor") for a in activos}
    clientes = rentabilidad_clientes(con, f, mant, horas)
    if p.cliente:
        clientes = [c for c in clientes if c["cliente"].lower() == p.cliente.lower()]
    for c in clientes:
        c["tipo"] = core_flota.TIPOS_ACTIVO.get(c.pop("tipo_activo"))
        c["_enlace"] = "/rentabilidad"
    avisos = []
    if not con.execute("SELECT 1 FROM tarifas LIMIT 1").fetchone():
        avisos.append({"nivel": "proximo", "enlace": "/rentabilidad",
                       "texto": "No hay tarifas por cliente: el ingreso y el margen salen vacíos. Regístralas en Rentabilidad."})
    if not core_ind._meta_num(con, "precio_combustible_gal"):
        avisos.append({"nivel": "info", "enlace": "/rentabilidad",
                       "texto": "Sin precio del galón de combustible en la configuración de costos: el costo de combustible "
                                "no se incluye."})
    if not core_ind._meta_num(con, "nomina_mes"):
        avisos.append({"nivel": "proximo", "enlace": "/rentabilidad",
                       "texto": "Sin nómina mensual de pilotos y técnicos en la configuración de costos: el margen no "
                                "descuenta el personal."})
    por_cliente = {}
    for c in clientes:
        if c["margen"] is not None:
            por_cliente[c["cliente"]] = por_cliente.get(c["cliente"], 0) + c["margen"]
    top = sorted(por_cliente.items(), key=lambda x: -x[1])[:12]
    return {
        "kpis": [k for k in (_kpi_ind(total, c) for c in claves) if k],
        "avisos": avisos,
        "graficas": [grafica("ranking", "Margen por cliente", [t[0] for t in top],
                             [{"nombre": "Margen", "datos": [t[1] for t in top]}], seccion=1, campo="cliente", unidad="$")],
        "secciones": [
            seccion("Por activo",
                    [col("equipo", "Activo", ancho=14), col("tipo", "Tipo", ancho=7),
                     col("hectareas", "Hectáreas", "numero", 0, total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("costo_mant", "Costo mantenimiento", "dinero", total=True), col("costo_ha", "Costo/ha", "dinero"),
                     col("ingreso_ha", "Ingreso/ha", "dinero"), col("margen", "Margen", "dinero", total=True)], filas_act),
            seccion("Por cliente y finca",
                    [col("cliente", "Cliente", ancho=20), col("finca", "Finca", ancho=18), col("tipo", "Tipo", ancho=7),
                     col("ha", "Hectáreas", "numero", 1, total=True), col("horas", "Horas", "horas", 1, total=True),
                     col("ingreso", "Ingreso", "dinero", total=True), col("combustible", "Combustible", "dinero", total=True),
                     col("mantenimiento", "Mantenimiento", "dinero", total=True),
                     col("nomina", "Nómina", "dinero", total=True), col("margen", "Margen", "dinero", total=True),
                     col("margen_ha", "Margen/ha", "dinero")], clientes,
                    descripcion="El mantenimiento de cada activo y la nómina se reparten entre clientes según las horas "
                                "voladas para cada uno. El ingreso usa la tarifa del cliente, por hectárea o por hora."),
        ],
    }


# ======================================================================
# NORMATIVA RAC (core/rac.py)
# ======================================================================

@informe("rac_cumplimiento", "Cumplimiento de la normativa RAC", "normativa",
         "Cada requisito de la RAC que aplica a la operación (RAC 91, 100, 137, 43…) evaluado con los datos de "
         "la empresa: cumple, requiere atención o falta.",
         filtros=(), roles=SIN_PILOTO, periodo=None, destacado=True,
         disponible=lambda: _modulo("core.rac", "estado_cumplimiento") is not None,
         palabras="rac aerocivil norma requisito cumplimiento auditoria",
         para='Para preparar una auditoría o inspección de la Aerocivil: qué se cumple y qué falta.')
def _rac_cumplimiento(con, p):
    rac = _modulo("core.rac", "estado_cumplimiento")
    r = rac.estado_cumplimiento(con)
    reqs = r.get("requisitos", [])
    aplica_txt = {"avion": "Avión", "dron": "Dron", "empresa": "Empresa", "personal": "Personal"}
    filas = [{"rac": q.get("rac"), "numeral": q.get("numeral"), "titulo": q.get("titulo"), "exige": q.get("exige"),
              "aplica": aplica_txt.get(q.get("aplica"), q.get("aplica")), "estado": q.get("estado"),
              "detalle": "; ".join(q.get("detalle") or []) or None, "donde": q.get("donde"),
              "_enlace": q.get("enlace") or "/normativa"} for q in reqs]
    orden = {"falta": 0, "atencion": 1, "manual": 2, "cumple": 3, "no_aplica": 4}
    filas.sort(key=lambda f: (orden.get(f["estado"], 9), f["rac"] or ""))
    cuenta = r.get("resumen", {})
    estados = ["cumple", "atencion", "falta", "manual", "no_aplica"]
    return {
        "subtitulo": "Autoevaluación con los datos registrados en la app. No reemplaza la inspección de la Aerocivil.",
        "kpis": [kpi("Índice de cumplimiento", r.get("indice"), "pct", 0, nota="requisitos que cumplen ÷ evaluables",
                     estado="ok" if (r.get("indice") or 0) >= 90 else "proximo" if (r.get("indice") or 0) >= 70 else "critico"),
                 kpi("Cumplen", cuenta.get("cumple", 0), "entero", estado="ok",
                     nota="Requisitos que los datos de la app muestran cumplidos."),
                 kpi("Requieren atención", cuenta.get("atencion", 0), "entero",
                     nota="Hay algo vencido, pendiente o incompleto.",
                     estado="proximo" if cuenta.get("atencion") else "ok"),
                 kpi("Faltan", cuenta.get("falta", 0), "entero", estado="vencido" if cuenta.get("falta") else "ok",
                     nota="No hay en la app el registro o el documento que exige la norma.")],
        "graficas": [grafica("dona", "Requisitos por estado", [ESTADOS[e][0] for e in estados],
                             [{"nombre": "Requisitos", "datos": [cuenta.get(e, 0) for e in estados]}],
                             seccion=0, campo="estado", colores=[ESTADOS[e][1] for e in estados])],
        "secciones": [seccion(
            "Requisitos",
            [col("rac", "RAC", ancho=14), col("numeral", "Numeral", ancho=16), col("titulo", "Requisito", ancho=28),
             col("exige", "Qué exige", ancho=44), col("aplica", "Aplica a", ancho=9), col("estado", "Estado", "estado"),
             col("detalle", "Situación", ancho=40), col("donde", "Dónde se lleva en la app", ancho=28)], filas)],
        "encabezado": [("Fuente", r.get("fuente") or "Aerocivil — RAC"), ("Evaluado el", _dmy(r.get("fecha")))],
    }


# ======================================================================
# BODEGA E INSUMOS (core/bodega.py)
# ======================================================================
# Se activan sólo si el módulo de bodega existe en esta instalación. Las existencias, el costo
# promedio y el kardex los calcula core/bodega.py (se reconstruyen con los movimientos).

def _bodega():
    return _modulo("core.bodega", "inventario")


def _hay_bodega():
    return _bodega() is not None


@informe("bodega_inventario", "Inventario de bodega y lista de compras", "bodega",
         "Existencias de repuestos e insumos con su costo promedio, valor, cobertura y lotes por vencer, y lo que "
         "hay que pedir según los cambios previstos de la flota.",
         filtros=(), roles=SIN_PILOTO, periodo=None, disponible=_hay_bodega,
         palabras="inventario existencias stock repuestos insumos minimo compras pedir lote vence",
         para="Para compras y el almacenista: qué hay, cuánto vale y qué hay que pedir antes de que falte.")
def _bodega_inventario(con, p):
    bod = _bodega()
    inv = [i for i in bod.inventario(con) if i.get("activo", 1)]
    filas = [{"clase": "Insumo" if i["clase"] == "insumo" else "Repuesto", "codigo": i.get("codigo"),
              "nombre": i["nombre"], "categoria": i.get("categoria"), "modelo": i.get("modelo"), "unidad": i.get("unidad"),
              "saldo": i.get("saldo"), "reservado": i.get("reservado") or None, "disponible": i.get("disponible"),
              "minimo": i.get("stock_minimo") or None, "costo": _r(i.get("costo"), 0), "valor": _r(i.get("valor"), 0),
              "consumo_90d": i.get("consumo_90d") or None, "cobertura": i.get("cobertura_dias"),
              "vence": i.get("proximo_vence"), "nivel": i.get("nivel") or "ok", "situacion": i.get("nivel_txt"),
              "_enlace": "/bodega"} for i in inv]
    comp = bod.compras(con, inv=inv) if callable(getattr(bod, "compras", None)) else {"lista": [], "sin_articulo": []}
    pedir = [{"nombre": x["nombre"], "codigo": x.get("codigo"), "unidad": x.get("unidad"), "tiene": x.get("tiene"),
              "necesita": x.get("necesita"), "pedir": x.get("pedir"), "costo": x.get("costo"), "motivo": x.get("motivo"),
              "proveedor": x.get("proveedor"), "dias": x.get("primera_dias"),
              "nivel": "critico" if x.get("urgente") else "proximo", "_enlace": "/bodega"} for x in comp["lista"]]
    pedir += [{"nombre": x["nombre"], "codigo": None, "unidad": "und", "tiene": 0, "necesita": x["cantidad"],
               "pedir": x["cantidad"], "costo": x.get("costo"), "motivo": f"no está en bodega ({x.get('modelo') or ''})",
               "proveedor": None, "dias": min((e["dias"] for e in x["eventos"] if e["dias"] is not None), default=None),
               "nivel": "proximo", "_enlace": "/bodega"} for x in comp.get("sin_articulo", [])]
    valor = sum(f["valor"] or 0 for f in filas if (f["valor"] or 0) > 0)
    malos = sum(1 for f in filas if f["nivel"] != "ok")
    return {
        "kpis": [kpi("Artículos", len(filas), "entero", nota="Repuestos e insumos activos en la bodega."),
                 kpi("Valor del inventario", valor, "dinero", nota="Σ existencia × costo promedio ponderado de cada artículo."),
                 kpi("Repuestos", sum(f["valor"] or 0 for f in filas if f["clase"] == "Repuesto" and (f["valor"] or 0) > 0),
                     "dinero", nota="Valor de los repuestos de drones y avión."),
                 kpi("Insumos", sum(f["valor"] or 0 for f in filas if f["clase"] == "Insumo" and (f["valor"] or 0) > 0),
                     "dinero", nota="Valor de fitosanitarios, coadyuvantes, aceites y demás insumos."),
                 kpi("Con alerta", malos, "entero", estado="critico" if malos else "ok",
                     nota="Agotados, bajo el mínimo, con saldo negativo o con lotes vencidos o por vencer."),
                 kpi("Por comprar", len(pedir), "entero", estado="proximo" if pedir else "ok",
                     nota=f"Cambios previstos en {comp.get('horizonte', 90)} días + lo apartado en órdenes + mínimo − existencias.")],
        "graficas": [grafica("dona", "Artículos por situación", [ESTADOS[n][0] for n in ("ok", "proximo", "critico")],
                             [{"nombre": "Artículos", "datos": [sum(1 for f in filas if f["nivel"] == n)
                                                                for n in ("ok", "proximo", "critico")]}],
                             seccion=0, campo="nivel", colores=["ok", "proximo", "critico"])],
        "secciones": [
            seccion("Existencias",
                    [col("clase", "Clase", ancho=9), col("codigo", "Código", ancho=13), col("nombre", "Artículo", ancho=28),
                     col("categoria", "Categoría", ancho=14), col("modelo", "Modelo", ancho=8), col("unidad", "Unidad", ancho=6),
                     col("saldo", "Existencia", "numero", 2), col("reservado", "Apartado", "numero", 2),
                     col("disponible", "Disponible", "numero", 2), col("minimo", "Mínimo", "numero", 2),
                     col("costo", "Costo promedio", "dinero"), col("valor", "Valor", "dinero", total=True),
                     col("consumo_90d", "Consumo 90 días", "numero", 2), col("cobertura", "Cobertura (días)", "entero"),
                     col("vence", "Próximo vencimiento", "fecha"), col("nivel", "Estado", "estado"),
                     col("situacion", "Situación", ancho=14)], filas),
            seccion("Lista de compras",
                    [col("nombre", "Artículo", ancho=28), col("codigo", "Código", ancho=13), col("unidad", "Unidad", ancho=6),
                     col("tiene", "Tiene", "numero", 2), col("necesita", "Necesita", "numero", 2),
                     col("pedir", "Pedir", "numero", 2), col("costo", "Costo estimado", "dinero", total=True),
                     col("dias", "Primer cambio (días)", "entero"), col("motivo", "Motivo", ancho=22),
                     col("proveedor", "Proveedor", ancho=16), col("nivel", "Urgencia", "estado")], pedir,
                    vacio="No hay nada que pedir: las existencias cubren los cambios previstos."),
        ],
    }


@informe("bodega_kardex", "Kardex de bodega", "bodega",
         "Cada entrada, salida, traslado, ajuste y baja del período con el saldo que dejó, su costo y a qué "
         "activo, orden u operación se cargó.",
         filtros=("periodo",), roles=SIN_PILOTO, periodo="90d", disponible=_hay_bodega,
         palabras="kardex movimientos entrada salida saldo auditoria",
         para="Para auditar la bodega: cada movimiento con su saldo, su valor y su responsable.")
def _bodega_kardex(con, p):
    bod = _bodega()
    movs = bod.movimientos(con, p.desde, p.hasta, limite=10 ** 6)
    equipos = {e["id"]: e["nombre"] for e in _filas(con, "SELECT id, nombre FROM equipos")}
    ubic = {u["id"]: u["nombre"] for u in bod.ubicaciones(con)} if callable(getattr(bod, "ubicaciones", None)) else {}
    filas = []
    for m in reversed(movs):
        c = m.get("cantidad") or 0
        signo = -1 if m["tipo"] in ("salida", "baja") else 1
        lugar = ubic.get(m.get("ubicacion_id"))
        if m["tipo"] == "traslado" and m.get("destino_id"):
            lugar = f"{lugar or '—'} → {ubic.get(m['destino_id'], '—')}"
        filas.append({"fecha": m["fecha"], "tipo": m.get("tipo_txt") or m["tipo"], "item": m.get("item"),
                      "clase": "Insumo" if m.get("clase") == "insumo" else "Repuesto",
                      "cantidad": _r(0 if m["tipo"] == "traslado" else c * signo, 3), "unidad": m.get("unidad"),
                      "saldo": m.get("saldo"), "costo": _r(m.get("costo_unitario") if m["tipo"] == "entrada" else m.get("costo_prom"), 0),
                      "valor": _r(m.get("valor"), 0), "ubicacion": lugar, "equipo": equipos.get(m.get("equipo_id")),
                      "lote": m.get("lote"), "motivo": m.get("motivo_txt") if m["tipo"] in ("salida", "baja") else m.get("proveedor"),
                      "responsable": m.get("responsable") or m.get("usuario"), "_enlace": "/bodega"})
    por_tipo = {}
    for f in filas:
        por_tipo[f["tipo"]] = por_tipo.get(f["tipo"], 0) + 1
    entradas = sum(f["valor"] or 0 for f in filas if f["tipo"].lower().startswith("entrada"))
    salidas = sum(f["valor"] or 0 for f in filas if f["tipo"].lower().startswith(("salida", "baja")))
    return {
        "kpis": [kpi("Movimientos", len(filas), "entero", nota="Registros del kardex en el período."),
                 kpi("Valor que entró", entradas, "dinero", nota="Σ cantidad × costo de compra de las entradas."),
                 kpi("Valor que salió", salidas, "dinero", nota="Σ cantidad × costo promedio de salidas y bajas.")],
        "graficas": [grafica("dona", "Movimientos por tipo", list(por_tipo),
                             [{"nombre": "Movimientos", "datos": list(por_tipo.values())}], seccion=0, campo="tipo")],
        "secciones": [seccion("Kardex",
                              [col("fecha", "Fecha", "fecha"), col("tipo", "Tipo", ancho=13), col("item", "Artículo", ancho=26),
                               col("clase", "Clase", ancho=8), col("cantidad", "Cantidad", "numero", 2),
                               col("unidad", "Unidad", ancho=6), col("saldo", "Saldo", "numero", 2),
                               col("costo", "Costo unitario", "dinero"), col("valor", "Valor", "dinero"),
                               col("ubicacion", "Ubicación", ancho=16), col("equipo", "Activo", ancho=11),
                               col("lote", "Lote", ancho=10), col("motivo", "Motivo / proveedor", ancho=18),
                               col("responsable", "Responsable", ancho=14)], filas,
                              descripcion="Cantidad con signo: positiva si entra, negativa si sale. Los traslados "
                                          "no cambian la existencia total.")],
    }


@informe("bodega_fitosanitarios", "Consumo y control de fitosanitarios", "bodega",
         "Por insumo: lo que debió gastarse según las hectáreas y la dosis de cada aplicación frente a lo que "
         "salió de bodega, con el descuadre, la dosis real y el costo por hectárea; y cada producto aplicado por "
         "operación con su registro ICA.",
         filtros=("periodo",), roles=SIN_PILOTO, periodo="90d",
         disponible=lambda: _modulo("core.bodega", "control_consumo") is not None,
         palabras="fitosanitario agroquimico insumo ica toxicologica consumo descuadre dosis",
         para="Para el control de agroquímicos (ICA) y para costear las aplicaciones: ¿cuadra lo que salió con "
              "lo que se aplicó?")
def _bodega_fitosanitarios(con, p):
    bod = _bodega()
    ctrl = bod.control_consumo(con, p.desde, p.hasta)
    filas = [{"nombre": f["nombre"], "categoria": f.get("categoria"), "ingrediente": f.get("ingrediente_activo"),
              "unidad": f.get("unidad"), "aplicaciones": f.get("aplicaciones"), "hectareas": f.get("hectareas"),
              "teorico": f.get("teorico"), "salidas": f.get("salidas"), "bajas": f.get("bajas") or None,
              "diferencia": f.get("diferencia"), "pct": f.get("pct"), "valor_diferencia": f.get("valor_diferencia"),
              "dosis_teorica": f.get("dosis_teorica"), "dosis_real": f.get("dosis_real"), "costo_ha": f.get("costo_ha"),
              "nivel": f["nivel"], "situacion": f.get("nivel_txt"), "_enlace": "/bodega"} for f in ctrl["filas"]]
    registro = []
    if callable(getattr(bod, "registro_aplicaciones", None)):
        for a in bod.registro_aplicaciones(con, p.desde, p.hasta):
            registro.append({"fecha": a["fecha"], "cliente": a.get("cliente"), "finca": a.get("finca"),
                             "producto": a.get("producto"), "ingrediente": a.get("ingrediente_activo"),
                             "ica": a.get("registro_ica"), "tox": a.get("categoria_tox"), "dosis": a.get("dosis_ha"),
                             "hectareas": _r(a.get("hectareas"), 2),
                             "cantidad": _r(a.get("descontado") if a.get("descontado") is not None else a.get("cantidad_teorica"), 3),
                             "unidad": a.get("unidad"), "lote": a.get("lote_producto"), "piloto": a.get("piloto"),
                             "equipo": a.get("equipo"), "_enlace": "/operaciones"})
    avisos = []
    if ctrl.get("por_conciliar"):
        avisos.append({"nivel": "proximo", "enlace": "/bodega",
                       "texto": f"{ctrl['por_conciliar']} operación(es) con producto anotado pero sin insumos de bodega "
                                "asociados: concílialas en Bodega para que el control cuadre."})
    return {
        "kpis": [kpi("Insumos con movimiento", len(filas), "entero", nota="Insumos con aplicaciones o salidas en el período."),
                 kpi("Hectáreas", ctrl.get("hectareas"), "numero", 1, "ha", nota="Σ hectáreas aplicadas en el período."),
                 kpi("Insumos aplicados", ctrl.get("valor_insumos_op"), "dinero",
                     nota="Valor de lo que salió de bodega hacia operaciones."),
                 kpi("Costo de insumos por hectárea", ctrl.get("costo_ha"), "dinero", nota="Insumos aplicados ÷ hectáreas."),
                 kpi("Descuadres", ctrl.get("n_descuadres"), "entero", estado="critico" if ctrl.get("n_descuadres") else "ok",
                     nota="Insumos cuya salida difiere 5 % o más de lo que se debió aplicar."),
                 kpi("Posibles pérdidas", ctrl.get("posibles_perdidas"), "dinero",
                     estado="critico" if (ctrl.get("posibles_perdidas") or 0) > 0 else "ok",
                     nota="Valor de lo que salió de más frente a lo aplicado (salidas − teórico) × costo.")],
        "avisos": avisos,
        "graficas": [grafica("barras", "Teórico frente a lo que salió", [f["nombre"] for f in filas[:12]],
                             [{"nombre": "Teórico", "datos": [f["teorico"] or 0 for f in filas[:12]]},
                              {"nombre": "Salió de bodega", "datos": [f["salidas"] or 0 for f in filas[:12]]}],
                             seccion=0, campo="nombre")],
        "secciones": [
            seccion("Control de consumo por insumo",
                    [col("nombre", "Insumo", ancho=22), col("categoria", "Categoría", ancho=12),
                     col("ingrediente", "Ingrediente activo", ancho=18), col("unidad", "Unidad", ancho=6),
                     col("aplicaciones", "Aplicaciones", "entero", total=True),
                     col("hectareas", "Hectáreas", "numero", 1, total=True), col("teorico", "Teórico", "numero", 2),
                     col("salidas", "Salió", "numero", 2), col("bajas", "Bajas", "numero", 2),
                     col("diferencia", "Diferencia", "numero", 2), col("pct", "Diferencia %", "pct", 1),
                     col("valor_diferencia", "Valor diferencia", "dinero", total=True),
                     col("dosis_teorica", "Dosis teórica /ha", "numero", 3), col("dosis_real", "Dosis real /ha", "numero", 3),
                     col("costo_ha", "Costo /ha", "dinero"), col("nivel", "Estado", "estado"),
                     col("situacion", "Situación", ancho=18)], filas,
                    descripcion="Teórico = Σ hectáreas × dosis de cada aplicación registrada. Diferencia = salió − teórico."),
            seccion("Productos aplicados por operación",
                    [col("fecha", "Fecha", "fecha"), col("cliente", "Cliente", ancho=16), col("finca", "Finca", ancho=16),
                     col("producto", "Producto", ancho=20), col("ingrediente", "Ingrediente activo", ancho=16),
                     col("ica", "Registro ICA", ancho=11), col("tox", "Cat. tox.", ancho=7),
                     col("dosis", "Dosis /ha", "numero", 3), col("hectareas", "Hectáreas", "numero", 2, total=True),
                     col("cantidad", "Cantidad", "numero", 3), col("unidad", "Unidad", ancho=6),
                     col("lote", "Lote", ancho=10), col("piloto", "Piloto", ancho=14), col("equipo", "Activo", ancho=10)],
                    registro, vacio="Ninguna operación del período tiene insumos de bodega asociados."),
        ],
    }


# ======================================================================
# Informes fijados por usuario (tabla meta)
# ======================================================================

def _clave_fijados(usuario_id):
    return f"informes_fijados:{usuario_id}"


def fijados(con, usuario_id):
    import json
    try:
        lista = json.loads(core_db.meta_get(con, _clave_fijados(usuario_id)) or "[]")
    except ValueError:
        lista = []
    return [c for c in lista if c in REGISTRO]


def fijar(con, usuario_id, clave, fijado=True):
    import json
    lista = [c for c in fijados(con, usuario_id) if c != clave]
    if fijado and clave in REGISTRO:
        lista.insert(0, clave)
    core_db.meta_set(con, _clave_fijados(usuario_id), json.dumps(lista[:30]))
    return lista
