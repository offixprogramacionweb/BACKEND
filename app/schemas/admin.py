from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.oferente import CategoriaRef, MatriculaRef
from app.schemas.resena import ReplicaOut
from app.schemas.trabajo import TrabajoOut


class OferenteAdminFila(BaseModel):
    """Una fila de la grilla "Gestión de Oferentes" (HU-07 CA02)."""

    id_oferente: int
    nombre: str
    apellido: str | None = None
    foto_perfil_url: str | None = None
    estado: Literal["Activo", "Suspendido"] = Field(description="Activo si la cuenta está activa; Suspendido en otro caso.")
    estado_cuenta: str = Field(description="Valor crudo de la cuenta: Activa | Suspendida | Bloqueada.")
    categoria: CategoriaRef | None = Field(default=None, description="El rubro.")
    especialidad: str | None = None
    matricula_verificada: bool = Field(description="true si tiene al menos una matrícula fidelizada (con el ícono de check).")
    matriculas: list[MatriculaRef] = Field(default_factory=list)
    promedio_calificacion: float
    cantidad_resenas: int = Field(description="Reseñas visibles (publicadas y no dadas de baja).")
    cantidad_trabajos: int = Field(description="Trabajos visibles (no dados de baja).")
    cantidad_rechazadas: int = Field(description="Reseñas rechazadas por el Profesional, en total.")


class OferenteAdminDetalle(OferenteAdminFila):
    """Tarjeta del Profesional en "Moderar Reseñas" y "Auditar Trabajos"."""

    descripcion: str | None = None
    email: str


class ContadoresOferentes(BaseModel):
    activos: int = Field(description="Cantidad global de Profesionales activos. No depende del filtro.")
    suspendidos: int = Field(description="Cantidad global de Profesionales suspendidos. No depende del filtro.")


class OferentesAdminPaginadosOut(BaseModel):
    items: list[OferenteAdminFila]
    contadores: ContadoresOferentes
    pagina: int
    por_pagina: int
    total: int = Field(description="Cantidad de resultados con el filtro y la búsqueda aplicados.")
    total_paginas: int


class MatriculaAdminIn(BaseModel):
    """Modal "Validar Matrícula" del administrador (HU-07 CA03). Sin consulta al padrón."""

    model_config = ConfigDict(json_schema_extra={"example": {"tipo_profesional": "Gasista", "numero_matricula": "1000008919"}})

    tipo_profesional: str = Field(description="Gasista | Aire acondicionado (los tipos de HU-02).")
    numero_matricula: str = Field(description="Solo dígitos, con la cantidad del tipo (ver GET /matriculas/tipos).")


class BajaIn(BaseModel):
    motivo: str | None = Field(default=None, max_length=200, description="Opcional. Se guarda en el historial de auditoría.")


class ResenaModeracionOut(BaseModel):
    """Una opinión en "Moderar Reseñas" (HU-07 CA04/CA05). Lo ve solo el administrador."""

    id_resena: int
    nombre_cliente: str
    puntuacion_global: float
    criterios: dict
    comentario: str | None = None
    fecha_creacion: datetime
    estado: Literal["Aceptada", "Rechazada", "Dada_de_baja"]
    dado_de_baja_en: datetime | None = None
    replica: ReplicaOut | None = None
    puede_dar_de_baja: bool = Field(description="true solo para las aceptadas que siguen visibles.")
    puede_reactivar: bool = Field(description="true solo para las dadas de baja.")


class TrabajoModeracionOut(TrabajoOut):
    """Un trabajo en "Auditar Trabajos Realizados" (HU-07 CA04/CA05)."""

    estado: Literal["Activo", "Dado_de_baja"]
    dado_de_baja_en: datetime | None = None


class AccionResenaOut(BaseModel):
    resena: ResenaModeracionOut
    oferente: OferenteAdminFila = Field(description="Métricas ya recalculadas, para actualizar la tarjeta sin otro request.")


class AccionTrabajoOut(BaseModel):
    trabajo: TrabajoModeracionOut
    oferente: OferenteAdminFila


class AuditoriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_auditoria: int
    accion: str
    fecha: datetime
    administrador_id: int | None = None
    resena_id: int | None = None
    trabajo_id: int | None = None
    detalle: str | None = None
