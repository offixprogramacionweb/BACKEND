"""replicas_resena: respuesta única del Profesional a una reseña (HU-01 v2.1)

Revision ID: d2a7c5e9f134
Revises: b7d3e5a1c924
Create Date: 2026-11-10 10:00:00.000000

Solo crea la tabla `replicas_resena`. No toca tablas existentes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7c5e9f134"
down_revision: Union[str, None] = "b7d3e5a1c924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "offix"


def upgrade() -> None:
    op.create_table(
        "replicas_resena",
        sa.Column("id_replica", sa.Integer(), primary_key=True),
        sa.Column("resena_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.resenas.id_resena", ondelete="CASCADE"), nullable=False),
        sa.Column("oferente_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.oferentes.id_oferente", ondelete="CASCADE"), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("resena_id", name="uq_replica_resena"),
        schema=SCHEMA,
    )
    op.create_index("ix_offix_replicas_resena_id_replica", "replicas_resena", ["id_replica"], schema=SCHEMA)
    op.create_index("ix_offix_replicas_resena_oferente_id", "replicas_resena", ["oferente_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_offix_replicas_resena_oferente_id", table_name="replicas_resena", schema=SCHEMA)
    op.drop_index("ix_offix_replicas_resena_id_replica", table_name="replicas_resena", schema=SCHEMA)
    op.drop_table("replicas_resena", schema=SCHEMA)
