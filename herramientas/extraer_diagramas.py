"""Extrae las láminas de despiece de los Excel «Material Information» de DJI.

Cada hoja de esos libros es una lámina: a la izquierda la foto del módulo con los números
sobre las piezas, a la derecha la tabla de materiales (No. / código / nombre CN / nombre EN /
nombre JP / si es material auxiliar). Este script saca las dos cosas:

  · la imagen grande de la hoja  ->  static_shell/diagramas/<modelo>/<clave>.png
  · la tabla de materiales       ->  core/diagramas/<modelo>.json

Los nombres en castellano no se calculan aquí: los pone `traducir_diagramas.js`, que usa el
mismo traductor que la pantalla de diagramas para que una pieza se llame igual en todas partes.

Uso:
    python herramientas/extraer_diagramas.py T100 "ruta/al/Excel 1.xlsx" "ruta/al/Excel 2.xlsx" ...
"""
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laminas  # noqa: E402  (vive junto a este script)

RAIZ = Path(__file__).resolve().parent.parent
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ---------- Imágenes: hoja -> dibujo -> media ----------

def _rels(z, parte):
    """Relaciones de una parte del paquete OOXML, como {id: destino}."""
    ruta = f"{parte.rsplit('/', 1)[0]}/_rels/{parte.rsplit('/', 1)[1]}.rels"
    if ruta not in z.namelist():
        return {}
    raiz = ET.fromstring(z.read(ruta))
    return {r.get("Id"): r.get("Target") for r in raiz}


def _absoluto(base, destino):
    """Resuelve un Target relativo ('../media/image1.png') contra la parte que lo declara."""
    partes = base.rsplit("/", 1)[0].split("/")
    for trozo in destino.split("/"):
        if trozo == "..":
            partes.pop()
        elif trozo not in (".", ""):
            partes.append(trozo)
    return "/".join(partes)


def imagenes_por_hoja(ruta_xlsx):
    """{título de hoja: bytes de su imagen más grande}. La lámina siempre es la foto grande."""
    salida = {}
    with zipfile.ZipFile(ruta_xlsx) as z:
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        rels_libro = _rels(z, "xl/workbook.xml")
        for hoja in libro.find(f"{NS_MAIN}sheets"):
            titulo = hoja.get("name")
            destino = rels_libro.get(hoja.get(f"{NS_R}id"))
            if not destino:
                continue
            parte_hoja = _absoluto("xl/workbook.xml", destino)
            candidatas = []
            for destino_hoja in _rels(z, parte_hoja).values():
                if "drawing" not in destino_hoja:
                    continue
                parte_dibujo = _absoluto(parte_hoja, destino_hoja)
                for destino_img in _rels(z, parte_dibujo).values():
                    if "media" not in destino_img:
                        continue
                    parte_img = _absoluto(parte_dibujo, destino_img)
                    try:
                        candidatas.append((z.getinfo(parte_img).file_size, parte_img))
                    except KeyError:
                        pass
            if candidatas:
                salida[titulo] = z.read(max(candidatas)[1])
    return salida


# ---------- Tabla de materiales ----------

def _texto(valor):
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def partes_de_hoja(ws):
    """Lee la tabla «物料清单 / Material List» de una hoja.

    La tabla no empieza siempre en la misma celda (la foto ocupa un ancho distinto en cada
    lámina), así que se localiza la fila de encabezado por su celda «No.» y a partir de ahí se
    leen las columnas por su posición relativa.
    """
    fila_enc = col_no = None
    for fila in ws.iter_rows(min_row=1, max_row=40):
        for celda in fila:
            if _texto(celda.value) == "No.":
                fila_enc, col_no = celda.row, celda.column
                break
        if fila_enc:
            break
    if not fila_enc:
        return []

    # A la derecha de «No.» van código, nombre CN, nombre EN, nombre JP, auxiliar y notas.
    col_codigo, col_zh, col_en, col_aux = col_no + 1, col_no + 2, col_no + 3, col_no + 5
    partes = []
    for fila in ws.iter_rows(min_row=fila_enc + 1, max_row=ws.max_row):
        def val(col):
            return _texto(ws.cell(row=fila[0].row, column=col).value)

        codigo, nombre_en = val(col_codigo), val(col_en)
        if not codigo and not nombre_en:
            continue  # numeración sobrante al final de la lámina
        try:
            n = int(float(val(col_no)))
        except ValueError:
            continue
        partes.append({
            "n": n,
            "codigo": codigo,
            "nombre_en": nombre_en,
            "nombre_zh": val(col_zh),
            # DJI marca con «是/Yes» lo que es material auxiliar (tornillería, juntas, adhesivos).
            "auxiliar": val(col_aux).lower() in ("是", "yes", "y", "sí", "si", "true", "1"),
        })
    return partes


def clave_desde(titulo, usadas):
    """Clave de emergencia para una lámina que no está en `laminas.LAMINAS`."""
    base = re.sub(r"[^a-z0-9]+", "_", titulo.lower()).strip("_") or "lamina"
    clave, i = base, 2
    while clave in usadas:
        clave, i = f"{base}_{i}", i + 1
    return clave


def _guardar_imagen(datos, destino):
    """Guarda la lámina como JPEG de 2000 px máximo.

    Los PNG que traen los Excel pesan hasta 7 MB cada uno (111 MB las 30 láminas del T100), que
    es inservible en una pantalla que las carga en galería. A 2000 px y calidad 82 se siguen
    leyendo los números sobre las piezas y el total baja a menos de 10 MB.
    """
    bruto = destino.with_suffix(".png")
    bruto.write_bytes(datos)
    hecho = subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82", "-Z", "2000",
         str(bruto), "--out", str(destino)],
        capture_output=True,
    ).returncode == 0
    if hecho:
        bruto.unlink()
    else:  # sin sips (fuera de macOS) se queda el PNG original
        bruto.replace(destino)


def main(modelo, rutas):
    dir_img = RAIZ / "static_shell" / "diagramas" / modelo.lower()
    dir_img.mkdir(parents=True, exist_ok=True)
    (RAIZ / "core" / "diagramas").mkdir(parents=True, exist_ok=True)

    modulos, usadas = [], set()
    for ruta in rutas:
        ruta = Path(ruta)
        imagenes = imagenes_por_hoja(ruta)
        wb = openpyxl.load_workbook(ruta, data_only=True)
        for ws in wb.worksheets:
            partes = partes_de_hoja(ws)
            if not partes:
                print(f"  · sin tabla, se omite: {ruta.name} / {ws.title}")
                continue
            sistema = laminas.sistema_de_archivo(ruta.name)
            mapeada = laminas.buscar(modelo, sistema, ws.title)
            if mapeada:
                clave, nombre_es, zona = mapeada
            else:
                clave = clave_desde(ws.title, usadas)
                nombre_es, zona = ws.title, ws.title
                print(f"  ! lámina sin nombrar en herramientas/laminas.py: "
                      f"({sistema!r}, {ws.title!r})")
            usadas.add(clave)
            imagen = None
            if ws.title in imagenes:
                imagen = f"{clave}.jpeg"
                _guardar_imagen(imagenes[ws.title], dir_img / imagen)
            modulos.append({
                "clave": clave,
                "nombre": nombre_es,
                "nombre_zh": ws.title.strip(),
                "sistema": laminas.SISTEMAS[sistema],
                "zona": zona,
                "imagen": imagen,
                "piezas_catalogo": laminas.piezas_catalogo(modelo, clave),
                "partes": partes,
            })
            print(f"  · {nombre_es:38} {clave:24} {len(partes):3d} piezas"
                  f" {'con imagen' if imagen else 'SIN IMAGEN'}")
        wb.close()

    destino = RAIZ / "core" / "diagramas" / f"{modelo.lower()}.json"
    destino.write_text(json.dumps(modulos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(modulos)} láminas y {sum(len(m['partes']) for m in modulos)} piezas -> {destino}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
