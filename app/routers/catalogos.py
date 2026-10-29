from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.catalogos import DIAS, EXPERIENCIA, HORARIO_POR_DEFECTO
from app.core.config import settings
from app.core.errores import error_negocio
from app.db.database import get_db
from app.models.categoria import Categoria, EstadoCategoria
from app.models.oferente import Oferente
from app.models.usuario import EstadoCuenta, Usuario
from app.schemas.catalogo import (
    CatalogoRegistroOut,
    CategoriaCatalogo,
    DiaCatalogo,
    ExperienciaCatalogo,
    HorarioPorDefecto,
    LimitesCatalogo,
)
from app.schemas.ubicacion import LocalidadOut, ProvinciaOut
from app.services.ubicaciones import catalogo_en_memoria, normalizar

router = APIRouter(prefix="/api/v1/catalogos", tags=["Catálogos"])

# El catálogo de localidades se carga al arrancar el backend, no en el primer pedido.
catalogo_en_memoria()


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


# Caché del CDN de Vercel y del navegador. `s-maxage` lo usa Vercel; `max-age`, el navegador.
# El catálogo completo solo cambia con una migración: 1 día. "Con profesionales" cambia
# cuando alguien se registra en una zona nueva: 5 minutos en Vercel, 1 en el navegador.
CACHE_CATALOGO = "public, max-age=86400, s-maxage=86400"
CACHE_CON_PROFESIONALES = "public, max-age=60, s-maxage=300"
SIN_CACHE = {"Cache-Control": "no-store"}

SOLO_CON_PROFESIONALES = Query(
    default=False,
    description="true: solo las zonas con profesionales activos (desplegable \"Zona\" del directorio). "
    "false: el catálogo completo (formulario de alta).",
)


def _localidades_con_profesionales(db: Session) -> set[str]:
    """La única consulta a la base del catálogo: qué localidades tienen al menos
    un profesional activo. El resto sale de la memoria."""
    filas = (
        db.query(Oferente.localidad_id)
        .join(Usuario, Usuario.id_usuario == Oferente.id_oferente)
        .filter(Usuario.estado_cuenta == EstadoCuenta.ACTIVA, Oferente.localidad_id.isnot(None))
        .distinct()
    )
    return {localidad_id for (localidad_id,) in filas}


@router.get("/provincias", response_model=list[ProvinciaOut], summary="Listar provincias (público)")
def listar_provincias(response: Response, solo_con_profesionales: bool = SOLO_CON_PROFESIONALES, db: Session = Depends(get_db)):
    """Catálogo oficial del INDEC, ordenado por nombre. Responde desde memoria;
    solo `solo_con_profesionales=true` consulta la base."""
    catalogo = catalogo_en_memoria()
    provincias = catalogo.provincias
    if solo_con_profesionales:
        con_profesionales = {
            catalogo.provincia_de_localidad[localidad_id]
            for localidad_id in _localidades_con_profesionales(db)
            if localidad_id in catalogo.provincia_de_localidad
        }
        provincias = tuple(p for p in provincias if p[0] in con_profesionales)
    response.headers["Cache-Control"] = CACHE_CON_PROFESIONALES if solo_con_profesionales else CACHE_CATALOGO
    return [ProvinciaOut(id=provincia_id, nombre=nombre) for provincia_id, nombre in provincias]


@router.get(
    "/provincias/{provincia_id}/localidades",
    response_model=list[LocalidadOut],
    summary="Listar las localidades de una provincia (público)",
    responses={404: {"description": "La provincia no existe (`provincia_inexistente`)"}},
)
def listar_localidades(
    provincia_id: str,
    response: Response,
    q: str | None = Query(
        default=None,
        description="Parte del nombre de la localidad, para autocompletar. No distingue mayúsculas ni tildes.",
    ),
    solo_con_profesionales: bool = SOLO_CON_PROFESIONALES,
    db: Session = Depends(get_db),
):
    """Ordenadas por nombre. Algunas provincias tienen localidades con el mismo
    nombre: el `departamento` sirve para distinguirlas en el desplegable.
    Responde desde memoria; solo `solo_con_profesionales=true` consulta la base."""
    localidades = catalogo_en_memoria().localidades_por_provincia.get(provincia_id)
    if localidades is None:
        raise error_negocio(404, "provincia_inexistente", "La provincia no existe", headers=SIN_CACHE)
    texto = normalizar((q or "").strip())
    if texto:
        localidades = tuple(loc for loc in localidades if texto in loc.clave)
    if solo_con_profesionales:
        con_profesionales = _localidades_con_profesionales(db)
        localidades = tuple(loc for loc in localidades if loc.id in con_profesionales)
    response.headers["Cache-Control"] = CACHE_CON_PROFESIONALES if solo_con_profesionales else CACHE_CATALOGO
    return [LocalidadOut(id=loc.id, nombre=loc.nombre, departamento=loc.departamento) for loc in localidades]
