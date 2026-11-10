"""HU-01 v2.1 — Réplica única del Profesional a una reseña publicada.

Cubre los CA01 a CA07 de la HU y los casos de la hoja "US Réplica de Reseñas"
que no dependen de la interfaz.
"""

import itertools

from app.core.security import hash_password
from app.models.replica_resena import ReplicaResena
from app.models.usuario import RolUsuario, Usuario
from app.tests.conftest import CRITERIOS_VALIDOS, PASSWORD, crear_oferente_completo, registrar_y_loguear

_correos = itertools.count(1)
TEXTO_OK = "Muchas gracias por tu comentario, fue un gusto trabajar con vos."


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _nuevo_correo():
    return f"cliente.rep.{next(_correos)}@test.com"


def _dejar_resena_publicada(client, oferente_id, token_dueno):
    """Genera el enlace, deja la reseña y el dueño la acepta. Devuelve su id."""
    enlace = client.post(
        f"/api/v1/oferentes/{oferente_id}/solicitudes-resena",
        json={"nombre_cliente": "Juan Cliente", "email_cliente": _nuevo_correo()},
    ).json()
    client.post("/api/v1/resenas", json={"codigo_unico": enlace["codigo_unico"], "calificaciones_comentarios": CRITERIOS_VALIDOS})
    pendiente = client.get("/api/v1/notificaciones", headers=_auth(token_dueno)).json()[0]
    moderada = client.patch(f"/api/v1/resenas/{pendiente['resena_id']}/moderar", json={"aceptar": True}, headers=_auth(token_dueno))
    assert moderada.status_code == 200, moderada.text
    return pendiente["resena_id"]


def _responder(client, resena_id, token, texto=TEXTO_OK):
    return client.post(f"/api/v1/resenas/{resena_id}/replica", json={"texto": texto}, headers=_auth(token))


def _resena_en_listado(client, oferente_id, resena_id, token=None):
    headers = _auth(token) if token else {}
    items = client.get(f"/api/v1/oferentes/{oferente_id}/resenas", headers=headers).json()["items"]
    return next(item for item in items if item["id_resena"] == resena_id)


# --- CA01: visualización de la opción de responder --------------------------


def test_ca01_el_dueno_ve_responder_solo_en_resenas_sin_replica(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca01@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    assert _resena_en_listado(client, oferente_id, resena_id, token)["puede_responder"] is True

    _responder(client, resena_id, token)

    assert _resena_en_listado(client, oferente_id, resena_id, token)["puede_responder"] is False


def test_ca01_resena_pendiente_no_se_puede_responder(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca01.pend@test.com")
    enlace = client.post(
        f"/api/v1/oferentes/{oferente_id}/solicitudes-resena",
        json={"nombre_cliente": "Juan Cliente", "email_cliente": _nuevo_correo()},
    ).json()
    client.post("/api/v1/resenas", json={"codigo_unico": enlace["codigo_unico"], "calificaciones_comentarios": CRITERIOS_VALIDOS})
    pendiente = client.get("/api/v1/notificaciones", headers=_auth(token)).json()[0]

    respuesta = _responder(client, pendiente["resena_id"], token)

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "resena_no_publicada"


# --- CA02: réplica del profesional ------------------------------------------


def test_ca02_responder_registra_la_replica_y_la_muestra_debajo_de_la_resena(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca02@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    respuesta = _responder(client, resena_id, token)

    assert respuesta.status_code == 201
    assert respuesta.json()["texto"] == TEXTO_OK
    resena = _resena_en_listado(client, oferente_id, resena_id)
    assert resena["replica"]["texto"] == TEXTO_OK
    assert resena["replica"]["fecha_creacion"]


def test_ca02_admite_el_largo_maximo_de_500(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca02.largo@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    texto = "a" * 500

    respuesta = _responder(client, resena_id, token, texto=texto)

    assert respuesta.status_code == 201
    assert _resena_en_listado(client, oferente_id, resena_id)["replica"]["texto"] == texto


def test_ca02_guarda_tildes_enie_y_signos_sin_alterarlos(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca02.tildes@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    texto = "¡Gracias! Atendí tu consulta el 15/10 a las 18:30 hs. Saludos, ñandú."

    _responder(client, resena_id, token, texto=texto)

    assert _resena_en_listado(client, oferente_id, resena_id)["replica"]["texto"] == texto


def test_ca02_la_replica_no_modifica_la_resena_del_cliente(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca02.intacta@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    antes = _resena_en_listado(client, oferente_id, resena_id)

    _responder(client, resena_id, token)

    despues = _resena_en_listado(client, oferente_id, resena_id)
    for campo in ("cliente", "puntuacion_global", "criterios", "comentario", "fecha_creacion"):
        assert despues[campo] == antes[campo]


def test_ca02_la_replica_persiste_al_volver_a_leer(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca02.persiste@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    _responder(client, resena_id, token)

    otro_listado = client.get(f"/api/v1/oferentes/{oferente_id}/resenas").json()["items"]

    assert any(item["replica"] is not None for item in otro_listado)


# --- CA03: réplica única por reseña ------------------------------------------


def test_ca03_responder_dos_veces_con_otro_texto_da_409(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca03@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    _responder(client, resena_id, token)

    respuesta = _responder(client, resena_id, token, texto="Otra respuesta distinta")

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "replica_existente"
    assert _resena_en_listado(client, oferente_id, resena_id)["replica"]["texto"] == TEXTO_OK


def test_ca03_doble_envio_con_el_mismo_texto_no_duplica(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca03.doble@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    primera = _responder(client, resena_id, token)
    segunda = _responder(client, resena_id, token)

    assert primera.status_code == 201
    assert segunda.status_code == 200
    assert db_session.query(ReplicaResena).filter(ReplicaResena.resena_id == resena_id).count() == 1


def test_ca03_no_hay_edicion_ni_borrado(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca03.nodit@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    _responder(client, resena_id, token)

    editar = client.put(f"/api/v1/resenas/{resena_id}/replica", json={"texto": "x"}, headers=_auth(token))
    borrar = client.delete(f"/api/v1/resenas/{resena_id}/replica", headers=_auth(token))

    assert editar.status_code == 405
    assert borrar.status_code == 405


# --- CA04: restricción a otros usuarios -------------------------------------


def test_ca04_visitante_no_ve_responder_y_no_puede_guardar(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca04.anon@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    assert _resena_en_listado(client, oferente_id, resena_id)["puede_responder"] is False

    respuesta = client.post(f"/api/v1/resenas/{resena_id}/replica", json={"texto": TEXTO_OK})

    assert respuesta.status_code == 401
    assert db_session.query(ReplicaResena).count() == 0


def test_ca04_otro_profesional_no_ve_responder_ni_puede_guardar(client, db_session):
    token_dueno, oferente_id = crear_oferente_completo(client, db_session, email="ca04.dueno@test.com", dni_cuit="20-30111222-0")
    token_otro, _ = crear_oferente_completo(client, db_session, email="ca04.otro@test.com", dni_cuit="20-30111223-9")
    resena_id = _dejar_resena_publicada(client, oferente_id, token_dueno)

    assert _resena_en_listado(client, oferente_id, resena_id, token_otro)["puede_responder"] is False

    respuesta = _responder(client, resena_id, token_otro)

    assert respuesta.status_code == 403
    assert db_session.query(ReplicaResena).count() == 0


def test_ca04_cliente_sin_cuenta_con_token_de_otro_no_puede_responder(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca04.cli@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    token_cliente = registrar_y_loguear(client, "cliente.sin.perfil@test.com")

    respuesta = _responder(client, resena_id, token_cliente)

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"]["codigo"] == "registro_incompleto"


def test_ca04_administrador_no_puede_responder(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca04.adm.dueno@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    admin = Usuario(email="ca04.admin@test.com", password_hash=hash_password(PASSWORD), rol=RolUsuario.ADMINISTRADOR)
    db_session.add(admin)
    db_session.commit()
    token_admin = client.post("/api/v1/auth/login", json={"email": "ca04.admin@test.com", "password": PASSWORD}).json()["access_token"]

    respuesta = _responder(client, resena_id, token_admin)

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"]["codigo"] == "rol_invalido"


def test_ca04_token_vencido_en_el_listado_se_trata_como_anonimo(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca04.vencido@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    respuesta = client.get(f"/api/v1/oferentes/{oferente_id}/resenas", headers=_auth("token.invalido.xyz"))

    assert respuesta.status_code == 200
    assert _resena_en_listado(client, oferente_id, resena_id)["puede_responder"] is False


# --- CA05: validación del comentario ----------------------------------------


def test_ca05_comentario_vacio_o_con_solo_espacios_da_422(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca05.vacio@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    for texto in ("", "     "):
        respuesta = _responder(client, resena_id, token, texto=texto)
        assert respuesta.status_code == 422
        assert respuesta.json()["errores"] == [{"campo": "texto", "codigo": "comentario_requerido"}]

    assert db_session.query(ReplicaResena).count() == 0


def test_ca05_comentario_de_501_caracteres_da_422(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca05.largo@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)

    respuesta = _responder(client, resena_id, token, texto="a" * 501)

    assert respuesta.status_code == 422
    assert respuesta.json()["errores"] == [{"campo": "texto", "codigo": "comentario_demasiado_largo"}]
    assert db_session.query(ReplicaResena).count() == 0


def test_ca05_html_y_script_se_guardan_como_texto_plano(client, db_session):
    token, oferente_id = crear_oferente_completo(client, db_session, email="ca05.html@test.com")
    resena_id = _dejar_resena_publicada(client, oferente_id, token)
    texto = "<script>alert('x')</script> <b>Gracias</b>"

    respuesta = _responder(client, resena_id, token, texto=texto)

    assert respuesta.status_code == 201
    assert _resena_en_listado(client, oferente_id, resena_id)["replica"]["texto"] == texto


# --- Reseñas que no están publicadas o no existen ---------------------------


def test_resena_inexistente_da_404(client, db_session):
    token, _ = crear_oferente_completo(client, db_session, email="inexistente@test.com")

    respuesta = _responder(client, 999999, token)

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"]["codigo"] == "resena_no_encontrada"
