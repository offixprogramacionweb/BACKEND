"""Creación y resolución de las notificaciones de la bandeja (la campana).

Vive fuera de los routers porque la escriben dos flujos distintos: la carga de
una reseña (HU-01) y, en la Fase 4, los resultados de la validación de matrícula
(HU-02). El estado de la notificación y el del hecho que la originó se mueven
siempre en la misma transacción: estas funciones agregan a la sesión y hacen
`flush`, nunca `commit`.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notificacion import EstadoNotificacion, Notificacion, TipoNotificacion
from app.models.oferente import Oferente
from app.models.resena import Resena
from app.models.solicitud_resena import SolicitudResena
from app.models.usuario import EstadoCuenta, RolUsuario, Usuario


def _contacto_del_cliente(solicitud: SolicitudResena) -> str:
    """Teléfono si se cargó; si no, el correo (texto literal de QA, caso A34)."""
    return solicitud.telefono_cliente_completo or solicitud.email_cliente or ""


def crear_notificacion_resena_nueva(db: Session, resena: Resena, solicitud: SolicitudResena) -> Notificacion:
    """Avisa al Profesional que tiene una reseña esperando su decisión.

    El mensaje lleva **el contacto del cliente y nada del contenido** de la
    reseña: el Profesional decide mirando quién la dejó, no qué dice. La fecha
    es la de creación de la reseña por el cliente, no la de la moderación.
    """
    notificacion = Notificacion(
        usuario_id=resena.oferente_id,
        tipo=TipoNotificacion.RESENA_NUEVA,
        mensaje=f"Recibiste una nueva reseña de un cliente {_contacto_del_cliente(solicitud)} a través de Offix.",
        requiere_accion=True,
        estado=EstadoNotificacion.PENDIENTE,
        resena_id=resena.id_resena,
        fecha_creacion=resena.fecha_creacion,
    )
    db.add(notificacion)
    db.flush()
    return notificacion


def resolver_notificacion_de_resena(db: Session, resena: Resena, aceptada: bool) -> Notificacion | None:
    """Cierra la notificación de la bandeja junto con la moderación de la reseña.

    Devuelve `None` si la reseña no tiene notificación asociada (reseñas
    cargadas antes de que existiera la bandeja, o datos de seed viejos): la
    moderación no se bloquea por eso.
    """
    notificacion = (
        db.query(Notificacion)
        .filter(
            Notificacion.resena_id == resena.id_resena,
            Notificacion.tipo == TipoNotificacion.RESENA_NUEVA,
            Notificacion.estado == EstadoNotificacion.PENDIENTE,
        )
        .first()
    )
    if not notificacion:
        return None

    notificacion.estado = EstadoNotificacion.ACEPTADA if aceptada else EstadoNotificacion.RECHAZADA
    notificacion.fecha_resolucion = datetime.now(timezone.utc)
    db.flush()
    return notificacion


def administradores_activos(db: Session) -> list[Usuario]:
    return (
        db.query(Usuario)
        .filter(Usuario.rol == RolUsuario.ADMINISTRADOR, Usuario.estado_cuenta == EstadoCuenta.ACTIVA)
        .all()
    )


def notificar_rechazos_reiterados(db: Session, oferente: Oferente) -> None:
    """HU-07 CA08: aviso en la campana de cada administrador activo cuando un
    Profesional llega a 5 o más reseñas rechazadas. Si el administrador ya tiene
    uno pendiente de ese Profesional, no se repite (A20)."""
    mensaje = (
        f"El profesional {oferente.nombre_completo} rechazó 5 o más reseñas a través de Offix"
    )
    for administrador in administradores_activos(db):
        ya_pendiente = (
            db.query(Notificacion.id_notificacion)
            .filter(
                Notificacion.usuario_id == administrador.id_usuario,
                Notificacion.tipo == TipoNotificacion.RECHAZOS_REITERADOS,
                Notificacion.oferente_id == oferente.id_oferente,
                Notificacion.estado == EstadoNotificacion.PENDIENTE,
            )
            .first()
        )
        if ya_pendiente is None:
            db.add(
                Notificacion(
                    usuario_id=administrador.id_usuario,
                    tipo=TipoNotificacion.RECHAZOS_REITERADOS,
                    mensaje=mensaje,
                    requiere_accion=False,
                    estado=EstadoNotificacion.PENDIENTE,
                    oferente_id=oferente.id_oferente,
                )
            )
    db.flush()


def notificar_reactivacion(db: Session, oferente: Oferente) -> None:
    """HU-07 CA06: aviso a los administradores cuando se da de alta un Profesional."""
    mensaje = (
        f"El oferente {oferente.nombre_completo} fue reactivado y podrá volver a operar e iniciar sesión con normalidad."
    )
    for administrador in administradores_activos(db):
        db.add(
            Notificacion(
                usuario_id=administrador.id_usuario,
                tipo=TipoNotificacion.OFERENTE_REACTIVADO,
                mensaje=mensaje,
                requiere_accion=False,
                estado=EstadoNotificacion.PENDIENTE,
                oferente_id=oferente.id_oferente,
            )
        )
    db.flush()
