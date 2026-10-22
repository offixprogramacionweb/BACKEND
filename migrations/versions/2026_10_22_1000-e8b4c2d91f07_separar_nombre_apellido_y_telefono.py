"""separar nombre/apellido y teléfonos en característica y número (HU-04, HU-06)

Revision ID: e8b4c2d91f07
Revises: a3f1c9d27b54
Create Date: 2026-10-22 10:00:00.000000

Qué hace:
- oferentes: `nombre` queda con el/los nombre/s, `apellido` con el/los apellido/s
  (nullable: en una razón social se omite). `telefono` se parte en
  `telefono_codigo_area` (2 a 4 dígitos) y `telefono_numero` (6 a 8 dígitos).
- solicitudes_resena: `telefono_cliente` se parte igual en
  `telefono_cliente_codigo_area` y `telefono_cliente_numero`.
- usuarios: se agrega `apellido`. Google lo llena en el próximo login, solo si
  manda nombre y apellido por separado. Acá no se toca nada de los datos viejos.

Backfill: heurístico. Lo que no se puede resolver con seguridad se imprime con
prefijo `[revisar]` al correr la migración, con el motivo, para corregirlo a mano:
- nombre: se parte por el último espacio, y las partículas ("de", "la", "del"...)
  se pegan al apellido ("Juan De la Fuente" -> "Juan" / "De la Fuente").
  Se marca si quedó un apellido compuesto, si hay 3 o más palabras, o si no hay
  apellido (una sola palabra, posible razón social).
- teléfono: característica de 11 (AMBA) con 2 dígitos; de las ciudades grandes
  conocidas, con 3 dígitos (351 Córdoba capital, 341 Rosario...); el resto con 4
  (3564 San Francisco...). Cualquier característica adivinada se marca.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8b4c2d91f07"
down_revision: Union[str, None] = "a3f1c9d27b54"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUFIJOS_DE_RAZON_SOCIAL = {"SRL", "SA", "SAS", "SH", "LTDA", "SCS"}
PARTICULAS_DE_APELLIDO = {"de", "del", "la", "las", "los", "y", "e", "di", "da", "das", "do", "dos", "van", "von"}
CARACTERISTICAS_DE_3_DIGITOS = {
    "351", "341", "342", "343", "261", "260", "264", "221", "223", "291", "294", "297", "299",
    "362", "370", "376", "379", "280", "381", "387", "388",
}


def separar_nombre(nombre: str | None) -> tuple[str | None, str | None, str | None]:
    """Devuelve (nombre, apellido, motivo_de_revision). El motivo es None si no hay nada que revisar."""
    partes = (nombre or "").split()
    if len(partes) < 2:
        return nombre, None, "sin apellido: una sola palabra (¿razón social?)"
    if partes[-1].upper().replace(".", "") in SUFIJOS_DE_RAZON_SOCIAL:
        # "Gasistas SRL" es una razón social: entera en `nombre`, sin apellido.
        return nombre, None, None

    inicio = len(partes) - 1
    while inicio > 1 and partes[inicio - 1].lower() in PARTICULAS_DE_APELLIDO:
        inicio -= 1

    motivo = None
    if inicio < len(partes) - 1:
        motivo = "apellido compuesto: revisar"
    elif len(partes) >= 3:
        motivo = "3 o más palabras: revisar"
    return " ".join(partes[:inicio]), " ".join(partes[inicio:]), motivo


def separar_telefono(telefono: str | None) -> tuple[str | None, str | None, str | None]:
    """Devuelve (codigo_area, numero, motivo_de_revision) a partir de los dígitos del teléfono."""
    if telefono is None:
        return None, None, None

    digitos = "".join(caracter for caracter in telefono if caracter.isdigit())
    if digitos.startswith("0"):
        digitos = digitos[1:]

    if digitos.startswith("11"):
        largo_codigo = 2
    elif digitos[:3] in CARACTERISTICAS_DE_3_DIGITOS:
        largo_codigo = 3
    else:
        largo_codigo = 4

    codigo, numero = digitos[:largo_codigo], digitos[largo_codigo:]
    motivos = []
    if len(digitos) != 10:
        motivos.append(f"teléfono de {len(digitos)} dígitos (se esperaban 10)")
    if largo_codigo == 4 and digitos[:3] not in CARACTERISTICAS_DE_3_DIGITOS:
        motivos.append("característica adivinada (4 dígitos)")
    return codigo, numero[:8], "; ".join(motivos) or None


def _imprimir_revision(tabla: str, id_fila, original: str, resultado: str, motivo: str) -> None:
    print(f"[revisar] {tabla} id={id_fila} original={original!r} -> {resultado}: {motivo}")


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("apellido", sa.String(length=150), nullable=True), schema="offix")

    op.add_column("oferentes", sa.Column("apellido", sa.String(length=150), nullable=True), schema="offix")
    op.add_column("oferentes", sa.Column("telefono_codigo_area", sa.String(length=4), nullable=True), schema="offix")
    op.add_column("oferentes", sa.Column("telefono_numero", sa.String(length=8), nullable=True), schema="offix")

    conexion = op.get_bind()
    profesionales = conexion.execute(sa.text("SELECT id_oferente, nombre, telefono FROM offix.oferentes")).fetchall()
    for id_oferente, nombre, telefono in profesionales:
        nuevo_nombre, apellido, motivo_nombre = separar_nombre(nombre)
        codigo, numero, motivo_telefono = separar_telefono(telefono)
        motivos = [m for m in (motivo_nombre, motivo_telefono) if m]
        if motivos:
            _imprimir_revision(
                "oferentes", id_oferente, f"{nombre} / {telefono}",
                f"{nuevo_nombre} | {apellido} / {codigo}-{numero}", " · ".join(motivos),
            )
        conexion.execute(
            sa.text(
                "UPDATE offix.oferentes SET nombre = :nombre, apellido = :apellido, "
                "telefono_codigo_area = :codigo, telefono_numero = :numero WHERE id_oferente = :id"
            ),
            {"nombre": nuevo_nombre, "apellido": apellido, "codigo": codigo or "", "numero": numero or "", "id": id_oferente},
        )

    op.alter_column("oferentes", "telefono_codigo_area", existing_type=sa.String(length=4), nullable=False, schema="offix")
    op.alter_column("oferentes", "telefono_numero", existing_type=sa.String(length=8), nullable=False, schema="offix")
    op.drop_column("oferentes", "telefono", schema="offix")

    op.add_column("solicitudes_resena", sa.Column("telefono_cliente_codigo_area", sa.String(length=4), nullable=True), schema="offix")
    op.add_column("solicitudes_resena", sa.Column("telefono_cliente_numero", sa.String(length=8), nullable=True), schema="offix")

    solicitudes = conexion.execute(
        sa.text("SELECT id_solicitud, telefono_cliente FROM offix.solicitudes_resena WHERE telefono_cliente IS NOT NULL")
    ).fetchall()
    for id_solicitud, telefono in solicitudes:
        codigo, numero, motivo = separar_telefono(telefono)
        if motivo:
            _imprimir_revision("solicitudes_resena", id_solicitud, telefono, f"{codigo}-{numero}", motivo)
        conexion.execute(
            sa.text(
                "UPDATE offix.solicitudes_resena SET telefono_cliente_codigo_area = :codigo, "
                "telefono_cliente_numero = :numero WHERE id_solicitud = :id"
            ),
            {"codigo": codigo, "numero": numero, "id": id_solicitud},
        )
    op.drop_column("solicitudes_resena", "telefono_cliente", schema="offix")


def downgrade() -> None:
    op.add_column("solicitudes_resena", sa.Column("telefono_cliente", sa.String(length=20), nullable=True), schema="offix")
    op.execute(
        "UPDATE offix.solicitudes_resena SET telefono_cliente = telefono_cliente_codigo_area || telefono_cliente_numero "
        "WHERE telefono_cliente_codigo_area IS NOT NULL AND telefono_cliente_numero IS NOT NULL"
    )
    op.drop_column("solicitudes_resena", "telefono_cliente_numero", schema="offix")
    op.drop_column("solicitudes_resena", "telefono_cliente_codigo_area", schema="offix")

    op.add_column("oferentes", sa.Column("telefono", sa.String(length=50), nullable=True), schema="offix")
    op.execute("UPDATE offix.oferentes SET telefono = telefono_codigo_area || telefono_numero")
    op.alter_column("oferentes", "telefono", existing_type=sa.String(length=50), nullable=False, schema="offix")
    op.execute("UPDATE offix.oferentes SET nombre = nombre || ' ' || apellido WHERE apellido IS NOT NULL")
    op.drop_column("oferentes", "telefono_numero", schema="offix")
    op.drop_column("oferentes", "telefono_codigo_area", schema="offix")
    op.drop_column("oferentes", "apellido", schema="offix")

    op.drop_column("usuarios", "apellido", schema="offix")
