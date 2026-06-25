"""
Detección de dimensiones de modelos 3D y tamaño de cama de impresoras.

Objetivo: antes de generar/subir un perfil para una impresora concreta,
verificar que el modelo cabe físicamente en la cama de esa impresora.
Si no cabe, no se genera el 3MF para esa máquina.

- Las dimensiones del modelo se calculan leyendo la malla del 3MF
  (3D/3dmodel.model) y computando el bounding box de los vértices
  ya transformados por los items de <build>.
- El tamaño de cama de cada impresora se define en su propia carpeta de
  plantilla, en un archivo `cama.txt` con la cama REAL (ej. "220x220x250").
  Si no existe, se intenta leer del project_settings.config de la plantilla.
  Al comprobar el encaje se resta MARGEN_SEGURIDAD_MM a cada eje.
"""

import os
import re
import glob
import json
from typing import Dict, List, Optional, Tuple

# Tipo: (ancho_x, fondo_y, alto_z) en milímetros
Dims = Tuple[float, float, float]

# Margen de seguridad (mm) que se resta a cada eje de la cama al comprobar
# si el modelo cabe. El archivo cama.txt guarda la cama real; este margen
# se aplica en código para no quedarse al límite del borde.
MARGEN_SEGURIDAD_MM = 10.0

# Nombre del archivo que define la cama dentro de cada carpeta de plantilla.
CAMA_FILENAME = "cama.txt"


def _localname(tag: str) -> str:
    """Devuelve el nombre de etiqueta XML sin el namespace."""
    return tag.rsplit("}", 1)[-1]


def _attr_local(elem, nombre: str) -> Optional[str]:
    """Obtiene un atributo por su nombre local, ignorando el namespace."""
    valor = elem.get(nombre)
    if valor is not None:
        return valor
    for k, v in elem.attrib.items():
        if _localname(k) == nombre:
            return v
    return None


def _parse_transform(s: Optional[str]) -> Optional[List[float]]:
    """
    Parsea un transform 3MF (12 floats: m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32).
    Devuelve la lista de 12 floats o None si no hay transform (identidad).
    """
    if not s:
        return None
    try:
        vals = [float(x) for x in s.split()]
    except ValueError:
        return None
    if len(vals) != 12:
        return None
    return vals


def _apply(m: Optional[List[float]], p: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Aplica un transform 3MF (12 floats) a un punto. p' = p * M (convención fila)."""
    if m is None:
        return p
    x, y, z = p
    nx = x * m[0] + y * m[3] + z * m[6] + m[9]
    ny = x * m[1] + y * m[4] + z * m[7] + m[10]
    nz = x * m[2] + y * m[5] + z * m[8] + m[11]
    return (nx, ny, nz)


def _matmul(inner: Optional[List[float]], outer: Optional[List[float]]) -> Optional[List[float]]:
    """
    Compone dos transforms: aplicar 'inner' y luego 'outer'.
    Equivale al producto de matrices 4x4 (convención fila): inner4 @ outer4.
    """
    if inner is None:
        return outer
    if outer is None:
        return inner

    def mat4(m: List[float]) -> List[List[float]]:
        return [
            [m[0], m[1], m[2], 0.0],
            [m[3], m[4], m[5], 0.0],
            [m[6], m[7], m[8], 0.0],
            [m[9], m[10], m[11], 1.0],
        ]

    a = mat4(inner)
    b = mat4(outer)
    r = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            r[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return [
        r[0][0], r[0][1], r[0][2],
        r[1][0], r[1][1], r[1][2],
        r[2][0], r[2][1], r[2][2],
        r[3][0], r[3][1], r[3][2],
    ]


# Factores de conversión a milímetros para la unidad del 3MF
_UNIT_TO_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}


def _localizar_model_file(work_folder: str) -> Optional[str]:
    """Localiza el archivo de malla principal dentro del 3MF descomprimido."""
    candidato = os.path.join(work_folder, "3D", "3dmodel.model")
    if os.path.exists(candidato):
        return candidato
    # Fallback: cualquier .model dentro de 3D/
    encontrados = glob.glob(os.path.join(work_folder, "3D", "*.model"))
    if encontrados:
        return encontrados[0]
    encontrados = glob.glob(os.path.join(work_folder, "**", "*.model"), recursive=True)
    return encontrados[0] if encontrados else None


def _ruta_modelo(work_folder: str, path_3mf: str) -> str:
    """Convierte una ruta interna del 3MF (ej. /3D/Objects/x.model) a ruta de disco."""
    rel = path_3mf.lstrip("/").replace("/", os.sep)
    return os.path.join(work_folder, rel)


def _parse_model_file(model_file: str) -> Tuple[Dict[str, Dict], List[Tuple[str, Optional[str], Optional[List[float]]]], str]:
    """
    Parsea un archivo .model del 3MF.

    Devuelve:
      objetos: id -> {"vertices": [...], "components": [(objid, path|None, transform)]}
      build_items: [(objid, path|None, transform)]  (normalmente solo en el modelo raíz)
      unidad: unidad declarada en <model>
    """
    import xml.etree.ElementTree as ET

    objetos: Dict[str, Dict] = {}
    build_items: List[Tuple[str, Optional[str], Optional[List[float]]]] = []
    unidad = "millimeter"

    contexto = ET.iterparse(model_file, events=("start", "end"))
    for evento, elem in contexto:
        tag = _localname(elem.tag)

        if evento == "start" and tag == "model":
            unidad = elem.get("unit", "millimeter")
            continue

        if evento != "end":
            continue

        if tag == "object":
            vertices: List[Tuple[float, float, float]] = []
            componentes: List[Tuple[str, Optional[str], Optional[List[float]]]] = []
            for hijo in elem:
                htag = _localname(hijo.tag)
                if htag == "mesh":
                    for m in hijo:
                        if _localname(m.tag) == "vertices":
                            for v in m:
                                if _localname(v.tag) == "vertex":
                                    try:
                                        vertices.append((
                                            float(v.get("x", 0.0)),
                                            float(v.get("y", 0.0)),
                                            float(v.get("z", 0.0)),
                                        ))
                                    except (TypeError, ValueError):
                                        pass
                elif htag == "components":
                    for c in hijo:
                        if _localname(c.tag) == "component":
                            objid = _attr_local(c, "objectid")
                            if objid is not None:
                                componentes.append((
                                    objid,
                                    _attr_local(c, "path"),
                                    _parse_transform(_attr_local(c, "transform")),
                                ))
            oid = elem.get("id")
            if oid is not None:
                objetos[oid] = {"vertices": vertices, "components": componentes}
            elem.clear()

        elif tag == "item":
            objid = _attr_local(elem, "objectid")
            if objid is not None:
                build_items.append((
                    objid,
                    _attr_local(elem, "path"),
                    _parse_transform(_attr_local(elem, "transform")),
                ))
            elem.clear()

    return objetos, build_items, unidad


def obtener_dimensiones_modelo(work_folder: str) -> Optional[Dims]:
    """
    Calcula las dimensiones (ancho, fondo, alto) del modelo en mm leyendo
    la malla del 3MF ya descomprimido en work_folder.

    Soporta la extensión "production" del 3MF (Creality Print / Bambu Studio),
    donde el modelo raíz solo contiene componentes con p:path que apuntan a
    archivos de malla externos dentro de 3D/Objects/.

    Devuelve None si no se puede determinar (en cuyo caso el llamador
    debería subir igualmente, sin bloquear).
    """
    import xml.etree.ElementTree as ET

    root_file = _localizar_model_file(work_folder)
    if not root_file:
        return None

    # Determinar la ruta interna del archivo raíz para resolver paths relativos
    root_internal = "/" + os.path.relpath(root_file, work_folder).replace(os.sep, "/")

    cache: Dict[str, Tuple[Dict[str, Dict], List, str]] = {}

    def cargar(path_interna: str) -> Optional[Tuple[Dict[str, Dict], List, str]]:
        if path_interna in cache:
            return cache[path_interna]
        disco = _ruta_modelo(work_folder, path_interna)
        if not os.path.exists(disco):
            cache[path_interna] = None
            return None
        try:
            datos = _parse_model_file(disco)
        except ET.ParseError:
            datos = None
        cache[path_interna] = datos
        return datos

    raiz = cargar(root_internal)
    if raiz is None:
        return None
    _, build_items, unidad_raiz = raiz

    # Bounding box global
    estado = {
        "min_x": float("inf"), "min_y": float("inf"), "min_z": float("inf"),
        "max_x": float("-inf"), "max_y": float("-inf"), "max_z": float("-inf"),
        "visto": False,
    }

    def acumular(path_actual: str, objid: str, transform: Optional[List[float]], profundidad: int = 0) -> None:
        if profundidad > 100:  # guarda contra referencias circulares
            return
        datos = cargar(path_actual)
        if datos is None:
            return
        objetos, _, _ = datos
        obj = objetos.get(objid)
        if not obj:
            return
        for v in obj["vertices"]:
            tx, ty, tz = _apply(transform, v)
            estado["visto"] = True
            if tx < estado["min_x"]: estado["min_x"] = tx
            if ty < estado["min_y"]: estado["min_y"] = ty
            if tz < estado["min_z"]: estado["min_z"] = tz
            if tx > estado["max_x"]: estado["max_x"] = tx
            if ty > estado["max_y"]: estado["max_y"] = ty
            if tz > estado["max_z"]: estado["max_z"] = tz
        for cid, cpath, ctransform in obj["components"]:
            destino = cpath if cpath else path_actual
            acumular(destino, cid, _matmul(ctransform, transform), profundidad + 1)

    if build_items:
        for objid, path, transform in build_items:
            acumular(path if path else root_internal, objid, transform)
    else:
        # Sin <build>: medir todos los objetos del archivo raíz en espacio local
        objetos_raiz = raiz[0]
        for objid in objetos_raiz:
            acumular(root_internal, objid, None)

    if not estado["visto"]:
        return None

    factor = _UNIT_TO_MM.get(unidad_raiz, 1.0)
    return (
        (estado["max_x"] - estado["min_x"]) * factor,
        (estado["max_y"] - estado["min_y"]) * factor,
        (estado["max_z"] - estado["min_z"]) * factor,
    )


def _parse_bed_de_config(config_path: str) -> Optional[Dims]:
    """
    Lee el tamaño de cama de un project_settings.config (formato JSON de
    Creality Print / Orca / Bambu Studio).

    Usa printable_area (lista de "XxY") y printable_height. Soporta también
    bed_shape (lista o cadena separada por comas) y max_print_height.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    area = data.get("printable_area") or data.get("bed_shape")
    if area is None:
        return None

    # Normalizar a lista de cadenas "XxY"
    if isinstance(area, str):
        puntos_raw = area.split(",")
    elif isinstance(area, list):
        puntos_raw = area
    else:
        return None

    xs: List[float] = []
    ys: List[float] = []
    for p in puntos_raw:
        if not isinstance(p, str):
            continue
        partes = p.lower().replace(" ", "").split("x")
        if len(partes) != 2:
            continue
        try:
            xs.append(float(partes[0]))
            ys.append(float(partes[1]))
        except ValueError:
            continue

    if not xs or not ys:
        return None

    ancho = max(xs) - min(xs)
    fondo = max(ys) - min(ys)

    altura_raw = data.get("printable_height") or data.get("max_print_height")
    if isinstance(altura_raw, list) and altura_raw:
        altura_raw = altura_raw[0]
    try:
        alto = float(altura_raw)
    except (TypeError, ValueError):
        alto = 0.0  # 0 = sin límite de altura conocido

    return (ancho, fondo, alto)


def _parse_cama_txt(path: str) -> Optional[Dims]:
    """
    Lee la cama de un archivo cama.txt. Acepta los tres números separados por
    'x', espacio, coma o '*' (ej. "220x220x250", "220 220 250"). Ignora texto
    y unidades. Devuelve (x, y, z) en mm o None.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    nums = re.findall(r"[-+]?\d*\.?\d+", txt)
    if len(nums) < 3:
        return None
    try:
        return (float(nums[0]), float(nums[1]), float(nums[2]))
    except ValueError:
        return None


def obtener_dimensiones_cama(plantilla_path: str, impresora: str) -> Optional[Dims]:
    """
    Determina el tamaño de cama (real, sin margen) de una impresora.

    Prioridad:
      1. cama.txt en la carpeta de la plantilla (fuente explícita, editable).
      2. project_settings.config de la plantilla (printable_area/height).
      3. Cualquier otro .config en la carpeta.

    Devuelve None si no se puede determinar.
    """
    cama_txt = os.path.join(plantilla_path, CAMA_FILENAME)
    if os.path.exists(cama_txt):
        bed = _parse_cama_txt(cama_txt)
        if bed:
            return bed

    candidatos = [os.path.join(plantilla_path, "project_settings.config")]
    candidatos += sorted(glob.glob(os.path.join(plantilla_path, "*.config")))
    for cfg in candidatos:
        if os.path.exists(cfg):
            bed = _parse_bed_de_config(cfg)
            if bed:
                return bed

    return None


def modelo_cabe_en_cama(
    modelo: Dims,
    cama: Dims,
    tolerancia_mm: float = MARGEN_SEGURIDAD_MM,
    permitir_rotacion: bool = True,
) -> bool:
    """
    Indica si un modelo cabe en una cama.

    Args:
        modelo: (x, y, z) del modelo en mm.
        cama: (x, y, z) de la cama REAL en mm. z<=0 = "sin límite de altura".
        tolerancia_mm: margen de seguridad que se resta a cada eje de la cama
                       (por defecto MARGEN_SEGURIDAD_MM = 10mm).
        permitir_rotacion: si True, permite girar el modelo 90° sobre Z
                           (intercambiar X/Y) para que quepa.

    Returns:
        True si cabe.
    """
    mx, my, mz = modelo
    bx, by, bz = cama

    bx_e = bx - tolerancia_mm
    by_e = by - tolerancia_mm

    # Altura: bz<=0 significa límite desconocido/ilimitado
    cabe_z = (bz <= 0) or (mz <= bz - tolerancia_mm)
    if not cabe_z:
        return False

    cabe_xy = (mx <= bx_e and my <= by_e)
    if permitir_rotacion:
        cabe_xy = cabe_xy or (mx <= by_e and my <= bx_e)

    return cabe_xy
