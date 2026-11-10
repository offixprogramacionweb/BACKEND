from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class AccionModeracion:
    SUSPENSION = "Suspension"
    ALTA = "Alta"
    BAJA_RESENA = "Baja_Resena"
    REACTIVACION_RESENA = "Reactivacion_Resena"
    BAJA_TRABAJO = "Baja_Trabajo"
    REACTIVACION_TRABAJO = "Reactivacion_Trabajo"
    VALIDACION_MATRICULA = "Validacion_Matricula"


class AuditoriaModeracion(Base):
    """Historial de las acciones del administrador sobre un Profesional (HU-07).
    Se escribe en la misma transacción que la acción."""

    __tablename__ = "auditoria_moderacion"

    id_auditoria = Column(Integer, primary_key=True, index=True)
    administrador_id = Column(Integer, ForeignKey("usuarios.id_usuario", ondelete="SET NULL"), nullable=True)
    oferente_id = Column(Integer, ForeignKey("oferentes.id_oferente", ondelete="CASCADE"), nullable=False, index=True)
    accion = Column(String(40), nullable=False)
    resena_id = Column(Integer, ForeignKey("resenas.id_resena", ondelete="SET NULL"), nullable=True)
    trabajo_id = Column(Integer, ForeignKey("trabajos_realizados.id_trabajo", ondelete="SET NULL"), nullable=True)
    detalle = Column(Text, nullable=True)
    fecha = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    administrador = relationship("Usuario")
