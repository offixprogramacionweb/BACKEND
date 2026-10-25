"""Catálogo de provincias y localidades: lectura del JSON versionado y carga a la base."""

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.ubicacion import Localidad, Provincia

ARCHIVO_CATALOGO = Path(__file__).resolve().parents[1] / "db" / "ubicaciones.json"


@lru_cache(maxsize=1)
def cargar_catalogo() -> dict:
    """`{"provincias": [{id, nombre}], "localidades": [{id, nombre, departamento, provincia_id}]}`."""
    return json.loads(ARCHIVO_CATALOGO.read_text(encoding="utf-8"))


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
