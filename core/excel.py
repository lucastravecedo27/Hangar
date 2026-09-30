"""Plantillas, exportación e importación en Excel (operaciones y contactos).

Regla de la casa: **toda descarga de Excel pensada para llenar información sale con los datos
al día**, nunca vacía. El archivo que se baja es el mismo que se sube y el mismo que se guarda
en Drive, así que tiene que valer como copia fiel de lo que hay en la app en ese momento; una
plantilla en blanco obligaba a mantener dos versiones de la verdad.

La columna ID es la que decide al reimportar: con ID se actualiza la fila existente, sin ID se
crea una nueva. Así el ciclo descargar → editar → subir no duplica nada.
"""
from datetime import date, datetime
from io import BytesIO

from core import db as core_db
from core import flota as core_flota

HOJA = "Operaciones"
HOJA_AYUDA = "Instrucciones"

# (clave interna, título de la columna, ancho, formato de número)
COLUMNAS = [
    ("id",           "ID",                  8,  "0"),
    ("equipo",       "Equipo *",            16, None),
    ("fecha",        "Fecha *",             13, "dd/mm/yyyy"),
    ("horas_vuelo",  "Horas de vuelo *",    16, "0.00"),
    ("tiempo_total", "Tiempo total (h)",    17, "0.00"),
    ("despegues",    "Despegues",           12, "0"),
    ("hectareas",    "Hectáreas",           12, "0.00"),
    ("litros",       "Litros",              11, "0"),
    ("producto",     "Producto / mezcla",   24, None),
    ("piloto",       "Piloto",              20, None),
    ("cliente",      "Cliente",             22, None),
    ("zona",         "Zona",                18, None),
    ("lote",         "Finca / lote",        22, None),
    # Avión (Cessna): lecturas de Hobbs/Tach, ciclos, combustible y traslado.
    ("hobbs_ini",       "Hobbs inicial",        13, "0.0"),
    ("hobbs_fin",       "Hobbs final",          13, "0.0"),
    ("tach_ini",        "Tach inicial",         12, "0.0"),
    ("tach_fin",        "Tach final",           12, "0.0"),
    ("aterrizajes",     "Aterrizajes",          12, "0"),
    ("arranques",       "Arranques",            11, "0"),
    ("combustible_gal", "Combustible (gal)",    16, "0.0"),
    ("pista",           "Pista",                16, None),
    ("tiempo_traslado", "Traslado (h)",         13, "0.00"),
    # Aplicación y condiciones (los mismos datos de la bitácora de campo).
    ("ha_programadas",  "Ha programadas",       15, "0.00"),
    ("dosis_objetivo",  "Dosis objetivo (L/ha)", 19, "0.0"),
    ("temperatura",     "Temperatura (°C)",     15, "0.0"),
    ("humedad",         "Humedad (%)",          12, "0"),
    ("viento",          "Viento (km/h)",        13, "0.0"),
    ("velocidad",       "Velocidad (m/s)",      14, "0.0"),
    ("altura",          "Altura (m)",           11, "0.0"),
    ("nota",         "Nota",                34, None),
]
CLAVES = [c[0] for c in COLUMNAS]

# Bloques en los que se agrupan las columnas dentro de la hoja.
GRUPOS = [
    ("Identificación",       ["id", "equipo", "fecha"]),
    ("Jornada de vuelo",     ["horas_vuelo", "tiempo_total", "despegues"]),
    ("Aplicación",           ["hectareas", "litros", "producto"]),
    ("Responsables y lugar", ["piloto", "cliente", "zona", "lote"]),
    ("Avión",                ["hobbs_ini", "hobbs_fin", "tach_ini", "tach_fin", "aterrizajes", "arranques",
                              "combustible_gal", "pista", "tiempo_traslado"]),
    ("Aplicación y condiciones", ["ha_programadas", "dosis_objetivo", "temperatura", "humedad", "viento",
                                  "velocidad", "altura"]),
    ("Observaciones",        ["nota"]),
]

AYUDA = [
    ("Cómo usar esta plantilla", True),
    ("", False),
    ("1. Descarga el archivo: viene con todas las operaciones registradas hasta hoy.", False),
    ("2. Corrige lo que haga falta y añade las operaciones nuevas al final.", False),
    ("3. Vuelve a subir este mismo archivo en Operaciones › Importar Excel.", False),
    ("", False),
    ("Reglas", True),
    ("· ID: no lo toques. Con ID la fila actualiza esa operación; vacío, crea una nueva.", False),
    ("· Equipo: debe coincidir con el nombre del equipo en Inventario (p. ej. SMR 4).", False),
    ("· Fecha: formato dd/mm/aaaa o aaaa-mm-dd.", False),
    ("· Horas de vuelo: obligatorio y mayor que 0. Es lo que suma desgaste a las piezas.", False),
    ("  En un avión puedes dejarla vacía si pones Hobbs inicial y final: se calcula sola.", False),
    ("· Columnas de Avión: sólo para aviones; en los drones se dejan vacías.", False),
    ("· Condiciones: temperatura −5 a 55 °C, humedad 0–100 %, viento 0–80 km/h; fuera de eso la fila se rechaza.", False),
    ("· Decimales con coma o con punto, ambos se aceptan.", False),
    ("· Equipo, Piloto, Cliente, Zona, Finca y Producto traen desplegable con lo ya registrado.", False),
    ("  Equipo obliga a elegir de la lista; los demás aceptan valores nuevos si escribes encima.", False),
    ("· Para eliminar una operación, hazlo desde la app: borrar la fila aquí no la borra.", False),
]


# ---------- Escritura ----------
# La hoja no es una tabla pelada: lleva cabecera de marca, una banda que agrupa las columnas por
# bloques y filas vacías ya formateadas para seguir escribiendo. La fila de títulos NO es la 1,
# así que al importar se busca en vez de darla por supuesta (ver _localizar_cabecera).

MARCA, LEMA = "HANGAR", "Control de flota aérea agrícola"
# Colores de marca: grafito y amarillo (los nombres AZUL* se conservan por compatibilidad).
AZUL, AZUL_MED, AZUL_SUAVE = "1A1D24", "3A3F4A", "FFF6DB"
TINTA, GRIS, LINEA, BANDA = "141A24", "6B7F99", "C5D4E6", "F7FAFD"

FILA_TITULOS = 6          # dónde van los nombres de columna
FILA_DATOS = 7            # dónde empiezan los datos
FILAS_LIBRES = 150        # filas vacías ya formateadas, listas para escribir


def _borde(color=LINEA, estilo="thin"):
    from openpyxl.styles import Border, Side
    lado = Side(style=estilo, color=color)
    return Border(left=lado, right=lado, top=lado, bottom=lado)


def _cabecera_formal(ws, columnas, grupos, titulo, subtitulo, meta):
    """Monta el encabezado: marca, título del documento, datos de generación y bandas de grupo."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    n = len(columnas)
    ultima = ws.cell(row=1, column=n).column_letter

    # Fila 1: banda de marca
    ws.merge_cells(f"A1:{ultima}1")
    c = ws["A1"]
    c.value = f"{MARCA}   ·   {LEMA}"
    c.fill = PatternFill("solid", fgColor=AZUL)
    c.font = Font(color="FFFFFF", bold=True, size=15)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 30

    # Fila 2: título del documento
    ws.merge_cells(f"A2:{ultima}2")
    c = ws["A2"]
    c.value = titulo
    c.fill = PatternFill("solid", fgColor=AZUL_SUAVE)
    c.font = Font(color=AZUL, bold=True, size=12.5)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 22

    # Fila 3: instrucción corta
    ws.merge_cells(f"A3:{ultima}3")
    c = ws["A3"]
    c.value = subtitulo
    c.fill = PatternFill("solid", fgColor=AZUL_SUAVE)
    c.font = Font(color=TINTA, size=10.5)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[3].height = 18

    # Fila 4: datos de generación
    ws.merge_cells(f"A4:{ultima}4")
    c = ws["A4"]
    c.value = meta
    c.fill = PatternFill("solid", fgColor=AZUL_SUAVE)
    c.font = Font(color=GRIS, size=9.5, italic=True)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    c.border = Border(bottom=Side(style="medium", color=AZUL_MED))
    ws.row_dimensions[4].height = 16

    ws.row_dimensions[5].height = 7        # respiro entre encabezado y tabla

    # Fila 5: bandas que agrupan las columnas por bloques
    claves = [x[0] for x in columnas]
    for nombre, grupo in grupos:
        indices = [claves.index(k) + 1 for k in grupo if k in claves]
        if not indices:
            continue
        ini, fin = min(indices), max(indices)
        l1 = ws.cell(row=5, column=ini).column_letter
        l2 = ws.cell(row=5, column=fin).column_letter
        if ini != fin:
            ws.merge_cells(f"{l1}5:{l2}5")
        c = ws.cell(row=5, column=ini)
        c.value = nombre.upper()
        c.fill = PatternFill("solid", fgColor=AZUL_MED)
        c.font = Font(color="FFFFFF", bold=True, size=8.5)
        c.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(ini, fin + 1):
            ws.cell(row=5, column=col).border = Border(
                left=Side(style="thin", color="FFFFFF"), right=Side(style="thin", color="FFFFFF"))
    ws.row_dimensions[5].height = 15

    # Fila 6: títulos de columna
    for i, (clave, titulo_col, ancho, _fmt) in enumerate(columnas, start=1):
        celda = ws.cell(row=FILA_TITULOS, column=i, value=titulo_col)
        obligatoria = titulo_col.rstrip().endswith("*")
        celda.fill = PatternFill("solid", fgColor=AZUL)
        celda.font = Font(color="FFF3D1" if obligatoria else "FFFFFF", bold=True, size=10.5)
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = _borde("FFFFFF")
        ws.column_dimensions[celda.column_letter].width = ancho
    ws.row_dimensions[FILA_TITULOS].height = 30

    ws.freeze_panes = f"A{FILA_DATOS}"
    ws.auto_filter.ref = f"A{FILA_TITULOS}:{ultima}{FILA_TITULOS}"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = AZUL


def _cuerpo(ws, columnas, filas, campos_fecha=()):
    """Escribe los datos y deja filas vacías ya formateadas para seguir llenando."""
    from openpyxl.styles import Alignment, Font, PatternFill
    borde = _borde()
    banda = PatternFill("solid", fgColor=BANDA)
    gris_id = PatternFill("solid", fgColor="EEF2F7")
    # Los objetos de estilo se crean UNA vez y se comparten: openpyxl los registra por valor,
    # y crear un Font nuevo por cada celda multiplicaba por 20 el tiempo con miles de filas.
    fuente_id = Font(size=10.5, color=GRIS)
    fuente = Font(size=10.5, color=TINTA)
    centrado = Alignment(horizontal="center")

    total = len(filas) + FILAS_LIBRES
    for r in range(FILA_DATOS, FILA_DATOS + total):
        dato = filas[r - FILA_DATOS] if r - FILA_DATOS < len(filas) else None
        for i, (clave, _t, _a, fmt) in enumerate(columnas, start=1):
            celda = ws.cell(row=r, column=i)
            if dato is not None:
                valor = dato.get(clave)
                if clave in campos_fecha and valor:
                    try:
                        valor = date.fromisoformat(str(valor)[:10])
                    except ValueError:
                        pass
                celda.value = valor
            celda.border = borde
            celda.font = fuente_id if clave == "id" else fuente
            if fmt:
                celda.number_format = fmt
            # La columna ID se ve apagada a propósito: es del sistema y no se toca.
            if clave == "id":
                celda.fill = gris_id
                celda.alignment = centrado
            elif (r - FILA_DATOS) % 2:
                celda.fill = banda
            if clave == "nota":
                celda.alignment = Alignment(wrap_text=False, vertical="center")
        ws.row_dimensions[r].height = 17


def _imprimir(ws, columnas):
    """Ajustes de impresión: apaisado, a una hoja de ancho y con la cabecera repetida."""
    from openpyxl.worksheet.properties import PageSetupProperties
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"1:{FILA_TITULOS}"
    ws.print_options.horizontalCentered = True
    ws.oddFooter.left.text = f"{MARCA} · {LEMA}"
    ws.oddFooter.right.text = "Página &P de &N"
    ws.oddFooter.left.size = ws.oddFooter.right.size = 8
    ws.oddFooter.left.color = ws.oddFooter.right.color = GRIS


def _hoja_ayuda(wb, ayuda=None):
    """Hoja de instrucciones con la misma cabecera de marca que la de datos."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    ws = wb.create_sheet(HOJA_AYUDA)
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 104
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:B1")
    c = ws["A1"]
    c.value = f"{MARCA}   ·   {LEMA}"
    c.fill = PatternFill("solid", fgColor=AZUL)
    c.font = Font(color="FFFFFF", bold=True, size=15)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:B2")
    c = ws["A2"]
    c.value = "Instrucciones de uso"
    c.fill = PatternFill("solid", fgColor=AZUL_SUAVE)
    c.font = Font(color=AZUL, bold=True, size=12.5)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    c.border = Border(bottom=Side(style="medium", color=AZUL_MED))
    ws.row_dimensions[2].height = 22

    fila = 4
    for texto, es_titulo in (ayuda or AYUDA):
        if not texto:
            ws.row_dimensions[fila].height = 8
            fila += 1
            continue
        celda = ws.cell(row=fila, column=2, value=texto)
        if es_titulo:
            celda.font = Font(bold=True, size=12, color=AZUL)
            celda.border = Border(bottom=Side(style="thin", color=LINEA))
            ws.row_dimensions[fila].height = 22
        else:
            celda.font = Font(size=10.5, color=TINTA)
            celda.alignment = Alignment(vertical="center", wrap_text=True)
            ws.row_dimensions[fila].height = 16
        fila += 1
    ws.sheet_properties.tabColor = AZUL_MED
    return ws


HOJA_LISTAS = "Listas"


def _hoja_listas(wb, listas):
    """Vuelca cada lista en una columna de una hoja oculta y devuelve su rango.

    Escribir los valores dentro de la propia fórmula («"a,b,c"») limita la validación a 255
    caracteres: con una docena de clientes ya se rebasa y el desplegable desaparecía sin avisar.
    En una hoja aparte no hay límite y las listas se pueden ampliar a mano.
    """
    ws = wb.create_sheet(HOJA_LISTAS)
    ws.sheet_state = "hidden"
    rangos = {}
    for i, (clave, valores) in enumerate(listas.items(), start=1):
        letra = ws.cell(row=1, column=i).column_letter
        ws.cell(row=1, column=i, value=clave)
        ws.column_dimensions[letra].width = 26
        vistos, limpios = set(), []
        for v in valores:
            texto = str(v).strip() if v not in (None, "") else ""
            if texto and texto.lower() not in vistos:
                vistos.add(texto.lower())
                limpios.append(texto)
        for r, v in enumerate(limpios[:400], start=2):
            ws.cell(row=r, column=i, value=v)
        if limpios:
            rangos[clave] = f"'{HOJA_LISTAS}'!${letra}$2:${letra}${min(len(limpios), 400) + 1}"
    return rangos


def _validar(ws, letra, rango, filas, prompt="", estricto=False):
    """Añade el desplegable a una columna.

    `estricto` sólo para lo que debe existir sí o sí (el equipo, el rol, el sí/no). En columnas
    como cliente o zona la lista es una ayuda para no volver a teclear lo de siempre, pero hay
    que poder escribir un valor nuevo: ahí la validación no bloquea.
    """
    if not rango:
        return
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1=rango, allow_blank=True, showDropDown=False)
    dv.showErrorMessage = bool(estricto)
    if estricto:
        dv.errorStyle = "stop"
        dv.error = "Elige un valor de la lista."
        dv.errorTitle = "Valor no válido"
    if prompt:
        dv.promptTitle = prompt
        dv.prompt = "Despliega la flecha o escribe directamente." if not estricto else "Elige de la lista."
        dv.showInputMessage = True
    ws.add_data_validation(dv)
    dv.add(f"{letra}{FILA_DATOS}:{letra}{max(filas, FILA_DATOS + 200)}")


def _letra(columnas, clave):
    from openpyxl.utils import get_column_letter
    return get_column_letter([c[0] for c in columnas].index(clave) + 1)


def _valores_distintos(con, consulta):
    return [f[0] for f in con.execute(consulta).fetchall() if f[0]]


def libro_operaciones(con, filas=None, equipo_id=None):
    """Devuelve el .xlsx en memoria, con las operaciones que se le pasen."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = HOJA
    filas = filas if filas is not None else []

    n_equipos = con.execute("SELECT COUNT(*) n FROM equipos WHERE estado!='baja'").fetchone()["n"]
    _cabecera_formal(
        ws, COLUMNAS, GRUPOS,
        "Registro de operaciones de vuelo",
        "Corrige lo que haga falta y añade las jornadas nuevas al final. La columna ID no se toca.",
        f"Generado el {date.today().strftime('%d/%m/%Y')}  ·  {len(filas)} operación(es)  ·  "
        f"{n_equipos} equipo(s) activo(s)  ·  "
        + (f"Sólo las {MAX_FILAS_EXCEL:,} jornadas más recientes: filtra por fechas para exportar otras  ·  ".replace(",", ".")
           if len(filas) >= MAX_FILAS_EXCEL else "")
        + "Este archivo es el que se sube a Drive")
    _cuerpo(ws, COLUMNAS, filas, campos_fecha=("fecha",))
    _imprimir(ws, COLUMNAS)

    # Desplegables con lo que ya existe en la app: evita teclear otra vez el mismo cliente o la
    # misma finca, y de paso que la misma cosa entre escrita de tres maneras distintas.
    listas = {
        "equipos": _valores_distintos(con, "SELECT nombre FROM equipos WHERE estado!='baja' ORDER BY nombre"),
        "pilotos": _valores_distintos(con,
            "SELECT nombre FROM personal WHERE activo=1 AND rol IN ('piloto','operario') "
            "UNION SELECT DISTINCT piloto FROM operaciones WHERE piloto IS NOT NULL ORDER BY 1"),
        "clientes": _valores_distintos(con,
            "SELECT DISTINCT cliente FROM operaciones WHERE cliente IS NOT NULL "
            "UNION SELECT DISTINCT cliente FROM ordenes_servicio WHERE cliente IS NOT NULL ORDER BY 1"),
        "zonas": _valores_distintos(con,
            "SELECT DISTINCT zona FROM operaciones WHERE zona IS NOT NULL "
            "UNION SELECT DISTINCT zona FROM ordenes_servicio WHERE zona IS NOT NULL ORDER BY 1"),
        "lotes": _valores_distintos(con,
            "SELECT DISTINCT lote FROM operaciones WHERE lote IS NOT NULL "
            "UNION SELECT DISTINCT finca FROM ordenes_servicio WHERE finca IS NOT NULL ORDER BY 1"),
        "productos": _valores_distintos(con,
            "SELECT DISTINCT producto FROM operaciones WHERE producto IS NOT NULL "
            "UNION SELECT DISTINCT nombre FROM os_productos ORDER BY 1"),
    }
    rangos = _hoja_listas(wb, listas)
    n = FILA_DATOS + len(filas) + FILAS_LIBRES
    _validar(ws, _letra(COLUMNAS, "equipo"),   rangos.get("equipos"),   n, "Equipo", estricto=True)
    _validar(ws, _letra(COLUMNAS, "piloto"),   rangos.get("pilotos"),   n, "Piloto")
    _validar(ws, _letra(COLUMNAS, "cliente"),  rangos.get("clientes"),  n, "Cliente")
    _validar(ws, _letra(COLUMNAS, "zona"),     rangos.get("zonas"),     n, "Zona")
    _validar(ws, _letra(COLUMNAS, "lote"),     rangos.get("lotes"),     n, "Finca / lote")
    _validar(ws, _letra(COLUMNAS, "producto"), rangos.get("productos"), n, "Producto / mezcla")
    _hoja_ayuda(wb)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


# Un Excel con más filas que esto pesa demasiado y tarda en generarse; nadie corrige a mano
# decenas de miles de jornadas. Sin filtros se exportan las más recientes hasta este tope (la
# hoja lo indica); con filtro de equipo o de fechas se exporta lo que se pida.
MAX_FILAS_EXCEL = 10000


def operaciones_para_excel(con, equipo_id=None, desde=None, hasta=None, tope=MAX_FILAS_EXCEL):
    cond, params = ["1=1"], []
    if equipo_id:
        cond.append("o.equipo_id=?"); params.append(equipo_id)
    if desde:
        cond.append("o.fecha>=?"); params.append(desde)
    if hasta:
        cond.append("o.fecha<=?"); params.append(hasta)
    limite = ""
    if tope and not desde and not hasta:
        limite = f"LIMIT {int(tope)}"
    filas = con.execute(
        f"""SELECT * FROM (
              SELECT o.id, e.nombre AS equipo, o.fecha, o.horas_vuelo, o.tiempo_total, o.despegues,
                     o.hectareas, o.litros, o.producto, o.piloto, o.cliente, o.zona, o.lote, o.nota,
                     o.hobbs_ini, o.hobbs_fin, o.tach_ini, o.tach_fin, o.aterrizajes, o.arranques,
                     o.combustible_gal, o.pista, o.tiempo_traslado, o.ha_programadas, o.dosis_objetivo,
                     o.temperatura, o.humedad, o.viento, o.velocidad, o.altura
              FROM operaciones o JOIN equipos e ON e.id=o.equipo_id
              WHERE {' AND '.join(cond)} ORDER BY o.fecha DESC, o.id DESC {limite}) ultimas
            ORDER BY fecha, id""", params).fetchall()
    return [dict(f) for f in filas]


# ---------- Lectura ----------

def _normalizar(titulo):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(titulo or "")).encode("ascii", "ignore").decode().lower()
    return t.replace("*", "").replace("(h)", "").strip(" .:/")


def _localizar_cabecera(filas, alias, obligatorias, limite=25):
    """Encuentra la fila de títulos y devuelve (índice, mapa de columnas).

    La hoja lleva encabezado de marca, instrucciones y una banda de grupos antes de la tabla, así
    que los títulos NO están en la primera fila. Se busca la primera que contenga todas las
    columnas obligatorias; así el archivo se puede seguir leyendo aunque el encabezado cambie de
    alto, y también sirve para hojas hechas a mano donde la tabla empieza más abajo.
    """
    for i, fila in enumerate(filas[:limite]):
        mapa = [alias.get(_normalizar(t)) for t in fila]
        if all(o in mapa for o in obligatorias):
            return i, mapa
    return None, None


ALIAS = {
    "id": "id", "equipo": "equipo", "dron": "equipo", "serial": "equipo",
    "fecha": "fecha", "horas de vuelo": "horas_vuelo", "horas": "horas_vuelo",
    "tiempo total": "tiempo_total", "despegues": "despegues", "hectareas": "hectareas",
    "ha": "hectareas", "litros": "litros", "producto / mezcla": "producto", "producto": "producto",
    "mezcla": "producto", "piloto": "piloto", "cliente": "cliente", "zona": "zona",
    "finca / lote": "lote", "finca": "lote", "lote": "lote", "nota": "nota", "observaciones": "nota",
    "hobbs inicial": "hobbs_ini", "hobbs final": "hobbs_fin", "tach inicial": "tach_ini", "tach final": "tach_fin",
    "aterrizajes": "aterrizajes", "arranques": "arranques", "combustible (gal)": "combustible_gal",
    "combustible": "combustible_gal", "pista": "pista", "traslado": "tiempo_traslado",
    "ha programadas": "ha_programadas", "has. programadas": "ha_programadas", "has programadas": "ha_programadas",
    "dosis objetivo (l/ha)": "dosis_objetivo", "volumen lts/ha": "dosis_objetivo",
    "temperatura (c)": "temperatura", "temperatura": "temperatura", "humedad (%)": "humedad",
    "humedad relativa": "humedad", "humedad": "humedad", "viento (km/h)": "viento", "viento (km/hra)": "viento",
    "viento": "viento", "velocidad (m/s)": "velocidad", "velocidad": "velocidad", "altura (m)": "altura",
    "altura promedio (m)": "altura", "altura": "altura",
}


def _fecha(valor):
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto[:10], formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def procesar_importacion(con, stream, crear_equipos=False):
    """Lee el .xlsx subido y crea/actualiza operaciones. No borra nada.

    Devuelve un informe con creadas, actualizadas, ignoradas y el detalle de los errores por fila,
    para poder mostrarlo en la interfaz sin adivinar qué pasó.
    """
    import openpyxl
    wb = openpyxl.load_workbook(stream, data_only=True)
    ws = wb[HOJA] if HOJA in wb.sheetnames else wb.worksheets[0]

    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return {"ok": False, "error": "El archivo está vacío."}

    fila_titulos, cabecera = _localizar_cabecera(filas, ALIAS, ("equipo", "horas_vuelo"))
    if cabecera is None:
        return {"ok": False, "error": "No encuentro las columnas «Equipo» y «Horas de vuelo». "
                                      "Usa el archivo que descarga la app."}

    equipos = {e["nombre"].strip().upper(): e["id"] for e in
               con.execute("SELECT id, nombre FROM equipos").fetchall()}
    informe = {"ok": True, "creadas": 0, "actualizadas": 0, "ignoradas": 0, "errores": [], "equipos_nuevos": []}
    tocados = set()

    for n, fila in enumerate(filas[fila_titulos + 1:], start=fila_titulos + 2):
        datos = {}
        for i, clave in enumerate(cabecera):
            if clave and i < len(fila):
                datos[clave] = fila[i]
        if not any(v not in (None, "") for v in datos.values()):
            continue

        nombre_equipo = str(datos.get("equipo") or "").strip()
        if not nombre_equipo:
            informe["ignoradas"] += 1
            informe["errores"].append({"fila": n, "motivo": "Sin equipo."})
            continue
        equipo_id = equipos.get(nombre_equipo.upper())
        if not equipo_id:
            if not crear_equipos:
                informe["ignoradas"] += 1
                informe["errores"].append({"fila": n, "motivo": f"El equipo «{nombre_equipo}» no existe en Inventario."})
                continue
            equipo_id = core_db.crear_equipo(con, nombre_equipo, "T50", nombre_equipo, "Creado al importar Excel.")
            equipos[nombre_equipo.upper()] = equipo_id
            informe["equipos_nuevos"].append(nombre_equipo)

        fecha = _fecha(datos.get("fecha"))
        try:
            horas = float(str(datos.get("horas_vuelo")).replace(",", "."))
        except (TypeError, ValueError):
            horas = None
        if horas is None:
            # Avión: si no trae horas pero sí Hobbs inicial y final, las horas salen de ahí.
            try:
                horas = round(float(str(datos.get("hobbs_fin")).replace(",", "."))
                              - float(str(datos.get("hobbs_ini")).replace(",", ".")), 2)
            except (TypeError, ValueError):
                horas = None
        if horas is None or horas <= 0:
            informe["ignoradas"] += 1
            informe["errores"].append({"fila": n, "motivo": "Horas de vuelo vacías o no numéricas (en un avión vale también Hobbs inicial y final)."})
            continue
        errores = core_db.validar_operacion({k: datos.get(k) for k in core_db.RANGOS_OPERACION if k in datos}
                                            | {"horas_vuelo": horas, "fecha": fecha,
                                               "hobbs_ini": datos.get("hobbs_ini"), "hobbs_fin": datos.get("hobbs_fin"),
                                               "tach_ini": datos.get("tach_ini"), "tach_fin": datos.get("tach_fin")})
        if errores:
            informe["ignoradas"] += 1
            informe["errores"].append({"fila": n, "motivo": "; ".join(errores)})
            continue

        campos = {k: datos.get(k) for k in core_db.CAMPOS_OPERACION if k in datos}
        campos["horas_vuelo"] = horas
        campos["fecha"] = fecha

        id_existente = datos.get("id")
        try:
            id_existente = int(id_existente) if id_existente not in (None, "") else None
        except (TypeError, ValueError):
            id_existente = None

        if id_existente and con.execute("SELECT 1 FROM operaciones WHERE id=?", (id_existente,)).fetchone():
            core_db.actualizar_operacion(con, id_existente, campos, commit=False, recalcular=False)
            tocados.add(con.execute("SELECT equipo_id FROM operaciones WHERE id=?", (id_existente,)).fetchone()["equipo_id"])
            informe["actualizadas"] += 1
        else:
            extras = {k: core_db._valor_operacion(k, campos.get(k)) for k in core_db.CAMPOS_OPERACION
                      if k not in ("fecha", "horas_vuelo")}
            core_db.registrar_operacion(con, equipo_id, horas, fecha=fecha, commit=False, recalcular=False, **extras)
            tocados.add(equipo_id)
            informe["creadas"] += 1

    # El uso de las piezas se recalcula una vez por equipo, no una vez por fila.
    for eid in tocados:
        core_flota.recalcular_equipo(con, eid)
    con.commit()
    informe["mensaje"] = (f"{informe['creadas']} creada(s), {informe['actualizadas']} actualizada(s)"
                          + (f", {informe['ignoradas']} ignorada(s)" if informe["ignoradas"] else ""))
    return informe


# ===================== Contactos =====================
# Mismo contrato que operaciones: se descarga con el directorio al día, se edita en Excel y se
# vuelve a subir. La columna ID decide entre actualizar y crear.

HOJA_CONTACTOS = "Contactos"

COLUMNAS_CONTACTOS = [
    ("id",             "ID",                  8,  "0"),
    ("nombre",         "Nombre completo *",   26, None),
    ("rol",            "Rol *",               24, None),
    ("cargo",          "Cargo",               26, None),
    ("empresa",        "Empresa",             22, None),
    ("documento",      "Documento",           16, None),
    ("email",          "Correo",              26, None),
    ("telefono",       "Teléfono",            16, None),
    ("telefono2",      "Teléfono alterno",    16, None),
    ("ciudad",         "Ciudad",              16, None),
    ("direccion",      "Dirección",           28, None),
    ("licencia",       "Licencia",            20, None),
    ("licencia_vence", "Licencia vence",      15, "dd/mm/yyyy"),
    ("ingreso",        "Fecha de ingreso",    16, "dd/mm/yyyy"),
    ("activo",         "Activo",              9,  None),
    ("nota",           "Notas",               36, None),
]

GRUPOS_CONTACTOS = [
    ("Identificación", ["id", "nombre", "rol", "cargo"]),
    ("Organización",   ["empresa", "documento"]),
    ("Contacto",       ["email", "telefono", "telefono2", "ciudad", "direccion"]),
    ("Licencia",       ["licencia", "licencia_vence", "ingreso"]),
    ("Estado",         ["activo", "nota"]),
]

AYUDA_CONTACTOS = [
    ("Cómo usar este archivo", True),
    ("", False),
    ("1. Se descarga con todos los contactos registrados hasta hoy.", False),
    ("2. Corrige lo que haga falta y añade los contactos nuevos al final.", False),
    ("3. Vuelve a subir este mismo archivo en Contactos › Importar.", False),
    ("", False),
    ("Reglas", True),
    ("· ID: no lo toques. Con ID la fila actualiza ese contacto; vacío, crea uno nuevo.", False),
    ("· Nombre: obligatorio. Es el que enlaza al contacto con sus órdenes de trabajo y servicio.", False),
    ("· Rol y Activo: elige de la lista desplegable; no admiten otros valores.", False),
    ("· Sólo piloto, técnico, administrador y operario reciben órdenes de trabajo o de servicio.", False),
    ("· Cargo, Empresa y Ciudad traen desplegable con lo ya usado, pero aceptan valores nuevos.", False),
    ("· Cargo: texto libre, el puesto tal y como se escribiría en una firma.", False),
    ("· Activo: «Sí» o «No». Un contacto inactivo se conserva pero no sale al asignar trabajo.", False),
    ("· Fechas: formato dd/mm/aaaa o aaaa-mm-dd.", False),
    ("· Para eliminar un contacto, hazlo desde la app: borrar la fila aquí no lo borra.", False),
]


def contactos_para_excel(con):
    filas = con.execute(
        "SELECT id, nombre, rol, cargo, empresa, documento, email, telefono, telefono2, ciudad, "
        "       direccion, licencia, licencia_vence, ingreso, activo, nota "
        "FROM personal ORDER BY activo DESC, nombre").fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["rol"] = core_db.ROLES.get(d["rol"], d["rol"])   # en Excel se ve la etiqueta, no la clave
        d["activo"] = "Sí" if d["activo"] else "No"
        salida.append(d)
    return salida


def libro_contactos(con, filas=None):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = HOJA_CONTACTOS
    filas = filas if filas is not None else contactos_para_excel(con)

    activos = sum(1 for c in filas if str(c.get("activo")).lower() in ("sí", "si", "1"))
    _cabecera_formal(
        ws, COLUMNAS_CONTACTOS, GRUPOS_CONTACTOS,
        "Directorio de contactos",
        "Corrige lo que haga falta y añade los contactos nuevos al final. La columna ID no se toca.",
        f"Generado el {date.today().strftime('%d/%m/%Y')}  ·  {len(filas)} contacto(s)  ·  "
        f"{activos} activo(s)  ·  Este archivo es el que se sube a Drive")
    _cuerpo(ws, COLUMNAS_CONTACTOS, filas, campos_fecha=("licencia_vence", "ingreso"))
    _imprimir(ws, COLUMNAS_CONTACTOS)

    listas = {
        "roles": list(core_db.ROLES.values()),
        "si_no": ["Sí", "No"],
        "cargos": _valores_distintos(con, "SELECT DISTINCT cargo FROM personal WHERE cargo IS NOT NULL ORDER BY 1"),
        "empresas": _valores_distintos(con,
            "SELECT DISTINCT empresa FROM personal WHERE empresa IS NOT NULL "
            "UNION SELECT DISTINCT cliente FROM ordenes_servicio WHERE cliente IS NOT NULL ORDER BY 1"),
        "ciudades": _valores_distintos(con,
            "SELECT DISTINCT ciudad FROM personal WHERE ciudad IS NOT NULL "
            "UNION SELECT DISTINCT zona FROM operaciones WHERE zona IS NOT NULL ORDER BY 1"),
    }
    rangos = _hoja_listas(wb, listas)
    n = FILA_DATOS + len(filas) + FILAS_LIBRES
    C = COLUMNAS_CONTACTOS
    _validar(ws, _letra(C, "rol"),       rangos.get("roles"),    n, "Rol en la app", estricto=True)
    _validar(ws, _letra(C, "activo"),    rangos.get("si_no"),    n, "Activo", estricto=True)
    _validar(ws, _letra(C, "cargo"),     rangos.get("cargos"),   n, "Cargo")
    _validar(ws, _letra(C, "empresa"),   rangos.get("empresas"), n, "Empresa")
    _validar(ws, _letra(C, "ciudad"),    rangos.get("ciudades"), n, "Ciudad")
    _hoja_ayuda(wb, AYUDA_CONTACTOS)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


ALIAS_CONTACTOS = {
    "id": "id", "nombre completo": "nombre", "nombre": "nombre", "rol": "rol",
    "cargo": "cargo", "puesto": "cargo", "empresa": "empresa", "compania": "empresa",
    "documento": "documento", "cedula": "documento", "nit": "documento",
    "correo": "email", "email": "email", "correo electronico": "email",
    "telefono": "telefono", "celular": "telefono", "movil": "telefono",
    "telefono alterno": "telefono2", "telefono 2": "telefono2",
    "ciudad": "ciudad", "direccion": "direccion",
    "licencia": "licencia", "licencia vence": "licencia_vence", "vence": "licencia_vence",
    "fecha de ingreso": "ingreso", "ingreso": "ingreso",
    "activo": "activo", "notas": "nota", "nota": "nota", "observaciones": "nota",
}


def _rol_desde_excel(valor):
    """Acepta tanto la clave interna («tecnico») como la etiqueta que se ve en Excel."""
    texto = _normalizar(valor)
    if not texto:
        return None
    for clave, etiqueta in core_db.ROLES.items():
        if texto in (_normalizar(clave), _normalizar(etiqueta)):
            return clave
    return None


def _si_no(valor, defecto=1):
    texto = _normalizar(valor)
    if texto in ("si", "s", "1", "true", "verdadero", "x", "activo"):
        return 1
    if texto in ("no", "n", "0", "false", "falso", "inactivo"):
        return 0
    return defecto


def procesar_importacion_contactos(con, stream):
    """Lee el .xlsx subido y crea/actualiza contactos. No borra nada."""
    import openpyxl
    wb = openpyxl.load_workbook(stream, data_only=True)
    ws = wb[HOJA_CONTACTOS] if HOJA_CONTACTOS in wb.sheetnames else wb.worksheets[0]

    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return {"ok": False, "error": "El archivo está vacío."}

    fila_titulos, cabecera = _localizar_cabecera(filas, ALIAS_CONTACTOS, ("nombre",))
    if cabecera is None:
        return {"ok": False, "error": "No encuentro la columna «Nombre completo». "
                                      "Usa el archivo que descarga la app."}

    informe = {"ok": True, "creados": 0, "actualizados": 0, "ignorados": 0, "errores": []}
    for n, fila in enumerate(filas[fila_titulos + 1:], start=fila_titulos + 2):
        datos = {}
        for i, clave in enumerate(cabecera):
            if clave and i < len(fila):
                datos[clave] = fila[i]
        if not any(v not in (None, "") for v in datos.values()):
            continue

        nombre = str(datos.get("nombre") or "").strip()
        if not nombre:
            informe["ignorados"] += 1
            informe["errores"].append({"fila": n, "motivo": "Sin nombre."})
            continue

        campos = {}
        for clave in core_db.CAMPOS_PERSONA:
            if clave not in datos:
                continue
            valor = datos[clave]
            if clave == "rol":
                valor = _rol_desde_excel(valor) or "tecnico"
            elif clave == "activo":
                valor = _si_no(valor)
            elif clave in ("licencia_vence", "ingreso"):
                valor = _fecha(valor)
            elif isinstance(valor, str):
                valor = valor.strip() or None
            campos[clave] = valor
        campos["nombre"] = nombre
        campos.setdefault("rol", "tecnico")
        campos.setdefault("activo", 1)

        id_existente = datos.get("id")
        try:
            id_existente = int(id_existente) if id_existente not in (None, "") else None
        except (TypeError, ValueError):
            id_existente = None

        existe = id_existente and con.execute("SELECT 1 FROM personal WHERE id=?", (id_existente,)).fetchone()
        if not existe:
            # Sin ID válido se busca por nombre, para que reimportar un archivo editado a mano no
            # cree duplicados de gente que ya estaba.
            fila_previa = con.execute("SELECT id FROM personal WHERE nombre=? COLLATE NOCASE", (nombre,)).fetchone()
            id_existente = fila_previa["id"] if fila_previa else None
            existe = bool(fila_previa)

        if existe:
            sets = ", ".join(f"{k}=?" for k in campos)
            con.execute(f"UPDATE personal SET {sets}, actualizado=datetime('now') WHERE id=?",
                        (*campos.values(), id_existente))
            informe["actualizados"] += 1
        else:
            cols = ", ".join(campos)
            con.execute(f"INSERT INTO personal({cols}) VALUES({', '.join('?' * len(campos))})",
                        tuple(campos.values()))
            informe["creados"] += 1

    con.commit()
    informe["mensaje"] = (f"{informe['creados']} creado(s), {informe['actualizados']} actualizado(s)"
                          + (f", {informe['ignorados']} ignorado(s)" if informe["ignorados"] else ""))
    return informe
