"""Gestión y moderación de Profesionales por el administrador (HU-07).

Las reglas viven acá; los routers solo validan el request y llaman. Todo lo que
cambia el estado de un Profesional deja registro en `auditoria_moderacion` y, si
corresponde, avisa en la campana de los administradores. Cada función agrega a la
sesión y hace `flush`: el `commit` lo hace el router.
"""

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.errores import error_negocio
from app.models.archivo_adjunto import TipoArchivo
from app.models.auditoria_moderacion import AccionModeracion, AuditoriaModeracion
from app.models.categoria import Categoria
from app.models.matricula import EstadoReemplazo, Matricula, OrigenMatricula, ResultadoValidacion, ValidacionMatricula
from app.models.notificacion import EstadoNotificacion, Notificacion, TipoNotificacion
from app.models.oferente import EstadoVerificacion, Oferente
from app.models.resena import EstadoResena, Resena
from app.models.trabajo_realizado import TrabajoRealizado
from app.models.usuario import EstadoCuenta, RolUsuario, Usuario
from app.schemas.admin import (
    ContadoresOferentes,
    OferenteAdminDetalle,
    OferenteAdminFila,
    OferentesAdminPaginadosOut,
    ResenaModeracionOut,
    TrabajoModeracionOut,
)
from app.schemas.oferente import CategoriaRef, MatriculaRef
from app.schemas.resena import ReplicaOut
from app.services.matriculas import MENSAJE_CA05_VALIDADA, validar_formato_matricula
from app.services.moderacion import resenas_visibles, trabajos_visibles
from app.services.notificaciones import notificar_reactivacion
from app.services.oferentes import _url_unica
from app.services.archivos import armar_trabajo
from app.services.resenas import recalcular_promedio

EstadoFiltro = Literal["todos", "activos", "suspendidos"]
FiltroResenas = Literal["todas", "aceptadas", "rechazadas", "dadas_de_baja"]


# --- Lectura -------------------------------------------------------------------


def _esta_activo(oferente: Oferente) -> bool:
    return oferente.usuario.estado_cuenta == EstadoCuenta.ACTIVA


def _matriculas_ordenadas(oferente: Oferente) -> list[Matricula]:
    return sorted(oferente.matriculas, key=lambda matricula: matricula.tipo_profesional)


def armar_fila(db: Session, oferente: Oferente) -> OferenteAdminFila:
    matriculas = _matriculas_ordenadas(oferente)
    cantidad_resenas = (
        db.query(func.count(Resena.id_resena)).filter(Resena.oferente_id == oferente.id_oferente, resenas_visibles()).scalar()
    )
    cantidad_trabajos = (
        db.query(func.count(TrabajoRealizado.id_trabajo))
        .filter(TrabajoRealizado.oferente_id == oferente.id_oferente, trabajos_visibles())
        .scalar()
    )
    cantidad_rechazadas = (
        db.query(func.count(Resena.id_resena))
        .filter(Resena.oferente_id == oferente.id_oferente, Resena.estado == EstadoResena.RECHAZADA)
        .scalar()
    )
    categoria = oferente.categoria
    return OferenteAdminFila(
        id_oferente=oferente.id_oferente,
        nombre=oferente.nombre,
        apellido=oferente.apellido,
        foto_perfil_url=_url_unica(db, oferente.id_oferente, TipoArchivo.PERFIL),
        estado="Activo" if _esta_activo(oferente) else "Suspendido",
        estado_cuenta=oferente.usuario.estado_cuenta,
        categoria=CategoriaRef(id_categoria=categoria.id_categoria, nombre=categoria.nombre) if categoria else None,
        especialidad=oferente.especialidad,
        matricula_verificada=bool(matriculas),
        matriculas=[MatriculaRef(tipo_profesional=m.tipo_profesional, numero_matricula=m.numero_matricula) for m in matriculas],
        promedio_calificacion=float(oferente.promedio_calificacion or 0),
        cantidad_resenas=cantidad_resenas,
        cantidad_trabajos=cantidad_trabajos,
        cantidad_rechazadas=cantidad_rechazadas,
    )


def armar_detalle(db: Session, oferente: Oferente) -> OferenteAdminDetalle:
    fila = armar_fila(db, oferente)
    return OferenteAdminDetalle(**fila.model_dump(), descripcion=oferente.descripcion, email=oferente.usuario.email)


def _base_oferentes(db: Session):
    """Registros completos: un Usuario con fila de Profesional (A2)."""
    return db.query(Oferente).join(Usuario, Usuario.id_usuario == Oferente.id_oferente)


def listar_oferentes(db: Session, *, q: str | None, estado: EstadoFiltro, pagina: int, por_pagina: int) -> OferentesAdminPaginadosOut:
    query = _base_oferentes(db)
    if estado == "activos":
        query = query.filter(Usuario.estado_cuenta == EstadoCuenta.ACTIVA)
    elif estado == "suspendidos":
        query = query.filter(Usuario.estado_cuenta != EstadoCuenta.ACTIVA)

    texto = (q or "").strip()
    if texto:
        like = f"%{texto}%"
        nombre_completo = Oferente.nombre.concat(" ").concat(func.coalesce(Oferente.apellido, ""))
        query = query.filter(
            or_(
                Oferente.nombre.ilike(like),
                Oferente.apellido.ilike(like),
                nombre_completo.ilike(like),
                Oferente.especialidad.ilike(like),
                Oferente.categoria.has(Categoria.nombre.ilike(like)),
                Oferente.matriculas.any(Matricula.numero_matricula.ilike(like)),
            )
        )

    total = query.count()
    oferentes = query.order_by(Oferente.nombre, Oferente.apellido, Oferente.id_oferente).offset((pagina - 1) * por_pagina).limit(por_pagina).all()

    activos = _base_oferentes(db).filter(Usuario.estado_cuenta == EstadoCuenta.ACTIVA).count()
    suspendidos = _base_oferentes(db).filter(Usuario.estado_cuenta != EstadoCuenta.ACTIVA).count()
    return OferentesAdminPaginadosOut(
        items=[armar_fila(db, oferente) for oferente in oferentes],
        contadores=ContadoresOferentes(activos=activos, suspendidos=suspendidos),
        pagina=pagina,
        por_pagina=por_pagina,
        total=total,
        total_paginas=-(-total // por_pagina),
    )


def obtener_oferente(db: Session, oferente_id: int) -> Oferente:
    oferente = db.get(Oferente, oferente_id)
    if oferente is None:
        raise error_negocio(404, "oferente_no_encontrado", "Oferente no encontrado")
    return oferente


def _resena_salida(resena: Resena) -> ResenaModeracionOut:
    dada_de_baja = resena.dado_de_baja_en is not None
    if resena.estado == EstadoResena.ACEPTADA and dada_de_baja:
        estado = "Dada_de_baja"
    else:
        estado = resena.estado
    contenido = resena.calificaciones_comentarios
    return ResenaModeracionOut(
        id_resena=resena.id_resena,
        nombre_cliente=resena.nombre_cliente,
        puntuacion_global=contenido["puntuacion_global"],
        criterios=contenido["criterios"],
        comentario=contenido.get("comentario"),
        fecha_creacion=resena.fecha_creacion,
        estado=estado,
        dado_de_baja_en=resena.dado_de_baja_en,
        replica=ReplicaOut.model_validate(resena.replica) if resena.replica else None,
        puede_dar_de_baja=resena.estado == EstadoResena.ACEPTADA and not dada_de_baja,
        puede_reactivar=dada_de_baja,
    )


def listar_resenas(db: Session, oferente: Oferente, filtro: FiltroResenas) -> list[ResenaModeracionOut]:
    query = db.query(Resena).filter(Resena.oferente_id == oferente.id_oferente)
    if filtro == "todas":
        # Publicadas (también las dadas de baja) y rechazadas. Las pendientes las decide el Profesional (A10).
        query = query.filter(Resena.estado.in_([EstadoResena.ACEPTADA, EstadoResena.RECHAZADA]))
    elif filtro == "aceptadas":
        query = query.filter(resenas_visibles())
    elif filtro == "rechazadas":
        query = query.filter(Resena.estado == EstadoResena.RECHAZADA)
    else:  # dadas_de_baja
        query = query.filter(Resena.estado == EstadoResena.ACEPTADA, Resena.dado_de_baja_en.is_not(None))
    resenas = query.order_by(Resena.fecha_creacion.desc(), Resena.id_resena.desc()).all()
    return [_resena_salida(resena) for resena in resenas]


def listar_trabajos(db: Session, oferente: Oferente) -> list[TrabajoModeracionOut]:
    trabajos = (
        db.query(TrabajoRealizado)
        .filter(TrabajoRealizado.oferente_id == oferente.id_oferente)
        .order_by(TrabajoRealizado.fecha_creacion.desc(), TrabajoRealizado.id_trabajo.desc())
        .all()
    )
    return [_trabajo_salida(trabajo) for trabajo in trabajos]


def _trabajo_salida(trabajo: TrabajoRealizado) -> TrabajoModeracionOut:
    base = armar_trabajo(trabajo).model_dump()
    dado_de_baja = trabajo.dado_de_baja_en is not None
    return TrabajoModeracionOut(**base, estado="Dado_de_baja" if dado_de_baja else "Activo", dado_de_baja_en=trabajo.dado_de_baja_en)


def listar_auditoria(db: Session, oferente: Oferente) -> list[AuditoriaModeracion]:
    return (
        db.query(AuditoriaModeracion)
        .filter(AuditoriaModeracion.oferente_id == oferente.id_oferente)
        .order_by(AuditoriaModeracion.fecha.desc(), AuditoriaModeracion.id_auditoria.desc())
        .all()
    )


# --- Escritura -----------------------------------------------------------------


def registrar_auditoria(
    db: Session,
    administrador: Usuario,
    oferente_id: int,
    accion: str,
    *,
    resena_id: int | None = None,
    trabajo_id: int | None = None,
    detalle: str | None = None,
) -> None:
    db.add(
        AuditoriaModeracion(
            administrador_id=administrador.id_usuario,
            oferente_id=oferente_id,
            accion=accion,
            resena_id=resena_id,
            trabajo_id=trabajo_id,
            detalle=detalle,
        )
    )


def cambiar_estado_oferente(db: Session, administrador: Usuario, oferente: Oferente, suspender: bool) -> None:
    """HU-07 CA06. Idempotente: si la cuenta ya está en ese estado, no audita ni avisa de nuevo."""
    usuario = oferente.usuario
    if suspender:
        if usuario.rol == RolUsuario.ADMINISTRADOR:
            raise error_negocio(400, "no_se_puede_suspender_admin", "No se puede suspender a un administrador")
        if usuario.estado_cuenta == EstadoCuenta.ACTIVA:
            usuario.estado_cuenta = EstadoCuenta.SUSPENDIDA
            registrar_auditoria(db, administrador, oferente.id_oferente, AccionModeracion.SUSPENSION)
    else:
        if usuario.estado_cuenta != EstadoCuenta.ACTIVA:
            usuario.estado_cuenta = EstadoCuenta.ACTIVA
            registrar_auditoria(db, administrador, oferente.id_oferente, AccionModeracion.ALTA)
            notificar_reactivacion(db, oferente)
    db.flush()


def validar_matricula_admin(db: Session, administrador: Usuario, oferente: Oferente, tipo: str, numero: str) -> None:
    """HU-07 CA03. El administrador carga el dato y se toma como válido: no se
    consulta el padrón. Deja la matrícula fidelizada y el distintivo de verificado."""
    numero = validar_formato_matricula(tipo, numero)

    otro = (
        db.query(Matricula.oferente_id)
        .filter(Matricula.tipo_profesional == tipo, Matricula.numero_matricula == numero, Matricula.oferente_id != oferente.id_oferente)
        .first()
    )
    if otro is not None:
        raise error_negocio(409, "matricula_de_otro_oferente", "Esa matrícula ya está fidelizada por otro Profesional")

    ahora = datetime.now(timezone.utc)
    matricula = db.query(Matricula).filter(Matricula.oferente_id == oferente.id_oferente, Matricula.tipo_profesional == tipo).first()
    if matricula is None:
        matricula = Matricula(oferente_id=oferente.id_oferente, tipo_profesional=tipo)
        db.add(matricula)
    matricula.numero_matricula = numero
    matricula.categoria = None
    matricula.fecha_vencimiento = None
    matricula.fecha_fidelizacion = ahora
    matricula.origen = OrigenMatricula.ADMINISTRADOR
    matricula.validada_por_id = administrador.id_usuario

    # Un reemplazo pendiente de HU-02 para ese oficio queda superado por esta validación.
    pendientes = (
        db.query(ValidacionMatricula)
        .filter(
            ValidacionMatricula.oferente_id == oferente.id_oferente,
            ValidacionMatricula.tipo_profesional == tipo,
            ValidacionMatricula.resultado == ResultadoValidacion.REEMPLAZO_SOLICITADO,
            ValidacionMatricula.estado_reemplazo == EstadoReemplazo.PENDIENTE,
        )
        .all()
    )
    for pendiente in pendientes:
        pendiente.estado_reemplazo = EstadoReemplazo.SUPERSEDED

    validacion = ValidacionMatricula(
        oferente_id=oferente.id_oferente,
        tipo_profesional=tipo,
        numero_matricula=numero,
        resultado=ResultadoValidacion.VALIDADA_ADMINISTRADOR,
    )
    db.add(validacion)
    db.flush()

    oferente.estado_verificacion = EstadoVerificacion.VERIFICADO
    oferente.usuario.fidelizado = True
    db.add(
        Notificacion(
            usuario_id=oferente.id_oferente,
            tipo=TipoNotificacion.MATRICULA_VALIDADA,
            mensaje=MENSAJE_CA05_VALIDADA,
            requiere_accion=False,
            estado=EstadoNotificacion.PENDIENTE,
            validacion_matricula_id=validacion.id_validacion,
        )
    )
    registrar_auditoria(db, administrador, oferente.id_oferente, AccionModeracion.VALIDACION_MATRICULA, detalle=f"{tipo} {numero}")
    db.flush()


def _resena_de_oferente(db: Session, resena_id: int) -> Resena:
    resena = db.get(Resena, resena_id)
    if resena is None:
        raise error_negocio(404, "resena_no_encontrada", "Reseña no encontrada")
    return resena


def dar_de_baja_resena(db: Session, administrador: Usuario, resena_id: int, motivo: str | None) -> Resena:
    """HU-07 CA05. Solo las publicadas se pueden dar de baja. Idempotente."""
    resena = _resena_de_oferente(db, resena_id)
    if resena.dado_de_baja_en is not None:
        return resena
    if resena.estado != EstadoResena.ACEPTADA:
        raise error_negocio(400, "resena_no_aceptada", "Solo se pueden dar de baja las opiniones publicadas")

    resena.dado_de_baja_en = datetime.now(timezone.utc)
    resena.dado_de_baja_por_id = administrador.id_usuario
    db.flush()
    recalcular_promedio(db, resena.oferente)
    registrar_auditoria(db, administrador, resena.oferente_id, AccionModeracion.BAJA_RESENA, resena_id=resena.id_resena, detalle=motivo)
    db.flush()
    return resena


def reactivar_resena(db: Session, administrador: Usuario, resena_id: int) -> Resena:
    resena = _resena_de_oferente(db, resena_id)
    if resena.dado_de_baja_en is None:
        return resena

    resena.dado_de_baja_en = None
    resena.dado_de_baja_por_id = None
    db.flush()
    recalcular_promedio(db, resena.oferente)
    registrar_auditoria(db, administrador, resena.oferente_id, AccionModeracion.REACTIVACION_RESENA, resena_id=resena.id_resena)
    db.flush()
    return resena


def _trabajo_de_oferente(db: Session, trabajo_id: int) -> TrabajoRealizado:
    trabajo = db.get(TrabajoRealizado, trabajo_id)
    if trabajo is None:
        raise error_negocio(404, "trabajo_no_encontrado", "Trabajo no encontrado")
    return trabajo


def dar_de_baja_trabajo(db: Session, administrador: Usuario, trabajo_id: int, motivo: str | None) -> TrabajoRealizado:
    trabajo = _trabajo_de_oferente(db, trabajo_id)
    if trabajo.dado_de_baja_en is not None:
        return trabajo

    trabajo.dado_de_baja_en = datetime.now(timezone.utc)
    trabajo.dado_de_baja_por_id = administrador.id_usuario
    registrar_auditoria(db, administrador, trabajo.oferente_id, AccionModeracion.BAJA_TRABAJO, trabajo_id=trabajo.id_trabajo, detalle=motivo)
    db.flush()
    return trabajo


def reactivar_trabajo(db: Session, administrador: Usuario, trabajo_id: int) -> TrabajoRealizado:
    trabajo = _trabajo_de_oferente(db, trabajo_id)
    if trabajo.dado_de_baja_en is None:
        return trabajo

    trabajo.dado_de_baja_en = None
    trabajo.dado_de_baja_por_id = None
    registrar_auditoria(db, administrador, trabajo.oferente_id, AccionModeracion.REACTIVACION_TRABAJO, trabajo_id=trabajo.id_trabajo)
    db.flush()
    return trabajo


