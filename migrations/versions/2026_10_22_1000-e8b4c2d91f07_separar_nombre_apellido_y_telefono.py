"""separar nombre y apellido, y teléfono en característica y número (HU-04)

Revision ID: e8b4c2d91f07
Revises: a3f1c9d27b54
Create Date: 2026-10-22 10:00:00.000000

Backfill (upgrade):
- nombre: se parte por el último espacio. Todo lo anterior queda en `nombre`
  y la última palabra va a `apellido`. Un nombre de una sola palabra queda en
  `nombre` y `apellido` queda NULL. Los apellidos compuestos ("De la Fuente")
  se parten mal: revisar a mano después de correr la migración.
- teléfono: se toman los primeros 4 dígitos como característica y los 6
  restantes como número. Las características de 3 dígitos (por ejemplo 351,
  Córdoba capital) quedan MAL partidas. Hay que revisar esas filas antes de
  dar por buena la migración.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8b4c2d91f07"
down_revision: Union[str, None] = "a3f1c9d27b54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("oferentes", sa.Column("apellido", sa.String(length=150), nullable=True), schema="offix")
    op.add_column("oferentes", sa.Column("telefono_codigo_area", sa.String(length=4), nullable=True), schema="offix")
    op.add_column("oferentes", sa.Column("telefono_numero", sa.String(length=7), nullable=True), schema="offix")

    conexion = op.get_bind()
    filas = conexion.execute(sa.text("SELECT id_oferente, nombre, telefono FROM offix.oferentes")).fetchall()
    for id_oferente, nombre, telefono in filas:
        partes = (nombre or "").split()
        if len(partes) >= 2:
            nuevo_nombre, apellido = " ".join(partes[:-1]), partes[-1]
        else:
            nuevo_nombre, apellido = nombre, None

        digitos = "".join(caracter for caracter in (telefono or "") if caracter.isdigit())
        codigo_area, numero = digitos[:4], digitos[4:10]

        conexion.execute(
            sa.text(
                "UPDATE offix.oferentes SET nombre = :nombre, apellido = :apellido, "
                "telefono_codigo_area = :codigo, telefono_numero = :numero WHERE id_oferente = :id"
            ),
            {"nombre": nuevo_nombre, "apellido": apellido, "codigo": codigo_area, "numero": numero, "id": id_oferente},
        )

    op.alter_column("oferentes", "telefono_codigo_area", existing_type=sa.String(length=4), nullable=False, schema="offix")
    op.alter_column("oferentes", "telefono_numero", existing_type=sa.String(length=7), nullable=False, schema="offix")
    op.drop_column("oferentes", "telefono", schema="offix")


def downgrade() -> None:
    op.add_column("oferentes", sa.Column("telefono", sa.String(length=50), nullable=True), schema="offix")
    op.execute("UPDATE offix.oferentes SET telefono = telefono_codigo_area || telefono_numero")
    op.alter_column("oferentes", "telefono", existing_type=sa.String(length=50), nullable=False, schema="offix")

    op.execute("UPDATE offix.oferentes SET nombre = nombre || ' ' || apellido WHERE apellido IS NOT NULL")

    op.drop_column("oferentes", "telefono_numero", schema="offix")
    op.drop_column("oferentes", "telefono_codigo_area", schema="offix")
    op.drop_column("oferentes", "apellido", schema="offix")
