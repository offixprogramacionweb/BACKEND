"""moderación del administrador: bajas lógicas, auditoría, matrículas validadas a mano y campana

Revision ID: f61b3d8a0c42
Revises: d2a7c5e9f134
Create Date: 2026-11-10 11:00:00.000000

Qué hace (HU-07):
- resenas y trabajos_realizados: baja lógica (`dado_de_baja_en`, `dado_de_baja_por_id`).
- matriculas: `origen` (Padron | Administrador), `validada_por_id`. `categoria` y
  `fecha_vencimiento` pasan a NULL: una matrícula validada a mano no tiene datos del padrón.
- notificaciones: `oferente_id` (el Profesional al que se refiere el aviso).
- auditoria_moderacion: historial de las acciones del administrador.
- Backfill: los Profesionales con 5 o más reseñas rechazadas reciben el aviso en la
  campana de cada administrador activo, y se actualiza `cantidad_rechazos_acumulados`
  con el total real (regla de CA08: 5 o más en total, no en una ventana).

No se borra ningún dato. El downgrade borra las matrículas validadas por el administrador
(no tienen datos para volver a `NOT NULL`).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f61b3d8a0c42"
down_revision: Union[str, None] = "d2a7c5e9f134"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "offix"
UMBRAL_RECHAZOS = 5


def upgrade() -> None:
    for tabla in ("resenas", "trabajos_realizados"):
        op.add_column(tabla, sa.Column("dado_de_baja_en", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)
        op.add_column(tabla, sa.Column("dado_de_baja_por_id", sa.Integer(), nullable=True), schema=SCHEMA)
        op.create_foreign_key(
            f"fk_{tabla}_dado_de_baja_por_id", tabla, "usuarios", ["dado_de_baja_por_id"], ["id_usuario"],
            source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="SET NULL",
        )

    op.add_column("matriculas", sa.Column("origen", sa.String(length=20), nullable=False, server_default="Padron"), schema=SCHEMA)
    op.add_column("matriculas", sa.Column("validada_por_id", sa.Integer(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_matriculas_validada_por_id", "matriculas", "usuarios", ["validada_por_id"], ["id_usuario"],
        source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="SET NULL",
    )
    op.alter_column("matriculas", "categoria", existing_type=sa.String(length=50), nullable=True, schema=SCHEMA)
    op.alter_column("matriculas", "fecha_vencimiento", existing_type=sa.Date(), nullable=True, schema=SCHEMA)

    op.add_column("notificaciones", sa.Column("oferente_id", sa.Integer(), nullable=True), schema=SCHEMA)
    op.create_foreign_key(
        "fk_notificaciones_oferente_id", "notificaciones", "oferentes", ["oferente_id"], ["id_oferente"],
        source_schema=SCHEMA, referent_schema=SCHEMA, ondelete="CASCADE",
    )
    op.create_index("ix_offix_notificaciones_oferente_id", "notificaciones", ["oferente_id"], schema=SCHEMA)

    op.create_table(
        "auditoria_moderacion",
        sa.Column("id_auditoria", sa.Integer(), primary_key=True),
        sa.Column("administrador_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.usuarios.id_usuario", ondelete="SET NULL"), nullable=True),
        sa.Column("oferente_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.oferentes.id_oferente", ondelete="CASCADE"), nullable=False),
        sa.Column("accion", sa.String(length=40), nullable=False),
        sa.Column("resena_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.resenas.id_resena", ondelete="SET NULL"), nullable=True),
        sa.Column("trabajo_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.trabajos_realizados.id_trabajo", ondelete="SET NULL"), nullable=True),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_offix_auditoria_moderacion_oferente_id", "auditoria_moderacion", ["oferente_id"], schema=SCHEMA)

    # Backfill de CA08: el umbral pasa a ser el total de rechazadas, no una ventana.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"UPDATE {SCHEMA}.oferentes o SET cantidad_rechazos_acumulados = "
            f"(SELECT count(*) FROM {SCHEMA}.resenas r WHERE r.oferente_id = o.id_oferente AND r.estado = 'Rechazada')"
        )
    )
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.notificaciones
                (usuario_id, tipo, mensaje, requiere_accion, estado, oferente_id, fecha_creacion)
            SELECT u.id_usuario,
                   'Rechazos_Reiterados',
                   'El profesional ' || trim(o.nombre || ' ' || coalesce(o.apellido, '')) || ' rechazó 5 o más reseñas a través de Offix',
                   false,
                   'Pendiente',
                   o.id_oferente,
                   now()
            FROM {SCHEMA}.oferentes o
            CROSS JOIN {SCHEMA}.usuarios u
            WHERE u.rol = 'Administrador'
              AND u.estado_cuenta = 'Activa'
              AND o.cantidad_rechazos_acumulados >= {UMBRAL_RECHAZOS}
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_offix_auditoria_moderacion_oferente_id", table_name="auditoria_moderacion", schema=SCHEMA)
    op.drop_table("auditoria_moderacion", schema=SCHEMA)

    op.drop_index("ix_offix_notificaciones_oferente_id", table_name="notificaciones", schema=SCHEMA)
    op.drop_constraint("fk_notificaciones_oferente_id", "notificaciones", schema=SCHEMA, type_="foreignkey")
    op.drop_column("notificaciones", "oferente_id", schema=SCHEMA)

    op.execute(f"DELETE FROM {SCHEMA}.matriculas WHERE origen = 'Administrador'")
    op.alter_column("matriculas", "fecha_vencimiento", existing_type=sa.Date(), nullable=False, schema=SCHEMA)
    op.alter_column("matriculas", "categoria", existing_type=sa.String(length=50), nullable=False, schema=SCHEMA)
    op.drop_constraint("fk_matriculas_validada_por_id", "matriculas", schema=SCHEMA, type_="foreignkey")
    op.drop_column("matriculas", "validada_por_id", schema=SCHEMA)
    op.drop_column("matriculas", "origen", schema=SCHEMA)

    for tabla in ("trabajos_realizados", "resenas"):
        op.drop_constraint(f"fk_{tabla}_dado_de_baja_por_id", tabla, schema=SCHEMA, type_="foreignkey")
        op.drop_column(tabla, "dado_de_baja_por_id", schema=SCHEMA)
        op.drop_column(tabla, "dado_de_baja_en", schema=SCHEMA)
