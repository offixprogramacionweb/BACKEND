import enum
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.database import get_db
from app.models.alerta_admin import AlertaAdministrador
from app.models.matricula import EstadoReemplazo, ResultadoValidacion, ValidacionMatricula
from app.models.notificacion import EstadoNotificacion, Notificacion
from app.models.oferente import EstadoVerificacion, Oferente
from app.models.resena import EstadoResena, Resena
from app.models.trabajo_realizado import TrabajoRealizado
from app.models.usuario import EstadoCuenta, Usuario
from app.schemas.admin import (
    AccionResenaOut,
    AccionTrabajoOut,
    AuditoriaOut,
    BajaIn,
    MatriculaAdminIn,
    OferenteAdminDetalle,
    OferenteAdminFila,
    OferentesAdminPaginadosOut,
    ResenaModeracionOut,
    TrabajoModeracionOut,
)
from app.schemas.matricula import ReemplazoResolucionIn, ReemplazoResueltoOut
from app.schemas.oferente import OferentePrivadoOut
from app.schemas.resena import ResenaAdminOut
from app.schemas.usuario import UsuarioOut
from app.services import admin as servicio_admin
from app.services.matriculas import resolver_reemplazo
from app.services.oferentes import armar_privada
from app.services.resenas import recalcular_promedio, recalcular_rechazos

RESPUESTAS_ADMIN_COMUNES = {
    401: {"description": "Falta token o es inválido"},
    403: {"description": "Requiere rol Administrador"},
}

POR_PAGINA_ADMIN = (10, 25, 50)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administración"],
    dependencies=[Depends(require_admin)],
    responses=RESPUESTAS_ADMIN_COMUNES,
)


class EstadoCuentaEnum(str, enum.Enum):
    ACTIVA = EstadoCuenta.ACTIVA
    SUSPENDIDA = EstadoCuenta.SUSPENDIDA
    BLOQUEADA = EstadoCuenta.BLOQUEADA


class EstadoVerificacionEnum(str, enum.Enum):
    PENDIENTE = EstadoVerificacion.PENDIENTE
    VERIFICADO = EstadoVerificacion.VERIFICADO
    RECHAZADO = EstadoVerificacion.RECHAZADO


RESPUESTA_NO_ENCONTRADO = {404: {"description": "No existe el Profesional, la reseña o el trabajo"}}


# --- Usuarios y verificación (existentes, sin cambios de contrato) -------------


@router.get("/usuarios", response_model=list[UsuarioOut], summary="Listar todos los usuarios")
def listar_usuarios(db: Session = Depends(get_db)):
    """RF14 — Gestión de usuarios."""
    return db.query(Usuario).all()


@router.patch(
    "/usuarios/{usuario_id}/estado",
    response_model=UsuarioOut,
    summary="Suspender/bloquear/reactivar un usuario",
    responses={404: {"description": "Usuario no encontrado"}},
)
def cambiar_estado_usuario(usuario_id: int, estado: EstadoCuentaEnum, db: Session = Depends(get_db)):
    """RF15 — Bloquear o suspender usuarios. Un usuario Suspendida/Bloqueada no puede hacer login."""
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    usuario.estado_cuenta = estado.value
    db.commit()
    db.refresh(usuario)
    return usuario


@router.patch(
    "/oferentes/{oferente_id}/verificacion",
    response_model=OferentePrivadoOut,
    summary="Marcar manualmente el estado de verificación de matrícula",
    responses={404: {"description": "Oferente no encontrado"}},
)
def actualizar_estado_verificacion(oferente_id: int, estado_verificacion: EstadoVerificacionEnum, db: Session = Depends(get_db)):
    """HU-02 T07 — Simula la integración con el ente validador de matrículas
    (electricista, gasista, plomero, técnico en aire acondicionado): para
    Sprint 1 el estado se marca manualmente en vez de consultar un servicio
    externo real."""
    oferente = db.get(Oferente, oferente_id)
    if not oferente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oferente no encontrado")

    oferente.estado_verificacion = estado_verificacion.value
    db.commit()
    db.refresh(oferente)
    return armar_privada(db, oferente)


@router.get("/alertas", summary="Listar alertas generadas por rechazos reiterados de reseñas")
def listar_alertas(db: Session = Depends(get_db)):
    """RF17 — Revisión de alertas por rechazos reiterados de reseñas."""
    return db.query(AlertaAdministrador).order_by(AlertaAdministrador.fecha_creacion.desc()).all()


@router.get(
    "/resenas/rechazadas",
    response_model=list[ResenaAdminOut],
    summary="Listar reseñas rechazadas por sus oferentes",
)
def listar_resenas_rechazadas(db: Session = Depends(get_db)):
    """RF17 — El administrador puede revisar y revertir rechazos incorrectos."""
    return db.query(Resena).filter(Resena.estado == EstadoResena.RECHAZADA).order_by(Resena.fecha_creacion.desc()).all()


@router.patch(
    "/resenas/{resena_id}/publicar",
    response_model=ResenaAdminOut,
    summary="Publicar una reseña que el oferente había rechazado",
    responses={404: {"description": "Reseña no encontrada"}},
)
def publicar_resena_rechazada(resena_id: int, db: Session = Depends(get_db)):
    """RF17 — El Administrador, como instancia final, publica una reseña rechazada por el Oferente."""
    resena = db.get(Resena, resena_id)
    if not resena:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reseña no encontrada")

    resena.estado = EstadoResena.ACEPTADA
    db.flush()
    # Publicarla la hace visible en el perfil, así que también tiene que entrar
    # al promedio: el recálculo es el mismo que usa la moderación del Oferente.
    recalcular_promedio(db, db.get(Oferente, resena.oferente_id))
    recalcular_rechazos(db, db.get(Oferente, resena.oferente_id))
    db.commit()
    db.refresh(resena)
    return resena


@router.patch(
    "/matriculas/reemplazos/{id_validacion}",
    response_model=ReemplazoResueltoOut,
    summary="Autorizar o denegar un reemplazo de matrícula pedido por un Oferente",
    responses={
        400: {"description": "El reemplazo ya fue resuelto (o fue reemplazado por un pedido más nuevo)"},
        404: {"description": "No hay un pedido de reemplazo con ese id"},
    },
)
def resolver_reemplazo_matricula(id_validacion: int, payload: ReemplazoResolucionIn, db: Session = Depends(get_db)):
    """HU-02 — Mientras el Administrador no decide, sigue vigente la matrícula
    anterior: el reemplazo recién se aplica acá. En la misma transacción se
    cierra la notificación accionable del Administrador y se avisa al
    Oferente del resultado."""
    validacion = db.get(ValidacionMatricula, id_validacion)
    if not validacion or validacion.resultado != ResultadoValidacion.REEMPLAZO_SOLICITADO:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay un pedido de reemplazo con ese id")
    if validacion.estado_reemplazo == EstadoReemplazo.SUPERSEDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El Oferente pidió un reemplazo más nuevo para este oficio: resolvé ese pedido",
        )
    if validacion.estado_reemplazo != EstadoReemplazo.PENDIENTE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El reemplazo ya fue resuelto")

    matricula = resolver_reemplazo(db, validacion, payload.autorizar)

    notificaciones_admin = (
        db.query(Notificacion)
        .filter(Notificacion.validacion_matricula_id == id_validacion, Notificacion.requiere_accion.is_(True))
        .all()
    )
    for notificacion in notificaciones_admin:
        notificacion.estado = EstadoNotificacion.ACEPTADA if payload.autorizar else EstadoNotificacion.RECHAZADA
        notificacion.fecha_resolucion = datetime.now(timezone.utc)

    db.commit()
    db.refresh(validacion)
    return ReemplazoResueltoOut(id_validacion=validacion.id_validacion, estado_reemplazo=validacion.estado_reemplazo, matricula=matricula)


# --- HU-07: grilla de Profesionales -------------------------------------------


@router.get(
    "/oferentes",
    response_model=OferentesAdminPaginadosOut,
    summary="Grilla de Profesionales: búsqueda, filtro por estado y paginado (HU-07 CA02)",
    responses={422: {"description": "`estado` o `por_pagina` inválidos"}},
)
def listar_oferentes_admin(
    q: str | None = Query(default=None, description="Nombre, rubro, especialidad o matrícula (coincidencia parcial)."),
    estado: Literal["todos", "activos", "suspendidos"] = Query(default="todos"),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=25, description="10, 25 o 50."),
    db: Session = Depends(get_db),
):
    if por_pagina not in POR_PAGINA_ADMIN:
        raise HTTPException(status_code=422, detail="Elegí 10, 25 o 50 por página")
    return servicio_admin.listar_oferentes(db, q=q, estado=estado, pagina=pagina, por_pagina=por_pagina)


@router.get(
    "/oferentes/{oferente_id}",
    response_model=OferenteAdminDetalle,
    summary="Tarjeta de un Profesional para la moderación",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def obtener_oferente_admin(oferente_id: int, db: Session = Depends(get_db)):
    return servicio_admin.armar_detalle(db, servicio_admin.obtener_oferente(db, oferente_id))


@router.post(
    "/oferentes/{oferente_id}/suspender",
    response_model=OferenteAdminFila,
    summary="Suspender la cuenta de un Profesional (HU-07 CA06)",
    responses={**RESPUESTA_NO_ENCONTRADO, 400: {"description": "No se puede suspender a un administrador"}},
)
def suspender_oferente(oferente_id: int, db: Session = Depends(get_db), administrador: Usuario = Depends(require_admin)):
    """La confirmación previa la pide el frontend. Si la cuenta ya está suspendida,
    responde igual, sin registrar otra vez en la auditoría."""
    oferente = servicio_admin.obtener_oferente(db, oferente_id)
    servicio_admin.cambiar_estado_oferente(db, administrador, oferente, suspender=True)
    db.commit()
    db.refresh(oferente)
    return servicio_admin.armar_fila(db, oferente)


@router.post(
    "/oferentes/{oferente_id}/dar-de-alta",
    response_model=OferenteAdminFila,
    summary="Dar de alta (reactivar) la cuenta de un Profesional suspendido (HU-07 CA06)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def dar_de_alta_oferente(oferente_id: int, db: Session = Depends(get_db), administrador: Usuario = Depends(require_admin)):
    oferente = servicio_admin.obtener_oferente(db, oferente_id)
    servicio_admin.cambiar_estado_oferente(db, administrador, oferente, suspender=False)
    db.commit()
    db.refresh(oferente)
    return servicio_admin.armar_fila(db, oferente)


@router.post(
    "/oferentes/{oferente_id}/matriculas",
    response_model=OferenteAdminFila,
    summary="Validar a mano la matrícula de un Profesional, sin padrón (HU-07 CA03)",
    responses={
        **RESPUESTA_NO_ENCONTRADO,
        409: {"description": "La matrícula ya está fidelizada por otro Profesional (`matricula_de_otro_oferente`)"},
        422: {"description": "Tipo inválido, o el número no tiene solo dígitos o la cantidad del tipo"},
    },
)
def validar_matricula_oferente(
    oferente_id: int,
    payload: MatriculaAdminIn,
    db: Session = Depends(get_db),
    administrador: Usuario = Depends(require_admin),
):
    oferente = servicio_admin.obtener_oferente(db, oferente_id)
    servicio_admin.validar_matricula_admin(db, administrador, oferente, payload.tipo_profesional, payload.numero_matricula)
    db.commit()
    db.refresh(oferente)
    return servicio_admin.armar_fila(db, oferente)


# --- HU-07: moderación de reseñas, trabajos y auditoría -----------------------


@router.get(
    "/oferentes/{oferente_id}/resenas",
    response_model=list[ResenaModeracionOut],
    summary="Opiniones de un Profesional para moderar (HU-07 CA04)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def listar_resenas_oferente(
    oferente_id: int,
    filtro: Literal["todas", "aceptadas", "rechazadas", "dadas_de_baja"] = Query(default="todas"),
    db: Session = Depends(get_db),
):
    return servicio_admin.listar_resenas(db, servicio_admin.obtener_oferente(db, oferente_id), filtro)


@router.get(
    "/oferentes/{oferente_id}/trabajos",
    response_model=list[TrabajoModeracionOut],
    summary="Trabajos de un Profesional para auditar (HU-07 CA04)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def listar_trabajos_oferente(oferente_id: int, db: Session = Depends(get_db)):
    return servicio_admin.listar_trabajos(db, servicio_admin.obtener_oferente(db, oferente_id))


@router.get(
    "/oferentes/{oferente_id}/auditoria",
    response_model=list[AuditoriaOut],
    summary="Historial de acciones de moderación sobre un Profesional",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def listar_auditoria_oferente(oferente_id: int, db: Session = Depends(get_db)):
    return servicio_admin.listar_auditoria(db, servicio_admin.obtener_oferente(db, oferente_id))


def _accion_resena(db: Session, resena: Resena) -> AccionResenaOut:
    db.commit()
    db.refresh(resena)
    return AccionResenaOut(
        resena=servicio_admin._resena_salida(resena),
        oferente=servicio_admin.armar_fila(db, resena.oferente),
    )


@router.post(
    "/resenas/{resena_id}/dar-de-baja",
    response_model=AccionResenaOut,
    summary="Dar de baja una opinión publicada (HU-07 CA05)",
    responses={
        **RESPUESTA_NO_ENCONTRADO,
        400: {"description": "Solo se pueden dar de baja opiniones publicadas (`resena_no_aceptada`)"},
    },
)
def dar_de_baja_resena(
    resena_id: int,
    payload: BajaIn | None = None,
    db: Session = Depends(get_db),
    administrador: Usuario = Depends(require_admin),
):
    """Deja de mostrarse en el perfil y ajusta calificación y cantidad. Queda en auditoría.
    Si ya estaba dada de baja, responde igual sin registrarlo de nuevo."""
    resena = servicio_admin.dar_de_baja_resena(db, administrador, resena_id, payload.motivo if payload else None)
    return _accion_resena(db, resena)


@router.post(
    "/resenas/{resena_id}/reactivar",
    response_model=AccionResenaOut,
    summary="Reactivar una opinión dada de baja (HU-07 CA05)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def reactivar_resena(resena_id: int, db: Session = Depends(get_db), administrador: Usuario = Depends(require_admin)):
    resena = servicio_admin.reactivar_resena(db, administrador, resena_id)
    return _accion_resena(db, resena)


def _accion_trabajo(db: Session, trabajo: TrabajoRealizado) -> AccionTrabajoOut:
    db.commit()
    db.refresh(trabajo)
    return AccionTrabajoOut(
        trabajo=servicio_admin._trabajo_salida(trabajo),
        oferente=servicio_admin.armar_fila(db, trabajo.oferente),
    )


@router.post(
    "/trabajos/{trabajo_id}/dar-de-baja",
    response_model=AccionTrabajoOut,
    summary="Dar de baja un trabajo realizado (HU-07 CA05)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def dar_de_baja_trabajo(
    trabajo_id: int,
    payload: BajaIn | None = None,
    db: Session = Depends(get_db),
    administrador: Usuario = Depends(require_admin),
):
    trabajo = servicio_admin.dar_de_baja_trabajo(db, administrador, trabajo_id, payload.motivo if payload else None)
    return _accion_trabajo(db, trabajo)


@router.post(
    "/trabajos/{trabajo_id}/reactivar",
    response_model=AccionTrabajoOut,
    summary="Reactivar un trabajo dado de baja (HU-07 CA05)",
    responses=RESPUESTA_NO_ENCONTRADO,
)
def reactivar_trabajo(trabajo_id: int, db: Session = Depends(get_db), administrador: Usuario = Depends(require_admin)):
    trabajo = servicio_admin.reactivar_trabajo(db, administrador, trabajo_id)
    return _accion_trabajo(db, trabajo)
