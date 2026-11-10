"""Qué se ve del Profesional (HU-07).

Una reseña o un trabajo dado de baja por el administrador no aparece en el perfil
público ni cuenta para promedios, contadores ni límites. Este es el único lugar
donde se define eso: todo filtro de visibilidad usa estas funciones.
"""

from sqlalchemy import and_

from app.models.resena import EstadoResena, Resena
from app.models.trabajo_realizado import TrabajoRealizado


def resenas_visibles():
    """Publicadas (Aceptada) y no dadas de baja."""
    return and_(Resena.estado == EstadoResena.ACEPTADA, Resena.dado_de_baja_en.is_(None))


def trabajos_visibles():
    return TrabajoRealizado.dado_de_baja_en.is_(None)
