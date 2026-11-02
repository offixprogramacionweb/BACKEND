from sqlalchemy import Column, Integer, String, UniqueConstraint

from app.db.database import Base


class Localidad(Base):
    """Catálogo de ubicaciones para los filtros de búsqueda (HU de búsqueda de
    Profesionales). Se carga una sola vez desde `app/db/localidades.json`
    (fuente: Georef/INDEC); la provincia va como texto, sin normalizar."""

    __tablename__ = "localidades"
    __table_args__ = (UniqueConstraint("provincia", "ciudad", name="uq_localidades_provincia_ciudad"),)

    id_localidad = Column(Integer, primary_key=True, index=True)
    provincia = Column(String(100), nullable=False, index=True)
    ciudad = Column(String(150), nullable=False)
