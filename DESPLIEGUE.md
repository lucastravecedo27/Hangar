# Hangar · despliegue en servidor

Aplicación web Flask + PostgreSQL, servida por Gunicorn detrás de Caddy (HTTPS automático).
Todo corre con Docker Compose en un VPS Linux.

## 1. Requisitos del servidor

- Ubuntu 22.04/24.04 (o Debian) con 2 GB de RAM y 20 GB de disco.
- Docker y Docker Compose instalados:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # cerrar sesión y volver a entrar
  ```
- Un dominio (p. ej. `hangar.midominio.com`) con un registro **A** apuntando a la IP del VPS.
- Puertos **80** y **443** abiertos en el firewall del proveedor.

## 2. Instalación

```bash
# En el servidor
git clone <repositorio> hangar   # o subir la carpeta con scp/rsync
cd hangar
cp .env.example .env
nano .env        # DOMINIO, SECRET_KEY, POSTGRES_PASSWORD (y SMTP si se quiere)
docker compose up -d --build
docker compose logs -f app       # "Esquema listo y catálogos sembrados." y Gunicorn arrancando
```

Abre `https://TU_DOMINIO`. La primera vez la app pide **crear el superadministrador** (sin empresa:
es quien administra la plataforma). El superadministrador entra a su **Panel de clientes**
(`/admin`): ahí crea las empresas, sus usuarios (administradores, técnicos, pilotos), las activa o
desactiva y ve su actividad, sin ver los datos operativos de ninguna. Con «Entrar» puede ver la app
como esa empresa para dar soporte, y «Volver al panel» lo saca. Cada administrador de empresa crea
en *Ajustes › Usuarios de la app* las cuentas de su propia gente.

## 3. Migrar los datos de la versión de escritorio (SQLite)

Copia el archivo `datos/app.db` de la versión antigua al servidor y ejecútalo dentro del contenedor:

```bash
docker compose cp /ruta/app.db app:/tmp/app.db
docker compose exec app python manage.py migrar-sqlite /tmp/app.db "Nombre de la empresa"
```

Se copian todas las tablas a esa empresa (se crea si no existe): equipos, componentes con sus
horas, las 1.038 operaciones, órdenes, etc. Si es la primera empresa con datos se conservan los
`id`; si ya hay otras, se reasignan manteniendo las relaciones. El usuario `admin` antiguo también
se copia con su misma contraseña (si el nombre ya existe en otra empresa, se le añade un sufijo).

Para importar una bitácora Excel nueva en una empresa (sólo seriales que no estén ya importados):

```bash
docker compose cp "Datos de Bitacora.xlsx" app:/tmp/bitacora.xlsx
docker compose exec app python manage.py importar-bitacora /tmp/bitacora.xlsx "Nombre de la empresa"
```

## 4. Operación diaria

| Tarea | Comando |
|---|---|
| Ver estado | `docker compose ps` |
| Logs de la app | `docker compose logs -f app` |
| Actualizar el código | `git pull && docker compose up -d --build` |
| Copia de seguridad de la base | `docker compose exec db pg_dump -U hangar hangar \| gzip > respaldo_$(date +%F).sql.gz` |
| Restaurar una copia | `gunzip -c respaldo.sql.gz \| docker compose exec -T db psql -U hangar hangar` |
| Listar empresas | `docker compose exec app python manage.py empresas` |
| Crear una empresa | `docker compose exec app python manage.py crear-empresa "Nombre"` |
| Restablecer clave de un admin de empresa | `docker compose exec app python manage.py crear-admin NOMBRE "Empresa"` |
| Crear / restablecer un superadministrador | `docker compose exec app python manage.py crear-admin NOMBRE` |
| Listar usuarios | `docker compose exec app python manage.py usuarios` |
| Completar clima y dosis desde la bitácora (sólo campos vacíos) | `docker compose exec app python manage.py completar-bitacora /tmp/bitacora.xlsx "Empresa"` |
| Foto del estado del día (disponibilidad histórica) | `docker compose exec app python manage.py fotos-estado` |

> **PostgreSQL 15 o superior** es obligatorio (las imágenes Docker usan 16). Las claves foráneas
> compuestas usan `ON DELETE SET NULL (columna)`, que no existe en versiones anteriores.

Programa la foto diaria del estado de la flota (para la disponibilidad histórica) y la copia de seguridad en el servidor (`crontab -e`):

```
50 23 * * * cd /home/USUARIO/hangar && docker compose exec -T app python manage.py fotos-estado
0 3 * * * cd /home/USUARIO/hangar && docker compose exec -T db pg_dump -U hangar hangar | gzip > /home/USUARIO/respaldos/hangar_$(date +\%F).sql.gz && find /home/USUARIO/respaldos -mtime +30 -delete
```

## 5. Probar en tu computador

**Con Docker Desktop (recomendado):** doble clic en `probar-local.command` (macOS) o, en una terminal:

```bash
docker compose -f docker-compose.local.yml up --build
```

Abre http://localhost:8000. La primera vez pide crear la empresa y el usuario. Para cargar los datos
de la versión de escritorio (el `app.db` que está en `datos/`):

```bash
docker compose -f docker-compose.local.yml exec app python manage.py migrar-sqlite datos/app.db "Mi empresa"
```

Para apagar: `Ctrl+C` (o `docker compose -f docker-compose.local.yml down`). Los datos se conservan.

## 5b. Desarrollo local (sin Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
# Necesita un PostgreSQL local (o `docker run -e POSTGRES_PASSWORD=hangar -e POSTGRES_USER=hangar -e POSTGRES_DB=hangar -p 5432:5432 postgres:16`)
echo "DATABASE_URL=postgresql://hangar:hangar@localhost:5432/hangar" > .env
echo "HANGAR_ENTORNO=desarrollo" >> .env
python manage.py init
python app.py            # http://localhost:8000
```

Pruebas (usan una base aparte):

```bash
DATABASE_URL=postgresql://hangar:hangar@localhost:5432/hangar_pruebas python -m pytest pruebas -q
```

## 6. Seguridad incluida

- **Multi-empresa**: cada fila de datos lleva `empresa_id`; PostgreSQL aplica **Row-Level Security**
  (la conexión de cada petición fija `app.empresa_id` y la base filtra todo SELECT/UPDATE/DELETE y
  rellena/valida el `empresa_id` de cada INSERT). Las claves foráneas entre tablas de datos son
  compuestas `(empresa_id, id)`, así que ni con un error de la app una orden puede apuntar a un dron
  de otra empresa. Detalle en `DER.md`. Probado: la empresa B no ve, no edita ni puede crear nada
  sobre datos de A, ni por listado ni por id.
- **Acceso**: cuentas individuales con roles (`superadmin`, `admin`, `tecnico`, `piloto`); contraseñas con hash
  scrypt (Werkzeug); mínimo 8 caracteres; bloqueo tras 8 intentos fallidos en 15 min (por usuario)
  y 32 por IP; usuarios desactivables; sesión de 12 h que caduca.
- **Permisos**: el admin puede todo; técnico y piloto sólo modifican lo de su trabajo y nunca
  borran equipos, usuarios ni configuración (tabla `PERMISOS` / `SOLO_ADMIN` en `app.py`).
- **CSRF**: token por sesión en cabecera `X-CSRF-Token` (lo añade `app.js` a todo `fetch`) y en el
  formulario de acceso; además se comprueba que `Origin`/`Referer` sean del propio sitio.
- **Cookies**: `HttpOnly`, `SameSite=Lax`, `Secure` (sólo por HTTPS).
- **Cabeceras**: `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`; la API no se cachea.
- **Datos**: todas las consultas SQL parametrizadas; XSS mitigado escapando todo texto de usuario
  en la interfaz (incluidas comillas en atributos); la contraseña SMTP se guarda cifrada (Fernet
  con clave derivada de `SECRET_KEY`); subida máxima de 20 MB; sin modo depuración en producción.
- **Infraestructura**: la app corre como usuario sin privilegios en el contenedor; PostgreSQL y
  Gunicorn no se exponen a Internet (sólo Caddy en 80/443); secretos en `.env`, fuera del código.

Pendiente recomendable (no bloqueante): autenticación de dos factores, registro de auditoría por
usuario (quién cambió qué) y quitar `'unsafe-inline'` de la CSP moviendo los `<script>` de las
plantillas a archivos.

## 7. Escalabilidad: qué se midió y hasta dónde llega

Prueba de carga realizada con **64 drones, 94.426 operaciones (2 años), 2.650 componentes,
2.401 mantenimientos y 300 contactos** en PostgreSQL 16, Gunicorn (3 workers × 2 hilos) en un
contenedor de **2 CPU**:

| Pantalla / API | Tiempo de respuesta | Notas |
|---|---|---|
| Resumen | 150 ms | flota completa en 3 consultas (antes 3 por dron) |
| Inventario (`/api/equipos`) | 75 ms | |
| Operaciones (últimas 500) | 26 ms | |
| Mantenimiento / alertas | 60 ms | |
| Reportes (histórico completo) | 400 ms | 12 agregaciones sobre 94 k filas |
| Reportes (filtrado por fechas) | 320 ms | |
| Repuestos / proyección | 115 ms | |
| Bitácora | 115 ms | |
| Contactos | 70 ms | antes 9 s: se reescribió la consulta |
| Excel de operaciones (10.000 filas) | 7,5 s | tope sin filtros; con filtro de equipo 0,5 s |

Con **40 usuarios simultáneos** navegando (una acción cada 3-7 s): mediana 143 ms, p95 1,8 s,
0 errores. Con 25 usuarios pidiendo pantallas pesadas sin pausa (peor caso irreal): 13,7 req/s,
0 errores, p95 4,6 s — el límite lo pone la CPU, no la base de datos.

Para crecer: más CPU en el VPS y subir `--workers` en el Dockerfile (regla: 2 × núcleos + 1);
PostgreSQL con estos volúmenes ocupa 31 MB, así que la base no es el problema hasta millones
de operaciones. Con varias empresas en la misma instancia, cada consulta va acotada por el índice
de `empresa_id`, así que el coste por pantalla depende del tamaño de esa empresa, no del total.
