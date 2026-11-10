"""HU-07 — Administración y moderación del Usuario Sistema.

Cubre los CA02 a CA08 de la HU y los casos de la hoja "US Admin" que no dependen
de la interfaz. Los tests del login con Google (CA01) están al final.
"""

import itertools
from datetime import datetime, timezone

from app.core.config import settings
from app.models.auditoria_moderacion import AuditoriaModeracion
from app.models.matricula import Matricula, OrigenMatricula
from app.models.notificacion import Notificacion, TipoNotificacion
from app.models.trabajo_realizado import TrabajoRealizado
from app.models.usuario import EstadoCuenta, RolUsuario, Usuario
from app.services.auth0 import Auth0ServiceFake, PerfilGoogle
from app.core.security import hash_password
from app.tests.conftest import CRITERIOS_VALIDOS, PASSWORD, crear_admin_db, crear_oferente_completo, registrar_y_loguear

_correos = itertools.count(1)
_dnis = itertools.count(1)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _token_admin(client, db_session, email="admin@test.com"):
    crear_admin_db(db_session, email=email)
    return client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]


def _nuevo_oferente(client, db_session, nombre_prefijo="Oferente"):
    n = next(_dnis)
    email = f"{nombre_prefijo.lower()}{n}@test.com"
    token, oferente_id = crear_oferente_completo(client, db_session, email=email, dni_cuit=str(30000000 + n))
    return token, oferente_id


def _resena_pendiente(client, oferente_id):
    """Un cliente deja una reseña con un correo nuevo. Devuelve su id."""
    enlace = client.post(
        f"/api/v1/oferentes/{oferente_id}/solicitudes-resena",
        json={"nombre_cliente": "Juan Cliente", "email_cliente": f"cliente.mod.{next(_correos)}@test.com"},
    ).json()
    respuesta = client.post("/api/v1/resenas", json={"codigo_unico": enlace["codigo_unico"], "calificaciones_comentarios": CRITERIOS_VALIDOS})
    return respuesta.json()["id_resena"]


def _moderar(client, token, resena_id, aceptar):
    return client.patch(f"/api/v1/resenas/{resena_id}/moderar", json={"aceptar": aceptar}, headers=_auth(token))


def _resena_publicada(client, oferente_id, token):
    resena_id = _resena_pendiente(client, oferente_id)
    _moderar(client, token, resena_id, aceptar=True)
    return resena_id


def _fila(client, token_admin, oferente_id):
    pagina = client.get("/api/v1/admin/oferentes?por_pagina=50", headers=_auth(token_admin)).json()
    return next(item for item in pagina["items"] if item["id_oferente"] == oferente_id)


# --- CA01: acceso del administrador -----------------------------------------


def test_ca01_profesional_no_puede_acceder_a_la_grilla(client, db_session):
    token, _ = _nuevo_oferente(client, db_session)

    respuesta = client.get("/api/v1/admin/oferentes", headers=_auth(token))

    assert respuesta.status_code == 403


def test_ca01_sin_token_no_hay_grilla(client):
    assert client.get("/api/v1/admin/oferentes").status_code == 401


# --- CA02: grilla de oferentes ----------------------------------------------


def test_ca02_grilla_con_contadores_de_activos_y_suspendidos(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, activo_1 = _nuevo_oferente(client, db_session)
    _, activo_2 = _nuevo_oferente(client, db_session)
    _, suspendido = _nuevo_oferente(client, db_session)
    client.post(f"/api/v1/admin/oferentes/{suspendido}/suspender", headers=_auth(token_admin))

    respuesta = client.get("/api/v1/admin/oferentes?por_pagina=50", headers=_auth(token_admin))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["contadores"] == {"activos": 2, "suspendidos": 1}
    estados = {item["id_oferente"]: item["estado"] for item in cuerpo["items"]}
    assert estados[activo_1] == "Activo"
    assert estados[activo_2] == "Activo"
    assert estados[suspendido] == "Suspendido"


def test_ca02_filtros_activos_y_suspendidos_no_cambian_los_contadores(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, activo = _nuevo_oferente(client, db_session)
    _, suspendido = _nuevo_oferente(client, db_session)
    client.post(f"/api/v1/admin/oferentes/{suspendido}/suspender", headers=_auth(token_admin))

    activos = client.get("/api/v1/admin/oferentes?estado=activos&por_pagina=50", headers=_auth(token_admin)).json()
    suspendidos = client.get("/api/v1/admin/oferentes?estado=suspendidos&por_pagina=50", headers=_auth(token_admin)).json()

    assert [item["id_oferente"] for item in activos["items"]] and all(item["estado"] == "Activo" for item in activos["items"])
    assert [item["id_oferente"] for item in suspendidos["items"]] == [suspendido]
    assert activos["contadores"] == suspendidos["contadores"]


def test_ca02_busqueda_por_nombre_y_sin_resultados(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    client.put("/api/v1/oferentes/me", json={"nombre": "Sergio Aguirre"}, headers=_auth(token))

    encontrado = client.get("/api/v1/admin/oferentes?q=Aguirre", headers=_auth(token_admin)).json()
    vacio = client.get("/api/v1/admin/oferentes?q=zzzzzz", headers=_auth(token_admin)).json()

    assert [item["id_oferente"] for item in encontrado["items"]] == [oferente_id]
    assert vacio["items"] == []
    assert vacio["total"] == 0


def test_ca02_la_grilla_no_incluye_a_quien_no_completo_el_registro(client, db_session):
    token_admin = _token_admin(client, db_session)
    registrar_y_loguear(client, "sin.registro@test.com")

    cuerpo = client.get("/api/v1/admin/oferentes?por_pagina=50", headers=_auth(token_admin)).json()

    assert "sin.registro@test.com" not in str(cuerpo)
    assert cuerpo["contadores"]["activos"] + cuerpo["contadores"]["suspendidos"] == cuerpo["total"]


def test_ca02_por_pagina_invalido_da_422(client, db_session):
    token_admin = _token_admin(client, db_session)

    assert client.get("/api/v1/admin/oferentes?por_pagina=7", headers=_auth(token_admin)).status_code == 422


# --- CA03: validación de matrícula por el administrador ----------------------


def test_ca03_validar_matricula_la_marca_verificada_sin_padron(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)

    respuesta = client.post(
        f"/api/v1/admin/oferentes/{oferente_id}/matriculas",
        json={"tipo_profesional": "Gasista", "numero_matricula": "1000008919"},
        headers=_auth(token_admin),
    )

    assert respuesta.status_code == 200
    fila = respuesta.json()
    assert fila["matricula_verificada"] is True
    assert fila["matriculas"] == [{"tipo_profesional": "Gasista", "numero_matricula": "1000008919"}]
    matricula = db_session.query(Matricula).filter(Matricula.oferente_id == oferente_id).one()
    assert matricula.origen == OrigenMatricula.ADMINISTRADOR
    assert matricula.categoria is None and matricula.fecha_vencimiento is None


def test_ca03_la_matricula_verificada_se_refleja_en_el_perfil_publico(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    client.post(
        f"/api/v1/admin/oferentes/{oferente_id}/matriculas",
        json={"tipo_profesional": "Aire acondicionado", "numero_matricula": "12345678"},
        headers=_auth(token_admin),
    )

    perfil = client.get(f"/api/v1/oferentes/{oferente_id}").json()

    assert perfil["tiene_matricula_validada"] is True


def test_ca03_formato_invalido_da_422_con_el_codigo_de_hu02(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)

    respuesta = client.post(
        f"/api/v1/admin/oferentes/{oferente_id}/matriculas",
        json={"tipo_profesional": "Aire acondicionado", "numero_matricula": "MP-12345"},
        headers=_auth(token_admin),
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["errores"] == [{"campo": "numero_matricula", "codigo": "solo_digitos"}]


def test_ca03_matricula_de_otro_profesional_da_409(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, primero = _nuevo_oferente(client, db_session)
    _, segundo = _nuevo_oferente(client, db_session)
    client.post(
        f"/api/v1/admin/oferentes/{primero}/matriculas",
        json={"tipo_profesional": "Gasista", "numero_matricula": "1000004305"},
        headers=_auth(token_admin),
    )

    respuesta = client.post(
        f"/api/v1/admin/oferentes/{segundo}/matriculas",
        json={"tipo_profesional": "Gasista", "numero_matricula": "1000004305"},
        headers=_auth(token_admin),
    )

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["codigo"] == "matricula_de_otro_oferente"


# --- CA06: suspensión y alta de la cuenta -----------------------------------


def test_ca06_suspender_cambia_el_estado_y_audita(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)

    respuesta = client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "Suspendido"
    auditoria = client.get(f"/api/v1/admin/oferentes/{oferente_id}/auditoria", headers=_auth(token_admin)).json()
    assert [entrada["accion"] for entrada in auditoria] == ["Suspension"]


def test_ca06_suspender_dos_veces_no_duplica_la_auditoria(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)

    client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))
    segunda = client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))

    assert segunda.status_code == 200
    assert db_session.query(AuditoriaModeracion).filter(AuditoriaModeracion.oferente_id == oferente_id).count() == 1


def test_ca06_dar_de_alta_reactiva_y_avisa_al_administrador(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))

    respuesta = client.post(f"/api/v1/admin/oferentes/{oferente_id}/dar-de-alta", headers=_auth(token_admin))

    assert respuesta.json()["estado"] == "Activo"
    avisos = db_session.query(Notificacion).filter(Notificacion.tipo == TipoNotificacion.OFERENTE_REACTIVADO).all()
    assert len(avisos) == 1
    assert avisos[0].oferente_id == oferente_id


def test_ca06_el_suspendido_no_puede_iniciar_sesion_con_el_mensaje_de_qa(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session, nombre_prefijo="Bloq")
    email = db_session.get(Usuario, oferente_id).email
    client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))

    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    token_viejo = client.get("/api/v1/auth/me", headers=_auth(token))

    assert login.status_code == 403
    assert login.json()["detail"] == {
        "codigo": "cuenta_suspendida",
        "mensaje": "Su cuenta se encuentra suspendida, comunicarse con Asesoría.",
    }
    assert token_viejo.status_code == 401
    assert token_viejo.json()["detail"]["codigo"] == "cuenta_suspendida"


def test_ca06_el_reactivado_vuelve_a_iniciar_sesion(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session, nombre_prefijo="Vuelve")
    email = db_session.get(Usuario, oferente_id).email
    client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))
    client.post(f"/api/v1/admin/oferentes/{oferente_id}/dar-de-alta", headers=_auth(token_admin))

    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})

    assert login.status_code == 200


def test_ca06_suspendido_no_tiene_perfil_publico_ni_acepta_reseñas(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    client.post(f"/api/v1/admin/oferentes/{oferente_id}/suspender", headers=_auth(token_admin))

    perfil_anonimo = client.get(f"/api/v1/oferentes/{oferente_id}")
    perfil_admin = client.get(f"/api/v1/oferentes/{oferente_id}", headers=_auth(token_admin))
    solicitud = client.post(
        f"/api/v1/oferentes/{oferente_id}/solicitudes-resena",
        json={"nombre_cliente": "Juan", "email_cliente": "nueva.resena@test.com"},
    )

    assert perfil_anonimo.status_code == 404
    assert perfil_admin.status_code == 200
    assert solicitud.status_code == 404


# --- CA04 y CA05: reseñas y trabajos ----------------------------------------


def test_ca04_ver_resenas_incluye_rechazadas_y_dadas_de_baja(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    publicada = _resena_publicada(client, oferente_id, token)
    rechazada = _resena_pendiente(client, oferente_id)
    _moderar(client, token, rechazada, aceptar=False)

    todas = client.get(f"/api/v1/admin/oferentes/{oferente_id}/resenas", headers=_auth(token_admin)).json()
    rechazadas = client.get(f"/api/v1/admin/oferentes/{oferente_id}/resenas?filtro=rechazadas", headers=_auth(token_admin)).json()

    estados = {item["id_resena"]: item["estado"] for item in todas}
    assert estados == {publicada: "Aceptada", rechazada: "Rechazada"}
    assert [item["id_resena"] for item in rechazadas] == [rechazada]


def test_ca05_dar_de_baja_oculta_la_resena_y_recalcula_metricas(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    resena = _resena_publicada(client, oferente_id, token)
    otra = _resena_publicada(client, oferente_id, token)
    antes = client.get(f"/api/v1/oferentes/{oferente_id}").json()["cantidad_resenas"]

    respuesta = client.post(f"/api/v1/admin/resenas/{resena}/dar-de-baja", json={"motivo": "lenguaje agresivo"}, headers=_auth(token_admin))

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resena"]["estado"] == "Dada_de_baja"
    assert cuerpo["resena"]["puede_reactivar"] is True
    assert cuerpo["oferente"]["cantidad_resenas"] == antes - 1
    publico = client.get(f"/api/v1/oferentes/{oferente_id}/resenas").json()["items"]
    assert [item["id_resena"] for item in publico] == [otra]
    assert client.get(f"/api/v1/oferentes/{oferente_id}").json()["cantidad_resenas"] == antes - 1


def test_ca05_reactivar_vuelve_a_mostrar_la_resena(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    resena = _resena_publicada(client, oferente_id, token)
    client.post(f"/api/v1/admin/resenas/{resena}/dar-de-baja", headers=_auth(token_admin))

    respuesta = client.post(f"/api/v1/admin/resenas/{resena}/reactivar", headers=_auth(token_admin))

    assert respuesta.json()["resena"]["estado"] == "Aceptada"
    publico = client.get(f"/api/v1/oferentes/{oferente_id}/resenas").json()["items"]
    assert [item["id_resena"] for item in publico] == [resena]


def test_ca05_solo_se_dan_de_baja_opiniones_publicadas(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    rechazada = _resena_pendiente(client, oferente_id)
    _moderar(client, token, rechazada, aceptar=False)

    respuesta = client.post(f"/api/v1/admin/resenas/{rechazada}/dar-de-baja", headers=_auth(token_admin))

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["codigo"] == "resena_no_aceptada"


def test_ca05_la_resena_dada_de_baja_oculta_su_replica(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    resena = _resena_publicada(client, oferente_id, token)
    client.post(f"/api/v1/resenas/{resena}/replica", json={"texto": "Gracias por la reseña"}, headers=_auth(token))

    client.post(f"/api/v1/admin/resenas/{resena}/dar-de-baja", headers=_auth(token_admin))

    assert client.get(f"/api/v1/oferentes/{oferente_id}/resenas").json()["items"] == []


def test_ca05_dar_de_baja_un_trabajo_lo_oculta_y_reactivarlo_lo_devuelve(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    trabajo = TrabajoRealizado(oferente_id=oferente_id, titulo="Instalación", descripcion="Instalación de un calefón")
    db_session.add(trabajo)
    db_session.commit()

    baja = client.post(f"/api/v1/admin/trabajos/{trabajo.id_trabajo}/dar-de-baja", json={"motivo": "no corresponde"}, headers=_auth(token_admin))
    publico_tras_baja = client.get(f"/api/v1/oferentes/{oferente_id}/trabajos").json()
    reactivacion = client.post(f"/api/v1/admin/trabajos/{trabajo.id_trabajo}/reactivar", headers=_auth(token_admin))
    publico_tras_reactivar = client.get(f"/api/v1/oferentes/{oferente_id}/trabajos").json()

    assert baja.json()["trabajo"]["estado"] == "Dado_de_baja"
    assert publico_tras_baja == []
    assert reactivacion.json()["trabajo"]["estado"] == "Activo"
    assert len(publico_tras_reactivar) == 1


def test_ca05_el_trabajo_dado_de_baja_no_cuenta_en_metricas(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    trabajo = TrabajoRealizado(oferente_id=oferente_id, titulo="Reparación", descripcion="Reparación de canilla")
    db_session.add(trabajo)
    db_session.commit()
    antes = client.get(f"/api/v1/oferentes/{oferente_id}").json()["cantidad_trabajos"]

    client.post(f"/api/v1/admin/trabajos/{trabajo.id_trabajo}/dar-de-baja", headers=_auth(token_admin))

    assert client.get(f"/api/v1/oferentes/{oferente_id}").json()["cantidad_trabajos"] == antes - 1


def test_ca04_listado_de_trabajos_muestra_el_estado(client, db_session):
    token_admin = _token_admin(client, db_session)
    _, oferente_id = _nuevo_oferente(client, db_session)
    trabajo = TrabajoRealizado(oferente_id=oferente_id, titulo="Pintura", descripcion="Pintura de un living")
    db_session.add(trabajo)
    db_session.commit()
    client.post(f"/api/v1/admin/trabajos/{trabajo.id_trabajo}/dar-de-baja", headers=_auth(token_admin))

    listado = client.get(f"/api/v1/admin/oferentes/{oferente_id}/trabajos", headers=_auth(token_admin)).json()

    assert [(item["titulo"], item["estado"]) for item in listado] == [("Pintura", "Dado_de_baja")]


# --- CA08: campana de rechazos reiterados -----------------------------------


def _rechazar(client, oferente_id, token, cantidad):
    for _ in range(cantidad):
        _moderar(client, token, _resena_pendiente(client, oferente_id), aceptar=False)


def test_ca08_con_4_rechazos_no_hay_notificacion(client, db_session):
    _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)

    _rechazar(client, oferente_id, token, 4)

    assert db_session.query(Notificacion).filter(Notificacion.tipo == TipoNotificacion.RECHAZOS_REITERADOS).count() == 0


def test_ca08_con_5_rechazos_avisa_a_cada_administrador_una_sola_vez(client, db_session):
    _token_admin(client, db_session, email="admin.uno@test.com")
    _token_admin(client, db_session, email="admin.dos@test.com")
    token, oferente_id = _nuevo_oferente(client, db_session)

    _rechazar(client, oferente_id, token, 5)
    _rechazar(client, oferente_id, token, 1)

    avisos = db_session.query(Notificacion).filter(Notificacion.tipo == TipoNotificacion.RECHAZOS_REITERADOS).all()
    assert len(avisos) == 2
    assert all(aviso.oferente_id == oferente_id for aviso in avisos)
    assert all(aviso.requiere_accion is False for aviso in avisos)


def test_ca08_la_notificacion_se_vuelve_a_crear_si_el_admin_la_descarto(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    _rechazar(client, oferente_id, token, 5)
    aviso = db_session.query(Notificacion).filter(Notificacion.tipo == TipoNotificacion.RECHAZOS_REITERADOS).one()
    client.patch(f"/api/v1/notificaciones/{aviso.id_notificacion}/leer", headers=_auth(token_admin))

    _rechazar(client, oferente_id, token, 1)

    assert db_session.query(Notificacion).filter(Notificacion.tipo == TipoNotificacion.RECHAZOS_REITERADOS).count() == 2


def test_ca08_la_campana_del_admin_lista_el_aviso_con_su_profesional(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    _rechazar(client, oferente_id, token, 5)

    pendientes = client.get("/api/v1/notificaciones?solo_pendientes=true", headers=_auth(token_admin)).json()

    avisos = [n for n in pendientes if n["tipo"] == "Rechazos_Reiterados"]
    assert len(avisos) == 1
    assert avisos[0]["oferente_id"] == oferente_id
    assert "rechazó 5 o más reseñas" in avisos[0]["mensaje"]


# --- Auditoría --------------------------------------------------------------


def test_auditoria_registra_la_moderacion_en_orden(client, db_session):
    token_admin = _token_admin(client, db_session)
    token, oferente_id = _nuevo_oferente(client, db_session)
    resena = _resena_publicada(client, oferente_id, token)
    client.post(f"/api/v1/admin/resenas/{resena}/dar-de-baja", json={"motivo": "datos personales"}, headers=_auth(token_admin))
    client.post(f"/api/v1/admin/resenas/{resena}/reactivar", headers=_auth(token_admin))

    auditoria = client.get(f"/api/v1/admin/oferentes/{oferente_id}/auditoria", headers=_auth(token_admin)).json()

    assert [entrada["accion"] for entrada in auditoria] == ["Reactivacion_Resena", "Baja_Resena"]
    assert auditoria[1]["detalle"] == "datos personales"
    assert auditoria[1]["resena_id"] == resena


# --- CA01 (Google): los correos de ADMIN_EMAILS entran como Administrador ----


def _callback_google(client, _email):
    login = client.get("/api/v1/auth/google/login", follow_redirects=False)
    state = login.cookies.get("oauth_state")
    return client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)


def test_ca01_correo_de_admin_emails_entra_como_administrador(client, db_session, monkeypatch, auth0):
    monkeypatch.setattr(settings, "admin_emails", "jefe.offix@gmail.com, otro@gmail.com")
    auth0.perfil = PerfilGoogle(email="jefe.offix@gmail.com", nombre="Jefe")

    _callback_google(client, "jefe.offix@gmail.com")

    usuario = db_session.query(Usuario).filter(Usuario.email == "jefe.offix@gmail.com").one()
    assert usuario.rol == RolUsuario.ADMINISTRADOR


def test_ca01_correo_comun_sigue_siendo_oferente(client, db_session, monkeypatch, auth0):
    monkeypatch.setattr(settings, "admin_emails", "jefe.offix@gmail.com")
    auth0.perfil = PerfilGoogle(email="comun@gmail.com", nombre="Comun")

    _callback_google(client, "comun@gmail.com")

    usuario = db_session.query(Usuario).filter(Usuario.email == "comun@gmail.com").one()
    assert usuario.rol == RolUsuario.OFERENTE


def test_ca01_cuenta_suspendida_por_google_redirige_con_motivo(client, db_session, monkeypatch, auth0):
    auth0.perfil = PerfilGoogle(email="suspendido.google@test.com", nombre="Suspendido")
    _callback_google(client, "x")
    usuario = db_session.query(Usuario).filter(Usuario.email == "suspendido.google@test.com").one()
    usuario.estado_cuenta = EstadoCuenta.SUSPENDIDA
    db_session.commit()

    respuesta = _callback_google(client, "x")

    assert "motivo=cuenta_suspendida" in respuesta.headers["location"]
