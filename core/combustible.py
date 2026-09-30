"""Estación de combustible: depósitos, tanqueos, consumo y control.

Cuatro tipos de movimiento (tabla `combustible_movimientos`):

  · compra    entra combustible a un depósito propio (cisterna, carrotanque, bidones).
  · tanqueo   sale combustible hacia el tanque de un AVIÓN (los drones son eléctricos: el
              tanqueo es sólo de aviones). Puede salir de un depósito propio o comprarse en el
              aeródromo (sin depósito: entonces lleva precio).
  · merma     drenaje de muestras, derrame, combustible contaminado que se desecha.
  · medicion  varillaje del depósito. Se guarda el nivel medido y, en `galones`, el descuadre
              frente al nivel calculado en ese momento (+ sobra, − falta).

El nivel de un depósito no se guarda: se reconstruye en orden cronológico, así corregir o borrar
un movimiento viejo arregla solo todos los niveles siguientes.

Consumo por hora. Se calcula de dos maneras y se comparan:
  · cargado:   galones tanqueados ÷ horas voladas. Con tanques llenos se usa el método de «lleno
               a lleno» (todo lo cargado desde el lleno anterior hasta este, entre las horas del
               tramo), que es el único exacto; sin llenos, se prorratea el período.
  · reportado: Σ combustible_gal que el piloto anota en la operación ÷ horas de esas operaciones.
Si difieren mucho hay combustible que no se está explicando: es la alerta de control.
"""
import json
from datetime import date, timedelta

TIPOS = {"compra": "Compra", "tanqueo": "Tanqueo", "merma": "Merma / drenaje", "medicion": "Medición"}

# Combustibles con el color con que se tiñen de verdad (se usa para pintar el líquido).
COMBUSTIBLES = {
    "avgas_100ll": {"nombre": "AVGAS 100LL", "corto": "100LL", "color": "#3b82d6",
                    "nota": "Gasolina de aviación, teñida de azul. Motores de pistón (Continental IO-520)."},
    "jet_a1": {"nombre": "Jet A-1", "corto": "JET", "color": "#c9b77a",
               "nota": "Queroseno de aviación, color pajizo. Sólo turbinas: en un motor de pistón destruye el motor."},
    "gasolina": {"nombre": "Gasolina corriente", "corto": "GAS", "color": "#e8a400",
                 "nota": "Generadores y vehículos de apoyo de los drones."},
    "diesel": {"nombre": "ACPM / diésel", "corto": "ACPM", "color": "#6b8f3a",
               "nota": "Generadores diésel y carrotanques."},
}

DESTINOS = {"aeronave": "Tanque de la aeronave", "generador": "Generador de carga",
            "vehiculo": "Vehículo de apoyo", "otro": "Otro"}

# Combustible del activo y capacidad de sus tanques, por modelo. Se puede corregir por activo.
# Cessna A188B: «Fuel capacity total 54 gal», «52 gallons usable fuel» (Owner's Manual D1145-13,
# Performance-Specifications). Motor IO-520-D: grado mínimo 100/130 → se usa 100LL.
ESPEC_MODELO = {
    "C188": {"combustible": "avgas_100ll", "capacidad_gal": 54, "usable_gal": 52, "consumo_ref": None,
             "fuente": "Cessna A188B Owner's Manual (D1145-13): 54 gal totales, 52 usables"},
}
ESPEC_DRON = {"combustible": "gasolina", "capacidad_gal": None, "usable_gal": None, "consumo_ref": None,
              "fuente": "Generador de carga de baterías"}

# Chequeo de seguridad y calidad del tanqueo de una aeronave (ver core/rac.py: la norma de cada
# punto). Los obligatorios bloquean el registro si no se marcan; los demás quedan como aviso.
CHEQUEO_AERONAVE = [
    ("motor_apagado", "Motor apagado y magnetos en OFF", True),
    ("sin_ocupantes", "Sin pasajeros a bordo ni personas ajenas cerca", True),
    ("puesta_tierra", "Aeronave y surtidor conectados a tierra (cable de unión)", True),
    ("extintor", "Extintor disponible junto al punto de tanqueo", True),
    ("lugar_autorizado", "Tanqueo en instalación autorizada (pista o aeródromo)", True),
    ("tormenta", "Sin tormenta eléctrica a menos de 10 km", True),
    ("tipo_verificado", "Tipo de combustible verificado contra la placa de la tapa", True),
    ("drenaje", "Muestra drenada de sumideros sin agua ni sedimentos", True),
    ("tapas", "Tapas de los tanques cerradas y aseguradas", True),
    ("sin_fuentes_ignicion", "Sin fuentes de ignición ni equipos eléctricos en uso", False),
]
CHEQUEO_APOYO = [
    ("motor_apagado", "Generador / vehículo apagado y frío", True),
    ("extintor", "Extintor disponible", True),
    ("recipiente", "Recipiente aprobado y rotulado", False),
    ("sin_fuentes_ignicion", "Lejos de baterías en carga y fuentes de ignición", True),
]

UMBRAL_DEPOSITO_BAJO = 0.20      # fracción de la capacidad
UMBRAL_DESCUADRE_GAL = 5.0       # o 2 % de la capacidad, lo que sea mayor
UMBRAL_CONCILIACION = 0.10       # cargado vs reportado
UMBRAL_REFERENCIA = 0.15         # consumo real vs referencia del modelo
UMBRAL_PRECIO = 0.20             # precio frente a la media de 90 días


def _num(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _r(v, n=2):
    return None if v is None else round(v, n)


# ======================================================================
# Configuración de combustible de cada activo
# ======================================================================

def _familia(modelo):
    for k in ESPEC_MODELO:
        if (modelo or "").upper().startswith(k):
            return k
    return None


def espec_equipo(con, equipo):
    """Combustible, capacidad y consumo de referencia del activo: el del modelo, corregido con lo
    que la empresa haya guardado para ese activo (`meta` comb_eq_<id>)."""
    e = dict(equipo)
    fam = _familia(e.get("modelo"))
    base = dict(ESPEC_MODELO[fam]) if fam else dict(ESPEC_DRON if e.get("tipo_activo") != "avion" else
                                                   {"combustible": "avgas_100ll", "capacidad_gal": None,
                                                    "usable_gal": None, "consumo_ref": None, "fuente": ""})
    fila = con.execute("SELECT valor FROM meta WHERE clave=?", (f"comb_eq_{e['id']}",)).fetchone()
    if fila and fila["valor"]:
        try:
            propio = json.loads(fila["valor"])
            for k in ("combustible", "capacidad_gal", "usable_gal", "consumo_ref"):
                if propio.get(k) not in (None, ""):
                    base[k] = propio[k]
            base["propio"] = True
        except ValueError:
            pass
    base["destino"] = "aeronave" if e.get("tipo_activo") == "avion" else "generador"
    return base


def guardar_espec(con, equipo_id, datos):
    limpio = {k: (_num(datos.get(k)) if k != "combustible" else datos.get(k))
              for k in ("combustible", "capacidad_gal", "usable_gal", "consumo_ref")}
    if limpio["combustible"] not in COMBUSTIBLES:
        limpio["combustible"] = None
    valor = json.dumps({k: v for k, v in limpio.items() if v is not None})
    clave = f"comb_eq_{int(equipo_id)}"
    if con.execute("SELECT 1 FROM meta WHERE clave=?", (clave,)).fetchone():
        con.execute("UPDATE meta SET valor=? WHERE clave=?", (valor, clave))
    else:
        con.execute("INSERT INTO meta(clave, valor) VALUES(?, ?)", (clave, valor))


# ======================================================================
# Movimientos
# ======================================================================

CAMPOS = ("tipo", "fecha", "hora", "deposito_id", "equipo_id", "destino", "combustible", "galones",
          "precio_gal", "total", "proveedor", "documento", "lleno", "lectura", "nivel_medido",
          "chequeo", "responsable", "nota", "archivo")


def validar(con, d):
    """Normaliza un movimiento y devuelve (campos, error)."""
    tipo = d.get("tipo") or "tanqueo"
    if tipo not in TIPOS:
        return None, "tipo de movimiento no válido"
    c = {k: d.get(k) for k in CAMPOS}
    c["tipo"] = tipo
    c["fecha"] = (d.get("fecha") or date.today().isoformat())[:10]
    for k in ("galones", "precio_gal", "total", "lectura", "nivel_medido"):
        c[k] = _num(c[k])
    for k in ("deposito_id", "equipo_id"):
        c[k] = int(c[k]) if str(c.get(k) or "").isdigit() else None
    c["lleno"] = 1 if d.get("lleno") in (True, 1, "1", "true", "on") else 0
    if isinstance(c.get("chequeo"), (dict, list)):
        c["chequeo"] = json.dumps(c["chequeo"])

    if c["deposito_id"] and not con.execute("SELECT 1 FROM combustible_depositos WHERE id=?",
                                            (c["deposito_id"],)).fetchone():
        return None, "el depósito no existe"
    if c["equipo_id"] and not con.execute("SELECT 1 FROM equipos WHERE id=?", (c["equipo_id"],)).fetchone():
        return None, "el activo no existe"

    if tipo == "medicion":
        if not c["deposito_id"] or c["nivel_medido"] is None or c["nivel_medido"] < 0:
            return None, "la medición necesita depósito y nivel medido"
        c["galones"] = 0          # se calcula al guardar (descuadre)
    else:
        if not c["galones"] or c["galones"] <= 0:
            return None, "indica los galones"
        if c["galones"] > 20000:
            return None, "cantidad fuera de rango"
    if tipo == "compra" and not c["deposito_id"]:
        return None, "una compra entra a un depósito"
    if tipo == "tanqueo" and not c["equipo_id"]:
        return None, "elige el avión que se tanquea"
    if tipo == "tanqueo":
        eq = con.execute("SELECT tipo_activo FROM equipos WHERE id=?", (c["equipo_id"],)).fetchone()
        if not eq or eq["tipo_activo"] != "avion":
            return None, "el tanqueo es sólo para aviones"
    if tipo == "merma" and not (c["deposito_id"] or c["equipo_id"]):
        return None, "indica de dónde salió la merma"

    if c["deposito_id"] and not d.get("combustible"):
        c["combustible"] = con.execute("SELECT combustible FROM combustible_depositos WHERE id=?",
                                       (c["deposito_id"],)).fetchone()["combustible"]
    if c["combustible"] not in COMBUSTIBLES:
        c["combustible"] = "avgas_100ll"

    # Precio y total: con uno se calcula el otro.
    if c["galones"]:
        if c["precio_gal"] is not None and c["total"] is None:
            c["total"] = round(c["precio_gal"] * c["galones"], 2)
        elif c["total"] is not None and c["precio_gal"] is None:
            c["precio_gal"] = round(c["total"] / c["galones"], 2)
    # Un tanqueo desde depósito propio se valora al costo medio del depósito.
    if tipo == "tanqueo" and c["deposito_id"] and c["precio_gal"] is None:
        p = precio_medio(con, deposito_id=c["deposito_id"], hasta=c["fecha"])
        if p:
            c["precio_gal"], c["total"] = round(p, 2), round(p * c["galones"], 2)

    if tipo == "tanqueo":
        c["destino"] = "aeronave"
    if c.get("destino") and c["destino"] not in DESTINOS:
        c["destino"] = "otro"
    for k in ("proveedor", "documento", "responsable", "nota", "hora", "archivo"):
        c[k] = (str(c[k]).strip() or None) if c.get(k) not in (None, "") else None
    return c, None


def guardar(con, c, usuario=None, id_=None):
    if c["tipo"] == "medicion":
        teorico = nivel_deposito(con, c["deposito_id"], hasta=(c["fecha"], c.get("hora") or "99", id_ or 10**12),
                                 excluir=id_)
        c["galones"] = round(c["nivel_medido"] - teorico, 2)
    if id_:
        sets = ", ".join(f"{k}=?" for k in CAMPOS)
        con.execute(f"UPDATE combustible_movimientos SET {sets} WHERE id=?", [c[k] for k in CAMPOS] + [id_])
        return id_
    cur = con.execute(f"INSERT INTO combustible_movimientos({', '.join(CAMPOS)}, usuario) "
                      f"VALUES({', '.join('?' * len(CAMPOS))}, ?)", [c[k] for k in CAMPOS] + [usuario])
    return cur.lastrowid


def _movs(con, desde=None, hasta=None, equipo_id=None, deposito_id=None):
    cond, p = ["1=1"], []
    if desde:
        cond.append("m.fecha>=?"); p.append(desde)
    if hasta:
        cond.append("m.fecha<=?"); p.append(hasta)
    if equipo_id:
        cond.append("m.equipo_id=?"); p.append(equipo_id)
    if deposito_id:
        cond.append("m.deposito_id=?"); p.append(deposito_id)
    return [dict(f) for f in con.execute(
        f"""SELECT m.*, e.nombre equipo, e.modelo, e.tipo_activo, e.matricula, d.nombre deposito
            FROM combustible_movimientos m
            LEFT JOIN equipos e ON e.id=m.equipo_id
            LEFT JOIN combustible_depositos d ON d.id=m.deposito_id
            WHERE {' AND '.join(cond)} ORDER BY m.fecha DESC, COALESCE(m.hora,'') DESC, m.id DESC""", p).fetchall()]


# ======================================================================
# Depósitos
# ======================================================================

def _efecto(m):
    """Cuánto cambia el nivel del depósito un movimiento."""
    g = m["galones"] or 0
    return {"compra": g, "tanqueo": -g, "merma": -g, "medicion": g}.get(m["tipo"], 0)


def nivel_deposito(con, deposito_id, hasta=None, excluir=None):
    """Nivel calculado del depósito. `hasta` = (fecha, hora, id): sólo lo anterior cuenta."""
    dep = con.execute("SELECT * FROM combustible_depositos WHERE id=?", (deposito_id,)).fetchone()
    if not dep:
        return 0
    nivel = dep["nivel_inicial_gal"] or 0
    for m in con.execute("""SELECT id, tipo, galones, fecha, hora FROM combustible_movimientos
                            WHERE deposito_id=? AND fecha>=COALESCE(?, '0000')
                            ORDER BY fecha, COALESCE(hora,''), id""",
                         (deposito_id, dep["fecha_inicial"])).fetchall():
        if excluir and m["id"] == excluir:
            continue
        if hasta and (m["fecha"], m["hora"] or "", m["id"]) >= hasta:
            break
        nivel += _efecto(m)
    return round(nivel, 2)


def serie_deposito(con, deposito_id):
    """Nivel después de cada movimiento: para dibujar la curva del depósito."""
    dep = con.execute("SELECT * FROM combustible_depositos WHERE id=?", (deposito_id,)).fetchone()
    nivel = dep["nivel_inicial_gal"] or 0
    serie = [{"fecha": dep["fecha_inicial"] or (dep["creado"] or "")[:10], "nivel": round(nivel, 1), "tipo": "inicio"}]
    for m in con.execute("""SELECT * FROM combustible_movimientos WHERE deposito_id=?
                            AND fecha>=COALESCE(?, '0000') ORDER BY fecha, COALESCE(hora,''), id""",
                         (deposito_id, dep["fecha_inicial"])).fetchall():
        nivel += _efecto(m)
        serie.append({"fecha": m["fecha"], "nivel": round(nivel, 1), "tipo": m["tipo"], "id": m["id"],
                      "galones": m["galones"]})
    return serie


def depositos(con):
    lista = []
    for d in con.execute("SELECT * FROM combustible_depositos ORDER BY activo DESC, nombre").fetchall():
        d = dict(d)
        d["nivel_gal"] = nivel_deposito(con, d["id"])
        cap = d["capacidad_gal"] or 0
        d["pct"] = round(d["nivel_gal"] / cap * 100, 1) if cap else None
        ult = con.execute("""SELECT fecha, nivel_medido, galones FROM combustible_movimientos
                             WHERE deposito_id=? AND tipo='medicion' ORDER BY fecha DESC, id DESC LIMIT 1""",
                          (d["id"],)).fetchone()
        d["ultima_medicion"] = dict(ult) if ult else None
        d["precio_medio"] = _r(precio_medio(con, deposito_id=d["id"]))
        # Días que alcanza al ritmo de los últimos 30 días.
        salida = con.execute("""SELECT COALESCE(SUM(galones),0) g FROM combustible_movimientos
                                WHERE deposito_id=? AND tipo IN ('tanqueo','merma') AND fecha>=?""",
                             (d["id"], (date.today() - timedelta(days=29)).isoformat())).fetchone()["g"]
        d["salida_30d"] = round(salida or 0, 1)
        d["dias_autonomia"] = round(d["nivel_gal"] / (salida / 30), 0) if salida else None
        lista.append(d)
    return lista


def precio_medio(con, deposito_id=None, combustible=None, desde=None, hasta=None):
    """Precio ponderado por galón de lo comprado (compras y tanqueos pagados en el aeródromo)."""
    cond, p = ["precio_gal IS NOT NULL", "galones>0",
               "(tipo='compra' OR (tipo='tanqueo' AND deposito_id IS NULL))"], []
    if deposito_id:
        cond[-1] = "tipo='compra'"
        cond.append("deposito_id=?"); p.append(deposito_id)
    if combustible:
        cond.append("combustible=?"); p.append(combustible)
    if desde:
        cond.append("fecha>=?"); p.append(desde)
    if hasta:
        cond.append("fecha<=?"); p.append(hasta)
    f = con.execute(f"SELECT SUM(precio_gal*galones) v, SUM(galones) g FROM combustible_movimientos "
                    f"WHERE {' AND '.join(cond)}", p).fetchone()
    return (f["v"] / f["g"]) if f and f["g"] else None


# ======================================================================
# Consumo por activo
# ======================================================================

def _horas(con, equipo_id, desde=None, hasta=None, desde_excl=False):
    cond, p = ["equipo_id=?"], [equipo_id]
    if desde:
        cond.append("fecha>?" if desde_excl else "fecha>=?"); p.append(desde)
    if hasta:
        cond.append("fecha<=?"); p.append(hasta)
    f = con.execute(f"""SELECT COALESCE(SUM(horas_vuelo),0) h, COALESCE(SUM(hectareas),0) ha,
                               SUM(combustible_gal) rep,
                               SUM(CASE WHEN combustible_gal IS NOT NULL THEN horas_vuelo END) h_rep
                        FROM operaciones WHERE {' AND '.join(cond)}""", p).fetchone()
    return dict(f)


def tramos_lleno(con, equipo_id, desde=None, hasta=None):
    """Tramos entre dos tanqueos a tanque lleno: galones cargados en el tramo ÷ horas del tramo.
    Si los dos llenos traen lectura de Hobbs/horómetro se usa esa diferencia (lo exacto); si no,
    las horas de las operaciones entre las dos fechas."""
    llenos = con.execute("""SELECT id, fecha, hora, lectura FROM combustible_movimientos
                            WHERE equipo_id=? AND tipo='tanqueo' AND lleno=1
                            ORDER BY fecha, COALESCE(hora,''), id""", (equipo_id,)).fetchall()
    tramos = []
    for a, b in zip(llenos, llenos[1:]):
        if desde and b["fecha"] < desde or hasta and b["fecha"] > hasta:
            continue
        gal = con.execute("""SELECT COALESCE(SUM(galones),0) g FROM combustible_movimientos
                             WHERE equipo_id=? AND tipo='tanqueo'
                               AND (fecha, COALESCE(hora,''), id) > (?, ?, ?)
                               AND (fecha, COALESCE(hora,''), id) <= (?, ?, ?)""",
                          (equipo_id, a["fecha"], a["hora"] or "", a["id"],
                           b["fecha"], b["hora"] or "", b["id"])).fetchone()["g"]
        if a["lectura"] is not None and b["lectura"] is not None and b["lectura"] > a["lectura"]:
            horas, fuente = b["lectura"] - a["lectura"], "lectura"
        else:
            horas, fuente = _horas(con, equipo_id, a["fecha"], b["fecha"], desde_excl=True)["h"], "operaciones"
        tramos.append({"desde": a["fecha"], "hasta": b["fecha"], "galones": round(gal, 1),
                       "horas": round(horas, 2), "fuente": fuente,
                       "gal_h": round(gal / horas, 2) if horas else None, "hasta_id": b["id"]})
    return tramos


def consumo_equipos(con, desde=None, hasta=None, equipo_id=None):
    filas = []
    cond = "WHERE e.id=?" if equipo_id else "WHERE e.estado!='baja' AND e.tipo_activo='avion'"
    for e in con.execute(f"SELECT * FROM equipos e {cond} ORDER BY e.tipo_activo DESC, e.nombre",
                         (equipo_id,) if equipo_id else ()).fetchall():
        e = dict(e)
        t = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(galones),0) g, SUM(total) costo, MAX(fecha) ultima
                           FROM combustible_movimientos WHERE equipo_id=? AND tipo='tanqueo'
                             AND fecha>=COALESCE(?, '0000') AND fecha<=COALESCE(?, '9999')""",
                        (e["id"], desde, hasta)).fetchone()
        h = _horas(con, e["id"], desde, hasta)
        esp = espec_equipo(con, e)
        tramos = tramos_lleno(con, e["id"], desde, hasta)
        tr_h = sum(x["horas"] for x in tramos)
        gal_h_lleno = (sum(x["galones"] for x in tramos) / tr_h) if tr_h else None
        gal_h_periodo = (t["g"] / h["h"]) if h["h"] and t["g"] else None
        gal_h = gal_h_lleno or gal_h_periodo
        gal_h_rep = (h["rep"] / h["h_rep"]) if h["rep"] and h["h_rep"] else None
        concil = None
        if t["g"] and h["rep"]:
            concil = round((t["g"] - h["rep"]) / t["g"], 3)
        ref = _num(esp.get("consumo_ref"))
        filas.append({
            "equipo_id": e["id"], "equipo": e["nombre"], "modelo": e["modelo"], "tipo_activo": e["tipo_activo"],
            "matricula": e.get("matricula"), "tanqueos": t["n"], "galones": round(t["g"], 1),
            "costo": _r(t["costo"], 0), "ultima": t["ultima"], "horas": round(h["h"], 2),
            "hectareas": round(h["ha"], 1), "gal_h": _r(gal_h), "metodo": "lleno" if gal_h_lleno else
            ("periodo" if gal_h_periodo else None), "gal_h_reportado": _r(gal_h_rep),
            "galones_reportados": _r(h["rep"], 1), "conciliacion": concil,
            "gal_ha": _r(t["g"] / h["ha"], 3) if h["ha"] and t["g"] else None,
            "costo_h": _r(t["costo"] / h["h"], 0) if t["costo"] and h["h"] else None,
            "consumo_ref": ref, "desvio_ref": _r((gal_h - ref) / ref, 3) if gal_h and ref else None,
            "espec": esp, "tramos": tramos,
        })
    return filas


# ======================================================================
# Alertas de control
# ======================================================================

def alertas(con, desde=None, hasta=None):
    """Lo que un jefe de operaciones querría saber sin buscarlo."""
    out = []

    def a(nivel, titulo, detalle, ref=None, **extra):
        out.append({"nivel": nivel, "titulo": titulo, "detalle": detalle, "rac": ref, **extra})

    for d in depositos(con):
        if not d["activo"]:
            continue
        cap = d["capacidad_gal"] or 0
        if cap and d["nivel_gal"] < cap * UMBRAL_DEPOSITO_BAJO:
            a("critico" if d["nivel_gal"] < cap * 0.1 else "proximo", f"{d['nombre']}: nivel bajo",
              f"Quedan {d['nivel_gal']:.0f} gal ({d['pct']:.0f} %)"
              + (f", unos {d['dias_autonomia']:.0f} días al ritmo actual." if d["dias_autonomia"] else "."),
              deposito_id=d["id"])
        if d["nivel_gal"] < -0.5:
            a("vencido", f"{d['nombre']}: nivel negativo",
              "Se ha sacado más combustible del que entró: falta registrar una compra o el nivel inicial.",
              deposito_id=d["id"])
        um = d["ultima_medicion"]
        if um and abs(um["galones"] or 0) > max(UMBRAL_DESCUADRE_GAL, cap * 0.02):
            a("critico", f"{d['nombre']}: descuadre en la medición del {um['fecha']}",
              f"La varilla dio {um['nivel_medido']:.0f} gal; el sistema esperaba "
              f"{um['nivel_medido'] - um['galones']:.0f} ({um['galones']:+.0f} gal).", deposito_id=d["id"])
        if cap and not um:
            a("info", f"{d['nombre']}: sin mediciones", "Mide el depósito con varilla al menos una vez por semana "
              "para detectar fugas o faltantes.", deposito_id=d["id"])

    hace90 = (date.today() - timedelta(days=90)).isoformat()
    for m in _movs(con, desde, hasta):
        if m["tipo"] != "tanqueo" or not m["equipo_id"]:
            continue
        eq = con.execute("SELECT * FROM equipos WHERE id=?", (m["equipo_id"],)).fetchone()
        esp = espec_equipo(con, eq)
        nombre = COMBUSTIBLES.get(m["combustible"], {}).get("nombre", m["combustible"])
        if esp.get("combustible") and m["combustible"] != esp["combustible"]:
            a("vencido", f"{m['equipo']}: combustible equivocado el {m['fecha']}",
              f"Se cargó {nombre} y el activo usa {COMBUSTIBLES[esp['combustible']]['nombre']}. "
              "Si fue real, no se vuela hasta drenar y revisar el motor.", ref="rac_tipo_combustible", mov_id=m["id"])
        cap = _num(esp.get("capacidad_gal"))
        if cap and m["galones"] > cap * 1.02:
            a("critico", f"{m['equipo']}: tanqueo mayor que el tanque",
              f"{m['galones']:.1f} gal en un tanque de {cap:.0f} gal ({m['fecha']}). Revisa la cantidad o dónde fue "
              "el resto.", mov_id=m["id"])
        if m["destino"] == "aeronave":
            chk = {}
            try:
                chk = json.loads(m["chequeo"] or "{}")
            except ValueError:
                pass
            faltan = [t for k, t, ob in CHEQUEO_AERONAVE if ob and not chk.get(k)]
            if faltan:
                a("proximo", f"{m['equipo']}: tanqueo sin chequeo completo ({m['fecha']})",
                  "Falta: " + "; ".join(faltan[:3]) + ("…" if len(faltan) > 3 else ""),
                  ref="rac_abastecimiento", mov_id=m["id"])
        if m["precio_gal"] and not m["deposito_id"]:
            media = precio_medio(con, combustible=m["combustible"], desde=hace90)
            if media and m["precio_gal"] > media * (1 + UMBRAL_PRECIO):
                a("info", f"Precio alto: {m['proveedor'] or m['equipo']} ({m['fecha']})",
                  f"$ {m['precio_gal']:,.0f}/gal frente a una media de $ {media:,.0f} en 90 días.".replace(",", "."),
                  mov_id=m["id"])

    for c in consumo_equipos(con, desde, hasta):
        if c["conciliacion"] is not None and abs(c["conciliacion"]) > UMBRAL_CONCILIACION and c["galones"] > 20:
            falta = c["galones"] - (c["galones_reportados"] or 0)
            a("critico" if c["conciliacion"] > 0.2 else "proximo", f"{c['equipo']}: combustible sin explicar",
              f"Se cargaron {c['galones']:.0f} gal y los pilotos reportan {c['galones_reportados']:.0f} gal "
              f"consumidos ({falta:+.0f} gal, {c['conciliacion']*100:+.0f} %).", equipo_id=c["equipo_id"])
        if c["desvio_ref"] is not None and abs(c["desvio_ref"]) > UMBRAL_REFERENCIA:
            a("proximo", f"{c['equipo']}: consumo fuera de lo normal",
              f"{c['gal_h']:.1f} gal/h frente a {c['consumo_ref']:.1f} de referencia "
              f"({c['desvio_ref']*100:+.0f} %). Revisa mezcla, fugas o registros.", equipo_id=c["equipo_id"])
    for eq in con.execute("SELECT id, nombre FROM equipos WHERE estado!='baja' AND tipo_activo='avion'").fetchall():
        for c in cargas_equipo(con, eq["id"]):
            if (desde and c["fecha"] < desde) or (hasta and c["fecha"] > hasta):
                continue
            if c.get("diferencia_pct") is not None and c["real"] > 5 and abs(c["diferencia_pct"]) > UMBRAL_CONCILIACION:
                a("critico" if c["diferencia_pct"] > 0.2 else "proximo",
                  f"{eq['nombre']}: carga del {c['fecha']} no cuadra",
                  f"Al volver a llenar se repusieron {c['real']:.1f} gal y los vuelos explican {c['consumido']:.1f} "
                  f"({c['diferencia']:+.1f} gal, {c['diferencia_pct']*100:+.0f} %).", mov_id=c["id"])
            if c["estado"] == "en_uso" and c.get("bajo_reserva"):
                a("critico", f"{eq['nombre']}: combustible bajo la reserva",
                  f"Quedan unos {c['restante']:.1f} gal a bordo y la reserva de 30 min es {c['reserva_gal']:.1f} gal. "
                  "Tanquear antes del próximo vuelo.", ref="comb_reserva", mov_id=c["id"])
    orden = {"vencido": 0, "critico": 1, "proximo": 2, "info": 3}
    return sorted(out, key=lambda x: orden.get(x["nivel"], 9))


# ======================================================================
# Resumen para la pantalla
# ======================================================================

def resumen(con, desde=None, hasta=None, equipo_id=None, tipo=None):
    movs = _movs(con, desde, hasta, equipo_id)
    if tipo:
        movs = [m for m in movs if (m.get("tipo_activo") or None) == tipo or (m["tipo"] != "tanqueo" and not equipo_id)]
    tanq = [m for m in movs if m["tipo"] == "tanqueo"]
    compras = [m for m in movs if m["tipo"] == "compra"]
    gasto = sum(m["total"] or 0 for m in compras) + sum(m["total"] or 0 for m in tanq if not m["deposito_id"])
    consumo = [c for c in consumo_equipos(con, desde, hasta, equipo_id) if not tipo or c["tipo_activo"] == tipo]
    horas = sum(c["horas"] for c in consumo if c["galones"])
    gal = sum(c["galones"] for c in consumo)
    costo_tanq = sum(c["costo"] or 0 for c in consumo)

    por_mes = {}
    for m in movs:
        mes = m["fecha"][:7]
        x = por_mes.setdefault(mes, {"mes": mes, "tanqueado": 0, "comprado": 0, "gasto": 0})
        if m["tipo"] == "tanqueo":
            x["tanqueado"] += m["galones"] or 0
        if m["tipo"] == "compra":
            x["comprado"] += m["galones"] or 0
        if m["tipo"] == "compra" or (m["tipo"] == "tanqueo" and not m["deposito_id"]):
            x["gasto"] += m["total"] or 0
    precios = [{"fecha": m["fecha"], "precio": m["precio_gal"], "combustible": m["combustible"],
                "proveedor": m["proveedor"], "id": m["id"]}
               for m in reversed(movs) if m["precio_gal"] and (m["tipo"] == "compra" or not m["deposito_id"])]
    # El precio medio sólo tiene sentido por combustible: se da el del que más galones mueve.
    por_comb = {}
    for m in movs:
        if m["tipo"] in ("compra", "tanqueo"):
            por_comb[m["combustible"]] = por_comb.get(m["combustible"], 0) + (m["galones"] or 0)
    principal = max(por_comb, key=por_comb.get) if por_comb else None
    return {
        "kpis": {"galones": round(gal, 1), "tanqueos": len(tanq), "gasto": round(gasto, 0),
                 "precio_medio": _r(precio_medio(con, combustible=principal, desde=desde, hasta=hasta), 0)
                 if principal else None, "combustible_principal": principal,
                 "gal_h": _r(gal / horas) if horas else None,
                 "costo_h": _r(costo_tanq / horas, 0) if horas and costo_tanq else None,
                 "comprado": round(sum(m["galones"] for m in compras), 1)},
        "movimientos": movs, "por_mes": sorted(por_mes.values(), key=lambda x: x["mes"]),
        "precios": precios, "consumo": consumo,
    }


def ultimo_precio(con, combustible):
    f = con.execute("""SELECT precio_gal, proveedor FROM combustible_movimientos
                       WHERE combustible=? AND precio_gal IS NOT NULL
                         AND (tipo='compra' OR (tipo='tanqueo' AND deposito_id IS NULL))
                       ORDER BY fecha DESC, id DESC LIMIT 1""", (combustible,)).fetchone()
    return dict(f) if f else None


# ======================================================================
# Seguimiento de un tanqueo: a dónde se fue ese combustible
# ======================================================================

def _clave_tanqueo(m):
    # Sin hora, el tanqueo se toma al empezar el día: los vuelos de ese día salen de esa carga.
    return (m["fecha"], m["hora"] or "", m["id"])


def _clave_vuelo(o):
    # Sin hora de salida, el vuelo se toma al final del día (después de cualquier tanqueo de ese día).
    return (o["fecha"], o["hora_salida"] or "99:99", 10**12)


def _horas_op(o):
    h = o["horas_vuelo"] or 0
    if not h and o["hobbs_ini"] is not None and o["hobbs_fin"] is not None and o["hobbs_fin"] > o["hobbs_ini"]:
        h = o["hobbs_fin"] - o["hobbs_ini"]
    return h


def cargas_equipo(con, equipo_id):
    """Recorre en orden todos los tanqueos de un avión y reparte cada vuelo en la carga de la que
    salió (el último tanqueo antes del vuelo). Lleva la cuenta del combustible a bordo desde el
    primer tanque lleno: lleno = usable del avión; parcial = lo que había + lo cargado.

    Por vuelo se usa lo que anotó el piloto; si no anotó, horas × gal/h real del avión (o el de
    referencia). Cuando se vuelve a llenar, lo que se repone dice lo que de verdad se gastó:
    consumo real = a bordo tras cargar − (usable − galones del lleno siguiente)."""
    eq = con.execute("SELECT * FROM equipos WHERE id=?", (equipo_id,)).fetchone()
    if not eq:
        return []
    esp = espec_equipo(con, eq)
    usable = _num(esp.get("usable_gal")) or _num(esp.get("capacidad_gal"))
    fila = consumo_equipos(con, equipo_id=equipo_id)[0]
    tasa, tasa_fuente = (fila["gal_h"], "real") if fila["gal_h"] else (_num(esp.get("consumo_ref")), "referencia")

    tanq = [dict(f) for f in con.execute(
        """SELECT * FROM combustible_movimientos WHERE equipo_id=? AND tipo='tanqueo'
           ORDER BY fecha, COALESCE(hora,''), id""", (equipo_id,)).fetchall()]
    if not tanq:
        return []
    ops = [dict(f) for f in con.execute(
        """SELECT id, fecha, hora_salida, horas_vuelo, hobbs_ini, hobbs_fin, combustible_gal, hectareas,
                  piloto, cliente, zona, lote
           FROM operaciones WHERE equipo_id=? AND fecha>=? ORDER BY fecha, COALESCE(hora_salida,''), id""",
        (equipo_id, tanq[0]["fecha"])).fetchall()]

    cargas, a_bordo, j = [], None, 0
    for i, t in enumerate(tanq):
        sig = tanq[i + 1] if i + 1 < len(tanq) else None
        # Lo que había antes de cargar, y lo que queda después.
        antes = a_bordo
        if t["lleno"] and usable:
            despues = usable
        elif antes is not None:
            despues = min(antes + t["galones"], usable) if usable else antes + t["galones"]
        else:
            despues = None
        vuelos = []
        while j < len(ops) and _clave_vuelo(ops[j]) < _clave_tanqueo(t):
            j += 1          # vuelos anteriores al primer tanqueo registrado
        while j < len(ops) and (not sig or _clave_vuelo(ops[j]) < _clave_tanqueo(sig)):
            o = ops[j]; j += 1
            h = _horas_op(o)
            est = h * tasa if tasa else None
            usado = o["combustible_gal"] if o["combustible_gal"] is not None else est
            vuelos.append({"id": o["id"], "fecha": o["fecha"], "hora": o["hora_salida"], "horas": round(h, 2),
                           "hectareas": _r(o["hectareas"], 1), "piloto": o["piloto"], "cliente": o["cliente"],
                           "zona": o["zona"] or o["lote"], "reportado": _r(o["combustible_gal"]),
                           "estimado": _r(est), "gal": _r(usado),
                           "fuente": "piloto" if o["combustible_gal"] is not None else ("estimado" if est is not None else None)})
        horas = sum(v["horas"] for v in vuelos)
        if sig and t["lectura"] is not None and sig["lectura"] is not None and sig["lectura"] > t["lectura"]:
            horas_tramo, horas_fuente = sig["lectura"] - t["lectura"], "lectura"
        else:
            horas_tramo, horas_fuente = horas, "operaciones"
        consumido = sum(v["gal"] or 0 for v in vuelos)
        sin_dato = sum(1 for v in vuelos if v["gal"] is None)

        real = None
        if sig and sig["lleno"] and usable and despues is not None:
            real = max(0.0, despues - (usable - sig["galones"]))
        restante = None
        if despues is not None:
            restante = max(0.0, despues - (real if real is not None else consumido))
        c = {"id": t["id"], "fecha": t["fecha"], "hora": t["hora"], "galones": t["galones"], "lleno": bool(t["lleno"]),
             "combustible": t["combustible"], "costo": _r(t["total"], 0), "precio_gal": t["precio_gal"],
             "a_bordo_antes": _r(antes, 1), "a_bordo_despues": _r(despues, 1), "usable": usable,
             "vuelos": vuelos, "n_vuelos": len(vuelos), "horas": round(horas_tramo, 2), "horas_fuente": horas_fuente,
             "hectareas": _r(sum(v["hectareas"] or 0 for v in vuelos), 1),
             "consumido": _r(consumido, 1), "vuelos_sin_dato": sin_dato,
             "reportado": _r(sum(v["reportado"] or 0 for v in vuelos), 1),
             "real": _r(real, 1), "restante": _r(restante, 1),
             "gal_h": _r((real if real is not None else consumido) / horas_tramo) if horas_tramo else None,
             "tasa": _r(tasa), "tasa_fuente": tasa_fuente if tasa else None,
             "siguiente": {"id": sig["id"], "fecha": sig["fecha"], "galones": sig["galones"],
                           "lleno": bool(sig["lleno"])} if sig else None,
             "estado": "cerrado" if sig else "en_uso"}
        # Autonomía de lo que queda: sólo tiene sentido para la carga que está en el tanque.
        if not sig and restante is not None and tasa:
            reserva = tasa * 0.5          # 30 min VFR diurno, RAC 91.610(a)(3) / 137.35(n)
            c["reserva_gal"] = round(reserva, 1)
            c["horas_restantes"] = round(max(0.0, restante - reserva) / tasa, 2)
            c["bajo_reserva"] = restante < reserva
        # Descuadre: lo que se repuso frente a lo que explican los vuelos.
        if real is not None and not sin_dato and vuelos:
            c["diferencia"] = round(real - consumido, 1)
            c["diferencia_pct"] = round((real - consumido) / real, 3) if real else None
        cargas.append(c)
        # A bordo al llegar al siguiente tanqueo.
        a_bordo = (usable - sig["galones"]) if sig and sig["lleno"] and usable else restante
    return cargas


def seguimiento_tanqueo(con, mov_id):
    m = con.execute("SELECT equipo_id, tipo FROM combustible_movimientos WHERE id=?", (mov_id,)).fetchone()
    if not m or m["tipo"] != "tanqueo" or not m["equipo_id"]:
        return None
    return next((c for c in cargas_equipo(con, m["equipo_id"]) if c["id"] == mov_id), None)


def carga_actual(con, equipo_id):
    """La carga que está ahora en el tanque del avión (el último tanqueo)."""
    cargas = cargas_equipo(con, equipo_id)
    return cargas[-1] if cargas else None
