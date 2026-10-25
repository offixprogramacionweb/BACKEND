"""Directorio de profesionales: búsqueda, filtros y zonas (US Búsqueda de Profesionales, CA04-CA07)."""

from datetime import date

from app.models.matricula import Matricula
from app.models.oferente import Oferente
from app.services.ubicaciones import cargar_catalogo
from app.tests.conftest import crear_categoria_db, crear_localidad_db, formulario_registro, registrar_y_loguear

SAN_FRANCISCO = "14140360"
FREYRE = "14140220"
FRONTERA = "82021200"


def _localidades(db_session):
    crear_localidad_db(db_session, SAN_FRANCISCO, "San Francisco")
    crear_localidad_db(db_session, FREYRE, "Freyre")
    crear_localidad_db(db_session, FRONTERA, "Frontera", provincia_id="82", provincia_nombre="Santa Fe", departamento="Castellanos")


def _alta(client, db_session, email: str, dni: str, categoria, **extra) -> int:
    token = registrar_y_loguear(client, email)
    respuesta = client.post(
        "/api/v1/oferentes",
        json=formulario_registro(categoria.id_categoria, dni_cuit=dni, **extra),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id_oferente"]


def _fidelizar(db_session, oferente_id: int, numero: str) -> None:
    db_session.add(
        Matricula(
            oferente_id=oferente_id,
            tipo_profesional="Gasista",
            numero_matricula=numero,
            categoria="Primera",
            fecha_vencimiento=date(2027, 3, 31),
        )
    )
    db_session.commit()


def _ids(client, **params) -> set[int]:
    cuerpo = client.get("/api/v1/oferentes", params={"por_pagina": 25, **params}).json()
    assert cuerpo["total"] == len(cuerpo["items"])
    return {o["id_oferente"] for o in cuerpo["items"]}


def _directorio(client, db_session) -> dict[str, int]:
    """Cuatro profesionales distintos en oficio, zona, matrícula y urgencias."""
    _localidades(db_session)
    electricista = crear_categoria_db(db_session, "Electricista")
    gasista = crear_categoria_db(db_session, "Gasista")
    ids = {
        "juan": _alta(client, db_session, "juan@test.com", "40000001", electricista, nombre="Juan", apellido="Pérez",
                      localidad_id=SAN_FRANCISCO, disponible_emergencia=True, especialidad="Tableros"),
        "maria": _alta(client, db_session, "maria@test.com", "40000002", gasista, nombre="María", apellido="Alessi",
                       localidad_id=SAN_FRANCISCO),
        "carlos": _alta(client, db_session, "carlos@test.com", "40000003", gasista, nombre="Carlos", apellido="Gómez",
                        localidad_id=FRONTERA, disponible_emergencia=True),
        "sin_zona": _alta(client, db_session, "sinzona@test.com", "40000004", electricista, nombre="Sergio", apellido="Díaz"),
    }
    _fidelizar(db_session, ids["maria"], "1000008919")
    _fidelizar(db_session, ids["carlos"], "1000004305")
    return ids


# --- Búsqueda por texto (CA05) ------------------------------------------------


def test_q_busca_por_oficio(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, q="electricista") == {ids["juan"], ids["sin_zona"]}
    assert _ids(client, q="GASISTA") == {ids["maria"], ids["carlos"]}


def test_q_busca_por_especialidad(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, q="tablero") == {ids["juan"]}


def test_q_busca_por_numero_de_matricula(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, q="1000008919") == {ids["maria"]}


def test_q_busca_por_localidad(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, q="frontera") == {ids["carlos"]}


def test_q_con_espacios_solos_trae_todos(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, q="   ") == set(ids.values())


# --- Filtros (CA05) -------------------------------------------------------------


def test_sin_filtros_trae_todos(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client) == set(ids.values())
    assert _ids(client, matriculado=False, urgencias=False) == set(ids.values())


def test_filtro_por_localidad(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, localidad_id=SAN_FRANCISCO) == {ids["juan"], ids["maria"]}


def test_filtro_por_provincia(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, provincia_id="14") == {ids["juan"], ids["maria"]}
    assert _ids(client, provincia_id="82") == {ids["carlos"]}


def test_filtro_solo_matriculados(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, matriculado=True) == {ids["maria"], ids["carlos"]}


def test_filtro_urgencias(client, db_session):
    ids = _directorio(client, db_session)
    assert _ids(client, urgencias=True) == {ids["juan"], ids["carlos"]}


def test_combinacion_de_texto_categoria_zona_y_filtros(client, db_session):
    ids = _directorio(client, db_session)
    gasista_id = client.get("/api/v1/oferentes", params={"q": "maría"}).json()["items"][0]["categoria"]["id_categoria"]

    assert _ids(client, q="gómez", categoria_id=gasista_id, provincia_id="82", matriculado=True, urgencias=True) == {ids["carlos"]}
    assert _ids(client, categoria_id=gasista_id, localidad_id=SAN_FRANCISCO, urgencias=True) == set()


def test_sin_coincidencias_devuelve_lista_vacia_y_total_cero(client, db_session):
    _directorio(client, db_session)
    for params in ({"q": "zzzz"}, {"localidad_id": FREYRE}, {"provincia_id": "99"}, {"localidad_id": "no-existe"}):
        cuerpo = client.get("/api/v1/oferentes", params=params).json()
        assert (cuerpo["items"], cuerpo["total"]) == ([], 0), params


def test_suspendido_no_aparece_en_ningun_filtro(client, db_session):
    ids = _directorio(client, db_session)
    db_session.get(Oferente, ids["carlos"]).usuario.estado_cuenta = "Suspendida"
    db_session.commit()
    assert ids["carlos"] not in _ids(client, provincia_id="82")


# --- Localidad en el alta, la edición y el perfil (CA07) -------------------------


def test_perfil_publico_trae_localidad_y_provincia(client, db_session):
    ids = _directorio(client, db_session)
    cuerpo = client.get(f"/api/v1/oferentes/{ids['carlos']}").json()

    assert cuerpo["localidad"] == {"id": FRONTERA, "nombre": "Frontera", "departamento": "Castellanos"}
    assert cuerpo["provincia"] == {"id": "82", "nombre": "Santa Fe"}
    assert not {"latitud", "longitud", "radio_cobertura_km"} & cuerpo.keys()


def test_alta_sin_localidad_es_valida(client, db_session):
    ids = _directorio(client, db_session)
    cuerpo = client.get(f"/api/v1/oferentes/{ids['sin_zona']}").json()
    assert (cuerpo["localidad"], cuerpo["provincia"]) == (None, None)


def test_alta_con_localidad_inexistente_es_422(client, db_session):
    categoria = crear_categoria_db(db_session)
    token = registrar_y_loguear(client, "mala@test.com")
    respuesta = client.post(
        "/api/v1/oferentes",
        json=formulario_registro(categoria.id_categoria, localidad_id="99999999"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["errores"] == [{"campo": "localidad_id", "codigo": "localidad_invalida"}]


def test_edicion_cambia_y_borra_la_localidad(client, db_session):
    _localidades(db_session)
    categoria = crear_categoria_db(db_session)
    token = registrar_y_loguear(client, "edita@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/oferentes", json=formulario_registro(categoria.id_categoria, localidad_id=SAN_FRANCISCO), headers=headers)

    cambiada = client.put("/api/v1/oferentes/me", json={"localidad_id": FREYRE}, headers=headers)
    assert cambiada.json()["localidad"]["nombre"] == "Freyre"

    invalida = client.put("/api/v1/oferentes/me", json={"localidad_id": "99999999"}, headers=headers)
    assert invalida.status_code == 422

    borrada = client.put("/api/v1/oferentes/me", json={"localidad_id": None}, headers=headers)
    assert borrada.status_code == 200
    assert borrada.json()["localidad"] is None


def test_edicion_ya_no_acepta_coordenadas(client, db_session):
    categoria = crear_categoria_db(db_session)
    token = registrar_y_loguear(client, "coords@test.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/oferentes", json=formulario_registro(categoria.id_categoria), headers=headers)

    respuesta = client.put("/api/v1/oferentes/me", json={"latitud": -31.4}, headers=headers)

    assert respuesta.status_code == 422
    assert respuesta.json()["errores"] == [{"campo": "latitud", "codigo": "campo_no_permitido"}]


# --- Catálogo de provincias y localidades ----------------------------------------


def test_catalogo_de_provincias_ordenado(client, db_session):
    _localidades(db_session)
    assert client.get("/api/v1/catalogos/provincias").json() == [
        {"id": "14", "nombre": "Córdoba"},
        {"id": "82", "nombre": "Santa Fe"},
    ]


def test_localidades_de_una_provincia_con_busqueda(client, db_session):
    _localidades(db_session)
    todas = client.get("/api/v1/catalogos/provincias/14/localidades").json()
    assert [loc["nombre"] for loc in todas] == ["Freyre", "San Francisco"]

    filtradas = client.get("/api/v1/catalogos/provincias/14/localidades", params={"q": "san fran"}).json()
    assert filtradas == [{"id": SAN_FRANCISCO, "nombre": "San Francisco", "departamento": "San Justo"}]


def test_localidades_de_provincia_inexistente_es_404(client, db_session):
    respuesta = client.get("/api/v1/catalogos/provincias/99/localidades")
    assert respuesta.status_code == 404
    assert respuesta.json()["detail"]["codigo"] == "provincia_inexistente"


def test_solo_zonas_con_profesionales(client, db_session):
    _directorio(client, db_session)

    provincias = client.get("/api/v1/catalogos/provincias", params={"solo_con_profesionales": True}).json()
    localidades = client.get("/api/v1/catalogos/provincias/14/localidades", params={"solo_con_profesionales": True}).json()

    assert [p["id"] for p in provincias] == ["14", "82"]
    assert [loc["id"] for loc in localidades] == [SAN_FRANCISCO]  # Freyre no tiene profesionales


def test_catalogo_versionado_es_consistente():
    catalogo = cargar_catalogo()
    provincias = {p["id"] for p in catalogo["provincias"]}
    ids_localidades = [loc["id"] for loc in catalogo["localidades"]]

    assert len(provincias) == 24
    assert len(ids_localidades) == len(set(ids_localidades)) > 4000
    assert all(loc["provincia_id"] in provincias for loc in catalogo["localidades"])
    assert all(len(loc["id"]) <= 8 and len(loc["nombre"]) <= 150 and len(loc["departamento"]) <= 150 for loc in catalogo["localidades"])
