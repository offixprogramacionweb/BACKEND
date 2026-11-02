"""crear tabla localidades y cargar provincias/ciudades

Revision ID: b7d3e5f1a924
Revises: e8b4c2d91f07
Create Date: 2026-10-30 10:00:00.000000

LOCALIDADES (nueva): provincia y ciudad como texto, sin normalizar, para los
filtros de la búsqueda de Profesionales. Los datos salen de
`app/db/localidades.json` (Georef/INDEC, sin repetidos).

OFERENTE: localidad_id (FK a localidades). Nullable porque los perfiles
anteriores no la tienen; el registro la exige desde ahora.
"""
import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3e5f1a924'
down_revision: Union[str, None] = 'e8b4c2d91f07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = 'offix'
ARCHIVO = Path(__file__).resolve().parents[2] / 'app' / 'db' / 'localidades.json'


def upgrade() -> None:
    tabla = op.create_table(
        'localidades',
        sa.Column('id_localidad', sa.Integer(), nullable=False),
        sa.Column('provincia', sa.String(length=100), nullable=False),
        sa.Column('ciudad', sa.String(length=150), nullable=False),
        sa.PrimaryKeyConstraint('id_localidad'),
        sa.UniqueConstraint('provincia', 'ciudad', name='uq_localidades_provincia_ciudad'),
        schema=SCHEMA,
    )
    op.create_index(op.f('ix_offix_localidades_id_localidad'), 'localidades', ['id_localidad'], unique=False, schema=SCHEMA)
    op.create_index(op.f('ix_offix_localidades_provincia'), 'localidades', ['provincia'], unique=False, schema=SCHEMA)

    with ARCHIVO.open(encoding='utf-8') as archivo:
        filas = [{'provincia': provincia, 'ciudad': ciudad} for provincia, ciudad in json.load(archivo)]
    op.bulk_insert(tabla, filas)

    op.add_column('oferentes', sa.Column('localidad_id', sa.Integer(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        'fk_oferentes_localidad_id', 'oferentes', 'localidades', ['localidad_id'], ['id_localidad'],
        source_schema=SCHEMA, referent_schema=SCHEMA, ondelete='SET NULL',
    )
    op.create_index(op.f('ix_offix_oferentes_localidad_id'), 'oferentes', ['localidad_id'], unique=False, schema=SCHEMA)


def downgrade() -> None:
    op.drop_index(op.f('ix_offix_oferentes_localidad_id'), table_name='oferentes', schema=SCHEMA)
    op.drop_constraint('fk_oferentes_localidad_id', 'oferentes', schema=SCHEMA, type_='foreignkey')
    op.drop_column('oferentes', 'localidad_id', schema=SCHEMA)
    op.drop_index(op.f('ix_offix_localidades_provincia'), table_name='localidades', schema=SCHEMA)
    op.drop_index(op.f('ix_offix_localidades_id_localidad'), table_name='localidades', schema=SCHEMA)
    op.drop_table('localidades', schema=SCHEMA)
