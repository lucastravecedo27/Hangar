# Hangar · modelo de datos (PostgreSQL, multi-empresa)

Tres capas:

1. **Sistema** — `empresas`, `usuarios`, `login_intentos`. Sin RLS; `usuarios` se filtra por `empresa_id` en el código.
2. **Catálogo global DJI** — `catalogo_piezas` (piezas con vida útil) y `catalogo_despiece` (despiece oficial). Compartido por todas las empresas, lo siembra la app desde `core/modelos.py` y `core/diagramas/*.json`.
3. **Datos de cada empresa** — todo lo demás. Cada tabla lleva `empresa_id` (con `DEFAULT empresa_actual()`) y una política **Row-Level Security** que filtra por la empresa fijada en la conexión (`app.empresa_id`). Las claves foráneas entre tablas de esta capa son **compuestas** `(empresa_id, id)`, así una fila nunca puede apuntar a otra empresa.

```mermaid
erDiagram
    empresas ||--o{ usuarios : "tiene"
    empresas ||--o{ equipos : "posee"
    empresas ||--o{ personal : "directorio"
    empresas ||--o{ meta : "configuración"
    empresas ||--o{ correo_cola : "bandeja"

    catalogo_piezas ||--o{ componentes : "instancia en cada dron"

    equipos ||--o{ componentes : "piezas con horas"
    equipos ||--o{ operaciones : "jornadas de vuelo"
    equipos ||--o{ mantenimientos : "bitácora"
    equipos ||--o{ ordenes_trabajo : "OT"
    equipos o|--o{ ordenes_servicio : "OS"
    equipos o|--o{ registros : "actividades"

    componentes o|--o{ mantenimientos : "pieza cambiada"
    componentes o|--o{ ot_tareas : "pieza a revisar"

    ordenes_trabajo ||--o{ ot_tareas : "trabajos"
    ordenes_servicio ||--o{ os_productos : "productos"
    ordenes_servicio ||--o{ os_eventos : "historial de estado"

    empresas {
        int id PK
        text nombre
        text nit
        int activa
    }
    usuarios {
        int id PK
        int empresa_id FK
        text usuario UK
        text password_hash
        text rol "superadmin|admin|tecnico|piloto"
        int activo
    }
    equipos {
        int id PK
        int empresa_id FK
        text nombre
        text modelo "T50|T70P|T100|T55|T100DB"
        text numero_serie
        float horas_totales
        text estado
    }
    catalogo_piezas {
        int id PK
        text modelo
        text clave
        text nombre
        float vida_util_horas
        float vida_util_meses
    }
    catalogo_despiece {
        int id PK
        text modelo
        text codigo
        text nombre
        text modulo_clave
        int n
    }
    componentes {
        int id PK
        int empresa_id FK
        int equipo_id FK
        int pieza_id FK
        float horas_uso
        text fecha_instalado
        text fecha_ultimo_cambio
    }
    operaciones {
        int id PK
        int empresa_id FK
        int equipo_id FK
        text fecha
        float horas_vuelo
        float hectareas
        float litros
        text piloto
        text cliente
        text lote
    }
    mantenimientos {
        int id PK
        int empresa_id FK
        int equipo_id FK
        int componente_id FK
        int pieza_id
        text fecha
        text motivo
        float horas_pieza
        float costo
    }
    ordenes_trabajo {
        int id PK
        int empresa_id FK
        text codigo "único por empresa"
        int equipo_id FK
        text estado
        text asignado_a
        text fecha_programada
    }
    ot_tareas {
        int id PK
        int empresa_id FK
        int orden_id FK
        int componente_id FK
        text descripcion
        text estado
    }
    ordenes_servicio {
        int id PK
        int empresa_id FK
        text codigo "único por empresa"
        int equipo_id FK
        text piloto
        text cliente
        text finca
        text fecha
        text estado
    }
    os_productos {
        int id PK
        int empresa_id FK
        int orden_id FK
        text nombre
        text dosis
    }
    os_eventos {
        int id PK
        int empresa_id FK
        int orden_id FK
        text estado
        text usuario
    }
    registros {
        int id PK
        int empresa_id FK
        int equipo_id FK
        text titulo
        text estado
        text vence
    }
    personal {
        int id PK
        int empresa_id FK
        text nombre
        text rol
        text email
    }
    meta {
        int empresa_id PK_FK
        text clave PK
        text valor
    }
    correo_cola {
        int id PK
        int empresa_id FK
        text para
        text asunto
        text estado
    }
```

## Relaciones (resumen)

| Hija | Columna | Padre | Al borrar el padre | Nota |
|---|---|---|---|---|
| usuarios | empresa_id | empresas | CASCADE | usuario único global |
| equipos, personal, meta, correo_cola, … | empresa_id | empresas | CASCADE | todas las tablas de datos |
| componentes | (empresa_id, equipo_id) | equipos | CASCADE | uno por pieza del catálogo del modelo |
| componentes | pieza_id | catalogo_piezas | CASCADE | catálogo global |
| operaciones | (empresa_id, equipo_id) | equipos | CASCADE | suma horas a equipo y componentes |
| mantenimientos | (empresa_id, equipo_id) | equipos | CASCADE | |
| mantenimientos | (empresa_id, componente_id) | componentes | SET NULL | guarda pieza_id/horas_pieza aparte para no perder historial |
| ordenes_trabajo | (empresa_id, equipo_id) | equipos | CASCADE | codigo único por empresa |
| ot_tareas | (empresa_id, orden_id) | ordenes_trabajo | CASCADE | |
| ot_tareas | (empresa_id, componente_id) | componentes | SET NULL | |
| ordenes_servicio | (empresa_id, equipo_id) | equipos | SET NULL | codigo único por empresa |
| os_productos, os_eventos | (empresa_id, orden_id) | ordenes_servicio | CASCADE | |
| registros | (empresa_id, equipo_id) | equipos | SET NULL | |

Convenciones: fechas en TEXTO ISO (`YYYY-MM-DD`), booleanos como INTEGER 0/1, `id` autonumérico en todas las tablas salvo `meta` (clave compuesta) y `login_intentos` (registro temporal).

## Flota mixta: drones y aviones (2026-09)

Todas estas tablas son **de empresa** (llevan `empresa_id`, RLS y FK compuestas `(empresa_id, id)`).
Requieren **PostgreSQL 15 o superior**: los `ON DELETE SET NULL (columna)` de las FK compuestas
ponen en NULL sólo la columna de la fila padre y no el `empresa_id`.

| Tabla | Para qué | Columnas clave |
|---|---|---|
| modelos_activo | modelos de dron / avión de la empresa (p. ej. Cessna 188A) | clave, tipo_activo (dron · avion), contadores, plantilla |
| contadores_equipo | contadores de cada activo y su valor inicial | equipo_id, contador (horas_vuelo · despegues · hobbs · tach · aterrizajes · arranques), valor_inicial |
| piezas_serie | piezas con número de serie (motor, hélice, magnetos, baterías) que viajan con su TSO/TSN | serial, uso_acumulado, ciclos_acumulados, equipo_id, componente_id |
| instalaciones | historial de montajes y desmontajes de cada pieza con serie | pieza_serie_id, equipo_id, desde, hasta, uso_al_montar, uso_al_desmontar |
| directivas | directivas de aeronavegabilidad (AD) y boletines de servicio (SB) | numero, tipo, recurrente, intervalo_*, limite_fecha, limite_valor |
| cumplimiento_directiva | cumplimiento por activo, firmado por el mecánico certificador | directiva_id, equipo_id, estado, firmado_por, licencia |
| documentos | certificados, seguros, licencias con vencimiento | equipo_id / personal_id, tipo, vence, archivo |
| tarifas | valor por hectárea por cliente y tipo de activo (rentabilidad) | cliente, tipo_activo, valor_ha, desde |
| auditoria | quién cambió qué (contadores, estado, baja, usos de piezas) | tabla, fila_id, campo, antes, despues, usuario |
| checklists | chequeo pre-vuelo: resultado apto · observaciones · no recomendado | equipo_id, fecha, piloto, resultado, items |
| estado_diario | **foto diaria** del estado de cada activo → disponibilidad histórica y MTTR | equipo_id, fecha (única por activo), estado (apto · observaciones · no_apto · taller · baja), motivos |

Columnas añadidas a tablas existentes:

- **equipos**: tipo_activo, matricula, anio, base, fabricante, fecha_baja, motivo_baja (los activos no se borran: se dan de baja y conservan su historial).
- **catalogo_piezas**: empresa_id (ítems propios), tipo_item (pieza · inspeccion), contador_base, contador_ciclos, limite_ciclos, tolerancia, serializada, referencia, precio.
- **componentes**: uso_inicial, ciclos_uso, ciclos_inicial, pieza_serie_id.
- **operaciones**: hobbs_ini/fin, tach_ini/fin, aterrizajes, arranques, combustible_gal, pista, tiempo_traslado, ha_programadas, dosis_objetivo, temperatura, humedad, viento, velocidad, altura. Se validan en el servidor (rangos: 0–24 h por jornada, 0–100 % humedad, −5–55 °C, lectura final ≥ inicial, fecha no futura).
- **mantenimientos / ot_tareas / ordenes_trabajo**: costo de repuesto y mano de obra, firma y licencia del certificador.
- **usuarios**: tema (sistema · claro · oscuro); rol admite `certificador` (mecánico certificador).
