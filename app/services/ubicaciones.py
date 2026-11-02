"""Catálogo de provincias y localidades.

- `catalogo_en_memoria()`: el catálogo agrupado por provincia y ordenado, para
  que los endpoints del catálogo respondan sin consultar la base. Se carga al
  arrancar el backend (lo importa `app/routers/catalogos.py`): leer el JSON
  tarda unos 30 ms y ocupa unos 2 MB.
- `sembrar_ubicaciones(db)`: carga el mismo JSON a las tablas (seed local).
- `huella_catalogo()`: hash del contenido, para detectar si el JSON cambió sin
  una migración nueva (ver el test de consistencia).

La tabla sigue siendo la que valida: el alta del profesional y la clave foránea
usan `localidades`, no la memoria. Los dos salen del mismo JSON.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.ubicacion import Localidad, Provincia

ARCHIVO_CATALOGO = Path(__file__).resolve().parents[1] / "db" / "ubicaciones.json"


@lru_cache(maxsize=1)
def cargar_catalogo() -> dict:
    """`{"provincias": [{id, nombre}], "localidades": [{id, nombre, departamento, provincia_id}]}`."""
    return json.loads(ARCHIVO_CATALOGO.read_text(encoding="utf-8"))


def huella_catalogo(datos: dict | None = None) -> str:
    """SHA-256 del contenido (sin el campo `fuente`), independiente del formato
    del archivo: los saltos de línea de Windows no cambian la huella."""
    datos = datos or cargar_catalogo()
    canonico = json.dumps(
        {"provincias": datos["provincias"], "localidades": datos["localidades"]},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def normalizar(texto: str) -> str:
    """Sin tildes y en minúsculas: para ordenar y para buscar ("cordoba" encuentra "Córdoba")."""
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return sin_tildes.casefold()


@dataclass(frozen=True)
class LocalidadEnMemoria:
    id: str
    nombre: str
    departamento: str
    clave: str  # nombre normalizado, para el filtro `q`


@dataclass(frozen=True)
class CatalogoEnMemoria:
    provincias: tuple[tuple[str, str], ...]  # (id, nombre), ordenadas por nombre
    localidades_por_provincia: dict[str, tuple[LocalidadEnMemoria, ...]]
    provincia_de_localidad: dict[str, str]


@lru_cache(maxsize=1)
def catalogo_en_memoria() -> CatalogoEnMemoria:
    datos = cargar_catalogo()
    provincias = tuple(
        (p["id"], p["nombre"]) for p in sorted(datos["provincias"], key=lambda p: normalizar(p["nombre"]))
    )
    por_provincia: dict[str, list[LocalidadEnMemoria]] = {provincia_id: [] for provincia_id, _ in provincias}
    for loc in sorted(datos["localidades"], key=lambda l: (normalizar(l["nombre"]), normalizar(l["departamento"]), l["id"])):
        por_provincia[loc["provincia_id"]].append(
            LocalidadEnMemoria(id=loc["id"], nombre=loc["nombre"], departamento=loc["departamento"], clave=normalizar(loc["nombre"]))
        )
    return CatalogoEnMemoria(
        provincias=provincias,
        localidades_por_provincia={provincia_id: tuple(lista) for provincia_id, lista in por_provincia.items()},
        provincia_de_localidad={loc["id"]: loc["provincia_id"] for loc in datos["localidades"]},
    )


def sembrar_ubicaciones(db: Session) -> int:
    """Inserta las provincias y localidades que falten. Idempotente: no pisa
    las existentes. Devuelve cuántas localidades se agregaron."""
    catalogo = cargar_catalogo()
    provincias_existentes = {fila[0] for fila in db.query(Provincia.id_provincia)}
    db.add_all(
        Provincia(id_provincia=p["id"], nombre=p["nombre"]) for p in catalogo["provincias"] if p["id"] not in provincias_existentes
    )
    db.flush()

    localidades_existentes = {fila[0] for fila in db.query(Localidad.id_localidad)}
    nuevas = [
        Localidad(id_localidad=loc["id"], nombre=loc["nombre"], departamento=loc["departamento"], provincia_id=loc["provincia_id"])
        for loc in catalogo["localidades"]
        if loc["id"] not in localidades_existentes
    ]
    db.add_all(nuevas)
    db.flush()
    return len(nuevas)
