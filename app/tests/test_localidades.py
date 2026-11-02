from sqlalchemy.exc import IntegrityError

from app.models.localidad import Localidad
from app.services.localidades import cargar_localidades, leer_localidades


def test_el_archivo_no_trae_pares_repetidos():
    pares = leer_localidades()

    assert len(pares) > 3000
    assert len(pares) == len(set(pares))
    assert ("Santa Fe", "Rosario") in pares


def test_cargar_localidades_es_idempotente(db_session):
    db_session.query(Localidad).delete()
    db_session.commit()

    primera = cargar_localidades(db_session)
    segunda = cargar_localidades(db_session)

    assert primera == len(leer_localidades())
    assert segunda == 0
    assert db_session.query(Localidad).count() == primera


def test_no_se_repite_la_ciudad_dentro_de_una_provincia(db_session):
    db_session.add(Localidad(provincia="Córdoba", ciudad="Villa Allende"))
    db_session.commit()
    db_session.add(Localidad(provincia="Córdoba", ciudad="Villa Allende"))

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("debería haber rechazado el duplicado")
