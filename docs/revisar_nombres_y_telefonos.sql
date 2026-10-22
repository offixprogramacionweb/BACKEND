-- Revisión manual después de correr la migración e8b4c2d91f07 (HU-04 / HU-06).
-- Corregir a mano en Supabase: nombre, apellido, característica o número.
-- La migración también imprime cada caso con prefijo "[revisar]" y el motivo.

-- 1) Profesionales: sin apellido (¿razón social?), nombre o apellido con más de
--    una palabra (puede ser correcto o un apellido compuesto mal partido) y
--    característica que no es 11 ni 351 (se adivinó con 4 dígitos).
SELECT id_oferente, nombre, apellido, telefono_codigo_area, telefono_numero
FROM offix.oferentes
WHERE apellido IS NULL
   OR nombre LIKE '% %'
   OR apellido LIKE '% %'
   OR telefono_codigo_area NOT IN ('11', '351')
ORDER BY id_oferente;

-- 2) Teléfonos de clientes con característica adivinada.
SELECT id_solicitud, telefono_cliente_codigo_area, telefono_cliente_numero
FROM offix.solicitudes_resena
WHERE telefono_cliente_codigo_area IS NOT NULL
  AND telefono_cliente_codigo_area NOT IN ('11', '351')
ORDER BY id_solicitud;
