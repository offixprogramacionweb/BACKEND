# HU-05 — Búsqueda de Profesionales: guía de conexión para el frontend

> **2026-10-25.** Cómo conectar la página de inicio, el directorio, los filtros y
> la tarjeta del profesional con el backend.
>
> El detalle de cada endpoint (todos los campos y tipos) está en Swagger
> (`/docs`) y en [`openapi.json`](openapi.json).

## Resumen

| Qué                              | Endpoint                                                      | Sesión |
| -------------------------------- | ------------------------------------------------------------- | ------ |
| Listado y filtros del directorio | `GET /api/v1/oferentes`                                       | No     |
| Opciones de "Categoría"          | `GET /api/v1/categorias`                                      | No     |
| Opciones de "Zona" (provincia)   | `GET /api/v1/catalogos/provincias`                            | No     |
| Opciones de "Zona" (localidad)   | `GET /api/v1/catalogos/provincias/{id}/localidades`           | No     |
| Ver perfil                       | `GET /api/v1/oferentes/{id}`                                  | No     |
| Contactar por WhatsApp           | El campo `whatsapp_url` de cada profesional (no hay endpoint) | No     |

Nada de esta HU requiere token: el directorio, el perfil y el contacto son públicos (CA09).

### ⚠️ Cambios que rompen algo

- **Se eliminaron `latitud`, `longitud` y `radio_cobertura_km`** del perfil. Si el
  frontend los lee, ahora llegan `undefined`. Si los manda en `PUT /oferentes/me`,
  la respuesta es **422 `campo_no_permitido`**. En su lugar está la **localidad**
  (sección 5).
- `q` ahora busca en más campos que nombre y apellido (sección 2). Esto no
  rompe nada, pero cambia los resultados.

---

## 1. Directorio: `GET /api/v1/oferentes` (CA04–CA06)

### Parámetros

Todos son opcionales y **se combinan entre sí** (AND). Sin parámetros se traen todos
los profesionales activos.

| Control de la pantalla     | Parámetro      | Valor                                          | Por defecto ("Todos") |
| -------------------------- | -------------- | ---------------------------------------------- | --------------------- |
| Buscador                   | `q`            | Texto libre                                    | No enviarlo           |
| Categoría                  | `categoria_id` | `id_categoria` (número)                        | No enviarlo           |
| Zona: provincia            | `provincia_id` | `id` de la provincia (texto, ej. `"14"`)       | No enviarlo           |
| Zona: localidad            | `localidad_id` | `id` de la localidad (texto, ej. `"14140360"`) | No enviarlo           |
| Solo Matriculados          | `matriculado`  | `true`                                         | `false` / no enviarlo |
| Disponible Hoy / Urgencias | `urgencias`    | `true`                                         | `false` / no enviarlo |
| Paginador                  | `pagina`       | Desde 1                                        | `1`                   |
| Tamaño de página           | `por_pagina`   | **Solo `10` o `25`** (otro valor → 422)        | `10`                  |

**Qué busca `q`** (sin distinguir mayúsculas, por coincidencia parcial):

- Nombre o apellido: `"lucía"`, `"rodrí"`
- Oficio, en la categoría o en la especialidad: `"electricista"`, `"tableros"`
- Número de matrícula: `"1000008919"`
- Localidad: `"san francisco"`

> `q` **sí distingue tildes**: `"cordoba"` no encuentra "Córdoba". El placeholder
> del buscador puede quedar como está en el diseño.

**Filtros:**

- **Solo Matriculados** trae a quienes tienen al menos una matrícula fidelizada
  (`tiene_matricula_validada: true`).
- **Urgencias** trae a quienes tienen `disponible_emergencia: true`.
- Si se manda una provincia o localidad que no existe, la respuesta es un
  listado vacío, no un error.

- **Contador "N profesionales encontrados"** (CA04/CA05): usar `total`, que es la
  cantidad de **todas las páginas**. `items.length` es solo la página actual.
- **Sin resultados** (CA06): `items: []` y `total: 0`. El mensaje "No se
  encontraron profesionales con los filtros seleccionados." y el ícono de lupa
  van en el frontend.
- Una página fuera de rango devuelve `items: []` con el `total` real: conviene
  volver a la página 1 cada vez que cambia un filtro.

### Recomendaciones

- **Debounce** de unos 300 ms en el buscador, para no hacer un request por letra.
- La **cruz para borrar** del buscador vacía el texto y vuelve a pedir el listado sin
  `q`.
- Guardar los filtros en la URL (`/directorio?q=...&categoria_id=...`), así los
  links del inicio y el botón "Volver" del perfil conservan la búsqueda.
- Los profesionales suspendidos o bloqueados nunca aparecen: no hace falta filtrarlos.

---

## 2. Desplegables "Categoría" y "Zona"

### Categoría

`GET /api/v1/categorias` devuelve las categorías activas, ordenadas por nombre.
Son **las mismas opciones del alta del profesional**, como pide el caso.
Agreguen al principio la opción "Todos los oficios", que equivale a no mandar
`categoria_id`.

### Zona (provincia → localidad)

La zona se arma con dos desplegables encadenados: provincia y localidad.

```
GET /api/v1/catalogos/provincias?solo_con_profesionales=true
→ [{ "id": "14", "nombre": "Córdoba" }, { "id": "82", "nombre": "Santa Fe" }]

GET /api/v1/catalogos/provincias/14/localidades?solo_con_profesionales=true
→ [{ "id": "14140360", "nombre": "San Francisco", "departamento": "San Justo" }]
```

- **En el directorio usen `solo_con_profesionales=true`**: lista solo las zonas que
  tienen profesionales. Sin ese parámetro, Córdoba sola tiene 532 localidades,
  casi todas vacías.
- "Todas las zonas" equivale a no mandar ni `provincia_id` ni `localidad_id`.
  Con solo la provincia elegida, se filtra por toda la provincia.
- Al cambiar de provincia, limpien la localidad elegida.
- **Los `id` son texto**, no números: `"02"` (CABA) y `"06"` (Buenos Aires)
  llevan un 0 adelante que no hay que perder.
- Algunas provincias tienen **localidades con el mismo nombre** (hay 68 casos).
  Para distinguirlas, muestren el departamento. Por ejemplo, Catamarca tiene
  `San José (Dpto. Fray Mamerto Esquiú)` y `San José (Dpto. Santa María)`.
- Provincia inexistente → **404** `{"detail": {"codigo": "provincia_inexistente", ...}}`.

---

## 3. Tarjeta y perfil del profesional (CA04, CA07)

Cada elemento de `items` (y la respuesta de `GET /api/v1/oferentes/{id}`) tiene esta
forma:

```json
{
  "id_oferente": 8,
  "nombre": "Serena",
  "apellido": "Ludueña",
  "categoria": { "id_categoria": 1, "nombre": "Electricista" },
  "especialidad": "Instalaciones domiciliarias",
  "experiencia": {
    "codigo": "3_A_5",
    "etiqueta": "3 a 5 años (Experimentado)"
  },
  "whatsapp_url": "https://wa.me/5493564400777?text=Hola%20Serena%20Ludue%C3%B1a%2C...",
  "dias_atencion": [1, 2, 3, 4, 5],
  "hora_inicio_atencion": "08:00",
  "hora_fin_atencion": "18:00",
  "disponible_emergencia": true,
  "info_guardia": "No domingos",
  "descripcion": "…",
  "localidad": {
    "id": "14140360",
    "nombre": "San Francisco",
    "departamento": "San Justo"
  },
  "provincia": { "id": "14", "nombre": "Córdoba" },
  "promedio_calificacion": "4.62",
  "cantidad_resenas": 2,
  "cantidad_trabajos": 0,
  "tiene_matricula_validada": false,
  "matriculas": [],
  "foto_perfil_url": null,
  "portada_url": null
}
```

### De dónde sale cada dato de la tarjeta

| Dato de la tarjeta                     | Campo                                                                                                                                                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Foto                                   | `foto_perfil_url` (`null` → avatar por defecto)                                                                                                                                    |
| Nombre                                 | `nombre` + `apellido` (`apellido` puede ser `null` en una razón social)                                                                                                            |
| Ícono de verificado                    | Solo si `tiene_matricula_validada` es `true`                                                                                                                                       |
| Oficio                                 | `categoria.nombre` (y `especialidad` si quieren el detalle)                                                                                                                        |
| Calificación                           | `promedio_calificacion`: **llega como texto** (`"4.62"`), usar `Number(...)`. Es `"0.00"` sin reseñas                                                                              |
| Cantidad de opiniones                  | `cantidad_resenas`                                                                                                                                                                 |
| Descripción resumida                   | `descripcion`, que puede ser `null`. En ese caso no se muestra (CA07)                                                                                                              |
| Zona / domicilio                       | `localidad.nombre` + `provincia.nombre`. Los dos son `null` si el profesional no cargó la localidad                                                                                |
| Horarios de atención                   | `dias_atencion` (ISO: 1 = lunes … 7 = domingo) + `hora_inicio_atencion`–`hora_fin_atencion`. Las etiquetas de los días están en `GET /api/v1/catalogos/registro-oferente` → `dias` |
| Disponibilidad / urgencias (destacado) | `disponible_emergencia`, y el detalle en `info_guardia`                                                                                                                            |
| Trabajos en OFFIX                      | `cantidad_trabajos`                                                                                                                                                                |
| Matrícula                              | `matriculas[].numero_matricula`, solo si `tiene_matricula_validada`                                                                                                                |

### Botón "Contactar" (CA07–CA10)

El backend ya arma el link: **no hay que componer el número ni el mensaje**.

```js
function contactar(profesional) {
  if (!profesional.whatsapp_url) {
    mostrarError(
      "No fue posible contactar al profesional. Intentá nuevamente más tarde.",
    );
    return;
  }
  window.open(profesional.whatsapp_url, "_blank", "noopener");
}
```

- El link trae el mensaje "Hola [Nombre], vi tu perfil de [Oficio] en OFFIX y
  necesito un presupuesto. ¿Estás disponible?" ya cargado (CA08). WhatsApp no
  lo envía solo: el usuario puede editarlo antes (CA08).
- Cada profesional tiene su propio link con su número (CA07).
- `whatsapp_url: null` significa que el teléfono guardado no es válido. En ese caso
  no se abre WhatsApp y se muestra el mensaje de CA10.

### Botón "Ver perfil"

Navega a la vista del perfil, que consulta `GET /api/v1/oferentes/{id_oferente}`.
Un id inexistente responde **404**. El botón "Volver" puede usar el historial del
navegador; si los filtros están en la URL, se conservan.

---

## 4. Localidad en el formulario del profesional (alta y edición)

Para que un profesional aparezca al filtrar por zona, tiene que tener cargada su
localidad. Hay que sumar al formulario un selector de provincia → localidad,
igual que en el directorio pero **sin** `solo_con_profesionales`, porque acá van
todas las localidades:

```
GET /api/v1/catalogos/provincias
GET /api/v1/catalogos/provincias/14/localidades?q=san fran     ← autocompletar
```

Se envía solo el `id` de la localidad. La provincia no se manda: el backend la
deduce de la localidad.

```json
POST /api/v1/oferentes
{ "nombre": "Serena", "apellido": "Ludueña", "...": "...", "localidad_id": "14140360" }

PUT /api/v1/oferentes/me
{ "localidad_id": "14140220" }   // cambiarla
{ "localidad_id": null }         // borrarla
```

- Por ahora es **opcional**: el formulario actual sigue funcionando sin ella.
  Cuando el frontend la envíe, se puede volver obligatoria.
- Una localidad inexistente responde **422**:
  `"errores": [{"campo": "localidad_id", "codigo": "localidad_invalida"}]` →
  texto sugerido: "Seleccioná una localidad de la lista".
- Para precargar la edición, `GET /api/v1/oferentes/me` trae `localidad` y
  `provincia` con la misma forma que el perfil público.

---

## 6. Caché del catálogo (no requiere nada del frontend)

El catálogo de provincias y localidades **no consulta la base**: el backend lo
carga en memoria al arrancar, desde `app/db/ubicaciones.json`. Además, las
respuestas traen un header `Cache-Control` para que el navegador y el CDN de
Vercel guarden una copia:

| Pedido | Se guarda | Consecuencia |
| ------ | --------- | ------------ |
| Catálogo completo (`/provincias`, `/provincias/{id}/localidades`, con o sin `q`) | 1 día | Abrir el desplegable de nuevo es instantáneo |
| Con `solo_con_profesionales=true` | 1 minuto en el navegador, 5 en Vercel | Una zona nueva puede tardar **hasta 5 minutos** en aparecer en "Zona" |
| Provincia inexistente (404) | No se guarda | — |

- **El frontend no tiene que hacer nada:** el navegador guarda las copias solo. No
  hace falta `localStorage` ni copiar el JSON al frontend.
- Las respuestas grandes llegan **comprimidas con gzip** (las localidades de Córdoba
  pasan de 47 KB a 6 KB); el navegador las descomprime solo.
- En el catálogo, `q` **no distingue tildes**: `cordoba` encuentra "Córdoba" y
  `rio cuarto`, "Río Cuarto". (En el buscador del directorio, sí las distingue.)
- Para probar con datos nuevos en desarrollo, usen recarga forzada
  (Ctrl+Shift+R) o "Disable cache" en las herramientas del navegador.

---

## Errores de esta HU

| Situación                                     | Respuesta                                                                  |
| --------------------------------------------- | -------------------------------------------------------------------------- |
| `por_pagina` distinto de 10 o 25              | 422 `errores: [{"campo": "por_pagina", "codigo": "invalido"}]`             |
| `pagina` menor a 1                            | 422                                                                        |
| Provincia inexistente en el catálogo          | 404 `detail.codigo = "provincia_inexistente"`                              |
| Localidad inexistente en el alta o la edición | 422 `errores: [{"campo": "localidad_id", "codigo": "localidad_invalida"}]` |
| Coordenadas en la edición (campos eliminados) | 422 `errores: [{"campo": "latitud", "codigo": "campo_no_permitido"}]`      |
| Perfil inexistente                            | 404                                                                        |
| Sin resultados en el directorio               | **200** con `items: []` y `total: 0` (no es un error)                      |

---

## Cómo probarlo

Con el seed cargado (`python -m app.db.seed`), los profesionales de demo tienen
localidad:

| Profesional        | Oficio       | Zona                   | Para probar                                              |
| ------------------ | ------------ | ---------------------- | -------------------------------------------------------- |
| Serena Ludueña     | Electricista | San Francisco, Córdoba | Urgencias, reseñas                                       |
| María Clara Alessi | Gasista      | San Francisco, Córdoba | Matriculada (matrícula `1000008919`, una vez fidelizada) |
| Carlos Fernández   | Plomero      | **Frontera, Santa Fe** | Filtro por provincia                                     |
| Sergio Díaz        | Albañil      | **Freyre**, Córdoba    | Filtro por localidad                                     |
| Pablo Ruiz         | Plomero      | San Francisco, Córdoba | `whatsapp_url: null` (CA10)                              |

Algunas búsquedas para la demo:

```
GET /api/v1/oferentes?provincia_id=82                    → Carlos
GET /api/v1/oferentes?q=electricista&urgencias=true      → Serena
GET /api/v1/oferentes?q=zzzz                             → total 0 (CA06)
GET /api/v1/catalogos/provincias/14/localidades?solo_con_profesionales=true
```

## Datos de referencia

- Catálogo de provincias y localidades: **INDEC**, localidades censales (24
  provincias, 4.027 localidades), tomado de la API Georef del Gobierno. Está
  versionado en `app/db/ubicaciones.json`.
- Migración en Supabase: `b7d3e5a1c924`. Crea las tablas `provincias` y
  `localidades`, agrega `oferentes.localidad_id` y borra latitud, longitud y radio.
- Tests: `app/tests/test_directorio.py`.
