#!/usr/bin/env python3
"""Tareas de administración de Hangar (se corren en el servidor, no desde la interfaz).

  python manage.py init                                  crea/actualiza el esquema y siembra los catálogos
  python manage.py empresas                              lista las empresas
  python manage.py crear-empresa "Nombre"                crea una empresa (devuelve su id)
  python manage.py migrar-sqlite datos/app.db [EMPRESA]  copia los datos de la base SQLite antigua a esa
                                                         empresa (id o nombre; si no existe se crea)
  python manage.py importar-bitacora X.xlsx EMPRESA      importa la bitácora Excel en esa empresa
  python manage.py crear-admin usuario [EMPRESA]         crea (o restablece la clave de) un administrador;
                                                         sin empresa crea un SUPERadministrador
  python manage.py usuarios                              lista todas las cuentas
  python manage.py completar-bitacora X.xlsx [EMPRESA]   rellena en las operaciones ya importadas las ha
                                                         programadas, dosis y clima (sólo campos vacíos)
  python manage.py fotos-estado                          guarda el estado del día de cada activo de todas
                                                         las empresas (disponibilidad histórica; cron diario)
"""
import getpass
import sqlite3
import sys

from core import db as core_db


def cmd_init():
    core_db.inicializar()
    print("Esquema listo y catálogos sembrados.")


def _resolver_empresa(con, ref, crear=True):
    """Empresa por id o por nombre; si no existe y `crear`, se crea."""
    if ref is None:
        return None
    if str(ref).isdigit():
        emp = core_db.empresa(con, int(ref))
        if not emp:
            print(f"No existe la empresa con id {ref}."); sys.exit(1)
        return emp["id"]
    emp = con.execute("SELECT id FROM empresas WHERE lower(nombre)=lower(?)", (ref,)).fetchone()
    if emp:
        return emp["id"]
    if not crear:
        print(f"No existe la empresa «{ref}»."); sys.exit(1)
    eid = core_db.crear_empresa(con, ref)
    print(f"Empresa «{ref}» creada con id {eid}.")
    return eid


def cmd_empresas():
    con = core_db.conectar(core_db.TODAS)
    for e in core_db.empresas(con):
        print(f"  {e['id']:3d}  {e['nombre']:35s} {'activa' if e['activa'] else 'inactiva':9s} {e['n_equipos']} equipos · {e['n_usuarios']} usuarios")
    con.close()


def cmd_crear_empresa(nombre):
    con = core_db.conectar(core_db.TODAS)
    print("id:", core_db.crear_empresa(con, nombre))
    con.close()


def cmd_migrar_sqlite(ruta, empresa_ref=None):
    """Vuelca la base SQLite (de una sola empresa) en PostgreSQL conservando los `id`.

    Los datos quedan asignados a la empresa indicada. Sólo se puede usar sobre una empresa
    vacía: los id de la base antigua se conservan tal cual.
    """
    core_db.inicializar()          # esquema + catálogo global de piezas, contra el que se emparejan
    viejo = sqlite3.connect(ruta)
    viejo.row_factory = sqlite3.Row
    con = core_db.conectar(core_db.TODAS)
    empresa_id = _resolver_empresa(con, empresa_ref) if empresa_ref else _resolver_empresa(con, "Empresa principal")
    vacia = con.execute("SELECT 1 FROM equipos WHERE empresa_id=? LIMIT 1", (empresa_id,)).fetchone()
    if vacia or con.execute("SELECT 1 FROM operaciones WHERE empresa_id=? LIMIT 1", (empresa_id,)).fetchone():
        print("Esa empresa ya tiene datos; la migración desde SQLite sólo se hace sobre una empresa vacía.")
        sys.exit(1)
    # Los id de la base antigua sólo se pueden conservar si no chocan con los de otras empresas.
    for t in ("equipos", "operaciones", "componentes", "mantenimientos", "personal", "ordenes_trabajo", "ordenes_servicio"):
        if con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone():
            conservar_ids = False
            break
    else:
        conservar_ids = True
    if not conservar_ids:
        print("Ya hay otras empresas con datos: los id se reasignan (se conservan las relaciones).")
    # Esta conexión escribe con la empresa destino: el DEFAULT de empresa_id la rellena.
    con.fijar_empresa(empresa_id)
    con.execute("DELETE FROM login_intentos")
    total = 0
    mapas = {}   # tabla -> {id viejo: id nuevo} cuando no se conservan los id
    FK = {"componentes": {"equipo_id": "equipos"}, "operaciones": {"equipo_id": "equipos"},
          "registros": {"equipo_id": "equipos"},
          "mantenimientos": {"equipo_id": "equipos", "componente_id": "componentes", "orden_id": "ordenes_trabajo"},
          "ordenes_trabajo": {"equipo_id": "equipos"}, "ot_tareas": {"orden_id": "ordenes_trabajo", "componente_id": "componentes"},
          "ordenes_servicio": {"equipo_id": "equipos"}, "os_productos": {"orden_id": "ordenes_servicio"},
          "os_eventos": {"orden_id": "ordenes_servicio"}}
    # El catálogo de piezas es global (lo siembra la app); las piezas de la base vieja se
    # emparejan por (modelo, clave), no por id, porque el id puede ser otro en esta base.
    piezas_pg = {(f["modelo"], f["clave"]): f["id"] for f in con.execute("SELECT id, modelo, clave FROM catalogo_piezas").fetchall()}
    try:
        piezas_viejas = {f["id"]: piezas_pg.get((f["modelo"], f["clave"]))
                         for f in viejo.execute("SELECT id, modelo, clave FROM catalogo_piezas").fetchall()}
    except sqlite3.OperationalError:
        piezas_viejas = {f["id"]: piezas_pg.get(("T50", f["clave"]))
                         for f in viejo.execute("SELECT id, clave FROM catalogo_piezas").fetchall()}
    for tabla in core_db.TABLAS:
        if tabla in ("login_intentos", "empresas", "catalogo_piezas", "catalogo_despiece"):
            continue
        try:
            filas = viejo.execute(f"SELECT * FROM {tabla}").fetchall()
        except sqlite3.OperationalError:
            print(f"  {tabla:20s} (no existe en SQLite, se omite)")
            continue
        if not filas:
            print(f"  {tabla:20s} 0")
            continue
        if tabla == "componentes":
            filas = [f for f in filas if piezas_viejas.get(f["pieza_id"])]
            if not filas:
                print(f"  {tabla:20s} 0 (ninguna pieza coincide con el catálogo actual)")
                continue
        if core_db.ES_SQLITE:
            columnas_pg = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})").fetchall()}
        else:
            columnas_pg = {f["column_name"] for f in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=?", (tabla,)).fetchall()}
        columnas = [c for c in filas[0].keys() if c in columnas_pg and c != "empresa_id"]
        if tabla == "usuarios":
            columnas = [c for c in columnas if c != "id"]     # los usuarios son globales: id nuevo
        if not conservar_ids and "id" in columnas:
            columnas.remove("id")
        mapas[tabla] = {}
        marcas = ",".join("?" * len(columnas))
        extra = ", empresa_id" if tabla == "usuarios" else ""
        sql = f"INSERT INTO {tabla}({', '.join(columnas)}{extra}) VALUES({marcas}{', ?' if extra else ''})"
        for f in filas:
            valores = []
            for c in columnas:
                v = f[c]
                ref = FK.get(tabla, {}).get(c)
                if ref and v is not None and not conservar_ids:
                    v = mapas.get(ref, {}).get(v)
                if c == "pieza_id" and v is not None:
                    v = piezas_viejas.get(v)
                valores.append(v)
            if extra:
                valores.append(empresa_id)
            if tabla == "usuarios":
                # El nombre de usuario es único en todo el sistema: si ya existe en otra empresa se
                # le añade un sufijo y se avisa.
                i_usuario = columnas.index("usuario")
                nombre = valores[i_usuario]
                if con.execute("SELECT 1 FROM usuarios WHERE usuario=?", (nombre,)).fetchone():
                    valores[i_usuario] = f"{nombre}_{empresa_id}"
                    print(f"  AVISO: el usuario «{nombre}» ya existía; en esta empresa se llama «{valores[i_usuario]}»")
            cur = con.execute(sql, tuple(valores))
            if "id" in f.keys():
                mapas[tabla][f["id"]] = cur.lastrowid or f["id"]
        # Las secuencias arrancan donde se quedaron los id.
        if "id" in columnas_pg and not core_db.ES_SQLITE:
            con.execute(f"SELECT setval(pg_get_serial_sequence('{tabla}','id'), "
                        f"COALESCE((SELECT MAX(id) FROM {tabla}), 0) + 1, false)")
        print(f"  {tabla:20s} {len(filas)}")
        total += len(filas)
    con.commit()
    con.close()
    # Con los id del catálogo ya copiados, la siembra sólo actualiza nombres y vidas útiles.
    core_db.inicializar()
    print(f"Migradas {total} filas desde {ruta} a la empresa {empresa_id}.")


def cmd_importar_bitacora(ruta, empresa_ref):
    from core import importar_bitacora
    admin = core_db.conectar(core_db.TODAS)
    empresa_id = _resolver_empresa(admin, empresa_ref, crear=False)
    admin.close()
    with core_db.conectar(empresa_id) as con:
        n = importar_bitacora.importar(con, ruta)
    print(f"Bitácora importada en la empresa {empresa_id}: {n} operaciones nuevas.")


def cmd_completar_bitacora(ruta, empresa_ref=None):
    from core import importar_bitacora
    admin = core_db.conectar(core_db.TODAS)
    ids = ([_resolver_empresa(admin, empresa_ref, crear=False)] if empresa_ref else
           [e["id"] for e in core_db.empresas(admin)])
    admin.close()
    for eid in ids:
        with core_db.conectar(eid) as con:
            inf = importar_bitacora.completar(con, ruta)
        if inf["actualizadas"] or empresa_ref:
            print(f"Empresa {eid}: {inf['actualizadas']} operaciones completadas ({inf['campos']} datos), "
                  f"{inf['descartados']} valores fuera de rango descartados.")


def cmd_fotos_estado():
    """Foto diaria del estado de cada activo. La app también la toma cuando alguien abre la flota,
    pero con el cron quedan registrados los días en que nadie entra."""
    from core import alertas as core_alertas, flota as core_flota
    admin = core_db.conectar(core_db.TODAS)
    ids = [e["id"] for e in core_db.empresas(admin)]
    admin.close()
    total = 0
    for eid in ids:
        with core_db.conectar(eid) as con:
            equipos = [dict(e) for e in con.execute("SELECT id, estado FROM equipos").fetchall()]
            activos = [e for e in equipos if e["estado"] != "baja"]
            estados = core_alertas.estado_flota(con, activos)
            core_flota.registrar_estado_diario(con, estados, equipos)
            con.commit()
            total += len(equipos)
    print(f"Estado del día guardado para {total} activos de {len(ids)} empresa(s).")


def cmd_crear_admin(usuario, empresa_ref=None):
    clave = getpass.getpass("Contraseña: ")
    if len(clave) < 8 or clave != getpass.getpass("Repite la contraseña: "):
        print("La contraseña debe tener 8 caracteres o más y coincidir.")
        sys.exit(1)
    con = core_db.conectar(core_db.TODAS)
    empresa_id = _resolver_empresa(con, empresa_ref, crear=False) if empresa_ref else None
    rol = "admin" if empresa_id else core_db.ROL_SUPERADMIN
    if con.execute("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)).fetchone():
        core_db.cambiar_password(con, usuario, clave)
        con.execute("UPDATE usuarios SET rol=?, activo=1, empresa_id=COALESCE(?, empresa_id) WHERE usuario=?",
                    (rol, empresa_id, usuario))
        con.commit()
        print(f"Contraseña de «{usuario}» restablecida (rol {rol}, activo).")
    else:
        core_db.crear_usuario(con, usuario, clave, rol=rol, empresa_id=empresa_id)
        print(f"Usuario «{usuario}» creado con rol {rol}.")
    con.close()


def cmd_usuarios():
    con = core_db.conectar(core_db.TODAS)
    for u in con.execute("SELECT u.usuario, u.rol, u.activo, u.ultimo_acceso, e.nombre empresa FROM usuarios u "
                         "LEFT JOIN empresas e ON e.id=u.empresa_id ORDER BY e.nombre, u.usuario").fetchall():
        print(f"  {u['usuario']:20s} {u['rol']:10s} {'activo' if u['activo'] else 'inactivo':8s} {u['empresa'] or '-':30s} {u['ultimo_acceso'] or '-'}")
    con.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(1)
    cmd, resto = args[0], args[1:]
    try:
        if cmd == "init":
            cmd_init()
        elif cmd == "empresas":
            cmd_empresas()
        elif cmd == "crear-empresa":
            cmd_crear_empresa(resto[0])
        elif cmd == "migrar-sqlite":
            cmd_migrar_sqlite(resto[0], resto[1] if len(resto) > 1 else None)
        elif cmd == "importar-bitacora":
            cmd_importar_bitacora(resto[0], resto[1])
        elif cmd == "crear-admin":
            cmd_crear_admin(resto[0], resto[1] if len(resto) > 1 else None)
        elif cmd == "completar-bitacora":
            cmd_completar_bitacora(resto[0], resto[1] if len(resto) > 1 else None)
        elif cmd == "fotos-estado":
            cmd_fotos_estado()
        elif cmd == "usuarios":
            cmd_usuarios()
        else:
            print(__doc__); sys.exit(1)
    except IndexError:
        print(__doc__); sys.exit(1)
