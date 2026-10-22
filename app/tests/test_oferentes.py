from app.tests.conftest import crear_categoria_db, crear_oferente_completo, formulario_registro, registrar_y_loguear


def test_crear_perfil_oferente_ok_id_igual_a_usuario(client, db_session):
    from jose import jwt

    from app.core.config import settings

    token, oferente_id = crear_oferente_completo(client, db_session, email="ok@test.com", dni_cuit="20-22222222-3")

    response = client.get(f"/api/v1/oferentes/{oferente_id}")
    assert response.status_code == 200

    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert int(payload["sub"]) == oferente_id


def test_crear_perfil_sin_token_401(client, db_session):
    categoria = crear_categoria_db(db_session)
    response = client.post(
        "/api/v1/oferentes",
        json={
            "nombre": "Sin",
            "apellido": "Apellido",
            "dni_cuit": "20-33333333-4",
            "telefono_codigo_area": "3564",
            "telefono_numero": "400000",
            "categoria_id": categoria.id_categoria,
        },
    )
    assert response.status_code == 401


def test_crear_perfil_duplicado_409(client, db_session):
    token, _ = crear_oferente_completo(client, db_session, email="duplicado@test.com", dni_cuit="20-44444444-5")
    categoria = crear_categoria_db(db_session, nombre="OtraCategoria")

    response = client.post(
        "/api/v1/oferentes",
        json=formulario_registro(categoria.id_categoria, dni_cuit="20-55555555-6", nombre="Otra Vez"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["codigo"] == "perfil_existente"


def test_crear_perfil_dni_duplicado_409(client, db_session):
    crear_oferente_completo(client, db_session, email="uno@test.com", dni_cuit="20-66666666-7")
    token_dos = registrar_y_loguear(client, "dos@test.com")
    categoria = crear_categoria_db(db_session, nombre="CategoriaDos")

    response = client.post(
        "/api/v1/oferentes",
        json=formulario_registro(categoria.id_categoria, dni_cuit="20-66666666-7", nombre="Dos Prueba"),
        headers={"Authorization": f"Bearer {token_dos}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["codigo"] == "dni_cuit_duplicado"


def test_crear_perfil_formato_invalido_422(client, db_session):
    token = registrar_y_loguear(client, "formato@test.com")
    categoria = crear_categoria_db(db_session, nombre="CategoriaFormato")

    response = client.post(
        "/api/v1/oferentes",
        json={
            "nombre": "Malo",
            "apellido": "Malo",
            "dni_cuit": "no-es-un-dni!!",
            "telefono_codigo_area": "3564",
            "telefono_numero": "400000",
            "categoria_id": categoria.id_categoria,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_buscar_oferentes_publico(client, db_session):
    crear_oferente_completo(client, db_session, email="buscable@test.com", dni_cuit="20-77777777-8")
    response = client.get("/api/v1/oferentes")
    assert response.status_code == 200
    assert len(response.json()["items"]) >= 1


def _crear_varios_oferentes(client, db_session, cantidad: int) -> list[int]:
    return [
        crear_oferente_completo(client, db_session, email=f"pag{i}@test.com", dni_cuit=f"{30000000 + i}")[1]
        for i in range(cantidad)
    ]


def test_listado_paginado_por_defecto_son_10_y_metadatos(client, db_session):
    ids = _crear_varios_oferentes(client, db_session, 12)

    cuerpo = client.get("/api/v1/oferentes").json()

    assert cuerpo["pagina"] == 1
    assert cuerpo["por_pagina"] == 10
    assert cuerpo["total"] == 12
    assert cuerpo["total_paginas"] == 2
    assert [o["id_oferente"] for o in cuerpo["items"]] == ids[:10]


def test_segunda_pagina_trae_el_resto_sin_repetir(client, db_session):
    ids = _crear_varios_oferentes(client, db_session, 12)

    cuerpo = client.get("/api/v1/oferentes", params={"pagina": 2, "por_pagina": 10}).json()

    assert [o["id_oferente"] for o in cuerpo["items"]] == ids[10:]
    assert cuerpo["total_paginas"] == 2


def test_por_pagina_25_trae_todos_en_una_pagina(client, db_session):
    _crear_varios_oferentes(client, db_session, 12)

    cuerpo = client.get("/api/v1/oferentes", params={"por_pagina": 25}).json()

    assert len(cuerpo["items"]) == 12
    assert cuerpo["total_paginas"] == 1


def test_por_pagina_fuera_de_10_y_25_es_422(client, db_session):
    for valor in (5, 15, 50, 100):
        respuesta = client.get("/api/v1/oferentes", params={"por_pagina": valor})
        assert respuesta.status_code == 422, valor
        assert respuesta.json()["errores"] == [{"campo": "por_pagina", "codigo": "invalido"}]


def test_pagina_menor_a_1_es_422(client, db_session):
    assert client.get("/api/v1/oferentes", params={"pagina": 0}).status_code == 422


def test_pagina_fuera_de_rango_devuelve_items_vacios_con_total_real(client, db_session):
    _crear_varios_oferentes(client, db_session, 3)

    cuerpo = client.get("/api/v1/oferentes", params={"pagina": 5}).json()

    assert cuerpo["items"] == []
    assert cuerpo["total"] == 3


def test_sin_resultados_total_paginas_es_cero(client, db_session):
    cuerpo = client.get("/api/v1/oferentes").json()

    assert cuerpo == {"items": [], "pagina": 1, "por_pagina": 10, "total": 0, "total_paginas": 0}


def test_busqueda_q_matchea_nombre_o_apellido(client, db_session):
    crear_oferente_completo(client, db_session, email="q1@test.com", dni_cuit="80000001")
    otro_token = registrar_y_loguear(client, "q2@test.com")
    categoria = crear_categoria_db(db_session, nombre="CategoriaQ")
    client.post(
        "/api/v1/oferentes",
        json=formulario_registro(categoria.id_categoria, dni_cuit="80000002", nombre="Lucía", apellido="Rodríguez"),
        headers={"Authorization": f"Bearer {otro_token}"},
    )

    por_nombre = client.get("/api/v1/oferentes", params={"q": "lucía"}).json()
    por_apellido = client.get("/api/v1/oferentes", params={"q": "rodrí"}).json()

    assert por_nombre["total"] == 1
    assert por_apellido["total"] == 1
    assert por_apellido["items"][0]["apellido"] == "Rodríguez"
