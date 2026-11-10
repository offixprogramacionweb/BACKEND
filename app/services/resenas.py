"""Reglas de reseña compartidas entre routers.

El recálculo del promedio lo disparan dos caminos —la moderación del Profesional
y la publicación forzada del Administrador (RF17)—, así que no puede vivir en
uno solo de los dos routers.
"""

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import error_negocio
from app.models.oferente import Oferente
from app.models.replica_resena import ReplicaResena
from app.models.resena import EstadoResena, Resena
from app.services.moderacion import resenas_visibles


def recalcular_promedio(db: Session, oferente: Oferente) -> None:
    """Promedio de las puntuaciones globales de las reseñas **aceptadas**, con
    dos decimales. Las pendientes y las rechazadas no suman; sin reseñas
    aceptadas, el promedio vuelve a 0."""
    aceptadas = db.query(Resena).filter(Resena.oferente_id == oferente.id_oferente, resenas_visibles()).all()
    puntuaciones = [resena.calificaciones_comentarios["puntuacion_global"] for resena in aceptadas]
    oferente.promedio_calificacion = round(sum(puntuaciones) / len(puntuaciones), 2) if puntuaciones else 0


def registrar_replica(db: Session, oferente: Oferente, resena_id: int, texto: str) -> tuple[ReplicaResena, bool]:
    """HU-01 v2.1 - Registra la réplica del Profesional dueño a una reseña publicada.

    Devuelve (replica, creada). Un doble envío con el mismo texto no duplica
    nada: devuelve la réplica que ya existe (creada=False). Con otro texto, la
    reseña ya tiene su única respuesta y se rechaza. Solo hace flush: el commit
    lo hace el router.
    """
    resena = db.get(Resena, resena_id)
    if resena is None:
        raise error_negocio(404, "resena_no_encontrada", "Reseña no encontrada")
    if resena.oferente_id != oferente.id_oferente:
        raise error_negocio(403, "no_autorizado", "Solo el Profesional dueño de la reseña puede responderla")
    if resena.estado != EstadoResena.ACEPTADA:
        raise error_negocio(400, "resena_no_publicada", "Solo se pueden responder reseñas publicadas")

    existente = resena.replica
    if existente is not None:
        return _resolver_existente(existente, texto)

    replica = ReplicaResena(resena_id=resena.id_resena, oferente_id=oferente.id_oferente, texto=texto)
    db.add(replica)
    try:
        db.flush()
    except IntegrityError:
        # Carrera del doble clic: la UNIQUE de resena_id ganó el otro INSERT.
        db.rollback()
        existente = db.query(ReplicaResena).filter(ReplicaResena.resena_id == resena_id).first()
        if existente is None:
            raise
        return _resolver_existente(existente, texto)
    return replica, True


def _resolver_existente(existente: ReplicaResena, texto: str) -> tuple[ReplicaResena, bool]:
    if existente.texto == texto:
        return existente, False
    raise error_negocio(409, "replica_existente", "La reseña ya tiene una réplica")


def recalcular_rechazos(db: Session, oferente: Oferente) -> int:
    """HU-07 CA08: cantidad total de reseñas rechazadas del Profesional. Se guarda en
    `cantidad_rechazos_acumulados` y es lo que decide la notificación al administrador."""
    total = db.query(func.count(Resena.id_resena)).filter(
        Resena.oferente_id == oferente.id_oferente, Resena.estado == EstadoResena.RECHAZADA
    ).scalar()
    oferente.cantidad_rechazos_acumulados = total
    return total
