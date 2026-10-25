from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_oferente_registrado
from app.core.errores import error_negocio, error_validacion
from app.db.database import get_db
from app.models.oferente import Oferente
from app.models.usuario import Usuario
from app.schemas.oferente import OferenteEdicion, OferentePrivadoOut, OferentePublicoOut, OferenteRegistro, OferentesPaginadosOut
from app.services.oferentes import aplicar_edicion, armar_privada, armar_publica, buscar_publicos, crear_oferente

router = APIRouter(prefix="/api/v1/oferentes", tags=["Oferentes"])

# Tamaños de página del listado público. Cualquier otro valor responde 422.
POR_PAGINA_PERMITIDOS = (10, 25)

RESPUESTAS_REGISTRO = {
    401: {"description": "Falta token o es inválido"},
    403: {"description": "El usuario es Administrador (`rol_invalido`) o no tiene perfil (`registro_incompleto`)"},
}


@router.get(
    "",
    response_model=OferentesPaginadosOut,
    summary="Buscar profesionales (público, paginado)",
    responses={422: {"description": "`por_pagina` distinto de 10 o 25, o `pagina` menor a 1"}},
)
def buscar_oferentes(
    q: str | None = Query(
        default=None,
        description="Texto libre: parte del nombre, apellido, oficio (categoría o especialidad), número de matrícula o localidad.",
    ),
    categoria_id: int | None = Query(default=None, description="Filtrar por categoría/oficio. Sin valor: todos los oficios."),
    provincia_id: str | None = Query(default=None, description="Código INDEC de la provincia. Sin valor: todas."),
    localidad_id: str | None = Query(default=None, description="Código INDEC de la localidad. Sin valor: todas las zonas."),
    matriculado: bool = Query(default=False, description="Solo Matriculados: con al menos una matrícula fidelizada."),
    urgencias: bool = Query(default=False, description="Disponible Hoy / Urgencias: solo quienes atienden emergencias."),
    pagina: int = Query(default=1, ge=1, description="Página a devolver, desde 1."),
    por_pagina: int = Query(default=10, description="Profesionales por página: 10 o 25."),
    db: Session = Depends(get_db),
):
    """RF7/RF8 — Directorio público paginado. Todos los filtros se combinan.
    Excluye las cuentas suspendidas o bloqueadas (observación F4 de QA).
    Sin coincidencias (o con una provincia/localidad inexistente) devuelve
    `items` vacío y `total` 0. Una página fuera de rango devuelve `items`
    vacío con el `total` real."""
    if por_pagina not in POR_PAGINA_PERMITIDOS:
        raise error_validacion("por_pagina", "invalido", "Elegí 10 o 25 profesionales por página")
    return buscar_publicos(
        db,
        q=q,
        categoria_id=categoria_id,
        provincia_id=provincia_id,
        localidad_id=localidad_id,
        matriculado=matriculado,
        urgencias=urgencias,
        pagina=pagina,
        por_pagina=por_pagina,
    )


@router.post(
    "",
    response_model=OferentePrivadoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Confirmar el registro de Profesional (CA02/CA03)",
    responses={
        **RESPUESTAS_REGISTRO,
        409: {"description": "Ya completó el registro (`perfil_existente`) o el DNI/CUIT ya existe (`dni_cuit_duplicado`)"},
        422: {"description": "Errores de validación. `errores[]` trae todos los campos a corregir"},
    },
)
def crear_perfil_oferente(
    payload: OferenteRegistro,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """HU-04 — Crea el perfil del Oferente y sus días de atención en una sola
    transacción. Si el formulario tiene errores, responde 422 con **todos** los
    campos a la vez (CA02). Si abandonan el formulario, no se persiste nada (CA06)."""
    oferente = crear_oferente(db, usuario, payload)
    return armar_privada(db, oferente)


@router.get(
    "/me",
    response_model=OferentePrivadoOut,
    summary="Mi perfil profesional completo",
    responses=RESPUESTAS_REGISTRO,
)
def obtener_mi_perfil(oferente: Oferente = Depends(get_oferente_registrado), db: Session = Depends(get_db)):
    """HU-04 CA04 — Perfil del dueño: incluye DNI/CUIT, que nadie más ve (D7)."""
    return armar_privada(db, oferente)


@router.put(
    "/me",
    response_model=OferentePrivadoOut,
    summary="Editar mi perfil profesional (sin DNI/CUIT ni correo)",
    responses={
        **RESPUESTAS_REGISTRO,
        409: {"description": "Cambio de nombre con una matrícula fidelizada (`nombre_bloqueado_por_matricula`)"},
        422: {"description": "Errores de validación, o un campo que no se puede editar (dni_cuit)"},
    },
)
def actualizar_mi_perfil(
    payload: OferenteEdicion,
    oferente: Oferente = Depends(get_oferente_registrado),
    db: Session = Depends(get_db),
):
    """HU-04 (D18) — Todos los campos son opcionales. El DNI/CUIT y el correo no
    se cambian: se rechazan o se ignoran."""
    actualizado = aplicar_edicion(db, oferente, payload)
    return armar_privada(db, actualizado)


@router.get(
    "/{oferente_id}",
    response_model=OferentePublicoOut,
    summary="Consultar el perfil de un profesional (público)",
    responses={404: {"description": "Oferente no encontrado"}},
)
def obtener_oferente(oferente_id: int, db: Session = Depends(get_db)):
    """RF7 — Perfil público. No devuelve DNI/CUIT, estado de verificación ni
    rechazos acumulados."""
    oferente = db.get(Oferente, oferente_id)
    if not oferente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Oferente no encontrado")
    return armar_publica(db, oferente)


@router.put(
    "/{oferente_id}",
    response_model=OferentePrivadoOut,
    summary="Editar el perfil propio (alias de compatibilidad de PUT /me)",
    responses={
        **RESPUESTAS_REGISTRO,
        403: {"description": "El perfil no es el del usuario autenticado"},
    },
)
def actualizar_perfil_oferente(
    oferente_id: int,
    payload: OferenteEdicion,
    oferente: Oferente = Depends(get_oferente_registrado),
    db: Session = Depends(get_db),
):
    """Se mantiene por compatibilidad con los llamados de Sprint 1. Delega en la
    misma lógica que `PUT /oferentes/me` y solo acepta el propio `id`."""
    if oferente.id_oferente != oferente_id:
        raise error_negocio(403, "no_autorizado", "No autorizado")
    actualizado = aplicar_edicion(db, oferente, payload)
    return armar_privada(db, actualizado)
