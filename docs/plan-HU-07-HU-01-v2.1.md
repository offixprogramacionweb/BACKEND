# Plan — HU-07 (Administración y moderación) y HU-01 v2.1 (Réplica de reseñas)

> **2026-11-09.** Armado con las dos HU que pasó la PM, las hojas *US Admin* y
> *US Réplica de Reseñas* de `Casos_de_Prueba_Offix.xlsx`, el documento
> `Offix_Replicas_Diseno_Tecnico.docx` (v2.0) y el código al commit `8862ab5`
> (`main`). La HU de filtros de búsqueda la hace el compañero: acá solo se marca
> dónde se tocan.
>
> Alcance: **backend + contrato de API para el frontend**, igual que en los
> sprints anteriores. Todas las decisiones están tomadas; las que conviene
> avisar a la PM figuran como **[Avisar a la PM]**, pero no bloquean.

## Resumen

| Paso | Qué | Migración |
|---|---|---|
| **0** | Arreglar la base de producción (los 500 que ve el frontend) y evitar que vuelva a pasar | Aplica la que falta (`b7d3e5a1c924`) |
| **1** | HU-01 v2.1 — réplica del Profesional a una reseña | `d2a7c5e9f134` (tabla `replicas_resena`) |
| **2** | HU-07 — grilla de oferentes, suspensión/alta, validación manual de matrícula | `f61b3d8a0c42` (parte 1) |
| **3** | HU-07 — baja/reactivación de reseñas y trabajos, auditoría | `f61b3d8a0c42` (parte 2) |
| **4** | HU-07 — notificaciones del administrador (campana) | `f61b3d8a0c42` (parte 3, backfill) |
| **5** | Login: admin con Google y cuenta suspendida | — |
| **6** | Tests, OpenAPI, contrato para el frontend | — |

Orden recomendado: 0 → 1 → 2 → 3 → 4 → 5 → 6. HU-01 va primero porque es chica
y el paso 3 modifica el mismo listado público de reseñas.

---

## Paso 0 — Estado actual del backend y de la base

### Diagnóstico (verificado el 2026-11-09)

- La base de Supabase (schema `offix`) está en la revisión **`e8b4c2d91f07`**.
  El código de `main` espera **`b7d3e5a1c924`** (HU-05: `provincias`,
  `localidades`, `oferentes.localidad_id`).
- Vercel despliega `main` en cada push, pero **las migraciones no se corren
  solas**. Después del merge del PR #9 nadie corrió `migrar_bd.bat`.
- El modelo `Oferente` lee `localidad_id`, que no existe en la tabla, y todo
  lo que carga un oferente explota:

| Endpoint en producción | Respuesta |
|---|---|
| `GET /api/v1/oferentes` (directorio) | **500** |
| `GET /api/v1/oferentes/{id}` (perfil) | **500** |
| `GET /api/v1/oferentes/{id}/trabajos` | **500** |
| `GET /api/v1/oferentes/{id}/resenas` | 200 (no carga el oferente) |
| `GET /api/v1/categorias`, `/catalogos/provincias` | 200 (no leen `oferentes`) |

- Se puede aplicar la migración sin perder datos: ningún oferente tiene
  `latitud`/`longitud`/`radio_cobertura_km` cargados (0 de 10), y los default
  privileges del schema `offix` ya le dan a `offix_app` permisos sobre las
  tablas nuevas que cree `postgres`.

### Arreglo (hacerlo ya, antes de cualquier otra cosa)

```bat
migrar_bd.bat
```

(o `venv\Scripts\python -m alembic upgrade head` con el `.env` apuntando a
Supabase, puerto 5432). Después, verificar que `GET /api/v1/oferentes` dé 200.

### Prevención (D19)

1. **Workflow `.github/workflows/migrar-bd.yml`**: en cada push a `main` que
   toque `migrations/**`, corre `alembic upgrade head`. Usa un secret
   `DATABASE_URL_MIGRACIONES` (URI del pooler en **modo session, puerto
   5432**, con el usuario `postgres`). Hay que cargar el secret a mano en
   GitHub > Settings > Secrets.
2. **`GET /health` informa la migración**: compara la revisión de
   `alembic_version` con el head del código (`ScriptDirectory.get_current_head()`).
   Devuelve `{"status": "ok", "migraciones": "al_dia"}` o **503** con
   `{"status": "error", "migraciones": "pendientes", "base": "<rev>", "codigo": "<head>"}`.
   En SQLite devuelve `"no_aplica"`. Así el próximo desfase se ve en un request.
3. Regla del equipo: un PR que agrega una migración lleva en la descripción
   "corre migración", y quien mergea confirma que el workflow pasó.

---

## Decisiones

| # | Tema | Decisión |
|---|---|---|
| R1 | Largo máximo de la réplica | **500 caracteres** (los casos de QA dicen 500; el docx decía 200 "por validar"). Mínimo 1 después de recortar espacios. **[Avisar a la PM]** |
| R2 | Sobre qué reseñas se replica | Solo **Aceptadas y no dadas de baja** (las publicadas). Cualquier calificación, no solo las negativas: el CA01 dice "una reseña publicada". **[Avisar a la PM]**: el título de la HU dice "negativa" |
| R3 | Normalización del texto | Se recortan los espacios de los extremos. **No** se colapsan espacios internos ni saltos de línea, y no se reemplaza ningún carácter (caso "tildes, ñ, signos"). Se guarda tal cual y el frontend lo muestra como texto (React escapa): nada de `dangerouslySetInnerHTML` |
| R4 | Teléfonos, correos y URL en la réplica | **No se bloquean.** Ningún CA lo pide y el caso "15/10 a las 18:30 hs" daría falso positivo |
| R5 | Doble clic en "Confirmar" | El backend es idempotente: si la réplica ya existe **con el mismo texto y del mismo Profesional**, responde 200 con la existente. Con otro texto, 409 `replica_existente`. La UNIQUE de `resena_id` cubre la carrera |
| R6 | Edición o borrado de la réplica | No existen (CA03). No hay endpoints `PUT`/`DELETE` |
| R7 | `puede_responder` | Lo calcula el backend en el listado público, con auth **opcional y tolerante**: un token vencido o inválido se trata como anónimo, para no romper el perfil público con 401 |
| A1 | Estado "suspendido" | Se usa `usuarios.estado_cuenta`. La grilla muestra **Activo** si es `Activa` y **Suspendido** para `Suspendida` o `Bloqueada`. "Dar de alta" siempre deja `Activa` |
| A2 | Quién aparece en la grilla | Usuarios con rol Oferente **y** fila en `oferentes` (registro completo). Los que no completaron el registro no aparecen |
| A3 | Confirmación de la suspensión/alta | La hace el frontend (modal). El backend no tiene un paso de confirmación |
| A4 | Suspender o dar de alta dos veces | **Idempotente**: responde 200 con el estado actual, sin auditoría ni notificación duplicadas |
| A5 | Efectos de la suspensión | No puede iniciar sesión (ya existe), su token deja de servir (ya existe), sale del directorio (ya existe). **Nuevo:** `GET /oferentes/{id}` responde 404 salvo que lo pida un admin, y `POST /oferentes/{id}/solicitudes-resena` responde 404 |
| A6 | Validación manual de matrícula (CA03) | El admin carga tipo y número en el mismo modal de HU-02 (mismos tipos y mismas reglas de dígitos). **No se consulta el padrón**: se crea o reemplaza la fila de `matriculas` con `origen = Administrador`, así el distintivo de verificado aparece en el perfil y en el directorio |
| A7 | Oficios sin tipo de matrícula | El modal solo ofrece Gasista y Aire acondicionado (los tipos de HU-02). Electricista, plomero, etc. no tienen formato definido. **[Avisar a la PM]**: el ejemplo "MP-12345" del caso no pasa la regla de solo dígitos; se deja la regla de HU-02 |
| A8 | Matrícula ya fidelizada por otro Oferente | 409 `matricula_de_otro_oferente`. El admin no puede pisar la de otro |
| A9 | Baja de reseña/trabajo | **Baja lógica** (columna `dado_de_baja_en`), no borrado. La reseña conserva su `estado` (`Aceptada`). Visible = `Aceptada` y sin baja. Se puede reactivar |
| A10 | Qué reseñas ve el admin | Aceptadas (activas o dadas de baja) y Rechazadas. **No** las pendientes: esas las decide el Profesional |
| A11 | Qué se puede dar de baja | Solo reseñas **Aceptadas** (caso "las rechazadas no muestran ningún icono"). Cualquier trabajo |
| A12 | Métricas | `promedio_calificacion`, `cantidad_resenas` y `cantidad_trabajos` cuentan solo lo visible. Se recalculan en la misma transacción de la baja/reactivación |
| A13 | Réplica de una reseña dada de baja | Se oculta con la reseña y vuelve con ella. No se borra |
| A14 | Trabajos dados de baja y el límite de 5 | **No cuentan** para el límite. El dueño no los ve en su perfil (mismo endpoint público). Puede borrarlos con el `DELETE` que ya existe |
| A15 | Motivo de la baja | Opcional, hasta 200 caracteres, en el body. Se guarda en la auditoría |
| A16 | Historial de auditoría | Tabla nueva `auditoria_moderacion`. Registra suspensión, alta, baja y reactivación de reseñas y trabajos, y validación manual de matrícula. Se consulta por oferente |
| A17 | Umbral de la campana (CA08) | **5 o más reseñas rechazadas en total** (no "5 de las últimas 10", como hasta ahora). Reemplaza la regla de la ventana para la alerta y para `cantidad_rechazos_acumulados`. Las rechazadas que el admin publica dejan de contar |
| A18 | Notificaciones del admin | Van a la tabla `notificaciones` que ya existe (misma campana), una por administrador. Tipos nuevos `Rechazos_Reiterados` y `Oferente_Reactivado`, informativas (`requiere_accion = false`), con `oferente_id` para el botón "Ver opiniones" |
| A19 | Descartar notificación (cruz) | `PATCH /notificaciones/{id}/leer`, que ya existe. La campana del admin pide `?solo_pendientes=true` para no mostrar las descartadas |
| A20 | Repetición de la alerta | Mientras el admin tenga una `Rechazos_Reiterados` pendiente de ese Profesional, no se crea otra. Si la descartó y el Profesional vuelve a rechazar, se crea una nueva |
| A21 | Admin con Google (CA01) | Variable nueva `ADMIN_EMAILS` (lista separada por comas). En el callback de Google, un correo de la lista entra con rol Administrador (se crea así o se promueve), salvo que ya tenga perfil de Oferente. La redirección a "Gestión de Oferentes" la decide el frontend con `rol` de `/auth/me` |
| A22 | Mensaje de cuenta suspendida | `"Su cuenta se encuentra suspendida, comunicarse con Asesoría."` con código `cuenta_suspendida`, en los tres caminos: `/auth/login` (403), callback de Google (`?motivo=cuenta_suspendida`) y token vigente (401) |
| A23 | Paginación de la grilla | `pagina` desde 1, `por_pagina` 10, 25 o 50 (25 por defecto). Los contadores de activos y suspendidos son **globales**, no dependen del filtro ni de la búsqueda |
| A24 | Migraciones | Dos migraciones encadenadas: `d2a7c5e9f134` (HU-01) → `f61b3d8a0c42` (HU-07). Si el compañero agrega una migración en paralelo, al mergear se aplica D16 (`alembic merge heads`) |

---

## Paso 1 — HU-01 v2.1: réplica del Profesional

### 1.1 Modelo — `app/models/replica_resena.py` (nuevo)

```python
class ReplicaResena(Base):
    __tablename__ = "replicas_resena"
    __table_args__ = (UniqueConstraint("resena_id", name="uq_replica_resena"),)

    id_replica = Column(Integer, primary_key=True, index=True)
    resena_id = Column(Integer, ForeignKey("resenas.id_resena", ondelete="CASCADE"), nullable=False)
    oferente_id = Column(Integer, ForeignKey("oferentes.id_oferente", ondelete="CASCADE"), nullable=False, index=True)
    texto = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    resena = relationship("Resena", back_populates="replica")
```

- `Resena`: agregar `replica = relationship("ReplicaResena", back_populates="resena", uselist=False, cascade="all, delete-orphan")`.
- Registrar el módulo en `app/main.py` (import de modelos) y en `app/db/seed.py`.

### 1.2 Migración `2026_11_10_1000-d2a7c5e9f134_replicas_de_resena.py`

- `down_revision = "b7d3e5a1c924"`.
- `create_table("replicas_resena", ..., schema="offix")` + índice de `oferente_id`.
- `downgrade`: `drop_table`.

### 1.3 Schemas — `app/schemas/resena.py`

```python
LARGO_MAXIMO_REPLICA = 500

class ReplicaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str

    @field_validator("texto")
    @classmethod
    def validar_texto(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise PydanticCustomError("comentario_requerido", "Debe ingresar un comentario para poder responder la reseña.")
        if len(valor) > LARGO_MAXIMO_REPLICA:
            raise PydanticCustomError("comentario_demasiado_largo", "El comentario no puede superar los 500 caracteres.")
        return valor

class ReplicaOut(BaseModel):
    texto: str
    fecha_creacion: datetime
```

- `ResenaPublicaOut`: agregar `replica: ReplicaOut | None = None` y
  `puede_responder: bool = False`.
- `ResenaPrivadaOut` y `ResenaAdminOut` también llevan `replica`.

### 1.4 Auth opcional tolerante — `app/core/deps.py`

```python
def get_usuario_opcional_tolerante(token = Depends(oauth2_scheme_opcional), db = Depends(get_db)) -> Usuario | None:
    """Para listados públicos: un token inválido, vencido o de una cuenta
    suspendida se trata como anónimo (no rompe la vista con 401)."""
    if not token:
        return None
    try:
        return get_current_user(token=token, db=db)
    except HTTPException:
        return None
```

### 1.5 Endpoint nuevo — `POST /api/v1/resenas/{resena_id}/replica`

En `app/routers/resenas.py`. Dependencia `get_oferente_registrado`.

| Caso | Respuesta |
|---|---|
| Reseña inexistente | 404 `resena_no_encontrada` |
| La reseña no es del Profesional autenticado | 403 `no_autorizado` |
| Reseña no publicada (pendiente, rechazada o dada de baja) | 400 `resena_no_publicada` "Solo se pueden responder reseñas publicadas" |
| Ya tiene réplica del mismo Profesional con el mismo texto (doble clic) | **200** con la réplica existente |
| Ya tiene réplica con otro texto | 409 `replica_existente` "La reseña ya tiene una réplica" |
| Texto vacío / solo espacios | 422 `errores[{campo: "texto", codigo: "comentario_requerido"}]` |
| Texto de más de 500 | 422 `comentario_demasiado_largo` |
| Sin token / token inválido | 401 |
| Usuario Administrador | 403 `rol_invalido` (lo da el guard) |
| OK | **201** `ReplicaOut` |

Lógica (en `app/services/resenas.py`, función `registrar_replica`): validar,
`db.add`, `flush`; si da `IntegrityError` (carrera del doble clic), `rollback`,
releer la réplica y aplicar la regla de R5. Las respuestas 200/201 van con el
mismo schema; el router usa `Response.status_code` para distinguirlas.

### 1.6 Listado público — `GET /api/v1/oferentes/{id}/resenas`

- Agregar `usuario = Depends(get_usuario_opcional_tolerante)`.
- Cargar las réplicas de la página en **una** query (`resena_id IN (...)`), no una por reseña.
- `puede_responder = usuario is not None and usuario.id_usuario == oferente_id and replica is None`.
- El resto no cambia (paginación, nombre reducido del cliente).

### 1.7 Qué hace el frontend (contrato)

- Botón **"Réplica"** solo si `puede_responder` (CA01, CA04).
- Formulario: título "Responder como [Nombre Profesional]", textarea, contador,
  "Cerrar" + "Confirmar". "Confirmar" deshabilitado con más de 500 caracteres,
  con el label rojo "El comentario no puede superar los 500 caracteres.".
  Con el campo vacío o con espacios, toast rojo "Debe ingresar un comentario
  para poder responder la reseña.". "Cerrar" descarta el texto (CA06).
- Éxito: toast verde "Respuesta enviada correctamente.", recargar la página de reseñas.
- La réplica va debajo del comentario, con la etiqueta "Respuesta del profesional",
  la fecha, y otro fondo (CA07).
- Si el `POST` responde 409 `replica_existente`, recargar el listado (no
  mostrar error: la réplica ya está).

---

## Paso 2 — HU-07: grilla, suspensión/alta y matrícula

### 2.1 Migración `2026_11_10_1100-f61b3d8a0c42_moderacion_administrador.py`

`down_revision = "d2a7c5e9f134"`. Todo en el schema `offix`:

| Tabla | Cambio |
|---|---|
| `resenas` | `dado_de_baja_en DateTime(tz) NULL`, `dado_de_baja_por_id Integer FK usuarios SET NULL NULL` |
| `trabajos_realizados` | los mismos dos campos |
| `matriculas` | `origen String(20) NOT NULL server_default 'Padron'`, `validada_por_id Integer FK usuarios SET NULL NULL`; `categoria` y `fecha_vencimiento` pasan a **NULL** (una matrícula validada a mano no tiene datos del padrón) |
| `notificaciones` | `oferente_id Integer FK oferentes CASCADE NULL` + índice |
| `auditoria_moderacion` (nueva) | ver 3.2 |
| backfill | ver 4.3 |

`downgrade`: revierte todo; antes de volver a `NOT NULL` en `matriculas`, borra
las filas con `origen = 'Administrador'`.

### 2.2 Modelos

- `Resena` y `TrabajoRealizado`: `dado_de_baja_en`, `dado_de_baja_por_id`, y una propiedad `visible`.
- `Matricula`: `origen` (constantes `OrigenMatricula.PADRON = "Padron"`, `ADMINISTRADOR = "Administrador"`), `validada_por_id`, `categoria`/`fecha_vencimiento` `nullable=True`.
- `MatriculaOut`: `categoria: str | None`, `fecha_vencimiento: date | None`, `origen: str`.
- `Notificacion`: `oferente_id`, relación `oferente`.
- `TipoNotificacion`: `RECHAZOS_REITERADOS = "Rechazos_Reiterados"`, `OFERENTE_REACTIVADO = "Oferente_Reactivado"`.
- `ResultadoValidacion`: `VALIDADA_ADMINISTRADOR = "Validada_Administrador"`, con mensaje en `MENSAJES_RESULTADO`: "Se validó correctamente la matrícula del Profesional".
- `EstadoCuenta`: sin cambios.

### 2.3 Schemas — `app/schemas/admin.py` (nuevo)

```python
class OferenteAdminFila(BaseModel):
    id_oferente: int
    nombre: str
    apellido: str | None
    foto_perfil_url: str | None
    estado: Literal["Activo", "Suspendido"]
    estado_cuenta: str                 # valor crudo: Activa | Suspendida | Bloqueada
    categoria: CategoriaRef | None     # "rubro"
    especialidad: str | None
    matricula_numero: str | None       # la primera fidelizada, por tipo alfabético
    matricula_verificada: bool         # tiene_matricula_validada
    matriculas: list[MatriculaRef]
    promedio_calificacion: float
    cantidad_resenas: int              # visibles
    cantidad_trabajos: int             # visibles
    cantidad_rechazadas: int

class OferenteAdminDetalle(OferenteAdminFila):
    descripcion: str | None            # tarjeta de "Moderar Reseñas"
    email: str

class ContadoresOferentes(BaseModel):
    activos: int
    suspendidos: int

class OferentesAdminPaginadosOut(BaseModel):
    items: list[OferenteAdminFila]
    contadores: ContadoresOferentes
    pagina: int
    por_pagina: int
    total: int
    total_paginas: int

class MatriculaAdminIn(BaseModel):     # mismo body que el modal de HU-02
    tipo_profesional: str
    numero_matricula: str

class BajaIn(BaseModel):
    motivo: str | None = Field(default=None, max_length=200)
```

### 2.4 Servicio — `app/services/admin.py` (nuevo)

Concentra la lógica; los routers solo validan y llaman. Funciones:

- `armar_fila(db, oferente) -> OferenteAdminFila`. Reutiliza `_url_unica` de `services/oferentes.py` (pasarla a pública: `url_unica`).
- `listar_oferentes_admin(db, q, estado, pagina, por_pagina)`:
  - base: `Oferente JOIN Usuario OUTER JOIN Categoria`, orden `Oferente.nombre, Oferente.apellido, id_oferente`.
  - `estado`: `todos` | `activos` (`estado_cuenta == Activa`) | `suspendidos` (`!= Activa`).
  - `q` (recortado): `ilike` sobre nombre, apellido, `nombre || ' ' || apellido` (con `func.concat` y `coalesce` para que ande en SQLite y Postgres), categoría, especialidad, y `Oferente.matriculas.any(Matricula.numero_matricula.ilike(f"%{q}%"))`. Acá la matrícula admite coincidencia parcial: es una herramienta interna.
  - contadores: dos `count` globales.
  - conteos de reseñas/trabajos de la página con `GROUP BY` (una query por métrica, no N+1).
- `cambiar_estado_oferente(db, admin, oferente, suspender: bool)` → aplica A4, auditoría (`Suspension` / `Alta`) y, al dar de alta, la notificación `Oferente_Reactivado` (4.2).
- `validar_matricula_admin(db, admin, oferente, tipo, numero)`:
  1. `validar_formato_matricula(tipo, numero)` — se **extrae** del router de matrículas a `services/matriculas.py` y lo usan los dos.
  2. Si otro oferente tiene esa matrícula fidelizada (mismo tipo y número) → 409 `matricula_de_otro_oferente`.
  3. Upsert de `Matricula` (oferente, tipo): número, `origen = Administrador`, `validada_por_id`, `categoria = None`, `fecha_vencimiento = None`, `fecha_fidelizacion = now`.
  4. Si había un reemplazo pendiente de HU-02 para ese tipo, marcarlo `Superseded` (reusar `_supersedear_reemplazos_previos`).
  5. `ValidacionMatricula` con `resultado = Validada_Administrador` (historial).
  6. `oferente.estado_verificacion = Verificado`, `usuario.fidelizado = True`.
  7. Notificación al Oferente tipo `Matricula_Validada` con el texto de CA05 de HU-02.
  8. Auditoría `Validacion_Matricula`.

### 2.5 Endpoints nuevos — `app/routers/admin.py`

Todos bajo `/api/v1/admin` con `require_admin` (ya está en el router).

| Método y ruta | Qué hace | Errores |
|---|---|---|
| `GET /oferentes?q=&estado=todos\|activos\|suspendidos&pagina=1&por_pagina=25` | Grilla (CA02) | 422 `por_pagina` inválido o `estado` inválido |
| `GET /oferentes/{id}` | Tarjeta del oferente en "Moderar Reseñas"/"Auditar Trabajos" | 404 |
| `POST /oferentes/{id}/suspender` | CA06. Devuelve `OferenteAdminFila` | 404; 400 `no_se_puede_suspender_admin` si el usuario es Administrador |
| `POST /oferentes/{id}/dar-de-alta` | CA06. Devuelve `OferenteAdminFila` | 404 |
| `POST /oferentes/{id}/matriculas` | CA03. Body `MatriculaAdminIn`. Devuelve `OferenteAdminFila` | 404; 409 `matricula_de_otro_oferente`; 422 con los mismos códigos que HU-02 (`solo_digitos`, `digitos_invalidos`, tipo inválido) |

Los endpoints existentes `PATCH /admin/usuarios/{id}/estado` y
`PATCH /admin/oferentes/{id}/verificacion` **quedan** por compatibilidad; el
frontend nuevo usa los de arriba (llevan auditoría y notificación).

### 2.6 Efectos de la suspensión en endpoints existentes (A5)

- `GET /api/v1/oferentes/{id}`: con `get_usuario_opcional_tolerante`; si la
  cuenta no está `Activa` y quien pide no es admin → 404 "Oferente no encontrado".
- `POST /api/v1/oferentes/{id}/solicitudes-resena`: 404 si la cuenta no está `Activa`.
- `GET /oferentes/{id}/resenas` y `/trabajos`: sin cambios (sin el perfil, el frontend no llega).

---

## Paso 3 — HU-07: moderación de reseñas y trabajos

### 3.1 Visibilidad única — `app/services/resenas.py`

```python
def filtro_resenas_visibles():
    return and_(Resena.estado == EstadoResena.ACEPTADA, Resena.dado_de_baja_en.is_(None))
```

Se usa en **todos** los lugares que hoy filtran `estado == Aceptada` para
mostrar o contar:

- `listar_resenas_publicas` (router de reseñas)
- `armar_publica` → `cantidad_resenas` (services/oferentes.py)
- `recalcular_promedio`
- la réplica (paso 1.5: "reseña no publicada")

Lo mismo para trabajos con `TrabajoRealizado.dado_de_baja_en.is_(None)`:
`listar_trabajos` (público), `armar_publica` → `cantidad_trabajos`, y
`cantidad_trabajos` de `services/archivos.py` (límite de 5, A14).

> **Ojo con HU-05 (compañero):** si el directorio agrega orden o filtro por
> calificación o cantidad de reseñas, tiene que usar este mismo filtro.

### 3.2 Auditoría — `app/models/auditoria_moderacion.py` (nuevo)

```python
class AccionModeracion:
    SUSPENSION = "Suspension"
    ALTA = "Alta"
    BAJA_RESENA = "Baja_Resena"
    REACTIVACION_RESENA = "Reactivacion_Resena"
    BAJA_TRABAJO = "Baja_Trabajo"
    REACTIVACION_TRABAJO = "Reactivacion_Trabajo"
    VALIDACION_MATRICULA = "Validacion_Matricula"

class AuditoriaModeracion(Base):
    __tablename__ = "auditoria_moderacion"
    id_auditoria = Column(Integer, primary_key=True, index=True)
    administrador_id = Column(Integer, ForeignKey("usuarios.id_usuario", ondelete="SET NULL"), nullable=True)
    oferente_id = Column(Integer, ForeignKey("oferentes.id_oferente", ondelete="CASCADE"), nullable=False, index=True)
    accion = Column(String(40), nullable=False)
    resena_id = Column(Integer, ForeignKey("resenas.id_resena", ondelete="SET NULL"), nullable=True)
    trabajo_id = Column(Integer, ForeignKey("trabajos_realizados.id_trabajo", ondelete="SET NULL"), nullable=True)
    detalle = Column(Text, nullable=True)      # motivo, o "Gasista 1000008919"
    fecha = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

Helper `registrar_auditoria(db, admin, oferente_id, accion, ...)` en
`services/admin.py`; solo `add` + `flush`.

### 3.3 Endpoints nuevos — `app/routers/admin.py`

| Método y ruta | Qué hace | Errores |
|---|---|---|
| `GET /oferentes/{id}/resenas?filtro=todas\|aceptadas\|rechazadas\|dadas_de_baja` | Listado de "Moderar Reseñas", más nuevas primero. `todas` = aceptadas (activas y dadas de baja) + rechazadas. `aceptadas` = solo visibles | 404; 422 filtro inválido |
| `POST /resenas/{id}/dar-de-baja` | Body `BajaIn`. Solo si `estado == Aceptada` | 404; 400 `resena_no_aceptada`; 200 idempotente si ya estaba dada de baja |
| `POST /resenas/{id}/reactivar` | Vuelve a ser visible | 404; 200 idempotente |
| `GET /oferentes/{id}/trabajos` | Listado de "Auditar Trabajos", con estado | 404 |
| `POST /trabajos/{id}/dar-de-baja` | Body `BajaIn` | 404; 200 idempotente |
| `POST /trabajos/{id}/reactivar` | Vuelve a ser visible. **No** valida el límite de 5 (el admin restituye algo que ya existía) | 404; 200 idempotente |
| `GET /oferentes/{id}/auditoria` | Historial, más nuevo primero | 404 |

Salidas:

```python
class ResenaModeracionOut(BaseModel):
    id_resena: int
    nombre_cliente: str                     # completo: lo ve solo el admin
    puntuacion_global: float
    criterios: dict
    comentario: str | None
    fecha_creacion: datetime
    estado: Literal["Aceptada", "Rechazada", "Dada_de_baja"]
    dado_de_baja_en: datetime | None
    replica: ReplicaOut | None
    puede_dar_de_baja: bool                 # estado == Aceptada
    puede_reactivar: bool                   # estado == Dada_de_baja

class TrabajoModeracionOut(TrabajoOut):
    estado: Literal["Activo", "Dado_de_baja"]
    dado_de_baja_en: datetime | None
```

Las acciones de baja/reactivación devuelven el elemento actualizado **y** las
métricas nuevas del oferente (`{"resena": ..., "oferente": OferenteAdminFila}`),
así el frontend actualiza la tarjeta sin otro request (caso "las métricas se ajustan").

Cada acción, en una sola transacción: cambiar el estado → `recalcular_promedio`
(si es reseña) → auditoría → `commit`.

---

## Paso 4 — HU-07: campana del administrador (CA08)

### 4.1 Rechazos reiterados — `moderar_resena` (router de reseñas)

Reemplaza el bloque de la ventana de 10:

```python
rechazadas = db.query(func.count(Resena.id_resena)).filter(
    Resena.oferente_id == oferente.id_oferente, Resena.estado == EstadoResena.RECHAZADA
).scalar()
oferente.cantidad_rechazos_acumulados = rechazadas
if rechazadas >= UMBRAL_RECHAZOS_ALERTA:
    notificar_rechazos_reiterados(db, oferente)   # services/notificaciones.py
```

`notificar_rechazos_reiterados`:
- Para cada usuario con rol Administrador y cuenta `Activa` que **no** tenga
  una `Rechazos_Reiterados` `Pendiente` de ese oferente, crea:
  `"El profesional {nombre_completo} rechazó 5 o más reseñas a través de Offix"`,
  `requiere_accion = False`, `oferente_id`.
- Sigue creando la `AlertaAdministrador` si no hay una pendiente (compatibilidad con `GET /admin/alertas`).
- Se borra `VENTANA_ULTIMAS_RESENAS`.

`publicar_resena_rechazada` (admin) también actualiza `cantidad_rechazos_acumulados`.

### 4.2 Oferente reactivado

Al dar de alta (2.4), a cada admin activo:
`"El oferente {nombre_completo} fue reactivado y podrá volver a operar e iniciar sesión con normalidad."`,
tipo `Oferente_Reactivado`, `oferente_id`.

### 4.3 Backfill en la migración `f61b3d8a0c42`

Para cada oferente con 5 o más reseñas `Rechazada`, insertar la notificación
de 4.1 para cada admin activo, y actualizar `cantidad_rechazos_acumulados` al
total. Se hace con SQL plano (`INSERT ... SELECT`) para no importar modelos en
la migración. Con `--sql` (sin conexión) se omite, igual que en `b7d3e5a1c924`.

### 4.4 Bandeja — `app/routers/notificaciones.py`

- `GET /notificaciones?solo_pendientes=false`: con `true`, solo `estado == Pendiente`.
- `NotificacionOut`: agregar `oferente_id: int | None`. `oferente_nombre` también
  se completa desde `oferente_id` (hoy solo sale de la validación de matrícula).
- "Ver opiniones" → el frontend navega a "Moderar Reseñas" con `oferente_id`.
- La cruz → `PATCH /notificaciones/{id}/leer` (ya existe).
- Mensaje de bandeja vacía: "No tenés notificaciones." **[Avisar a la PM]**: el caso dice "texto a definir".

---

## Paso 5 — Login: admin con Google y cuenta suspendida

### 5.1 `ADMIN_EMAILS` (A21)

- `app/core/config.py`: `admin_emails: str = ""` y propiedad `admin_emails_list` (minúsculas, sin espacios).
- `.env.example` y Vercel: `ADMIN_EMAILS=correo.del.admin@gmail.com`.
- `callback_login_google`: si el correo está en la lista y el usuario no tiene
  fila en `oferentes`, `rol = Administrador` (al crearlo o al loguearse). Un
  correo que sale de la lista **no** se degrada solo (se hace a mano).
- El frontend, después del login, lee `rol` de `/auth/me`: Administrador →
  "Gestión de Oferentes"; Oferente → lo de siempre. Las rutas de admin del
  frontend redirigen a quien no es admin (CA01); el backend ya responde 403.

### 5.2 Cuenta suspendida (A22)

Constante `MENSAJE_CUENTA_SUSPENDIDA = "Su cuenta se encuentra suspendida, comunicarse con Asesoría."` en `app/core/errores.py`.

| Camino | Hoy | Después |
|---|---|---|
| `POST /auth/login` | 403 `"La cuenta no está activa"` | 403 `{"codigo": "cuenta_suspendida", "mensaje": ...}` |
| Callback de Google | `?error=auth_failed&motivo=cuenta_inactiva` | `?error=auth_failed&motivo=cuenta_suspendida` |
| Token de una cuenta suspendida | 401 `"La cuenta no está activa"` | 401 `{"codigo": "cuenta_suspendida", "mensaje": ...}` |

> **Cambio de contrato:** en los dos primeros casos `detail` pasa de texto a
> objeto. Avisar al frontend: tiene que leer `detail.mensaje` (o mapear `motivo`).

---

## Paso 6 — Tests, documentación y contrato

### 6.1 Tests nuevos (pytest, SQLite en memoria como el resto)

`app/tests/test_replicas.py` (HU-01 v2.1):
- CA01: `puede_responder` true solo para el dueño y solo sin réplica; false para anónimo, otro Profesional, admin y token vencido (sin 401).
- CA02: 201 con texto válido; con 500 caracteres exactos; con tildes/ñ/signos se guarda igual; la reseña del cliente no cambia; aparece en el listado público.
- CA03: segundo `POST` con otro texto → 409; mismo texto → 200 y una sola fila; no hay `PUT`/`DELETE` (405).
- CA04: otro Profesional → 403; anónimo → 401; admin → 403.
- CA05: vacío, solo espacios → 422 `comentario_requerido`; 501 → 422 `comentario_demasiado_largo`; `<script>` se guarda literal.
- Reseña pendiente, rechazada o dada de baja → 400 `resena_no_publicada`.

`app/tests/test_admin_oferentes.py` (HU-07 CA02, CA03, CA06, CA07):
- grilla con 2 activos y 1 suspendido: contadores 2/1; filtros; búsqueda por nombre, rubro y matrícula; sin resultados → `items` vacío; no-admin → 403.
- suspender/dar de alta: estado y contadores; idempotencia sin auditoría doble; no se puede suspender a un admin; el suspendido no hace login (mensaje literal) ni usa su token; el reactivado sí.
- perfil de suspendido: 404 para anónimo, 200 para admin.
- matrícula: crea `Matricula` con `origen = Administrador`, el perfil público queda con `tiene_matricula_validada`; formato inválido → 422; de otro oferente → 409; reemplaza la anterior del mismo tipo.

`app/tests/test_moderacion.py` (CA04, CA05):
- listado de reseñas con filtros; las pendientes no aparecen.
- baja de una aceptada: sale del perfil público, ajusta promedio y `cantidad_resenas`, queda en auditoría, no afecta a las demás; rechazada → 400; reactivar la devuelve.
- la réplica se oculta con la reseña.
- trabajos: baja/reactivación, `cantidad_trabajos`, el dado de baja no cuenta para el límite.

`app/tests/test_admin_notificaciones.py` (CA08):
- 4 rechazadas → sin notificación; la 5ª → una por admin; la 6ª con la anterior pendiente → no duplica; descartada y otra más → nueva.
- dos profesionales sobre el umbral → dos notificaciones; `solo_pendientes`.
- alta → `Oferente_Reactivado` con `oferente_id`.

Ajustar los existentes que cambian de contrato: `test_admin.py` (alertas con el
umbral total), `test_auth.py` / `test_auth_google.py` (detalle `cuenta_suspendida`),
`test_resenas_sprint2.py` (ventana de 10).

### 6.2 Documentación

- Regenerar `docs/openapi.json` (`generar_openapi.bat`) y actualizar `docs/openapi.md`.
- Actualizar el texto de "Estado del proyecto" en `app/main.py` (Sprint 3).
- `.env.example`: `ADMIN_EMAILS`.
- Este plan queda como fuente de verdad del sprint.

### 6.3 Checklist de despliegue

1. Mergear a `main`.
2. Correr la migración (workflow del paso 0 o `migrar_bd.bat`). Verificar `GET /health` → `"al_dia"`.
3. Cargar `ADMIN_EMAILS` en Vercel y redeployar.
4. Probar a mano: login del admin con Google, grilla, suspender/dar de alta, una réplica.

---

## Resumen del contrato para el frontend

| Vista | Endpoint |
|---|---|
| Reseñas del perfil (réplica) | `GET /oferentes/{id}/resenas` (`replica`, `puede_responder`) · `POST /resenas/{id}/replica` |
| Gestión de Oferentes | `GET /admin/oferentes` · `POST /admin/oferentes/{id}/suspender` · `POST /admin/oferentes/{id}/dar-de-alta` · `POST /admin/oferentes/{id}/matriculas` · `GET /matriculas/tipos` (ya existe: tipos y dígitos del modal) |
| Moderar Reseñas | `GET /admin/oferentes/{id}` · `GET /admin/oferentes/{id}/resenas?filtro=` · `POST /admin/resenas/{id}/dar-de-baja` · `POST /admin/resenas/{id}/reactivar` |
| Auditar Trabajos | `GET /admin/oferentes/{id}/trabajos` · `POST /admin/trabajos/{id}/dar-de-baja` · `POST /admin/trabajos/{id}/reactivar` |
| Ver perfil | `GET /oferentes/{id}` (con el token del admin, también si está suspendido) |
| Campana del admin | `GET /notificaciones?solo_pendientes=true` · `PATCH /notificaciones/{id}/leer` |
| Login | `/auth/me` → `rol`; `detail.codigo == "cuenta_suspendida"` / `motivo=cuenta_suspendida` |

Textos literales de QA que muestra el frontend:

| Momento | Texto |
|---|---|
| Réplica enviada | "Respuesta enviada correctamente." |
| Réplica vacía | "Debe ingresar un comentario para poder responder la reseña." |
| Réplica larga | "El comentario no puede superar los 500 caracteres." |
| Matrícula validada por el admin | "Se validó correctamente la matrícula del Profesional" |
| Oferente reactivado (toast) | "Cliente activado correctamente." **[Avisar a la PM]**: dice "Cliente", debería ser "Profesional" |
| Login de un suspendido | "Su cuenta se encuentra suspendida, comunicarse con Asesoría." |
| Grilla sin resultados | "No se encontraron profesionales." |
| Sin opiniones | "No se encontraron opiniones." |
| Sin trabajos | "No se encontraron trabajos." **[Avisar a la PM]**: el caso dice "No se encontraron reseñas." en la vista de trabajos |
