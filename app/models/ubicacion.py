"""Provincias y localidades de Argentina (catálogo oficial del INDEC).

Los ids son los códigos oficiales, no autoincrementales: provincia "14" =
Córdoba, localidad "14140240"... Se cargan desde `app/db/ubicaciones.json`
(migración en Postgres, seed en SQLite) y no se editan desde la API.
"""

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.orm import relationship

from app.db.database import Base


class Provincia(Base):
    __tablename__ = "provincias"

    id_provincia = Column(String(2), primary_key=True)
    nombre = Column(String(100), nullable=False)

    localidades = relationship("Localidad", back_populates="provincia")


class Localidad(Base):
    __tablename__ = "localidades"

    id_localidad = Column(String(8), primary_key=True)
    nombre = Column(String(150), nullable=False)
    # Distingue las localidades con el mismo nombre dentro de una provincia (hay 68 casos).
    departamento = Column(String(150), nullable=False)
    provincia_id = Column(String(2), ForeignKey("provincias.id_provincia"), nullable=False, index=True)

    provincia = relationship("Provincia", back_populates="localidades")
