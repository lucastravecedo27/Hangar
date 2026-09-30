"""Proyección de repuestos: cuándo toca cambiar cada pieza según el ritmo real de operación.

El ritmo se saca de las operaciones registradas: cuánto avanza cada contador (horas de vuelo,
Hobbs, Tach, aterrizajes…) por día natural. Con él se traduce lo que le queda a cada pieza a
días y a una fecha estimada de cambio.

Hay piezas cuyo plazo no es de uso sino de calendario (del T100, DJI sólo publica meses). Esas
no dependen del ritmo: los días que les quedan se cuentan solos. Si una pieza tiene varios
plazos (horas, ciclos, meses), vale el que venza antes.
"""
from datetime import date, timedelta

from core import alertas as core_alertas
from core import conexion as core_conexion
from core import flota as core_flota

VENTANA_DIAS = 90          # ventana de referencia para el ritmo de vuelo
RITMO_MINIMO = 0.02        # unidades/día: por debajo de esto la proyección no es informativa


def _sumas(extra_where="", params=()):
    columnas = ", ".join(f"SUM({expr}) AS {clave}" for clave, (_, _, expr) in core_flota.CONTADORES.items())
    return (f"SELECT o.equipo_id, COUNT(*) n, MIN(o.fecha) desde, MAX(o.fecha) hasta, {columnas} "
            f"FROM operaciones o {extra_where} GROUP BY o.equipo_id"), params


def ritmos(con, ventana=VENTANA_DIAS):
    """{equipo_id: {contador: {'por_dia', 'base', 'total', 'dias', 'n'}}} con dos consultas para
    toda la flota (antes eran dos por equipo)."""
    cache = getattr(con, "cache", None)
    clave = ("ritmos", ventana)
    if cache is not None and clave in cache:
        return cache[clave]
    sql, p = _sumas(f"WHERE o.fecha >= {core_conexion.sql_hoy_menos_dias('?')}", (int(ventana),))
    recientes = {f["equipo_id"]: f for f in con.execute(sql, p).fetchall()}
    sql, p = _sumas()
    historico = {f["equipo_id"]: f for f in con.execute(sql, p).fetchall()}
    salida = {}
    for eq in con.execute("SELECT id FROM equipos").fetchall():
        eid = eq["id"]
        r, h = recientes.get(eid), historico.get(eid)
        por_contador = {}
        for c in core_flota.CONTADORES:
            if r and r["n"] and (r[c] or 0):
                por_contador[c] = {"total": round(r[c], 1), "dias": ventana, "por_dia": r[c] / ventana,
                                   "base": f"últimos {ventana} días", "n": r["n"]}
            elif h and h["n"] and (h[c] or 0):
                # Sin actividad reciente: se usa todo el histórico para no dejar la proyección en blanco.
                try:
                    dias = max((date.fromisoformat(h["hasta"]) - date.fromisoformat(h["desde"])).days + 1, 1)
                except (TypeError, ValueError):
                    dias = 1
                por_contador[c] = {"total": round(h[c], 1), "dias": dias, "por_dia": h[c] / dias,
                                   "base": "histórico completo", "n": h["n"]}
            else:
                por_contador[c] = {"total": 0, "dias": 0, "por_dia": 0, "base": "sin operaciones registradas", "n": 0}
        salida[eid] = por_contador
    if cache is not None:
        cache[clave] = salida
    return salida


def ritmo_por_equipo(con, ventana=VENTANA_DIAS):
    """Compatibilidad: ritmo de horas de vuelo de cada equipo (como antes)."""
    return {eid: {"horas": r["horas_vuelo"]["total"], "dias": r["horas_vuelo"]["dias"],
                  "h_dia": r["horas_vuelo"]["por_dia"], "base": r["horas_vuelo"]["base"], "n": r["horas_vuelo"]["n"]}
            for eid, r in ritmos(con, ventana).items()}


def proximos_repuestos(con, equipo_id=None, limite=40, horizonte_dias=None):
    """Piezas ordenadas por cercanía al cambio, con días y fecha estimados según el ritmo real."""
    todos = ritmos(con)
    hoy = date.today()
    salida = []
    vacio = {"por_dia": 0, "base": "sin operaciones registradas", "total": 0, "dias": 0}
    for c in core_alertas.componentes_con_estado(con, equipo_id):
        if c["equipo_estado"] == "baja":
            continue
        del_equipo = todos.get(c["equipo_id"], {})
        ritmo = del_equipo.get(c["contador_base"], vacio)
        restante = c["restante"]
        por_dia = ritmo["por_dia"]

        # Días que faltan por uso (dependen del ritmo), por ciclos y por calendario (no).
        dias_horas = None
        if restante is not None:
            if restante <= 0:
                dias_horas = 0
            elif por_dia >= RITMO_MINIMO:
                dias_horas = int(round(restante / por_dia))
        dias_ciclos = None
        if c["restante_ciclos"] is not None and c["contador_ciclos"]:
            rc = del_equipo.get(c["contador_ciclos"], vacio)["por_dia"]
            if c["restante_ciclos"] <= 0:
                dias_ciclos = 0
            elif rc >= RITMO_MINIMO:
                dias_ciclos = int(round(c["restante_ciclos"] / rc))
        dias_calendario = None
        if c["meses_restantes"] is not None:
            dias_calendario = max(int(round(c["meses_restantes"] * core_alertas.DIAS_POR_MES)), 0)

        candidatos = [x for x in (dias_horas, dias_ciclos, dias_calendario) if x is not None]
        dias = min(candidatos) if candidatos else None
        fecha = (hoy + timedelta(days=min(dias, 3650))).isoformat() if dias is not None else None
        d = dict(c)
        d.update({
            "dias_estimados": dias,
            "dias_por_horas": dias_horas,
            "dias_por_ciclos": dias_ciclos,
            "dias_por_calendario": dias_calendario,
            "fecha_estimada": fecha,
            "h_dia": round(por_dia, 2),
            "base_ritmo": ritmo["base"],
            "horas_ritmo": ritmo["total"],
            "urgencia": "vencido" if c["nivel"] == "vencido" else (
                "inmediato" if dias is not None and dias <= 15 else
                "corto" if dias is not None and dias <= 45 else
                "medio" if dias is not None and dias <= 120 else "lejano"),
        })
        salida.append(d)

    salida.sort(key=lambda d: (d["dias_estimados"] if d["dias_estimados"] is not None else 10 ** 6, -d["pct"]))
    if horizonte_dias:
        salida = [d for d in salida if d["dias_estimados"] is not None and d["dias_estimados"] <= horizonte_dias]
    return salida[:limite]


def resumen(con, equipo_id=None, lista=None):
    """Cabecera del panel de repuestos: cuántas piezas caen en cada franja de tiempo.
    Se le puede pasar la lista ya calculada para no recorrer la flota dos veces."""
    if lista is None:
        lista = proximos_repuestos(con, equipo_id, limite=10 ** 6)
    franjas = {"vencido": 0, "inmediato": 0, "corto": 0, "medio": 0, "lejano": 0}
    for d in lista:
        franjas[d["urgencia"]] += 1
    return {"franjas": franjas, "total": len(lista),
            "accionables": franjas["vencido"] + franjas["inmediato"] + franjas["corto"]}
