"""Alta, edición y armado de los perfiles de Oferente (HU-04).

Las salidas se arman acá y no en el router: el perfil público y el privado
comparten casi todo, y la regla de "qué ve cada uno" (D7) tiene que estar en un
único lugar.
"""

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.catalogos import ETIQUETA_EXPERIENCIA
from app.core.errores import error_negocio, error_validacion
from app.models.archivo_adjunto import ArchivoAdjunto, TipoArchivo
from app.models.categoria import Categoria, EstadoCategoria
from app.models.matricula import Matricula
from app.models.oferente import EstadoVerificacion, Oferente
from app.models.oferente_dia_atencion import OferenteDiaAtencion
from app.models.resena import EstadoResena, Resena
from app.models.trabajo_realizado import TrabajoRealizado
from app.models.ubicacion import Localidad
from app.models.usuario import EstadoCuenta, RolUsuario, Usuario
from app.schemas.oferente import (
    CategoriaRef,
    ExperienciaRef,
    LocalidadRef,
    MatriculaRef,
    ProvinciaRef,
    OferenteEdicion,
    OferentePrivadoOut,
    OferentePublicoOut,
    OferenteRegistro,
    OferentesPaginadosOut,
)
from app.services.mensajes import armar_whatsapp_contacto, telefono_partes_son_validas
from app.services.storage import url_publica

# Campos que la edición no puede dejar en NULL: el registro los exige.
CAMPOS_NO_NULOS = {
    "nombre",
    "telefono_codigo_area",
    "telefono_numero",
    "categoria_id",
    "dias_atencion",
    "hora_inicio_atencion",
    "hora_fin_atencion",
    "disponible_emergencia",
}


def _hora(valor) -> str | None:
    return valor.strftime("%H:%M") if valor is not None else None


def _url_unica(db: Session, oferente_id: int, tipo: str) -> str | None:
    """Foto de perfil o portada: hay una sola vigente por tipo."""
    archivo = (
        db.query(ArchivoAdjunto)
        .filter(ArchivoAdjunto.oferente_id == oferente_id, ArchivoAdjunto.tipo == tipo, ArchivoAdjunto.trabajo_id.is_(None))
        .first()
    )
    return url_publica(archivo.storage_path) if archivo else None


def armar_publica(db: Session, oferente: Oferente) -> OferentePublicoOut:
    cantidad_resenas = (
        db.query(func.count(Resena.id_resena))
        .filter(Resena.oferente_id == oferente.id_oferente, Resena.estado == EstadoResena.ACEPTADA)
        .scalar()
    )
    cantidad_trabajos = (
        db.query(func.count(TrabajoRealizado.id_trabajo)).filter(TrabajoRealizado.oferente_id == oferente.id_oferente).scalar()
    )
    categoria = oferente.categoria
    localidad = oferente.localidad
    return OferentePublicoOut(
        id_oferente=oferente.id_oferente,
        nombre=oferente.nombre,
        apellido=oferente.apellido,
        categoria_id=oferente.categoria_id,
        categoria=CategoriaRef(id_categoria=categoria.id_categoria, nombre=categoria.nombre) if categoria else None,
        especialidad=oferente.especialidad,
        experiencia=(
            ExperienciaRef(codigo=oferente.experiencia, etiqueta=ETIQUETA_EXPERIENCIA[oferente.experiencia])
            if oferente.experiencia
            else None
        ),
        telefono_codigo_area=oferente.telefono_codigo_area,
        telefono_numero=oferente.telefono_numero,
        whatsapp_url=armar_whatsapp_contacto(oferente.telefono_completo, oferente.nombre_completo, categoria.nombre if categoria else None),
        email=oferente.usuario.email,
        dias_atencion=[dia.dia for dia in oferente.dias_atencion],
        hora_inicio_atencion=_hora(oferente.hora_inicio_atencion),
        hora_fin_atencion=_hora(oferente.hora_fin_atencion),
        disponible_emergencia=oferente.disponible_emergencia,
        info_guardia=oferente.info_guardia,
        descripcion=oferente.descripcion,
        localidad=(
            LocalidadRef(id=localidad.id_localidad, nombre=localidad.nombre, departamento=localidad.departamento)
            if localidad
            else None
        ),
        provincia=ProvinciaRef(id=localidad.provincia.id_provincia, nombre=localidad.provincia.nombre) if localidad else None,
        promedio_calificacion=oferente.promedio_calificacion,
        cantidad_resenas=cantidad_resenas,
        cantidad_trabajos=cantidad_trabajos,
        tiene_matricula_validada=oferente.tiene_matricula_validada,
        matriculas=[MatriculaRef(tipo_profesional=m.tipo_profesional, numero_matricula=m.numero_matricula) for m in oferente.matriculas],
        foto_perfil_url=_url_unica(db, oferente.id_oferente, TipoArchivo.PERFIL),
        portada_url=_url_unica(db, oferente.id_oferente, TipoArchivo.PORTADA),
    )


def armar_privada(db: Session, oferente: Oferente) -> OferentePrivadoOut:
    publica = armar_publica(db, oferente)
    return OferentePrivadoOut(
        **publica.model_dump(),
        dni_cuit=oferente.dni_cuit,
        estado_verificacion=oferente.estado_verificacion,
        cantidad_rechazos_acumulados=oferente.cantidad_rechazos_acumulados,
    )


def validar_categoria(db: Session, categoria_id: int) -> None:
    categoria = db.get(Categoria, categoria_id)
    if categoria is None or categoria.estado != EstadoCategoria.ACTIVA:
        raise error_validacion("categoria_id", "categoria_invalida", "Seleccioná una categoría de la lista")


def validar_localidad(db: Session, localidad_id: str | None) -> None:
    """La localidad es opcional; si viene, tiene que existir en el catálogo."""
    if localidad_id is not None and db.get(Localidad, localidad_id) is None:
        raise error_validacion("localidad_id", "localidad_invalida", "Seleccioná una localidad de la lista")


def reemplazar_dias(db: Session, oferente_id: int, dias: list[int]) -> None:
    # Borrado por query y no por la colección: la PK (oferente, día) se repite
    # entre lo viejo y lo nuevo, y el orden de los INSERT/DELETE no se controla.
    db.query(OferenteDiaAtencion).filter(OferenteDiaAtencion.oferente_id == oferente_id).delete(synchronize_session=False)
    for dia in dias:
        db.add(OferenteDiaAtencion(oferente_id=oferente_id, dia=dia))


def crear_oferente(db: Session, usuario: Usuario, datos: OferenteRegistro) -> Oferente:
    """CA03: crea el perfil y sus días en una sola transacción. El doble clic
    (caso A26) llega como dos INSERT con la misma PK: el segundo falla con
    IntegrityError y se responde 409 perfil_existente."""
    if usuario.rol != RolUsuario.OFERENTE:
        raise error_negocio(403, "rol_invalido", "Solo los usuarios con rol Oferente pueden registrarse como Profesional")
    if db.get(Oferente, usuario.id_usuario) is not None:
        raise error_negocio(409, "perfil_existente", "Ya completaste el registro de Profesional")

    validar_categoria(db, datos.categoria_id)
    validar_localidad(db, datos.localidad_id)
    if db.query(Oferente.id_oferente).filter(Oferente.dni_cuit == datos.dni_cuit).first():
        raise error_negocio(409, "dni_cuit_duplicado", "Ese DNI/CUIT ya está registrado")

    oferente = Oferente(
        id_oferente=usuario.id_usuario,
        nombre=datos.nombre,
        apellido=datos.apellido,
        dni_cuit=datos.dni_cuit,
        telefono_codigo_area=datos.telefono_codigo_area,
        telefono_numero=datos.telefono_numero,
        categoria_id=datos.categoria_id,
        especialidad=datos.especialidad,
        experiencia=datos.experiencia,
        hora_inicio_atencion=datos.hora_inicio_atencion,
        hora_fin_atencion=datos.hora_fin_atencion,
        disponible_emergencia=datos.disponible_emergencia,
        info_guardia=datos.info_guardia,
        localidad_id=datos.localidad_id,
        estado_verificacion=EstadoVerificacion.PENDIENTE,
    )
    try:
        db.add(oferente)
        db.flush()
        reemplazar_dias(db, oferente.id_oferente, datos.dias_atencion)
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.get(Oferente, usuario.id_usuario) is not None:
            raise error_negocio(409, "perfil_existente", "Ya completaste el registro de Profesional")
        raise error_negocio(409, "dni_cuit_duplicado", "Ese DNI/CUIT ya está registrado")

    db.refresh(oferente)
    return oferente


def aplicar_edicion(db: Session, oferente: Oferente, datos: OferenteEdicion) -> Oferente:
    cambios = datos.model_dump(exclude_unset=True)

    for campo in CAMPOS_NO_NULOS:
        if campo in cambios and cambios[campo] is None:
            raise error_validacion(campo, "requerido", "Complete este campo")

    # Si ya hay una matrícula fidelizada, la identidad (nombre y apellido)
    # queda atada al distintivo de verificado: cambiarla dejaría el distintivo
    # colgado de otra persona (HU-04, D18).
    cambio_identidad = any(campo in cambios and cambios[campo] != getattr(oferente, campo) for campo in ("nombre", "apellido"))
    if cambio_identidad and oferente.matriculas:
        raise error_negocio(
            409,
            "nombre_bloqueado_por_matricula",
            "No podés cambiar el nombre ni el apellido mientras tengas una matrícula fidelizada",
        )

    if {"telefono_codigo_area", "telefono_numero"} & cambios.keys():
        # Cada parte ya pasó su propio formato en el schema; acá se valida el
        # par, combinando lo nuevo con lo que ya estaba guardado.
        codigo = cambios.get("telefono_codigo_area", oferente.telefono_codigo_area)
        numero = cambios.get("telefono_numero", oferente.telefono_numero)
        if not telefono_partes_son_validas(codigo, numero):
            raise error_validacion("telefono_numero", "telefono_invalido", "Código de área y número tienen que sumar 10 dígitos")

    if "categoria_id" in cambios:
        validar_categoria(db, cambios["categoria_id"])
    if "localidad_id" in cambios:
        validar_localidad(db, cambios["localidad_id"])

    inicio = cambios.get("hora_inicio_atencion", oferente.hora_inicio_atencion)
    fin = cambios.get("hora_fin_atencion", oferente.hora_fin_atencion)
    if inicio is not None and fin is not None and fin <= inicio:
        raise error_validacion("hora_fin_atencion", "horario_invalido", "El horario de cierre tiene que ser posterior a la apertura")

    dias = cambios.pop("dias_atencion", None)
    for campo, valor in cambios.items():
        setattr(oferente, campo, valor)
    if dias is not None:
        reemplazar_dias(db, oferente.id_oferente, dias)
    if not oferente.disponible_emergencia:
        oferente.info_guardia = None

    db.commit()
    db.refresh(oferente)
    return oferente


def buscar_publicos(
    db: Session,
    *,
    q: str | None,
    categoria_id: int | None,
    pagina: int,
    por_pagina: int,
    provincia_id: str | None = None,
    localidad_id: str | None = None,
    matriculado: bool = False,
    urgencias: bool = False,
) -> OferentesPaginadosOut:
    """RF7/RF8 — Búsqueda pública paginada del directorio. Excluye las cuentas
    suspendidas o bloqueadas (observación F4 de QA): un Profesional suspendido
    no aparece. Todos los filtros se combinan (AND).

    El orden es por `id_oferente` para que una página no se mezcle con la
    siguiente. Solo se arman los perfiles de la página pedida."""
    # Outer joins de a uno (categoría y localidad): no multiplican filas, así
    # que el conteo sigue siendo exacto. Las matrículas van con EXISTS por eso mismo.
    query = (
        db.query(Oferente)
        .join(Usuario, Usuario.id_usuario == Oferente.id_oferente)
        .outerjoin(Categoria, Categoria.id_categoria == Oferente.categoria_id)
        .outerjoin(Localidad, Localidad.id_localidad == Oferente.localidad_id)
        .filter(Usuario.estado_cuenta == EstadoCuenta.ACTIVA)
    )
    if categoria_id:
        query = query.filter(Oferente.categoria_id == categoria_id)
    if localidad_id:
        query = query.filter(Oferente.localidad_id == localidad_id)
    if provincia_id:
        query = query.filter(Localidad.provincia_id == provincia_id)
    if matriculado:
        query = query.filter(Oferente.matriculas.any())
    if urgencias:
        query = query.filter(Oferente.disponible_emergencia.is_(True))
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Oferente.nombre.ilike(like),
                Oferente.apellido.ilike(like),
                Categoria.nombre.ilike(like),
                Oferente.especialidad.ilike(like),
                Localidad.nombre.ilike(like),
                Oferente.matriculas.any(Matricula.numero_matricula.ilike(like)),
            )
        )

    total = query.count()
    perfiles = query.order_by(Oferente.id_oferente).offset((pagina - 1) * por_pagina).limit(por_pagina).all()
    return OferentesPaginadosOut(
        items=[armar_publica(db, oferente) for oferente in perfiles],
        pagina=pagina,
        por_pagina=por_pagina,
        total=total,
        total_paginas=-(-total // por_pagina),
    )
