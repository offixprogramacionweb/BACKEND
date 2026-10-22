"""Textos de WhatsApp y armado de los links `wa.me`.

Hay dos mensajes:

- **Invitación a reseña (HU-01):** uno solo para los dos canales (lo definió
  QA): el mismo texto viaja url-encodeado dentro de `wa.me/<número>?text=` y
  dentro del cuerpo HTML del correo.
- **Contacto desde el perfil (HU-06, caso CA08):** el cliente abre el chat con
  el Profesional y el mensaje queda precargado, editable y sin enviar.
"""

import re
from urllib.parse import quote

from app.core.config import settings

# 10 dígitos en total: 2 a 4 de código de área + 6 a 8 de línea. Se acepta un
# guión como separador. Sin 0 inicial, sin 15 y sin +54: eso lo pone el backend.
TELEFONO_RE = re.compile(r"^\d{2,4}-?\d{6,8}$")

PLANTILLA_CONTACTO = "Hola {nombre}, vi tu perfil de {oficio} en OFFIX y necesito un presupuesto. ¿Estás disponible?"
PLANTILLA_CONTACTO_SIN_OFICIO = "Hola {nombre}, vi tu perfil en OFFIX y necesito un presupuesto. ¿Estás disponible?"

PLANTILLA_INVITACION = """¡Hola!
Gracias por confiar en {nombre_profesional} a través de Offix.
Tu opinión nos ayuda a seguir mejorando y a que otros usuarios elijan mejor.
¿Nos dejás una reseña sobre tu experiencia con {nombre_profesional}?
Calificá tu experiencia acá: {link_resena}
Solo te va a tomar un minuto. ¡Gracias por ser parte de Offix!"""


# Teléfono partido (HU-04): característica de 2 a 4 dígitos sin 0 inicial (11,
# 351, 3564...), y número de 6 a 8 dígitos. Entre los dos tienen que sumar 10.
CODIGO_AREA_RE = re.compile(r"[1-9]\d{1,3}")
NUMERO_LINEA_RE = re.compile(r"\d{6,8}")


def codigo_area_es_valido(codigo: str) -> bool:
    return CODIGO_AREA_RE.fullmatch(codigo) is not None


def numero_linea_es_valido(numero: str) -> bool:
    return NUMERO_LINEA_RE.fullmatch(numero) is not None


def telefono_partes_son_validas(codigo: str, numero: str) -> bool:
    return codigo_area_es_valido(codigo) and numero_linea_es_valido(numero) and len(codigo) + len(numero) == 10


def telefono_es_valido(telefono: str) -> bool:
    if not TELEFONO_RE.match(telefono):
        return False
    digitos = solo_digitos(telefono)
    # El 0 inicial (código de área de la larga distancia) no va: "Sin 0, 15 o +54 al inicio".
    return len(digitos) == 10 and not digitos.startswith("0")


def solo_digitos(telefono: str) -> str:
    return telefono.replace("-", "").strip()


def normalizar_telefono(telefono: str) -> str:
    """Lo que se guarda: los 10 dígitos, sin el guión."""
    return solo_digitos(telefono)


def telefono_internacional(telefono: str) -> str:
    """Lo que exige `wa.me`: prefijo de país + los 10 dígitos, sin símbolos."""
    return f"{settings.whatsapp_prefijo_pais}{normalizar_telefono(telefono)}"


def texto_invitacion(nombre_profesional: str, link_resena: str) -> str:
    return PLANTILLA_INVITACION.format(nombre_profesional=nombre_profesional, link_resena=link_resena)


def armar_whatsapp_contacto(telefono: str | None, nombre: str, oficio: str | None) -> str | None:
    """HU-06 — Link `wa.me` con el mensaje de contacto ya cargado (CA02).

    Devuelve `None` si el teléfono no tiene un formato válido: el frontend no
    abre WhatsApp y muestra el error (CA03). Sin oficio (perfiles sin rubro) se
    usa la plantilla sin el oficio.
    """
    if not telefono or not telefono_es_valido(telefono):
        return None
    if oficio:
        texto = PLANTILLA_CONTACTO.format(nombre=nombre, oficio=oficio)
    else:
        texto = PLANTILLA_CONTACTO_SIN_OFICIO.format(nombre=nombre)
    return f"https://wa.me/{telefono_internacional(telefono)}?text={quote(texto)}"


def armar_whatsapp_url(telefono: str, nombre_profesional: str, link_resena: str) -> str:
    """Link que abre el chat con el mensaje precargado. El envío lo dispara una
    persona presionando "enviar": no hay servicio de mensajería saliente."""
    texto = texto_invitacion(nombre_profesional, link_resena)
    return f"https://wa.me/{telefono_internacional(telefono)}?text={quote(texto)}"
