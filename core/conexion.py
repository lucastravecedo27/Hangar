"""Conexión a la base de datos: SQLite en el escritorio, PostgreSQL en el servidor.

Las dos variantes tienen la misma forma de uso (la de sqlite3), así que el resto de la app no
sabe en cuál corre. Lo que sigue describe la variante PostgreSQL.

Toda la app se escribió contra `sqlite3`: `con.execute(sql, params).fetchone()["columna"]`,
`cur.lastrowid`, marcadores `?`, `date('now')`… En vez de reescribir ~150 consultas, esta capa
envuelve `psycopg` y traduce lo poco que difiere:

  · `?`               -> `%s`   (el marcador de psycopg; los `%` literales se escapan)
  · `datetime('now')` -> hora local en texto ISO, igual que guardaba SQLite
  · `date('now')`     -> fecha local en texto ISO
  · `date('now','start of month')` -> primer día del mes
  · `cur.lastrowid`   -> se añade `RETURNING id` a los INSERT y se guarda el id devuelto
  · filas             -> diccionarios; Decimal -> float y fechas -> texto ISO, para que
                         `jsonify` las escriba igual que antes

Las fechas se siguen guardando como TEXTO ISO (`YYYY-MM-DD`), exactamente como hacía la app:
así los filtros `fecha >= '2026-01-01'`, `substr(fecha,1,7)` y las plantillas siguen valiendo.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from core import config

try:                                   # en el escritorio no hace falta instalar psycopg
    import psycopg
except ImportError:                    # pragma: no cover
    psycopg = None

# Tablas sin columna `id`: a sus INSERT no se les añade RETURNING id.
_TABLAS_SIN_ID = {"meta", "login_intentos"}

_RE_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_TRADUCCIONES = (
    ("date('now','start of month')", "to_char(date_trunc('month', CURRENT_DATE), 'YYYY-MM-DD')"),
    ("datetime('now')", "to_char(now(), 'YYYY-MM-DD HH24:MI:SS')"),
    ("date('now')", "to_char(CURRENT_DATE, 'YYYY-MM-DD')"),
)


def traducir(sql, con_params=True):
    for viejo, nuevo in _TRADUCCIONES:
        sql = sql.replace(viejo, nuevo)
    if not con_params:
        # Sin parámetros psycopg no interpreta `%`: se deja el SQL tal cual.
        return sql
    # Los `%` literales (LIKE 'OT-%') hay que doblarlos antes de meter los `%s` de psycopg.
    if "%" in sql:
        sql = sql.replace("%", "%%")
    return sql.replace("?", "%s")


def _valor(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


class Fila(dict):
    """Fila como diccionario que además admite índice numérico (`fila[0]`), como sqlite3.Row."""

    def __getitem__(self, clave):
        if isinstance(clave, int):
            return list(self.values())[clave]
        return dict.__getitem__(self, clave)

    def keys(self):
        return list(dict.keys(self))


def _filas_dict(cursor):
    nombres = [d.name for d in cursor.description] if cursor.description else []

    def hacer(valores):
        return Fila((n, _valor(v)) for n, v in zip(nombres, valores))
    return hacer


class Cursor:
    """Lo que devuelve `con.execute(...)`: fetchone/fetchall/lastrowid/rowcount."""

    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def fetchone(self):
        try:
            return self._cur.fetchone()
        except Exception:
            return None

    def fetchall(self):
        try:
            return self._cur.fetchall()
        except Exception:
            return []

    @property
    def rowcount(self):
        return self._cur.rowcount

    def __iter__(self):
        return iter(self.fetchall())


class Conexion:
    def __init__(self, url=None, zona_horaria=None):
        self._con = psycopg.connect(url or config.DATABASE_URL, row_factory=_filas_dict)
        zona = zona_horaria or config.ZONA_HORARIA
        if re.fullmatch(r"[A-Za-z0-9_/+\-]+", zona):
            self._con.execute(f"SET TIME ZONE '{zona}'")
        self.empresa_id = None
        self.cache = {}

    def fijar_empresa(self, empresa_id):
        """Empresa de esta conexión: la leen las políticas RLS y el DEFAULT de empresa_id.
        `None` -> sin empresa (las tablas de datos quedan vacías); `"*"` -> todas (administración)."""
        self.empresa_id = empresa_id
        self.cache = {}
        if empresa_id is None:
            valor = ""
        elif empresa_id == "*":
            valor = "*"
        else:
            valor = str(int(empresa_id))
        self._con.execute("SELECT set_config('app.empresa_id', %s, false)", (valor,))

    def execute(self, sql, params=None):
        # Cualquier escritura invalida los cálculos memorizados de esta conexión (ver
        # core/alertas.componentes_con_estado).
        if self.cache and sql.lstrip()[:6].upper() != "SELECT":
            self.cache.clear()
        sql_pg = traducir(sql, params is not None)
        lastrowid = None
        m = _RE_INSERT.match(sql_pg)
        if m and m.group(1).lower() not in _TABLAS_SIN_ID and "returning" not in sql_pg.lower():
            sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING id"
            cur = self._con.execute(sql_pg, params) if params is not None else self._con.execute(sql_pg)
            fila = cur.fetchone()
            lastrowid = fila["id"] if fila else None
            return Cursor(cur, lastrowid)
        if params is None:
            cur = self._con.execute(sql_pg)
        else:
            cur = self._con.execute(sql_pg, tuple(params) if not isinstance(params, (tuple, list)) else params)
        return Cursor(cur)

    def executescript(self, sql):
        self._con.execute(sql)
        self._con.commit()

    def commit(self):
        self._con.commit()

    def rollback(self):
        self.cache.clear()
        self._con.rollback()

    def close(self):
        self._con.close()

    @property
    def closed(self):
        return self._con.closed

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, tb):
        if tipo is None:
            self._con.commit()
        else:
            self._con.rollback()
        self._con.close()
        return False


# ---------------------------------------------------------------------------------------------
# Variante SQLite (escritorio)
# ---------------------------------------------------------------------------------------------
import sqlite3


class _StringAgg:
    """string_agg(valor, separador) de PostgreSQL, que SQLite no trae (su group_concat no
    admite DISTINCT con separador propio)."""
    def __init__(self):
        self.vals = []
        self.sep = ","

    def step(self, valor, sep=","):
        if valor is not None:
            self.vals.append(str(valor))
        self.sep = sep

    def finalize(self):
        return self.sep.join(self.vals) if self.vals else None


def _dow(texto):
    """EXTRACT(DOW ...) de PostgreSQL: 0 = domingo."""
    try:
        return (datetime.strptime(str(texto)[:10], "%Y-%m-%d").weekday() + 1) % 7
    except (TypeError, ValueError):
        return None


def _abrir_sqlite(url):
    ruta = url.split("sqlite:///", 1)[1] if url.startswith("sqlite:///") else url
    from pathlib import Path
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta, timeout=15)
    con.row_factory = lambda cur, fila: Fila((d[0], _valor(v)) for d, v in zip(cur.description, fila))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    # Funciones de PostgreSQL que usa la app y SQLite no trae.
    con.create_function("LEFT", 2, lambda s, n: None if s is None else str(s)[:int(n)], deterministic=True)
    con.create_function("RIGHT", 2, lambda s, n: None if s is None else str(s)[-int(n):], deterministic=True)
    con.create_function("LEAST", -1, lambda *a: min((x for x in a if x is not None), default=None), deterministic=True)
    con.create_function("GREATEST", -1, lambda *a: max((x for x in a if x is not None), default=None), deterministic=True)
    con.create_function("DOW", 1, _dow, deterministic=True)
    con.create_aggregate("string_agg", 2, _StringAgg)
    return con


_RE_UPDATE_ALIAS = re.compile(r"(\bUPDATE\s+\w+)\s+(?!AS\b|SET\b)(\w+)\s+SET\b", re.IGNORECASE)


_RE_HOY = re.compile(r"to_char\(\s*CURRENT_DATE\s*,\s*'YYYY-MM-DD'\s*\)")
_RE_AHORA = re.compile(r"to_char\(\s*now\(\)\s*,\s*'YYYY-MM-DD HH24:MI:SS'\s*\)")
_RE_HOY_MENOS = re.compile(r"to_char\(\s*CURRENT_DATE\s*-\s*(\d+)\s*,\s*'YYYY-MM-DD'\s*\)")


class ConexionSQLite:
    """Misma interfaz que `Conexion`, sobre sqlite3. En el escritorio hay una sola empresa y no
    hay RLS: `fijar_empresa` sólo recuerda cuál es, para los INSERT que la necesiten."""

    def __init__(self, url=None):
        self._con = _abrir_sqlite(url or config.DATABASE_URL)
        self.empresa_id = None
        self.cache = {}
        # empresa_actual() de PostgreSQL: la empresa fijada en esta conexión (None si es «todas»).
        self._con.create_function("empresa_actual", 0,
                                  lambda: self.empresa_id if isinstance(self.empresa_id, int) else None)

    def fijar_empresa(self, empresa_id):
        self.empresa_id = empresa_id
        self.cache = {}

    def execute(self, sql, params=None):
        if self.cache and sql.lstrip()[:6].upper() != "SELECT":
            self.cache.clear()
        # SQLite da la hora UTC; la app trabaja con la hora local (igual que PostgreSQL con TZ).
        sql = sql.replace("date('now')", "date('now','localtime')").replace("datetime('now')", "datetime('now','localtime')")
        # «UPDATE tabla alias SET» (PostgreSQL) -> «UPDATE tabla AS alias SET» (SQLite).
        sql = _RE_UPDATE_ALIAS.sub(r"\1 AS \2 SET", sql)
        sql = _RE_HOY.sub("date('now','localtime')", sql)
        sql = _RE_AHORA.sub("datetime('now','localtime')", sql)
        sql = _RE_HOY_MENOS.sub(lambda m: f"date('now','localtime','-{m.group(1)} days')", sql)
        if params is None:
            cur = self._con.execute(sql)
        else:
            cur = self._con.execute(sql, tuple(params) if not isinstance(params, (tuple, list)) else params)
        return Cursor(cur, cur.lastrowid)

    def executescript(self, sql):
        self._con.executescript(sql)
        self._con.commit()

    def commit(self):
        self._con.commit()

    def rollback(self):
        self.cache.clear()
        self._con.rollback()

    def close(self):
        self._con.close()

    @property
    def closed(self):
        try:
            self._con.execute("SELECT 1")
            return False
        except sqlite3.ProgrammingError:
            return True

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, tb):
        if tipo is None:
            self._con.commit()
        else:
            self._con.rollback()
        self._con.close()
        return False


ES_SQLITE = config.MOTOR == "sqlite"

# Errores de integridad de cada motor, para que la app los capture sin importar psycopg.
if ES_SQLITE:
    ERROR_REFERENCIA = sqlite3.IntegrityError     # la app distingue por el mensaje
    ERROR_UNICO = sqlite3.IntegrityError
else:
    ERROR_REFERENCIA = psycopg.errors.ForeignKeyViolation
    ERROR_UNICO = psycopg.errors.UniqueViolation


def conectar(url=None):
    if ES_SQLITE if url is None else str(url).startswith("sqlite"):
        return ConexionSQLite(url)
    return Conexion(url)


# ---------------------------------------------------------------------------------------------
# Fragmentos de SQL que cambian entre motores
# ---------------------------------------------------------------------------------------------
def sql_fecha(expr):
    """Una fecha en texto ISO convertida a fecha comparable/restable."""
    return f"julianday({expr})" if ES_SQLITE else f"({expr})::date"


def sql_dias(desde, hasta):
    """Días enteros entre dos fechas ISO (hasta - desde)."""
    if ES_SQLITE:
        return f"CAST(julianday(substr({hasta},1,10)) - julianday(substr({desde},1,10)) AS INTEGER)"
    return f"(LEFT({hasta},10)::date - LEFT({desde},10)::date)"


def sql_hoy_menos_dias(param="?"):
    """Fecha ISO de hoy menos N días (N como parámetro)."""
    if ES_SQLITE:
        return f"date('now','localtime', '-' || CAST({param} AS INTEGER) || ' days')"
    return f"to_char(CURRENT_DATE - {param}::int, 'YYYY-MM-DD')"


def sql_hoy():
    """Fecha de hoy en texto ISO."""
    return "date('now','localtime')" if ES_SQLITE else "to_char(CURRENT_DATE, 'YYYY-MM-DD')"


def sql_dow(expr):
    """Día de la semana (0 = domingo) de una fecha ISO."""
    return f"DOW({expr})" if ES_SQLITE else f"EXTRACT(DOW FROM ({expr})::date)::int"
