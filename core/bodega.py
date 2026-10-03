"""Bodega: repuestos e insumos de operación, por ubicación, con kardex y control de consumo.

Dos bodegas en una misma tabla de artículos (`bodega_items.clase`):

  · repuesto  piezas de drones y del avión. Se enlazan al catálogo: `catalogo='pieza'` +
              `catalogo_ref` = clave de catalogo_piezas (las que tienen vida útil y aparecen en la
              proyección de repuestos) o `catalogo='despiece'` + código DJI de catalogo_despiece.
  · insumo    fitosanitarios (herbicidas, fungicidas, insecticidas), aceite agrícola,
              coadyuvantes, fertilizantes foliares, aceite de motor… con ingrediente activo,
              categoría toxicológica, registro ICA, lote y vencimiento.

Cinco tipos de movimiento (tabla `bodega_movimientos`):

  · entrada   compra o ingreso a una ubicación (y a un tanque, si es a granel). Lleva costo.
  · salida    consumo: en una orden de trabajo, en una operación o suelto.
  · traslado  de una ubicación (o tanque) a otra. No cambia el total ni el costo.
  · ajuste    conteo físico: se guarda lo contado y, en `cantidad`, el descuadre con signo.
  · baja      vencido, dañado, derrame: sale del inventario sin consumirse.

Como en el combustible, las existencias no se guardan: se reconstruyen en orden cronológico, así
corregir o borrar un movimiento viejo arregla solo los saldos siguientes. El costo es promedio
ponderado: cada entrada con precio lo recalcula y las salidas salen al promedio del momento.

Los lotes y su vencimiento se siguen por ubicación. Una salida sin lote consume primero el que
vence antes (FEFO), que es lo que se hace en la bodega de verdad.
"""
import re
import unicodedata
from datetime import date, timedelta

from core import flota as core_flota

CLASES = {"repuesto": "Repuestos", "insumo": "Insumos de operación"}

TIPOS = {"entrada": "Entrada / compra", "salida": "Salida / consumo", "traslado": "Traslado",
         "ajuste": "Ajuste por conteo", "baja": "Baja"}

# Qué tipos puede registrar cada rol (el administrador, todos). Crear artículos, ajustar por
# conteo, dar de baja y borrar es del administrador: son los que cambian el valor del inventario
# sin que salga nada a la operación.
TIPOS_POR_ROL = {"tecnico": ("entrada", "salida", "traslado"),
                 "certificador": ("entrada", "salida", "traslado"),
                 "piloto": ("salida", "traslado")}

MOTIVOS_SALIDA = {"consumo": "Consumo", "ot": "Orden de trabajo", "operacion": "Operación de aplicación",
                  "mantenimiento": "Mantenimiento menor", "otro": "Otro"}
MOTIVOS_BAJA = {"vencido": "Vencido", "danado": "Dañado", "derrame": "Derrame / fuga",
                "perdida": "Pérdida", "otro": "Otro"}

TIPOS_UBICACION = {"hangar": "Hangar", "pista": "Pista", "base": "Base de operación",
                   "vehiculo": "Vehículo de apoyo", "otro": "Otro"}

# Categorías de insumo con el color con que se pintan sus tanques y fichas (el usuario puede
# elegir otro por tanque). Ninguno es el amarillo de marca: el acento no se usa para datos.
CATEGORIAS_INSUMO = {
    "herbicida": {"nombre": "Herbicida", "color": "#6f8f2f", "fito": True},
    "fungicida": {"nombre": "Fungicida", "color": "#3b6fb6", "fito": True},
    "insecticida": {"nombre": "Insecticida", "color": "#b5542b", "fito": True},
    "coadyuvante": {"nombre": "Coadyuvante / adherente", "color": "#0d9488", "fito": True},
    "aceite_agricola": {"nombre": "Aceite agrícola", "color": "#c7a24a", "fito": True},
    "fertilizante": {"nombre": "Fertilizante foliar", "color": "#2f8f4e", "fito": False},
    "aceite_motor": {"nombre": "Aceite de motor", "color": "#6b4f2a", "fito": False},
    "otro": {"nombre": "Otro", "color": "#737a86", "fito": False},
}

# Productos que se proponen al crear un insumo de cada categoría (se rellenan solos al elegirlos).
PRODUCTOS_SUGERIDOS = {
    "aceite_agricola": [
        {"nombre": "Banole", "unidad": "L", "color": "#e3c77c",
         "nota": "Aceite mineral agrícola: vehículo y coadyuvante de las aplicaciones aéreas (banano, sigatoka)."},
    ],
}

# Categoría toxicológica (franja de color de la etiqueta en Colombia).
CATEGORIAS_TOX = {
    "I": {"nombre": "I · Extremadamente tóxico", "color": "#d7261e"},
    "II": {"nombre": "II · Altamente tóxico", "color": "#e8b500"},
    "III": {"nombre": "III · Medianamente tóxico", "color": "#1f5fbf"},
    "IV": {"nombre": "IV · Ligeramente tóxico", "color": "#2f8f4e"},
}

UNIDADES = {"und": "unidades", "L": "litros", "kg": "kilos", "gal": "galones", "mL": "mililitros", "g": "gramos"}

FORMAS_TANQUE = {"tanque": "Tanque vertical", "tambor": "Tambor (200 L)", "garrafa": "Garrafa / bidón",
                 "ibc": "IBC (1000 L)"}

DIAS_POR_VENCER = 60          # un lote que vence dentro de este plazo avisa
HORIZONTE_COMPRA = 90         # días de proyección de repuestos para la lista de compras
UMBRAL_DESCUADRE = 0.05       # |salidas − teórico| / teórico: ámbar
UMBRAL_DESCUADRE_ROJO = 0.10  # rojo
RETENCION_MESES = 12          # RAC 137.71(3)
EPS = 1e-9


def _num(v):
    return core_flota._num(v)


def _r(v, n=2):
    return None if v is None else round(v, n)


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# ======================================================================
# Catálogos de la empresa
# ======================================================================

def ubicaciones(con, incluir_inactivas=True):
    filas = con.execute("SELECT * FROM bodega_ubicaciones ORDER BY activo DESC, nombre").fetchall()
    return [dict(f) for f in filas if incluir_inactivas or f["activo"]]


def items(con, clase=None):
    cond, p = "", ()
    if clase:
        cond, p = "WHERE clase=?", (clase,)
    return [dict(f) for f in con.execute(f"SELECT * FROM bodega_items {cond} ORDER BY nombre", p).fetchall()]


def color_item(item):
    """Color con que se pinta un insumo: el propio si lo eligió el usuario, si no el de su categoría."""
    if not item:
        return "#737a86"
    if item.get("color"):
        return item["color"]
    if item.get("clase") == "insumo":
        return CATEGORIAS_INSUMO.get(item.get("categoria") or "otro", CATEGORIAS_INSUMO["otro"])["color"]
    return "#737a86"


CAMPOS_ITEM = ("clase", "nombre", "codigo", "modelo", "catalogo", "catalogo_ref", "categoria",
               "ingrediente_activo", "concentracion", "categoria_tox", "registro_ica", "unidad",
               "presentacion", "contenido", "stock_minimo", "cantidad_cambio", "dosis_ha", "proveedor",
               "costo_referencia", "color", "serializado", "activo", "nota", "propietario", "cliente")
# De quién es el producto. Lo que pone el cliente se registra (trazabilidad de la aplicación,
# RAC 137.71) pero no es inventario de la empresa: no tiene valor, mínimo ni alerta de compra.
PROPIETARIOS = {"empresa": "De la empresa", "cliente": "Del cliente"}
_NUMERICOS_ITEM = ("contenido", "stock_minimo", "cantidad_cambio", "dosis_ha", "costo_referencia")


def limpiar_item(datos, previo=None):
    """Valida y normaliza los campos de un artículo. Devuelve (campos, error)."""
    d = dict(previo or {})
    for k in CAMPOS_ITEM:
        if k in datos:
            v = datos[k]
            if k in _NUMERICOS_ITEM:
                v = _num(v)
            elif k in ("serializado", "activo"):
                v = 1 if v in (1, True, "1", "true", "on") else 0
            elif isinstance(v, str):
                v = v.strip() or None
            d[k] = v
    if not d.get("nombre"):
        return None, "falta el nombre del artículo"
    if d.get("clase") not in CLASES:
        d["clase"] = "repuesto"
    if d.get("unidad") not in UNIDADES:
        d["unidad"] = "und" if d["clase"] == "repuesto" else "L"
    if d["clase"] == "insumo" and d.get("categoria") not in CATEGORIAS_INSUMO:
        d["categoria"] = "otro"
    if d.get("categoria_tox") and d["categoria_tox"] not in CATEGORIAS_TOX:
        return None, "categoría toxicológica no válida (I, II, III o IV)"
    for k in ("stock_minimo", "contenido", "costo_referencia", "dosis_ha"):
        if d.get(k) is not None and d[k] < 0:
            return None, f"{k.replace('_', ' ')} no puede ser negativo"
    if d.get("stock_minimo") is None:
        d["stock_minimo"] = 0
    if not d.get("cantidad_cambio") or d["cantidad_cambio"] <= 0:
        d["cantidad_cambio"] = 1
    if d.get("color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", d["color"]):
        d["color"] = None
    if d.get("catalogo") not in (None, "pieza", "despiece"):
        d["catalogo"] = None
    if d.get("propietario") not in PROPIETARIOS:
        d["propietario"] = "empresa"
    if d["propietario"] == "cliente":
        if d["clase"] != "insumo":
            return None, "sólo los insumos de aplicación pueden ser del cliente"
        d["stock_minimo"] = 0
        d["costo_referencia"] = None
    else:
        d["cliente"] = None
    d.setdefault("serializado", 0)
    d.setdefault("activo", 1)
    return d, None


def guardar_item(con, d, id_=None):
    campos = [k for k in CAMPOS_ITEM if k in d]
    if id_:
        con.execute(f"UPDATE bodega_items SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?",
                    [d[k] for k in campos] + [id_])
        return id_
    cur = con.execute(f"INSERT INTO bodega_items({', '.join(campos)}) VALUES({', '.join('?' * len(campos))})",
                      [d[k] for k in campos])
    return cur.lastrowid


# ======================================================================
# Reconstrucción del inventario (existencias, costo promedio, lotes, tanques)
# ======================================================================

def _movs(con, item_id=None, desde=None, hasta=None):
    cond, p = ["1=1"], []
    if item_id:
        cond.append("m.item_id=?"); p.append(item_id)
    filas = con.execute(
        f"""SELECT m.*, u.nombre AS ubicacion, d.nombre AS destino, t.nombre AS tanque,
                   td.nombre AS tanque_destino, e.nombre AS equipo, o.codigo AS orden_codigo
            FROM bodega_movimientos m
            LEFT JOIN bodega_ubicaciones u ON u.id=m.ubicacion_id
            LEFT JOIN bodega_ubicaciones d ON d.id=m.destino_id
            LEFT JOIN bodega_tanques t ON t.id=m.tanque_id
            LEFT JOIN bodega_tanques td ON td.id=m.tanque_destino_id
            LEFT JOIN equipos e ON e.id=m.equipo_id
            LEFT JOIN ordenes_trabajo o ON o.id=m.orden_id
            WHERE {' AND '.join(cond)} ORDER BY m.fecha, m.id""", p).fetchall()
    return [dict(f) for f in filas]


def _clave_vence(l):
    return (l["vence"] is None, l["vence"] or "", l["lote"] or "")


def _sacar_lotes(lotes, cantidad, lote=None):
    """Descuenta `cantidad` de la lista de lotes de una ubicación: del lote pedido o, si no se
    dice, del que vence antes (FEFO). Devuelve los trozos sacados [(lote, vence, cant)]. Si no
    alcanza, el resto queda como saldo negativo «sin lote» (se ve y se corrige con un ajuste)."""
    sacado, falta = [], cantidad
    orden = sorted(lotes, key=_clave_vence)
    if lote:
        orden = [l for l in orden if l["lote"] == lote] + [l for l in orden if l["lote"] != lote]
    for l in orden:
        if falta <= EPS:
            break
        if l["cant"] <= EPS:
            continue
        t = min(l["cant"], falta)
        l["cant"] -= t
        falta -= t
        sacado.append((l["lote"], l["vence"], t))
    if falta > EPS:
        sin = next((l for l in lotes if l["lote"] is None and l["vence"] is None), None)
        if not sin:
            sin = {"lote": None, "vence": None, "cant": 0.0}
            lotes.append(sin)
        sin["cant"] -= falta
        sacado.append((None, None, falta))
    return sacado


def _meter_lote(lotes, lote, vence, cantidad):
    l = next((x for x in lotes if x["lote"] == lote and x["vence"] == vence), None)
    if not l:
        l = {"lote": lote, "vence": vence, "cant": 0.0}
        lotes.append(l)
    l["cant"] += cantidad


def reconstruir(con, item_id=None, movs=None):
    """Recorre el kardex en orden y devuelve ({item_id: estado}, movimientos anotados).

    estado = {saldo, costo_prom, valor, por_ubicacion{uid: cant}, por_tanque{tid: cant},
              lotes{uid: [{lote, vence, cant}]}, ultima_entrada, ultimo_costo, ultimo_proveedor}
    Cada movimiento sale con `saldo` (del artículo tras él), `costo_prom` y `valor` (cantidad × costo).
    """
    if movs is None:
        movs = _movs(con, item_id)
    est = {}
    for m in movs:
        s = est.setdefault(m["item_id"], {"saldo": 0.0, "costo_prom": None, "por_ubicacion": {}, "por_tanque": {},
                                          "lotes": {}, "ultima_entrada": None, "ultimo_costo": None,
                                          "ultimo_proveedor": None})
        c = m["cantidad"] or 0
        u, dst = m["ubicacion_id"], m["destino_id"]
        pu = s["por_ubicacion"]
        tipo = m["tipo"]
        if tipo == "entrada":
            cu = m["costo_unitario"]
            if cu is not None and c > 0:
                base = max(s["saldo"], 0)
                prom = s["costo_prom"] if s["costo_prom"] is not None else cu
                s["costo_prom"] = (base * prom + c * cu) / (base + c) if base + c > EPS else cu
                s["ultimo_costo"] = cu
            s["saldo"] += c
            pu[u] = pu.get(u, 0) + c
            _meter_lote(s["lotes"].setdefault(u, []), m["lote"], m["vence"], c)
            if m["tanque_id"]:
                s["por_tanque"][m["tanque_id"]] = s["por_tanque"].get(m["tanque_id"], 0) + c
            s["ultima_entrada"] = m["fecha"]
            if m["proveedor"]:
                s["ultimo_proveedor"] = m["proveedor"]
        elif tipo in ("salida", "baja"):
            s["saldo"] -= c
            pu[u] = pu.get(u, 0) - c
            _sacar_lotes(s["lotes"].setdefault(u, []), c, m["lote"])
            if m["tanque_id"]:
                s["por_tanque"][m["tanque_id"]] = s["por_tanque"].get(m["tanque_id"], 0) - c
        elif tipo == "traslado":
            pu[u] = pu.get(u, 0) - c
            pu[dst] = pu.get(dst, 0) + c
            for lote, vence, t in _sacar_lotes(s["lotes"].setdefault(u, []), c, m["lote"]):
                _meter_lote(s["lotes"].setdefault(dst, []), lote, vence, t)
            if m["tanque_id"]:
                s["por_tanque"][m["tanque_id"]] = s["por_tanque"].get(m["tanque_id"], 0) - c
            if m["tanque_destino_id"]:
                s["por_tanque"][m["tanque_destino_id"]] = s["por_tanque"].get(m["tanque_destino_id"], 0) + c
        elif tipo == "ajuste":
            s["saldo"] += c
            pu[u] = pu.get(u, 0) + c
            if c >= 0:
                _meter_lote(s["lotes"].setdefault(u, []), m["lote"], m["vence"], c)
            else:
                _sacar_lotes(s["lotes"].setdefault(u, []), -c, m["lote"])
            if m["tanque_id"]:
                s["por_tanque"][m["tanque_id"]] = s["por_tanque"].get(m["tanque_id"], 0) + c
        m["saldo"] = _r(s["saldo"], 3)
        m["costo_prom"] = _r(s["costo_prom"], 2)
        costo = m["costo_unitario"] if tipo == "entrada" and m["costo_unitario"] is not None else s["costo_prom"]
        m["valor"] = _r(abs(c) * costo, 0) if costo is not None else None
    for s in est.values():
        s["valor"] = _r(max(s["saldo"], 0) * (s["costo_prom"] or 0), 0)
        s["saldo"] = _r(s["saldo"], 3)
        s["por_ubicacion"] = {k: _r(v, 3) for k, v in s["por_ubicacion"].items() if abs(v) > EPS}
        s["por_tanque"] = {k: _r(v, 3) for k, v in s["por_tanque"].items()}
        s["lotes"] = {k: [dict(l, cant=_r(l["cant"], 3)) for l in sorted(v, key=_clave_vence) if abs(l["cant"]) > EPS]
                      for k, v in s["lotes"].items()}
    return est, movs


_VACIO = {"saldo": 0, "costo_prom": None, "valor": 0, "por_ubicacion": {}, "por_tanque": {}, "lotes": {},
          "ultima_entrada": None, "ultimo_costo": None, "ultimo_proveedor": None}


def reservas_abiertas(con):
    """{item_id: cantidad} apartada en órdenes de trabajo que siguen abiertas."""
    filas = con.execute(
        """SELECT l.item_id, SUM(l.cantidad) c FROM bodega_ot_lineas l
           JOIN ordenes_trabajo o ON o.id=l.orden_id
           WHERE l.estado='reservado' AND o.estado NOT IN ('completada','cancelada')
           GROUP BY l.item_id""").fetchall()
    return {f["item_id"]: f["c"] or 0 for f in filas}


def _consumo_dias(movs, dias=90, hoy=None):
    """{item_id: salidas de los últimos `dias`} (consumo, OT y operaciones; no bajas ni traslados)."""
    desde = ((hoy or date.today()) - timedelta(days=dias)).isoformat()
    salida = {}
    for m in movs:
        if m["tipo"] == "salida" and (m["fecha"] or "") >= desde:
            salida[m["item_id"]] = salida.get(m["item_id"], 0) + (m["cantidad"] or 0)
    return salida


def inventario(con, clase=None, hoy=None):
    """Todos los artículos con sus existencias, valor, disponibilidad, lotes y semáforo."""
    hoy = hoy or date.today()
    est, movs = reconstruir(con)
    reservas = reservas_abiertas(con)
    consumo = _consumo_dias(movs, 90, hoy)
    ubic = {u["id"]: u for u in ubicaciones(con)}
    limite = (hoy + timedelta(days=DIAS_POR_VENCER)).isoformat()
    salida = []
    for it in items(con, clase):
        s = est.get(it["id"], _VACIO)
        d = dict(it)
        d.update({k: s[k] for k in ("saldo", "costo_prom", "valor", "ultima_entrada", "ultimo_costo", "ultimo_proveedor")})
        d["costo"] = s["costo_prom"] if s["costo_prom"] is not None else it["costo_referencia"]
        d["reservado"] = _r(reservas.get(it["id"], 0), 3)
        d["disponible"] = _r((s["saldo"] or 0) - d["reservado"], 3)
        d["color_final"] = color_item(it)
        d["de_cliente"] = (it.get("propietario") or "empresa") == "cliente"
        if d["de_cliente"]:
            d["valor"] = 0   # no es de la empresa: no suma al valor del inventario
        d["existencias"] = [{"ubicacion_id": k, "ubicacion": (ubic.get(k) or {}).get("nombre") or "Sin ubicación",
                             "cantidad": v} for k, v in sorted(s["por_ubicacion"].items(), key=lambda x: -x[1])]
        lotes = []
        for uid, ls in s["lotes"].items():
            for l in ls:
                if l["cant"] > EPS and (l["lote"] or l["vence"]):
                    lotes.append({**l, "ubicacion_id": uid, "ubicacion": (ubic.get(uid) or {}).get("nombre") or "—"})
        lotes.sort(key=_clave_vence)
        d["lotes"] = lotes
        d["vencidos"] = _r(sum(l["cant"] for l in lotes if l["vence"] and l["vence"] < hoy.isoformat()), 3)
        d["por_vencer"] = _r(sum(l["cant"] for l in lotes if l["vence"] and hoy.isoformat() <= l["vence"] <= limite), 3)
        d["proximo_vence"] = next((l["vence"] for l in lotes if l["vence"]), None)
        c90 = consumo.get(it["id"], 0)
        d["consumo_90d"] = _r(c90, 3)
        d["cobertura_dias"] = int((s["saldo"] or 0) / (c90 / 90)) if c90 > EPS and (s["saldo"] or 0) > 0 else None
        # Semáforo del artículo: rojo sin existencias (o negativas, o vencido), ámbar bajo el mínimo
        # o por vencer, verde el resto.
        if (s["saldo"] or 0) < -EPS:
            d["nivel"], d["nivel_txt"] = "critico", "saldo negativo"
        elif d["vencidos"]:
            d["nivel"], d["nivel_txt"] = "critico", "lote vencido"
        elif it["stock_minimo"] and (s["saldo"] or 0) <= EPS:
            d["nivel"], d["nivel_txt"] = "critico", "agotado"
        elif it["stock_minimo"] and d["disponible"] < it["stock_minimo"]:
            d["nivel"], d["nivel_txt"] = "proximo", "bajo el mínimo"
        elif d["por_vencer"]:
            d["nivel"], d["nivel_txt"] = "proximo", "por vencer"
        else:
            d["nivel"], d["nivel_txt"] = "ok", "en orden"
        salida.append(d)
    return salida


def estado_tanques(con, inv=None):
    """Tanques con su contenido, nivel y porcentaje."""
    if inv is None:
        inv = inventario(con)
    por_id = {i["id"]: i for i in inv}
    est, _ = reconstruir(con)
    salida = []
    for t in con.execute(
            """SELECT t.*, u.nombre AS ubicacion FROM bodega_tanques t
               LEFT JOIN bodega_ubicaciones u ON u.id=t.ubicacion_id ORDER BY t.activo DESC, t.nombre""").fetchall():
        d = dict(t)
        it = por_id.get(t["item_id"])
        nivel = 0.0
        for s in est.values():
            nivel += s["por_tanque"].get(t["id"], 0)
        d["nivel"] = _r(nivel, 2)
        d["pct"] = _r(nivel / t["capacidad"] * 100, 1) if t["capacidad"] else None
        d["item"] = it["nombre"] if it else None
        d["unidad"] = it["unidad"] if it else "L"
        d["categoria"] = it["categoria"] if it else None
        d["color_final"] = t["color"] or (color_item(it) if it else "#9aa0aa")
        d["valor"] = _r(max(nivel, 0) * (it["costo"] or 0), 0) if it else 0
        d["vacio"] = abs(nivel) < 1e-6
        salida.append(d)
    return salida


# ======================================================================
# Movimientos
# ======================================================================

CAMPOS_MOV = ("tipo", "fecha", "item_id", "ubicacion_id", "destino_id", "tanque_id", "tanque_destino_id",
              "cantidad", "conteo", "costo_unitario", "lote", "vence", "serie", "proveedor", "documento",
              "motivo", "equipo_id", "orden_id", "ot_linea_id", "operacion_id", "responsable", "nota", "usuario")


def _entero(v):
    try:
        return int(v) if v not in (None, "", "x") else None
    except (TypeError, ValueError):
        return None


def disponible_en(con, item_id, ubicacion_id=None, tanque_id=None, est=None):
    if est is None:
        est, _ = reconstruir(con, item_id)
    s = est.get(item_id, _VACIO)
    if tanque_id:
        return s["por_tanque"].get(tanque_id, 0)
    if ubicacion_id:
        return s["por_ubicacion"].get(ubicacion_id, 0)
    return s["saldo"]


def validar_mov(con, datos, rol="admin", hoy=None):
    """Valida un movimiento y lo deja listo para guardar. Devuelve (movimiento, error, avisos)."""
    hoy = hoy or date.today()
    m = {k: datos.get(k) for k in CAMPOS_MOV}
    avisos = []
    if m["tipo"] not in TIPOS:
        return None, "tipo de movimiento no válido", avisos
    permitidos = TIPOS_POR_ROL.get(rol)
    if permitidos is not None and m["tipo"] not in permitidos:
        return None, f"tu rol no puede registrar «{TIPOS[m['tipo']].lower()}»; pídelo al administrador", avisos
    for k in ("item_id", "ubicacion_id", "destino_id", "tanque_id", "tanque_destino_id", "equipo_id",
              "orden_id", "ot_linea_id", "operacion_id"):
        m[k] = _entero(m[k])
    for k in ("cantidad", "conteo", "costo_unitario"):
        m[k] = _num(m[k])
    for k in ("lote", "vence", "serie", "proveedor", "documento", "motivo", "responsable", "nota"):
        m[k] = (str(m[k]).strip() or None) if m[k] not in (None, "") else None
    m["fecha"] = (datos.get("fecha") or hoy.isoformat())[:10]
    try:
        if date.fromisoformat(m["fecha"]) > hoy:
            return None, "la fecha no puede ser futura", avisos
    except ValueError:
        return None, "fecha no válida", avisos
    if m["vence"]:
        try:
            date.fromisoformat(m["vence"])
        except ValueError:
            return None, "fecha de vencimiento no válida", avisos
    item = con.execute("SELECT * FROM bodega_items WHERE id=?", (m["item_id"],)).fetchone() if m["item_id"] else None
    if not item:
        return None, "elige el artículo", avisos
    unidad = item["unidad"]

    # El tanque manda sobre la ubicación: está en un sitio y guarda un producto.
    for campo_t, campo_u in (("tanque_id", "ubicacion_id"), ("tanque_destino_id", "destino_id")):
        if m[campo_t]:
            t = con.execute("SELECT * FROM bodega_tanques WHERE id=?", (m[campo_t],)).fetchone()
            if not t:
                return None, "el tanque no existe", avisos
            if t["item_id"] != item["id"]:
                return None, f"el tanque «{t['nombre']}» no está configurado para {item['nombre']}", avisos
            if t["ubicacion_id"]:
                m[campo_u] = t["ubicacion_id"]
    if not m["ubicacion_id"]:
        return None, "elige la ubicación", avisos
    if not con.execute("SELECT 1 FROM bodega_ubicaciones WHERE id=?", (m["ubicacion_id"],)).fetchone():
        return None, "la ubicación no existe", avisos

    est, _ = reconstruir(con, item["id"])
    en_origen = disponible_en(con, item["id"], m["ubicacion_id"], m["tanque_id"], est)

    if m["tipo"] == "ajuste":
        if m["conteo"] is None or m["conteo"] < 0:
            return None, "anota cuánto contaste (cero o más)", avisos
        m["cantidad"] = round(m["conteo"] - en_origen, 4)
        if abs(m["cantidad"]) < 1e-9:
            avisos.append("El conteo coincide con el sistema: el ajuste queda como constancia, sin descuadre.")
    else:
        if m["cantidad"] is None or m["cantidad"] <= 0:
            return None, f"la cantidad debe ser mayor que cero ({unidad})", avisos

    if m["tipo"] == "entrada":
        if m["costo_unitario"] is not None and m["costo_unitario"] < 0:
            return None, "el costo no puede ser negativo", avisos
        if m["costo_unitario"] is None:
            s = est.get(item["id"], _VACIO)
            m["costo_unitario"] = s["costo_prom"] if s["costo_prom"] is not None else item["costo_referencia"]
        if m["tanque_id"]:
            t = con.execute("SELECT capacidad, nombre FROM bodega_tanques WHERE id=?", (m["tanque_id"],)).fetchone()
            if t["capacidad"] and en_origen + m["cantidad"] > t["capacidad"] + 1e-6:
                return None, (f"no cabe: el tanque «{t['nombre']}» tiene {en_origen:g} de {t['capacidad']:g} {unidad}"), avisos
        if m["vence"] and m["vence"] < hoy.isoformat():
            avisos.append("El lote que entra ya está vencido.")
    if m["tipo"] in ("salida", "traslado", "baja"):
        if m["cantidad"] > en_origen + 1e-6 and not datos.get("forzar"):
            donde = "el tanque" if m["tanque_id"] else "esa ubicación"
            return None, (f"no hay suficiente en {donde}: hay {max(en_origen, 0):g} {unidad} y quieres sacar "
                          f"{m['cantidad']:g}"), avisos
        if m["tipo"] == "salida":
            m["motivo"] = m["motivo"] if m["motivo"] in MOTIVOS_SALIDA else "consumo"
            # La salida guarda el costo promedio con que salió (para el costo de la OT o de la ha).
            m["costo_unitario"] = est.get(item["id"], _VACIO)["costo_prom"]
            if m["costo_unitario"] is None:
                m["costo_unitario"] = item["costo_referencia"]
        if m["tipo"] == "baja":
            m["motivo"] = m["motivo"] if m["motivo"] in MOTIVOS_BAJA else "otro"
            m["costo_unitario"] = est.get(item["id"], _VACIO)["costo_prom"]
    if m["tipo"] == "traslado":
        if not m["destino_id"]:
            return None, "elige a dónde se traslada", avisos
        if m["destino_id"] == m["ubicacion_id"] and (m["tanque_id"] or None) == (m["tanque_destino_id"] or None):
            return None, "el origen y el destino son el mismo", avisos
        if m["tanque_destino_id"]:
            t = con.execute("SELECT capacidad, nombre FROM bodega_tanques WHERE id=?", (m["tanque_destino_id"],)).fetchone()
            nivel = disponible_en(con, item["id"], None, m["tanque_destino_id"], est)
            if t["capacidad"] and nivel + m["cantidad"] > t["capacidad"] + 1e-6:
                return None, f"no cabe en «{t['nombre']}»: tiene {nivel:g} de {t['capacidad']:g} {unidad}", avisos
    else:
        m["destino_id"] = None
        m["tanque_destino_id"] = None
    m["_item"] = dict(item)
    return m, None, avisos


def guardar_mov(con, m, usuario=None):
    m = {k: v for k, v in m.items() if not k.startswith("_")}
    m["usuario"] = usuario or m.get("usuario")
    campos = [k for k in CAMPOS_MOV if k in m]
    cur = con.execute(f"INSERT INTO bodega_movimientos({', '.join(campos)}) VALUES({', '.join('?' * len(campos))})",
                      [m[k] for k in campos])
    item = con.execute("SELECT nombre, unidad FROM bodega_items WHERE id=?", (m["item_id"],)).fetchone()
    core_flota.auditar(con, "bodega_movimientos", cur.lastrowid, m["tipo"], None,
                       f"{m['cantidad']:g} {item['unidad']} {item['nombre']}", usuario,
                       m.get("motivo") or m.get("nota"))
    return cur.lastrowid


def borrar_mov(con, id_, usuario=None, motivo=None):
    f = con.execute("SELECT m.*, i.nombre, i.unidad FROM bodega_movimientos m JOIN bodega_items i ON i.id=m.item_id "
                    "WHERE m.id=?", (id_,)).fetchone()
    if not f:
        return False
    core_flota.auditar(con, "bodega_movimientos", id_, "borrado",
                       f"{f['tipo']} {f['cantidad']:g} {f['unidad']} {f['nombre']} {f['fecha']}", None, usuario, motivo)
    con.execute("UPDATE bodega_ot_lineas SET estado='reservado', movimiento_id=NULL WHERE movimiento_id=?", (id_,))
    con.execute("UPDATE bodega_aplicaciones SET movimiento_id=NULL WHERE movimiento_id=?", (id_,))
    con.execute("DELETE FROM bodega_movimientos WHERE id=?", (id_,))
    return True


def movimientos(con, desde=None, hasta=None, item_id=None, tipo=None, clase=None, ubicacion_id=None, limite=500):
    """Kardex con saldo tras cada movimiento, del más nuevo al más viejo, ya filtrado."""
    _, movs = reconstruir(con, item_id)
    nombres = {i["id"]: i for i in items(con)}
    salida = []
    for m in reversed(movs):
        it = nombres.get(m["item_id"]) or {}
        if desde and (m["fecha"] or "") < desde:
            continue
        if hasta and (m["fecha"] or "") > hasta:
            continue
        if tipo and m["tipo"] != tipo:
            continue
        if clase and it.get("clase") != clase:
            continue
        if ubicacion_id and ubicacion_id not in (m["ubicacion_id"], m["destino_id"]):
            continue
        m["item"] = it.get("nombre")
        m["clase"] = it.get("clase")
        m["unidad"] = it.get("unidad")
        m["codigo"] = it.get("codigo")
        m["tipo_txt"] = TIPOS.get(m["tipo"], m["tipo"])
        m["motivo_txt"] = (MOTIVOS_BAJA if m["tipo"] == "baja" else MOTIVOS_SALIDA).get(m["motivo"] or "", m["motivo"])
        salida.append(m)
        if len(salida) >= limite:
            break
    return salida


# ======================================================================
# Repuestos en órdenes de trabajo
# ======================================================================

def lineas_ot(con, orden_id):
    filas = con.execute(
        """SELECT l.*, i.nombre AS item, i.codigo, i.unidad, u.nombre AS ubicacion, t.descripcion AS tarea
           FROM bodega_ot_lineas l JOIN bodega_items i ON i.id=l.item_id
           LEFT JOIN bodega_ubicaciones u ON u.id=l.ubicacion_id
           LEFT JOIN ot_tareas t ON t.id=l.tarea_id
           WHERE l.orden_id=? ORDER BY l.id""", (orden_id,)).fetchall()
    est, _ = reconstruir(con)
    salida = []
    for f in filas:
        d = dict(f)
        s = est.get(f["item_id"], _VACIO)
        d["en_ubicacion"] = _r(s["por_ubicacion"].get(f["ubicacion_id"], 0), 3)
        d["costo_prom"] = s["costo_prom"]
        d["costo_estimado"] = _r((d["costo_unitario"] if d["estado"] == "consumido" else s["costo_prom"] or 0)
                                 * f["cantidad"], 0) if (d["costo_unitario"] or s["costo_prom"]) else None
        d["alcanza"] = d["estado"] == "consumido" or d["en_ubicacion"] + 1e-9 >= f["cantidad"]
        salida.append(d)
    return salida


def agregar_linea_ot(con, orden_id, datos, usuario=None):
    """Aparta un repuesto de bodega para una orden (y una tarea). Devuelve (id, error)."""
    ot = con.execute("SELECT estado FROM ordenes_trabajo WHERE id=?", (orden_id,)).fetchone()
    if not ot:
        return None, "la orden no existe"
    if ot["estado"] in ("completada", "cancelada"):
        return None, "la orden ya está cerrada: reábrela para cambiar los repuestos"
    item_id, ubic = _entero(datos.get("item_id")), _entero(datos.get("ubicacion_id"))
    cantidad = _num(datos.get("cantidad")) or 1
    if cantidad <= 0:
        return None, "la cantidad debe ser mayor que cero"
    item = con.execute("SELECT * FROM bodega_items WHERE id=?", (item_id,)).fetchone() if item_id else None
    if not item:
        return None, "elige el repuesto"
    tarea_id = _entero(datos.get("tarea_id"))
    if tarea_id and not con.execute("SELECT 1 FROM ot_tareas WHERE id=? AND orden_id=?", (tarea_id, orden_id)).fetchone():
        return None, "la tarea no es de esta orden"
    if ubic and not con.execute("SELECT 1 FROM bodega_ubicaciones WHERE id=?", (ubic,)).fetchone():
        return None, "la ubicación no existe"
    cur = con.execute("""INSERT INTO bodega_ot_lineas(orden_id, tarea_id, item_id, ubicacion_id, cantidad, usuario)
                         VALUES(?,?,?,?,?,?)""", (orden_id, tarea_id, item_id, ubic, cantidad, usuario))
    core_flota.auditar(con, "bodega_ot_lineas", cur.lastrowid, "reserva", None,
                       f"{cantidad:g} {item['unidad']} {item['nombre']}", usuario)
    return cur.lastrowid, None


def consumir_ot(con, orden_id, fecha=None, usuario=None):
    """Al completar la orden: los repuestos de las tareas hechas salen de bodega al costo
    promedio y ese costo pasa a la tarea (`costo_repuesto`). Los de tareas no hechas se liberan.
    Una orden sin repuestos de bodega no cambia en nada. Devuelve {n, costo, faltantes}."""
    ot = con.execute("SELECT id, codigo, equipo_id FROM ordenes_trabajo WHERE id=?", (orden_id,)).fetchone()
    if not ot:
        return {"n": 0, "costo": 0, "faltantes": []}
    lineas = con.execute(
        """SELECT l.*, t.estado AS tarea_estado, t.id AS tarea_existe, i.nombre, i.unidad
           FROM bodega_ot_lineas l JOIN bodega_items i ON i.id=l.item_id
           LEFT JOIN ot_tareas t ON t.id=l.tarea_id
           WHERE l.orden_id=? AND l.estado='reservado' ORDER BY l.id""", (orden_id,)).fetchall()
    fecha = (fecha or date.today().isoformat())[:10]
    n, costo_total, faltantes, por_tarea = 0, 0.0, [], {}
    for l in lineas:
        if l["tarea_id"] and not l["tarea_existe"]:
            con.execute("DELETE FROM bodega_ot_lineas WHERE id=?", (l["id"],))   # la tarea se borró
            continue
        if l["tarea_id"] and l["tarea_estado"] != "hecho":
            con.execute("UPDATE bodega_ot_lineas SET estado='liberado' WHERE id=?", (l["id"],))
            continue
        est, _ = reconstruir(con, l["item_id"])
        s = est.get(l["item_id"], _VACIO)
        hay = s["por_ubicacion"].get(l["ubicacion_id"], 0) if l["ubicacion_id"] else s["saldo"]
        if hay + 1e-9 < l["cantidad"]:
            faltantes.append(f"{l['nombre']}: había {max(hay, 0):g} de {l['cantidad']:g} {l['unidad']}")
        ubic = l["ubicacion_id"]
        if not ubic:
            # Sin ubicación elegida sale de donde más haya.
            ubic = max(s["por_ubicacion"].items(), key=lambda x: x[1])[0] if s["por_ubicacion"] else None
        cu = s["costo_prom"]
        if cu is None:
            cu = con.execute("SELECT costo_referencia FROM bodega_items WHERE id=?", (l["item_id"],)).fetchone()["costo_referencia"]
        mov = guardar_mov(con, {"tipo": "salida", "fecha": fecha, "item_id": l["item_id"], "ubicacion_id": ubic,
                                "cantidad": l["cantidad"], "costo_unitario": cu, "motivo": "ot",
                                "equipo_id": ot["equipo_id"], "orden_id": orden_id, "ot_linea_id": l["id"],
                                "nota": f"{ot['codigo']}"}, usuario)
        con.execute("UPDATE bodega_ot_lineas SET estado='consumido', costo_unitario=?, movimiento_id=?, ubicacion_id=? "
                    "WHERE id=?", (cu, mov, ubic, l["id"]))
        costo = (cu or 0) * l["cantidad"]
        costo_total += costo
        n += 1
        if l["tarea_id"]:
            por_tarea[l["tarea_id"]] = por_tarea.get(l["tarea_id"], 0) + costo
    for tarea_id, costo in por_tarea.items():
        con.execute("UPDATE ot_tareas SET costo_repuesto=? WHERE id=?", (round(costo, 2), tarea_id))
    return {"n": n, "costo": round(costo_total, 2), "faltantes": faltantes}


def revertir_ot(con, orden_id, usuario=None, motivo=None):
    """La orden se reabre o se borra: las salidas de sus repuestos se deshacen (el movimiento se
    borra, con constancia en la auditoría) y las reservas vuelven a quedar apartadas."""
    n = 0
    for l in con.execute("SELECT * FROM bodega_ot_lineas WHERE orden_id=? AND estado='consumido'", (orden_id,)).fetchall():
        if l["movimiento_id"]:
            borrar_mov(con, l["movimiento_id"], usuario, motivo or "orden reabierta o borrada")
        con.execute("UPDATE bodega_ot_lineas SET estado='reservado', movimiento_id=NULL WHERE id=?", (l["id"],))
        n += 1
    con.execute("UPDATE bodega_ot_lineas SET estado='reservado' WHERE orden_id=? AND estado='liberado'", (orden_id,))
    return n


def buscar_stock(con, texto=None, codigo=None, clave=None, modelo=None, clase="repuesto", limite=12):
    """Artículos que casan con una pieza (por código DJI, clave del catálogo o texto), con sus
    existencias por ubicación. Es lo que ve el técnico al poner un repuesto en la orden."""
    inv = inventario(con, clase)
    consulta = _norm(texto).split() if texto else []
    salida = []
    for it in inv:
        if not it["activo"]:
            continue
        puntos = 0
        if codigo and it["codigo"] and _norm(it["codigo"]) == _norm(codigo):
            puntos += 10
        if clave and it["catalogo"] == "pieza" and it["catalogo_ref"] == clave:
            puntos += 8
        if consulta:
            heno = _norm(" ".join(str(x or "") for x in (it["nombre"], it["codigo"], it["modelo"], it["categoria"],
                                                         it["ingrediente_activo"])))
            if all(t in heno for t in consulta):
                puntos += 3
        if not (codigo or clave or consulta):
            puntos = 1
        if puntos:
            if modelo and it["modelo"] and it["modelo"] != modelo:
                puntos -= 2
            salida.append((puntos, it))
    salida.sort(key=lambda x: (-x[0], -(x[1]["saldo"] or 0), _norm(x[1]["nombre"])))
    return [it for p, it in salida if p > 0][:limite]


# ======================================================================
# Lo que hay que comprar: proyección de repuestos + reservas + mínimos
# ======================================================================

def compras(con, horizonte=HORIZONTE_COMPRA, inv=None):
    """«Vas a necesitar X, tienes Y, pide Z». X = cambios previstos en el horizonte (proyección
    con el ritmo real de vuelo) × unidades por cambio + lo apartado en órdenes abiertas.
    Z = X + mínimo − existencias. También devuelve las piezas previstas que ni siquiera están
    en la bodega (`sin_articulo`), con su precio de catálogo si lo hay."""
    from core import proyeccion as core_proyeccion
    if inv is None:
        inv = inventario(con)
    proy = [p for p in core_proyeccion.proximos_repuestos(con, None, limite=10 ** 6)
            if p.get("tipo_item") != "inspeccion"
            and (p["nivel"] == "vencido" or (p["dias_estimados"] is not None and p["dias_estimados"] <= horizonte))]
    por_clave = {}
    for it in inv:
        if it["clase"] == "repuesto" and it["catalogo"] == "pieza" and it["catalogo_ref"] and it["activo"]:
            por_clave.setdefault(it["catalogo_ref"], []).append(it)
    necesidad, sin_articulo = {}, {}
    for p in proy:
        candidatos = por_clave.get(p["clave"], [])
        it = next((c for c in candidatos if c["modelo"] in (None, p["modelo"])), None) or (candidatos[0] if candidatos else None)
        evento = {"equipo": p["equipo"], "equipo_id": p["equipo_id"], "dias": p["dias_estimados"],
                  "fecha": p["fecha_estimada"], "nivel": p["nivel"]}
        if it:
            n = necesidad.setdefault(it["id"], {"cantidad": 0, "eventos": []})
            n["cantidad"] += it["cantidad_cambio"] or 1
            n["eventos"].append(evento)
        else:
            k = (p["modelo"], p["clave"])
            s = sin_articulo.setdefault(k, {"clave": p["clave"], "nombre": p["nombre"], "modelo": p["modelo"],
                                            "modulo": p["modulo"], "cantidad": 0, "eventos": [],
                                            "precio_ref": p.get("precio")})
            s["cantidad"] += 1
            s["eventos"].append(evento)
    lista = []
    for it in inv:
        if not it["activo"] or it.get("de_cliente"):
            continue
        prevista = necesidad.get(it["id"], {"cantidad": 0, "eventos": []})
        necesita = prevista["cantidad"] + (it["reservado"] or 0)
        tiene = max(it["saldo"] or 0, 0)
        minimo = it["stock_minimo"] or 0
        pedir = necesita + minimo - tiene
        if pedir <= EPS:
            continue
        # Se pide en presentaciones enteras (una garrafa de 20 L, no 13,4 L).
        if it["clase"] == "insumo" and it["contenido"] and pedir > 0:
            pedir = -(-pedir // it["contenido"]) * it["contenido"]
        elif it["unidad"] == "und":
            pedir = float(-(-pedir // 1))
        costo = it["costo"]
        primera = min((e["dias"] for e in prevista["eventos"] if e["dias"] is not None), default=None)
        lista.append({
            "item_id": it["id"], "nombre": it["nombre"], "codigo": it["codigo"], "clase": it["clase"],
            "modelo": it["modelo"], "unidad": it["unidad"], "proveedor": it["ultimo_proveedor"] or it["proveedor"],
            "necesita": _r(necesita, 3), "prevista": _r(prevista["cantidad"], 3), "reservado": it["reservado"],
            "tiene": _r(tiene, 3), "minimo": minimo, "pedir": _r(pedir, 3),
            "costo_unitario": costo, "costo": _r(pedir * costo, 0) if costo is not None else None,
            "eventos": prevista["eventos"], "primera_dias": primera,
            "urgente": (primera is not None and primera <= 30) or tiene <= EPS,
            "motivo": ("cambios previstos" if prevista["cantidad"] else
                       "apartado en órdenes" if it["reservado"] else "bajo el mínimo"),
        })
    lista.sort(key=lambda x: (not x["urgente"], x["primera_dias"] if x["primera_dias"] is not None else 10 ** 6,
                              -(x["costo"] or 0)))
    sin = sorted(sin_articulo.values(), key=lambda x: min((e["dias"] or 0) for e in x["eventos"]))
    for s in sin:
        s["costo"] = _r(s["cantidad"] * s["precio_ref"], 0) if s["precio_ref"] else None
    return {"lista": lista, "sin_articulo": sin, "horizonte": horizonte,
            "costo_total": _r(sum(x["costo"] or 0 for x in lista), 0),
            "costo_sin_articulo": _r(sum(x["costo"] or 0 for x in sin), 0)}


# ======================================================================
# Insumos en la operación: aplicaciones, control de consumo y registro RAC 137
# ======================================================================

def aplicaciones_de(con, operacion_id):
    filas = con.execute(
        """SELECT a.*, i.nombre AS item, i.unidad, i.categoria, i.ingrediente_activo, i.registro_ica,
                  m.cantidad AS descontado, m.ubicacion_id, m.tanque_id, m.lote
           FROM bodega_aplicaciones a JOIN bodega_items i ON i.id=a.item_id
           LEFT JOIN bodega_movimientos m ON m.id=a.movimiento_id
           WHERE a.operacion_id=? ORDER BY a.id""", (operacion_id,)).fetchall()
    return [dict(f) for f in filas]


def guardar_aplicaciones(con, operacion_id, productos, usuario=None, rol="admin", forzar=False):
    """Deja los productos aplicados en una operación y, si se pide, los descuenta de bodega.

    Reemplaza lo que hubiera: las salidas anteriores de esa operación se deshacen primero (con
    constancia en la auditoría). Devuelve (resultado, error)."""
    op = con.execute("SELECT * FROM operaciones WHERE id=?", (operacion_id,)).fetchone()
    if not op:
        return None, "la operación no existe"
    previas = con.execute("SELECT * FROM bodega_aplicaciones WHERE operacion_id=?", (operacion_id,)).fetchall()
    for a in previas:
        if a["movimiento_id"]:
            borrar_mov(con, a["movimiento_id"], usuario, "productos de la operación corregidos")
    con.execute("DELETE FROM bodega_aplicaciones WHERE operacion_id=?", (operacion_id,))
    ha = op["hectareas"]
    n, descontado, avisos = 0, 0, []
    for p in productos or []:
        item_id = _entero(p.get("item_id"))
        item = con.execute("SELECT * FROM bodega_items WHERE id=?", (item_id,)).fetchone() if item_id else None
        if not item:
            continue
        dosis = _num(p.get("dosis_ha"))
        teorica = _num(p.get("cantidad_teorica"))
        if teorica is None and dosis is not None and ha:
            teorica = round(dosis * ha, 4)
        if dosis is None and teorica is not None and ha:
            dosis = round(teorica / ha, 4)
        mov = None
        if p.get("descontar"):
            real = _num(p.get("cantidad")) or teorica
            if not real or real <= 0:
                return None, f"{item['nombre']}: sin hectáreas ni cantidad no hay qué descontar"
            m, error, av = validar_mov(con, {"tipo": "salida", "fecha": op["fecha"], "item_id": item_id,
                                             "ubicacion_id": p.get("ubicacion_id"), "tanque_id": p.get("tanque_id"),
                                             "cantidad": real, "motivo": "operacion", "equipo_id": op["equipo_id"],
                                             "operacion_id": operacion_id, "lote": p.get("lote"),
                                             "responsable": op["piloto"], "forzar": forzar,
                                             "nota": " · ".join(x for x in (op["cliente"], op["lote"]) if x) or None},
                                       rol="admin")   # la salida a una operación la puede registrar cualquier rol
            if error:
                return None, f"{item['nombre']}: {error}"
            avisos += av
            mov = guardar_mov(con, m, usuario)
            descontado += 1
        con.execute("""INSERT INTO bodega_aplicaciones(operacion_id, item_id, dosis_ha, hectareas, cantidad_teorica,
                                                          movimiento_id, usuario) VALUES(?,?,?,?,?,?,?)""",
                    (operacion_id, item_id, dosis, ha, teorica, mov, usuario))
        n += 1
    return {"productos": n, "descontados": descontado, "avisos": avisos}, None


def _partir_producto(texto):
    return [t.strip() for t in re.split(r"\+|,|/|;| y ", texto or "") if t.strip()]


def sugerir_items(texto, insumos):
    """Artículos de insumo que casan con el texto libre del producto de una operación
    («SEEKER + DITHANE» → Seeker y Dithane)."""
    salida = []
    for parte in _partir_producto(texto):
        n = _norm(parte)
        if not n:
            continue
        mejor = None
        for it in insumos:
            nom = _norm(it["nombre"])
            if nom == n or nom.startswith(n + " ") or n.startswith(nom + " ") or (len(n) >= 4 and n in nom):
                mejor = it
                break
        if mejor and mejor not in salida:
            salida.append(mejor)
    return salida


def por_conciliar(con, desde=None, hasta=None, limite=300):
    """Operaciones con producto anotado y sin productos de bodega asociados, con sugerencia."""
    insumos = [i for i in items(con, "insumo") if i["activo"]]
    cond, p = ["o.producto IS NOT NULL", "o.producto != ''",
               "NOT EXISTS (SELECT 1 FROM bodega_aplicaciones a WHERE a.operacion_id=o.id)"], []
    if desde:
        cond.append("o.fecha>=?"); p.append(desde)
    if hasta:
        cond.append("o.fecha<=?"); p.append(hasta)
    filas = con.execute(
        f"""SELECT o.id, o.fecha, o.producto, o.hectareas, o.litros, o.dosis_objetivo, o.cliente, o.lote,
                   o.piloto, o.equipo_id, e.nombre AS equipo
            FROM operaciones o JOIN equipos e ON e.id=o.equipo_id
            WHERE {' AND '.join(cond)} ORDER BY o.fecha DESC, o.id DESC LIMIT ?""", p + [limite]).fetchall()
    salida = []
    for f in filas:
        d = dict(f)
        d["sugeridos"] = [{"item_id": i["id"], "nombre": i["nombre"], "dosis_ha": i["dosis_ha"], "unidad": i["unidad"]}
                          for i in sugerir_items(f["producto"], insumos)]
        salida.append(d)
    return salida


def control_consumo(con, desde=None, hasta=None):
    """Consumo teórico según las operaciones frente a lo que salió de bodega, por insumo.

    · teórico  = Σ hectáreas × dosis de cada aplicación registrada en el período.
    · salidas  = Σ salidas de bodega del insumo en el período (a operaciones y sueltas).
    · diferencia = salidas − teórico. Positiva: salió más de lo que se aplicó (pérdida, dosis
      alta, operaciones sin registrar). Es el control.
    · dosis real de producto = salidas atribuidas a operaciones ÷ hectáreas; y la del caldo
      (litros de mezcla ÷ ha) frente a la dosis objetivo de las operaciones.
    """
    rango, p = ["1=1"], []
    if desde:
        rango.append("o.fecha>=?"); p.append(desde)
    if hasta:
        rango.append("o.fecha<=?"); p.append(hasta)
    w = " AND ".join(rango)
    teor = {f["item_id"]: dict(f) for f in con.execute(
        f"""SELECT a.item_id, SUM(a.cantidad_teorica) teorico, SUM(a.hectareas) ha, COUNT(*) n,
                   SUM(CASE WHEN a.movimiento_id IS NULL THEN 1 ELSE 0 END) sin_descontar,
                   SUM(o.litros) litros, SUM(CASE WHEN o.litros IS NOT NULL AND o.hectareas>0 THEN o.hectareas END) ha_caldo,
                   SUM(CASE WHEN o.dosis_objetivo>0 AND o.hectareas>0 THEN o.dosis_objetivo*o.hectareas END) obj_pond,
                   SUM(CASE WHEN o.dosis_objetivo>0 AND o.hectareas>0 THEN o.hectareas END) ha_obj
            FROM bodega_aplicaciones a JOIN operaciones o ON o.id=a.operacion_id
            WHERE {w} GROUP BY a.item_id""", p).fetchall()}
    _, movs = reconstruir(con)
    sal = {}
    for m in movs:
        if m["tipo"] not in ("salida", "baja"):
            continue
        if desde and (m["fecha"] or "") < desde:
            continue
        if hasta and (m["fecha"] or "") > hasta:
            continue
        s = sal.setdefault(m["item_id"], {"salidas": 0.0, "a_operaciones": 0.0, "sueltas": 0.0, "bajas": 0.0,
                                          "valor": 0.0, "valor_op": 0.0})
        c = m["cantidad"] or 0
        if m["tipo"] == "baja":
            s["bajas"] += c
            continue
        s["salidas"] += c
        s["valor"] += m["valor"] or 0
        if m["operacion_id"]:
            s["a_operaciones"] += c
            s["valor_op"] += m["valor"] or 0
        elif m["motivo"] != "ot":
            s["sueltas"] += c
    inv = {i["id"]: i for i in inventario(con, "insumo")}
    filas = []
    for iid, it in inv.items():
        t = teor.get(iid, {})
        s = sal.get(iid, {"salidas": 0, "a_operaciones": 0, "sueltas": 0, "bajas": 0, "valor": 0, "valor_op": 0})
        teorico = t.get("teorico") or 0
        if not teorico and not s["salidas"] and not s["bajas"]:
            continue
        diferencia = s["salidas"] - teorico
        pct = diferencia / teorico * 100 if teorico > EPS else None
        if teorico <= EPS and s["salidas"] > EPS:
            nivel, txt = "proximo", "salidas sin operaciones asociadas"
        elif pct is None:
            nivel, txt = "ok", "sin consumo"
        elif abs(pct) / 100 >= UMBRAL_DESCUADRE_ROJO:
            nivel, txt = "critico", ("salió más de lo aplicado" if pct > 0 else "se aplicó más de lo que salió")
        elif abs(pct) / 100 >= UMBRAL_DESCUADRE:
            nivel, txt = "proximo", ("salió algo más de lo aplicado" if pct > 0 else "se aplicó algo más de lo que salió")
        else:
            nivel, txt = "ok", "cuadra"
        ha = t.get("ha") or 0
        costo = it["costo"] or 0
        filas.append({
            "item_id": iid, "nombre": it["nombre"], "unidad": it["unidad"], "categoria": it["categoria"],
            "color": it["color_final"], "ingrediente_activo": it["ingrediente_activo"],
            "teorico": _r(teorico, 3), "salidas": _r(s["salidas"], 3), "a_operaciones": _r(s["a_operaciones"], 3),
            "sueltas": _r(s["sueltas"], 3), "bajas": _r(s["bajas"], 3),
            "diferencia": _r(diferencia, 3), "pct": _r(pct, 1), "nivel": nivel, "nivel_txt": txt,
            "valor_diferencia": _r(diferencia * costo, 0), "valor_salidas": _r(s["valor"], 0),
            "hectareas": _r(ha, 2), "aplicaciones": t.get("n") or 0, "sin_descontar": t.get("sin_descontar") or 0,
            "dosis_teorica": _r(teorico / ha, 3) if ha else None,
            "dosis_real": _r(s["a_operaciones"] / ha, 3) if ha and s["a_operaciones"] else None,
            "dosis_ref": it["dosis_ha"],
            "caldo_real": _r(t["litros"] / t["ha_caldo"], 2) if t.get("litros") and t.get("ha_caldo") else None,
            "caldo_objetivo": _r(t["obj_pond"] / t["ha_obj"], 2) if t.get("obj_pond") and t.get("ha_obj") else None,
            "costo_ha": _r(s["valor_op"] / ha, 0) if ha and s["valor_op"] else None,
        })
    filas.sort(key=lambda x: -abs(x["valor_diferencia"] or 0))
    # Totales del período: costo de insumos por hectárea con todas las hectáreas aplicadas.
    ha_total = con.execute(f"SELECT SUM(o.hectareas) ha FROM operaciones o WHERE {w} AND o.hectareas>0", p).fetchone()["ha"] or 0
    valor_op = sum(s["valor_op"] for s in sal.values())
    posibles = sum(f["valor_diferencia"] for f in filas if (f["valor_diferencia"] or 0) > 0 and f["nivel"] != "ok")
    return {"filas": filas, "hectareas": _r(ha_total, 2), "valor_insumos_op": _r(valor_op, 0),
            "costo_ha": _r(valor_op / ha_total, 0) if ha_total and valor_op else None,
            "posibles_perdidas": _r(posibles, 0),
            "n_descuadres": sum(1 for f in filas if f["nivel"] != "ok"),
            "por_conciliar": len(por_conciliar(con, desde, hasta, limite=10 ** 6))}


def detalle_consumo(con, item_id, desde=None, hasta=None):
    """Aplicaciones y salidas de un insumo en el período, para ver de dónde sale el descuadre."""
    rango, p = ["a.item_id=?"], [item_id]
    if desde:
        rango.append("o.fecha>=?"); p.append(desde)
    if hasta:
        rango.append("o.fecha<=?"); p.append(hasta)
    apl = [dict(f) for f in con.execute(
        f"""SELECT a.*, o.fecha, o.cliente, o.lote AS finca, o.piloto, o.producto, o.litros, o.dosis_objetivo,
                   e.nombre AS equipo, m.cantidad AS descontado
            FROM bodega_aplicaciones a JOIN operaciones o ON o.id=a.operacion_id
            JOIN equipos e ON e.id=o.equipo_id LEFT JOIN bodega_movimientos m ON m.id=a.movimiento_id
            WHERE {' AND '.join(rango)} ORDER BY o.fecha DESC, o.id DESC""", p).fetchall()]
    movs = [m for m in movimientos(con, desde, hasta, item_id=item_id, limite=2000) if m["tipo"] in ("salida", "baja")]
    por_mes = {}
    for a in apl:
        k = (a["fecha"] or "")[:7]
        por_mes.setdefault(k, {"teorico": 0, "salidas": 0})["teorico"] += a["cantidad_teorica"] or 0
    for m in movs:
        if m["tipo"] == "salida":
            k = (m["fecha"] or "")[:7]
            por_mes.setdefault(k, {"teorico": 0, "salidas": 0})["salidas"] += m["cantidad"] or 0
    return {"aplicaciones": apl, "movimientos": movs,
            "por_mes": [{"mes": k, **v} for k, v in sorted(por_mes.items())]}


def registro_aplicaciones(con, desde=None, hasta=None):
    """Registro RAC 137.71(3): nombre y cantidad de los productos aplicados en cada operación."""
    rango, p = ["1=1"], []
    if desde:
        rango.append("o.fecha>=?"); p.append(desde)
    if hasta:
        rango.append("o.fecha<=?"); p.append(hasta)
    return [dict(f) for f in con.execute(
        f"""SELECT o.fecha, e.nombre AS equipo, e.matricula, o.piloto, o.cliente, o.zona, o.lote AS finca,
                   o.hectareas, o.litros, i.nombre AS producto, i.ingrediente_activo, i.registro_ica,
                   i.categoria_tox, a.dosis_ha, a.cantidad_teorica, m.cantidad AS descontado, i.unidad,
                   m.lote AS lote_producto
            FROM bodega_aplicaciones a JOIN operaciones o ON o.id=a.operacion_id
            JOIN equipos e ON e.id=o.equipo_id JOIN bodega_items i ON i.id=a.item_id
            LEFT JOIN bodega_movimientos m ON m.id=a.movimiento_id
            WHERE {' AND '.join(rango)} ORDER BY o.fecha DESC, o.id DESC""", p).fetchall()]


# ======================================================================
# Resumen para gerencia
# ======================================================================

def resumen(con, desde=None, hasta=None, hoy=None):
    hoy = hoy or date.today()
    inv = inventario(con, hoy=hoy)
    tanques = estado_tanques(con, inv)
    comp = compras(con, inv=inv)
    ctrl = control_consumo(con, desde, hasta)
    valor = {c: _r(sum(max(i["valor"] or 0, 0) for i in inv if i["clase"] == c), 0) for c in CLASES}
    vencen = []
    for i in inv:
        for l in i["lotes"]:
            if l["vence"] and l["vence"] <= (hoy + timedelta(days=DIAS_POR_VENCER)).isoformat():
                dias = (date.fromisoformat(l["vence"]) - hoy).days
                vencen.append({"item_id": i["id"], "nombre": i["nombre"], "lote": l["lote"], "vence": l["vence"],
                               "dias": dias, "cantidad": l["cant"], "unidad": i["unidad"],
                               "ubicacion": l["ubicacion"], "valor": _r(l["cant"] * (i["costo"] or 0), 0),
                               "nivel": "critico" if dias < 0 else ("proximo" if dias <= 30 else "ok")})
    vencen.sort(key=lambda x: x["vence"])
    ubic = []
    for u in ubicaciones(con):
        v = sum((next((e["cantidad"] for e in i["existencias"] if e["ubicacion_id"] == u["id"]), 0) or 0)
                * (i["costo"] or 0) for i in inv)
        n = sum(1 for i in inv if any(e["ubicacion_id"] == u["id"] and e["cantidad"] > EPS for e in i["existencias"]))
        ubic.append({**u, "tipo_txt": TIPOS_UBICACION.get(u["tipo"], u["tipo"]), "valor": _r(max(v, 0), 0),
                     "articulos": n})
    bajo = [i for i in inv if i["activo"] and i["nivel"] != "ok" and i["nivel_txt"] in ("bajo el mínimo", "agotado")]
    return {
        "kpis": {
            "valor_total": _r(valor["repuesto"] + valor["insumo"], 0), "valor_repuestos": valor["repuesto"],
            "valor_insumos": valor["insumo"],
            "comprar_n": len(comp["lista"]) + len(comp["sin_articulo"]),
            "comprar_costo": _r((comp["costo_total"] or 0) + (comp["costo_sin_articulo"] or 0), 0),
            "comprar_urgente": sum(1 for x in comp["lista"] if x["urgente"]),
            "vencen_n": len(vencen), "vencidos_n": sum(1 for v in vencen if v["dias"] < 0),
            "vencen_valor": _r(sum(v["valor"] or 0 for v in vencen), 0),
            "posibles_perdidas": ctrl["posibles_perdidas"], "descuadres": ctrl["n_descuadres"],
            "costo_ha": ctrl["costo_ha"], "hectareas": ctrl["hectareas"],
            "valor_insumos_op": ctrl["valor_insumos_op"], "por_conciliar": ctrl["por_conciliar"],
            "bajo_minimo": len(bajo), "articulos": len([i for i in inv if i["activo"]]),
        },
        "inventario": inv, "tanques": tanques, "compras": comp, "control": ctrl, "vencen": vencen,
        "ubicaciones": ubic,
    }


# ======================================================================
# Envases vacíos: triple lavado y devolución (posconsumo)
# ======================================================================
# Lo pidió la gerencia en la encuesta de validación: GlobalG.A.P., Rainforest Alliance y las
# auditorías del cliente preguntan por el triple lavado y por la devolución de envases vacíos al
# programa posconsumo (en Colombia, Campo Limpio). Un registro por lote de envases.

def envases(con, desde=None, hasta=None, limite=500):
    cond, p = ["1=1"], []
    if desde:
        cond.append("fecha>=?"); p.append(desde)
    if hasta:
        cond.append("fecha<=?"); p.append(hasta)
    filas = [dict(f) for f in con.execute(
        f"SELECT * FROM envases WHERE {' AND '.join(cond)} ORDER BY fecha DESC, id DESC LIMIT ?", p + [limite]).fetchall()]
    total = sum(f["cantidad"] or 0 for f in filas)
    lavados = sum(f["cantidad"] or 0 for f in filas if f["triple_lavado"])
    devueltos = sum(f["cantidad"] or 0 for f in filas if f["devuelto_en"])
    return {"filas": filas, "kpis": {
        "envases": total, "lavados": lavados, "devueltos": devueltos, "por_devolver": total - devueltos,
        "pct_lavado": _r(lavados / total * 100, 1) if total else None,
        "pct_devuelto": _r(devueltos / total * 100, 1) if total else None}}


def guardar_envase(con, datos, usuario=None, id_=None):
    """Valida y guarda un lote de envases. Devuelve (id, error)."""
    producto = (datos.get("producto") or "").strip()
    if not producto:
        return None, "falta el producto"
    cantidad = _entero(datos.get("cantidad"))
    if not cantidad or cantidad <= 0:
        return None, "la cantidad de envases tiene que ser un número entero mayor que cero"
    si = lambda k: 1 if datos.get(k) in (1, True, "1", "true", "on") else 0
    devuelto = (datos.get("devuelto_en") or "").strip() or None
    if devuelto and not (datos.get("centro_acopio") or "").strip():
        return None, "indica el centro de acopio donde se entregaron"
    if devuelto and not si("triple_lavado"):
        return None, "un envase sólo se devuelve con triple lavado"
    valores = {"fecha": datos.get("fecha") or date.today().isoformat(), "producto": producto,
               "cliente": (datos.get("cliente") or "").strip() or None,
               "operacion_id": _entero(datos.get("operacion_id")),
               "orden_servicio": (datos.get("orden_servicio") or "").strip() or None,
               "cantidad": cantidad, "capacidad": (datos.get("capacidad") or "").strip() or None,
               "triple_lavado": si("triple_lavado"), "perforado": si("perforado"),
               "lavado_por": (datos.get("lavado_por") or "").strip() or None, "devuelto_en": devuelto,
               "centro_acopio": (datos.get("centro_acopio") or "").strip() or None,
               "certificado": (datos.get("certificado") or "").strip() or None,
               "archivo": datos.get("archivo") or None, "nota": (datos.get("nota") or "").strip() or None}
    if id_:
        con.execute(f"UPDATE envases SET {', '.join(f'{k}=?' for k in valores)} WHERE id=?",
                    list(valores.values()) + [id_])
    else:
        valores["usuario"] = usuario
        cur = con.execute(f"INSERT INTO envases({', '.join(valores)}) VALUES({', '.join('?' * len(valores))})",
                          list(valores.values()))
        id_ = cur.lastrowid
    con.commit()
    return id_, None
