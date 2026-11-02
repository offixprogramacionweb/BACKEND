"""Carga del catálogo de localidades desde `app/db/localidades.json`.

En Postgres la tabla y los datos los crea la migración; esto sirve para SQLite
(desarrollo y seed) y es idempotente: solo inserta lo que falta.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.localidad import Localidad

ARCHIVO_LOCALIDADES = Path(__file__).resolve().parent.parent / "db" / "localidades.json"


def leer_localidades() -> list[tuple[str, str]]:
    with ARCHIVO_LOCALIDADES.open(encoding="utf-8") as archivo:
        return [(provincia, ciudad) for provincia, ciudad in json.load(archivo)]


def cargar_localidades(db: Session) -> int:
    """Inserta las localidades que todavía no están. Devuelve cuántas agregó."""
    existentes = {(provincia, ciudad) for provincia, ciudad in db.query(Localidad.provincia, Localidad.ciudad)}
    nuevas = [par for par in leer_localidades() if par not in existentes]
    db.bulk_insert_mappings(Localidad, [{"provincia": provincia, "ciudad": ciudad} for provincia, ciudad in nuevas])
    db.commit()
    return len(nuevas)
