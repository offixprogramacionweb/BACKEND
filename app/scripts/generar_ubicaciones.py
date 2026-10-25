"""Genera `app/db/ubicaciones.json`: provincias y localidades de Argentina.

Fuente: API Georef del Gobierno nacional (https://apis.datos.gob.ar/georef),
que publica los datos oficiales del INDEC. Se usan las **localidades censales**
(ciudades y pueblos, unas 4.000), no las "localidades" de BAHRA, que incluyen
barrios y parajes sueltos.

Por qué no se sacan de los padrones de matrículas: ahí la localidad es texto
libre ("BS AS", "Capital", "punilla", "Lote 1"...) y solo existe para gasistas y
técnicos de aire acondicionado.

Los ids son los códigos oficiales del INDEC (provincia "14" = Córdoba): no
cambian entre corridas.

El JSON se versiona en el repo: la migración y el seed lo leen de ahí, sin
depender de la red. Volver a correr este script solo si cambia el catálogo
oficial, y cargar los cambios con una migración nueva.

Uso: python -m app.scripts.generar_ubicaciones
"""

import json

import httpx

from app.services.ubicaciones import ARCHIVO_CATALOGO

GEOREF = "https://apis.datos.gob.ar/georef/api"


def _get(recurso: str, campos: str) -> list[dict]:
    respuesta = httpx.get(f"{GEOREF}/{recurso}", params={"campos": campos, "max": 5000}, timeout=60)
    respuesta.raise_for_status()
    cuerpo = respuesta.json()
    filas = cuerpo[recurso.replace("-", "_")]
    # Con max=5000 llega todo de una vez; si algún día no alcanza, mejor fallar que cortar el catálogo.
    if cuerpo["total"] != len(filas):
        raise RuntimeError(f"{recurso}: llegaron {len(filas)} de {cuerpo['total']}")
    return filas


def generar() -> dict:
    provincias = sorted(
        ({"id": p["id"], "nombre": p["nombre"]} for p in _get("provincias", "id,nombre")),
        key=lambda p: p["nombre"],
    )
    ids_provincia = {p["id"] for p in provincias}
    localidades = sorted(
        (
            {
                "id": loc["id"],
                "nombre": loc["nombre"],
                # CABA no tiene departamento en Georef: se usa su propio nombre.
                "departamento": loc["departamento"]["nombre"] or loc["nombre"],
                "provincia_id": loc["provincia"]["id"],
            }
            for loc in _get("localidades-censales", "id,nombre,departamento.nombre,provincia.id")
        ),
        key=lambda loc: (loc["provincia_id"], loc["nombre"], loc["id"]),
    )
    huerfanas = [loc["id"] for loc in localidades if loc["provincia_id"] not in ids_provincia]
    if huerfanas:
        raise RuntimeError(f"Localidades con una provincia que no existe: {huerfanas[:10]}")
    return {"fuente": f"{GEOREF} (INDEC, localidades censales)", "provincias": provincias, "localidades": localidades}


def main() -> None:
    datos = generar()
    ARCHIVO_CATALOGO.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{ARCHIVO_CATALOGO}: {len(datos['provincias'])} provincias, {len(datos['localidades'])} localidades.")


if __name__ == "__main__":
    main()
