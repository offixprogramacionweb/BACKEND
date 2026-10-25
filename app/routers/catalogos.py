from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.catalogos import DIAS, EXPERIENCIA, HORARIO_POR_DEFECTO
from app.core.config import settings
from app.core.errores import error_negocio
from app.db.database import get_db
from app.models.categoria import Categoria, EstadoCategoria
from app.models.oferente import Oferente
from app.models.ubicacion import Localidad, Provincia
from app.models.usuario import EstadoCuenta, Usuario
from app.schemas.ubicacion import LocalidadOut, ProvinciaOut
from app.schemas.catalogo import (
    CatalogoRegistroOut,
    CategoriaCatalogo,
    DiaCatalogo,
    ExperienciaCatalogo,
    HorarioPorDefecto,
    LimitesCatalogo,
)

router = APIRouter(prefix="/api/v1/catalogos", tags=["Catálogos"])


@router.get(
    "/registro-oferente",
    response_model=CatalogoRegistroOut,
    summary="Opciones del formulario de registro de Profesional (público)",
)
def catalogo_registro_oferente(db: Session = Depends(get_db)):
    """HU-04 — Una sola llamada llena categorías, rangos de experiencia, días,
    horario por defecto y los límites de trabajos realizados. Solo se listan las
    categorías activas."""
    categorias = (
        db.query(Categoria)
        .filter(Categoria.estado == EstadoCategoria.ACTIVA)
        .order_by(Categoria.nombre)
        .all()
    )
    return CatalogoRegistroOut(
        categorias=[CategoriaCatalogo(id=categoria.id_categoria, nombre=categoria.nombre) for categoria in categorias],
        experiencia=[ExperienciaCatalogo(codigo=rango.codigo, etiqueta=rango.etiqueta) for rango in EXPERIENCIA],
        dias=[DiaCatalogo(dia=dia, corto=corto, largo=largo) for dia, corto, largo in DIAS],
        horario_default=HorarioPorDefecto(**HORARIO_POR_DEFECTO),
        limites=LimitesCatalogo(
            trabajos=settings.trabajos_maximos,
            fotos_por_trabajo=settings.fotos_por_trabajo_maximas,
            tamano_maximo_mb=settings.archivo_tamano_maximo_mb,
        ),
    )


SOLO_CON_PROFESIONALES = Query(
    default=False,
    description="true: solo las zonas con profesionales activos (desplegable \"Zona\" del directorio). "
    "false: el catálogo completo (formulario de alta).",
)


def _localidades_con_profesionales(db: Session):
    """Subconsulta con las localidades que tienen al menos un profesional activo."""
    return (
        db.query(Oferente.localidad_id)
        .join(Usuario, Usuario.id_usuario == Oferente.id_oferente)
        .filter(Usuario.estado_cuenta == EstadoCuenta.ACTIVA, Oferente.localidad_id.isnot(None))
    )


@router.get("/provincias", response_model=list[ProvinciaOut], summary="Listar provincias (público)")
def listar_provincias(solo_con_profesionales: bool = SOLO_CON_PROFESIONALES, db: Session = Depends(get_db)):
    """Catálogo oficial del INDEC, ordenado por nombre."""
    query = db.query(Provincia)
    if solo_con_profesionales:
        con_profesionales = db.query(Localidad.provincia_id).filter(
            Localidad.id_localidad.in_(_localidades_con_profesionales(db))
        )
        query = query.filter(Provincia.id_provincia.in_(con_profesionales))
    return [ProvinciaOut(id=p.id_provincia, nombre=p.nombre) for p in query.order_by(Provincia.nombre)]


@router.get(
    "/provincias/{provincia_id}/localidades",
    response_model=list[LocalidadOut],
    summary="Listar las localidades de una provincia (público)",
    responses={404: {"description": "La provincia no existe (`provincia_inexistente`)"}},
)
def listar_localidades(
    provincia_id: str,
    q: str | None = Query(default=None, description="Parte del nombre de la localidad, para autocompletar."),
    solo_con_profesionales: bool = SOLO_CON_PROFESIONALES,
    db: Session = Depends(get_db),
):
    """Ordenadas por nombre. Algunas provincias tienen localidades con el mismo
    nombre: el `departamento` sirve para distinguirlas en el desplegable."""
    if db.get(Provincia, provincia_id) is None:
        raise error_negocio(404, "provincia_inexistente", "La provincia no existe")
    query = db.query(Localidad).filter(Localidad.provincia_id == provincia_id)
    q = (q or "").strip()
    if q:
        query = query.filter(Localidad.nombre.ilike(f"%{q}%"))
    if solo_con_profesionales:
        query = query.filter(Localidad.id_localidad.in_(_localidades_con_profesionales(db)))
    return [
        LocalidadOut(id=loc.id_localidad, nombre=loc.nombre, departamento=loc.departamento)
        for loc in query.order_by(Localidad.nombre, Localidad.departamento)
    ]
