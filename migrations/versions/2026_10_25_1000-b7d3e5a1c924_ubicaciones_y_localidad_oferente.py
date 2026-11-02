"""provincias, localidades y localidad del oferente (directorio: filtro por zona)

Revision ID: b7d3e5a1c924
Revises: e8b4c2d91f07
Create Date: 2026-10-25 10:00:00.000000

Qué hace:
- Crea `provincias` y `localidades` y las llena con el catálogo oficial del INDEC
  versionado en `app/db/ubicaciones.json` (24 provincias, 4.027 localidades
  censales). Los ids son los códigos oficiales.
- oferentes: agrega `localidad_id` (nullable: el alta todavía no la exige) y
  borra `latitud`, `longitud` y `radio_cobertura_km`, que el alta nunca cargó.
  Si algún oferente tenía coordenadas, se imprime con `[revisar]` antes de borrarlas.

El catálogo viene de la API Georef (ver `app/scripts/generar_ubicaciones.py`).
Si el catálogo oficial cambia, se regenera el JSON y se carga con una migración nueva.
"""

import hashlib
import json
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d3e5a1c924"
down_revision: Union[str, None] = "e8b4c2d91f07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "offix"
CATALOGO = Path(__file__).resolve().parents[2] / "app" / "db" / "ubicaciones.json"
# Huella del JSON que carga esta migración (ver `huella_catalogo` en app/services/ubicaciones.py).
# El backend muestra las localidades desde ese JSON en memoria y valida contra la tabla:
# si el JSON cambia, hace falta una migración nueva, y el test de consistencia lo exige.
CATALOGO_SHA256 = "f3367734c6c8bf3ba66ddc90e9050f2aa3c634ad64071a42f474897f8c6c1cd8"


def _huella(datos: dict) -> str:
    canonico = json.dumps(
        {"provincias": datos["provincias"], "localidades": datos["localidades"]},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _avisar_coordenadas_cargadas() -> None:
    # Con `alembic upgrade --sql` no hay conexión para consultar: solo se genera el script.
    if op.get_context().as_sql:
        return
    filas = op.get_bind().execute(
        sa.text(
            "SELECT id_oferente, latitud, longitud, radio_cobertura_km FROM offix.oferentes "
            "WHERE latitud IS NOT NULL OR longitud IS NOT NULL OR radio_cobertura_km IS NOT NULL"
        )
    ).fetchall()
    for id_oferente, latitud, longitud, radio in filas:
        print(
            f"[revisar] oferentes id={id_oferente} latitud={latitud} longitud={longitud} radio_km={radio}: "
            "se borran las coordenadas; cargarle la localidad a mano"
        )


def upgrade() -> None:
    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    if _huella(catalogo) != CATALOGO_SHA256:
        raise RuntimeError(
            "app/db/ubicaciones.json cambió después de escribir esta migración. "
            "Los cambios del catálogo se cargan con una migración nueva."
        )

    provincias = op.create_table(
        "provincias",
        sa.Column("id_provincia", sa.String(length=2), primary_key=True),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        schema=SCHEMA,
    )
    localidades = op.create_table(
        "localidades",
        sa.Column("id_localidad", sa.String(length=8), primary_key=True),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("departamento", sa.String(length=150), nullable=False),
        sa.Column("provincia_id", sa.String(length=2), sa.ForeignKey(f"{SCHEMA}.provincias.id_provincia"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_offix_localidades_provincia_id", "localidades", ["provincia_id"], schema=SCHEMA)

    op.bulk_insert(provincias, [{"id_provincia": p["id"], "nombre": p["nombre"]} for p in catalogo["provincias"]])
    op.bulk_insert(
        localidades,
        [
            {"id_localidad": loc["id"], "nombre": loc["nombre"], "departamento": loc["departamento"], "provincia_id": loc["provincia_id"]}
            for loc in catalogo["localidades"]
        ],
    )

    op.add_column(
        "oferentes",
        sa.Column("localidad_id", sa.String(length=8), sa.ForeignKey(f"{SCHEMA}.localidades.id_localidad"), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_offix_oferentes_localidad_id", "oferentes", ["localidad_id"], schema=SCHEMA)

    _avisar_coordenadas_cargadas()
    op.drop_column("oferentes", "radio_cobertura_km", schema=SCHEMA)
    op.drop_column("oferentes", "longitud", schema=SCHEMA)
    op.drop_column("oferentes", "latitud", schema=SCHEMA)


def downgrade() -> None:
    # Las coordenadas vuelven vacías: no se pueden reconstruir.
    op.add_column("oferentes", sa.Column("latitud", sa.Numeric(precision=10, scale=8), nullable=True), schema=SCHEMA)
    op.add_column("oferentes", sa.Column("longitud", sa.Numeric(precision=11, scale=8), nullable=True), schema=SCHEMA)
    op.add_column("oferentes", sa.Column("radio_cobertura_km", sa.Numeric(precision=5, scale=2), nullable=True), schema=SCHEMA)

    op.drop_index("ix_offix_oferentes_localidad_id", table_name="oferentes", schema=SCHEMA)
    op.drop_column("oferentes", "localidad_id", schema=SCHEMA)

    op.drop_index("ix_offix_localidades_provincia_id", table_name="localidades", schema=SCHEMA)
    op.drop_table("localidades", schema=SCHEMA)
    op.drop_table("provincias", schema=SCHEMA)
