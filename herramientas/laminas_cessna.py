"""Láminas del Cessna 188A para la pantalla Diagramas, desde el catálogo ilustrado P694-12.

Uso:  python3 herramientas/laminas_cessna.py

Lee de «Informacion Drones/C188»:
  · 1. Manuales del fabricante/Catalogo de piezas P694-12/*.pdf   (dibujos de cada figura)
  · 2. Catalogo transcrito/catalogo P694-12 para la app (fig 22-151).json   (piezas 22-151)
  · 2. Catalogo transcrito/figuras P694-12.json   (título y páginas de cada figura)
  · 3D/cessna-188-despiece.glb   (piezas de las figuras 5-21, ala y empenaje, por el nombre de
    sus mallas «Nombre — P/N — F<fig>-<índice>»)

Escribe core/diagramas/c188a.json y static_shell/diagramas/c188a/f<fig>[_<hoja>].jpg. Los
números impresos en cada dibujo se ubican con el OCR de macOS (herramientas/bin/ocr, compilado
de herramientas/ocr.swift): sólo se aceptan los que coinciden con un índice de esa figura, así
que un número mal leído se queda sin punto y se coloca con «Ajustar posiciones».
Requiere PyMuPDF (pip install pymupdf).
"""
import collections
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import fitz

APP = Path(__file__).resolve().parent.parent
C188 = APP.parent / "Informacion " / "Informacion Drones" / "C188"
PDF = next((C188 / "1. Manuales del fabricante" / "Catalogo de piezas P694-12").glob("*.pdf"))
CATALOGO = C188 / "2. Catalogo transcrito" / "catalogo P694-12 para la app (fig 22-151).json"
FIGURAS = C188 / "2. Catalogo transcrito" / "figuras P694-12.json"
TRADUCCIONES = C188 / "2. Catalogo transcrito" / "traducciones P694-12.json"
GLB = C188 / "3D" / "cessna-188-despiece.glb"
SALIDA_JSON = APP / "core" / "diagramas" / "c188a.json"
SALIDA_IMG = APP / "static_shell" / "diagramas" / "c188a"
OCR = APP / "herramientas" / "bin" / "ocr"
DPI = 180

# Sistema de cada figura: el mismo reparto que los grupos MOD_* del modelo 3D.
SISTEMAS = [
    ("Ala", lambda f: 5 <= f <= 16 and f not in (12, 13) or f == 98),
    ("Empenaje", lambda f: 17 <= f <= 21),
    ("Combustible y aceite", lambda f: f in (12, 13, 37) or 99 <= f <= 107 and f not in (104, 105, 106, 107)),
    ("Cabina", lambda f: f in (30, 35, 36, 38, 39, 52, 53, 54, 57, 58, 59, 61) or 82 <= f <= 86),
    ("Fuselaje", lambda f: 22 <= f <= 34 or f == 60),
    ("Tolva", lambda f: f in (40, 41)),
    ("Tren de aterrizaje", lambda f: 44 <= f <= 51 or f == 87),
    ("Mandos", lambda f: f in (55, 56) or 88 <= f <= 97),
    ("Hélice", lambda f: 62 <= f <= 65),
    ("Motor", lambda f: 66 <= f <= 81 or 104 <= f <= 107),
    ("Sistema de aplicación", lambda f: 108 <= f <= 136),
    ("Eléctrico y aviónica", lambda f: f in (42, 43) or f >= 137),
]
# Figuras sólo de la versión turbo (T188): no son de un 188A.
TURBO = {21, 65, 67, 70, 71, 73, 75, 76, 78, 81, 107, 139, 142}

# Ítems de la plantilla del avión (core/aeronaves.py) que se ven en cada figura.
PIEZAS_CATALOGO = {
    62: ["helice"], 68: ["motor", "motor_arranque", "mangueras_motor"], 69: ["magneto_izq", "magneto_der", "bujias"],
    79: ["filtro_aire"], 105: ["aceite"], 44: ["tren_principal"], 46: ["tren_principal"], 87: ["tren_principal"],
    48: ["rueda_cola"], 50: ["rueda_cola"], 92: ["cables_mando"], 93: ["cables_mando"], 97: ["cables_mando"],
    58: ["arnes"], 40: ["tolva"], 132: ["tolva"], 108: ["bomba_aspersion"], 111: ["boquillas"], 115: ["boquillas"],
    128: ["boquillas"],
}


def sistema(f):
    return next((n for n, regla in SISTEMAS if regla(f)), "Fuselaje")


def numero(indice):
    m = re.match(r"(\d+)", indice or "")
    return int(m.group(1)) if m else None


def partes_del_catalogo():
    """Figuras 22-151: una parte por renglón con número de parte, agrupadas por índice."""
    por_fig = collections.defaultdict(list)
    for e in json.loads(CATALOGO.read_text(encoding="utf-8")):
        n = numero(e["indice"])
        pn = (e["numero_parte"] or "").strip()
        if n is None or not pn or pn.upper().startswith("SEE"):
            continue
        por_fig[e["figura"]].append({"n": n, "indice": e["indice"], "codigo": pn, "nombre_en": e["descripcion_en"],
                                     "nombre_es": e["nombre_es"], "cantidad": e["cantidad"],
                                     "uso": e["uso"], "auxiliar": bool(e["fijacion"])})
    return por_fig


def titulos_del_glb():
    b = GLB.read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    salida = {}
    for x in json.loads(b[20:20 + n])["nodes"]:
        m = re.match(r"^FIG_(\d+) (.+)$", x.get("name", ""))
        if m:
            salida[int(m.group(1))] = m.group(2)
    return salida


def partes_del_glb():
    """Figuras 5-21 (ala y empenaje): del nombre de las mallas del modelo 3D."""
    b = GLB.read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    nodos = json.loads(b[20:20 + n])["nodes"]
    por_fig, vistos = collections.defaultdict(dict), set()
    for x in nodos:
        m = re.match(r"^(.+?) — (.+?) — F(\d+)-(\w+)(?: \((\d+) de (\d+)\))?$", x.get("name", ""))
        if not m or int(m.group(3)) > 21:
            continue
        nombre, pn, f, indice, _, total = m.groups()
        clave = (int(f), indice, pn, nombre)
        if clave in vistos or numero(indice) is None:
            continue
        vistos.add(clave)
        por_fig[int(f)][clave] = {"n": numero(indice), "indice": indice, "codigo": pn, "nombre_en": "",
                                  "nombre_es": nombre, "cantidad": total or "1", "uso": "", "auxiliar": False}
    return {f: list(d.values()) for f, d in por_fig.items()}


def agrupar(filas):
    """Una entrada por número del dibujo; las variantes (LH/RH, otra serie, 17A…) van dentro."""
    grupos = collections.OrderedDict()
    for p in sorted(filas, key=lambda p: (p["n"], p["indice"])):
        g = grupos.get(p["n"])
        if g is None:
            grupos[p["n"]] = dict(p, variantes=[])
        elif p["codigo"] != g["codigo"] or p["nombre_es"] != g["nombre_es"]:
            g["variantes"].append({k: p[k] for k in ("indice", "codigo", "nombre_es", "nombre_en", "cantidad", "uso")})
    return list(grupos.values())


def paginas_de_dibujo(doc, figuras, catalogo):
    """Páginas del dibujo de cada figura. En el catálogo cada lista va justo después de su dibujo."""
    paginas = {int(k): v["paginas"] for k, v in figuras.items() if v.get("paginas")}
    primera_lista = {}
    for e in catalogo:
        primera_lista[e["figura"]] = min(primera_lista.get(e["figura"], 9999), e["pagina_pdf"])
    for f, p in primera_lista.items():
        if f in paginas:
            continue
        # Hacia atrás desde la lista: páginas sin tabla de piezas (dibujo) hasta la lista anterior.
        hojas, i = [], p - 1
        while i > 0 and "UNITS PER" not in doc[i].get_text().upper() and len(hojas) < 4:
            hojas.insert(0, i)
            i -= 1
        paginas[f] = hojas or [p - 1]
    return paginas


def ubicar_numeros(doc, hojas, indices_por_hoja, carpeta):
    """Números impresos de cada dibujo. El OCR de la página entera no ve los números pequeños
    sueltos, así que cada página se lee en 3 × 3 teselas ampliadas que se solapan un poco."""
    import tempfile
    n, solape = 3, 0.06
    teselas = []                     # (ruta png, hoja, x0, y0, ancho, alto) en fracción de página
    tmp = Path(tempfile.mkdtemp(dir=carpeta))
    for hoja, pag in hojas:
        R = doc[pag].rect
        for i in range(n):
            for j in range(n):
                x0, y0 = max(0, i / n - solape), max(0, j / n - solape)
                x1, y1 = min(1, (i + 1) / n + solape), min(1, (j + 1) / n + solape)
                ruta = tmp / f"{hoja}_{i}{j}.png"
                clip = fitz.Rect(x0 * R.width, y0 * R.height, x1 * R.width, y1 * R.height)
                doc[pag].get_pixmap(dpi=400, clip=clip, colorspace=fitz.csGRAY).save(str(ruta))
                teselas.append((str(ruta), hoja, x0, y0, x1 - x0, y1 - y0))
    por_ruta = {t[0]: t for t in teselas}
    puntos, actual = collections.defaultdict(list), None
    salida = subprocess.run([str(OCR), *por_ruta], capture_output=True, text=True).stdout
    for linea in salida.splitlines():
        if linea.startswith("### "):
            actual = por_ruta.get(linea[4:])
            continue
        if not actual or "|" not in linea:
            continue
        cajas, _, texto = linea.partition("|")
        x, y, w, h = map(float, cajas.split())
        _, hoja, tx, ty, tw, th = actual
        cx, cy = (tx + (x + w / 2) * tw) * 100, (ty + (y + h / 2) * th) * 100
        if cy > 90 or cy < 7:            # cabecera «188 Parts Catalog» y pie «Figure N. …»
            continue
        for trozo in texto.split():
            trozo = trozo.rstrip(".,")
            num = numero(trozo)
            if num is None or not re.fullmatch(r"\d+[A-Z]?", trozo) or num not in indices_por_hoja[hoja]:
                continue
            # Las teselas se solapan: el mismo número leído dos veces cuenta una.
            if any(q["n"] == num and abs(q["x"] - cx) < 1.5 and abs(q["y"] - cy) < 1.5 for q in puntos[hoja]):
                continue
            puntos[hoja].append({"n": num, "x": round(cx, 2), "y": round(cy, 2)})
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    return puntos


def main():
    doc = fitz.open(PDF)
    figuras = json.loads(FIGURAS.read_text(encoding="utf-8"))
    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    trad = json.loads(TRADUCCIONES.read_text(encoding="utf-8"))
    partes = partes_del_catalogo()
    partes.update(partes_del_glb())
    paginas = paginas_de_dibujo(doc, figuras, catalogo)
    titulo_en = {int(k): v["titulo"] for k, v in figuras.items() if v.get("titulo")}
    titulo_es = titulos_del_glb()
    for e in catalogo:
        titulo_en.setdefault(e["figura"], e["descripcion_en"].title())
        if not e["indice"] and e["nombre_es"] and e["nombre_es"] != e["descripcion_en"].capitalize():
            titulo_es.setdefault(e["figura"], e["nombre_es"])

    SALIDA_IMG.mkdir(parents=True, exist_ok=True)
    laminas, rutas, indices = [], [], {}
    for f in sorted(partes):
        if f in TURBO or not partes[f]:
            continue
        lista = agrupar(partes[f])
        en = titulo_en.get(f, "")
        es = titulo_es.get(f) or trad.get(en.upper()) or trad.get(en.upper().split(" - ")[0]) or en
        hojas = paginas.get(f) or []
        for k, pag in enumerate(hojas, 1):
            sufijo = f"_{k}" if len(hojas) > 1 else ""
            imagen = f"f{f:03d}{sufijo}.jpg"
            ruta = SALIDA_IMG / imagen
            doc[pag].get_pixmap(dpi=DPI, colorspace=fitz.csGRAY).save(str(ruta), jpg_quality=72)
            rutas.append((imagen, pag))
            indices[imagen] = {p["n"] for p in lista}
            nombre = f"Fig. {f} · {es}" + (f" (hoja {k} de {len(hojas)})" if sufijo else "")
            laminas.append({"clave": f"f{f:03d}{sufijo}", "nombre": nombre, "nombre_en": en, "figura": f,
                            "sistema": sistema(f), "zona": sistema(f), "imagen": imagen,
                            "piezas_catalogo": PIEZAS_CATALOGO.get(f, []), "partes": lista})
    puntos = ubicar_numeros(doc, rutas, indices, SALIDA_IMG.parent)
    for m in laminas:
        m["hotspots"] = puntos.get(m["imagen"], [])
    orden = [n for n, _ in SISTEMAS]
    laminas.sort(key=lambda m: (orden.index(m["sistema"]), m["figura"], m["clave"]))
    SALIDA_JSON.write_text(json.dumps(laminas, ensure_ascii=False, indent=1), encoding="utf-8")
    con_punto = sum(len({h["n"] for h in m["hotspots"]}) for m in laminas)
    total = sum(len(m["partes"]) for m in laminas)
    print(f"{len(laminas)} láminas · {total} números de pieza · {con_punto} ubicados en el dibujo "
          f"({100 * con_punto // max(total, 1)} %)", file=sys.stderr)


if __name__ == "__main__":
    main()
