"""Chequeo de que la base está en la misma revisión de Alembic que el código.

Si el código se despliega sin correr `alembic upgrade head`, los modelos leen
columnas que no existen y los endpoints responden 500 (pasó con `localidad_id`).
`/health` usa esto para avisarlo.
"""

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import settings
from app.db.database import DATABASE_SCHEMA, engine, es_sqlite
from pathlib import Path

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def head_del_codigo() -> str:
    script = ScriptDirectory.from_config(_config())
    return script.get_current_head()


def _config():
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    return config


def revision_de_la_base() -> str | None:
    with engine.connect() as connection:
        if DATABASE_SCHEMA:
            connection.execute(text(f'SET search_path TO "{DATABASE_SCHEMA}"'))
        return MigrationContext.configure(
            connection, opts={"version_table_schema": DATABASE_SCHEMA}
        ).get_current_revision()


def estado_migraciones() -> dict:
    """`no_aplica` en SQLite (se crea sola). Si no coincide, `pendientes`."""
    if es_sqlite(settings.database_url):
        return {"migraciones": "no_aplica"}
    codigo = head_del_codigo()
    base = revision_de_la_base()
    if base == codigo:
        return {"migraciones": "al_dia"}
    return {"migraciones": "pendientes", "base": base, "codigo": codigo}
