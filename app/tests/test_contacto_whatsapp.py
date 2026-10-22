"""HU-06 — Contacto por WhatsApp desde el perfil del Profesional (CA01-CA03, T05, T06)."""

from urllib.parse import unquote

from app.models.oferente import Oferente
from app.tests.conftest import crear_oferente_completo


def _texto(url: str) -> str:
    return unquote(url.split("?text=", 1)[1])


def test_perfil_publico_trae_el_link_sin_iniciar_sesion(client, db_session):
    # T06: el perfil y el enlace son públicos, no hace falta token.
    _, oferente_id = crear_oferente_completo(client, db_session, email="wpp.publico@test.com", dni_cuit="20-30111222-0")

    respuesta = client.get(f"/api/v1/oferentes/{oferente_id}")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    # Formulario de registro: teléfono "3564-400000" -> 10 dígitos, prefijo de país 549.
    assert cuerpo["whatsapp_url"].startswith("https://wa.me/5493564400000?text=")
    assert _texto(cuerpo["whatsapp_url"]) == (
        f"Hola Oferente Prueba, vi tu perfil de {cuerpo['categoria']['nombre']} en OFFIX "
        "y necesito un presupuesto. ¿Estás disponible?"
    )


def test_cada_profesional_tiene_su_propio_numero(client, db_session):
    # T05: el link de cada tarjeta usa el número de ese Profesional, no el de otro.
    _, primero = crear_oferente_completo(client, db_session, email="wpp.uno@test.com", dni_cuit="20-30111222-0")
    _, segundo = crear_oferente_completo(client, db_session, email="wpp.dos@test.com", dni_cuit="20-30111223-9")
    db_session.get(Oferente, segundo).telefono_codigo_area = "3564"
    db_session.get(Oferente, segundo).telefono_numero = "400999"
    db_session.commit()

    url_primero = client.get(f"/api/v1/oferentes/{primero}").json()["whatsapp_url"]
    url_segundo = client.get(f"/api/v1/oferentes/{segundo}").json()["whatsapp_url"]

    assert url_primero.startswith("https://wa.me/5493564400000?")
    assert url_segundo.startswith("https://wa.me/5493564400999?")


def test_profesional_con_telefono_invalido_no_tiene_link(client, db_session):
    # CA03: el número guardado no tiene formato válido -> sin link.
    _, oferente_id = crear_oferente_completo(client, db_session, email="wpp.invalido@test.com", dni_cuit="20-30111224-7")
    perfil = db_session.get(Oferente, oferente_id)
    perfil.telefono_codigo_area, perfil.telefono_numero = "0351", "4400888"
    db_session.commit()

    cuerpo = client.get(f"/api/v1/oferentes/{oferente_id}").json()

    assert cuerpo["whatsapp_url"] is None
    assert (cuerpo["telefono_codigo_area"], cuerpo["telefono_numero"]) == ("0351", "4400888")


def test_directorio_trae_el_link_en_cada_tarjeta(client, db_session):
    _, oferente_id = crear_oferente_completo(client, db_session, email="wpp.directorio@test.com", dni_cuit="20-30111225-5")
    perfil = db_session.get(Oferente, oferente_id)
    perfil.telefono_codigo_area, perfil.telefono_numero = "0351", "4400888"
    db_session.commit()
    _, otro_id = crear_oferente_completo(client, db_session, email="wpp.directorio2@test.com", dni_cuit="20-30111226-3")

    tarjetas = {tarjeta["id_oferente"]: tarjeta for tarjeta in client.get("/api/v1/oferentes").json()["items"]}

    assert tarjetas[oferente_id]["whatsapp_url"] is None
    assert tarjetas[otro_id]["whatsapp_url"].startswith("https://wa.me/5493564400000?")
