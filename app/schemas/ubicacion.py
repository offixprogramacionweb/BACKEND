from pydantic import BaseModel, Field


class ProvinciaOut(BaseModel):
    id: str = Field(description="Código INDEC de la provincia (\"14\" = Córdoba).")
    nombre: str


class LocalidadOut(BaseModel):
    id: str = Field(description="Código INDEC de la localidad. Es lo que se envía como `localidad_id`.")
    nombre: str
    departamento: str = Field(description="Para distinguir localidades con el mismo nombre en una provincia.")
