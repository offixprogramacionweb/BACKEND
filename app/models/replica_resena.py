from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.database import Base


class ReplicaResena(Base):
    """Respuesta única del Profesional a una reseña publicada (HU-01 v2.1).

    Sin edición ni borrado: una vez registrada queda fija (CA03). La UNIQUE sobre
    `resena_id` cubre la carrera del doble clic.
    """

    __tablename__ = "replicas_resena"
    __table_args__ = (UniqueConstraint("resena_id", name="uq_replica_resena"),)

    id_replica = Column(Integer, primary_key=True, index=True)
    resena_id = Column(Integer, ForeignKey("resenas.id_resena", ondelete="CASCADE"), nullable=False)
    oferente_id = Column(Integer, ForeignKey("oferentes.id_oferente", ondelete="CASCADE"), nullable=False, index=True)
    texto = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    resena = relationship("Resena", back_populates="replica")
