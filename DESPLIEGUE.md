# Hangar · despliegue en servidor

Aplicación web Flask + PostgreSQL, servida por Gunicorn detrás de Caddy (HTTPS automático).
Todo corre con Docker Compose en un VPS Linux.

## 0. Cómo encaja todo

```
Internet ──443──▶ caddy (HTTPS Let's Encrypt, estáticos con caché)
                    └──▶ app (Gunicorn, Flask)  ──▶ db (PostgreSQL 16, volumen pgdata)
                           └── volumen appdatos (fotos y PDF subidos)
                  tareas    → foto diaria del estado de la flota (23:50)
                  respaldos → pg_dump + archivos subidos cada día a las 03:00 en ./respaldos
```

Todo vive en `/opt/hangar` del VPS. El código se sube desde tu Mac con `./desplegar.sh`
(rsync: el servidor no necesita acceso a GitHub). `.env`, `respaldos/` y los volúmenes de
Docker existen **sólo en el servidor** y el despliegue nunca los toca.

## 1. Requisitos

- Un VPS **Ubuntu 24.04** con 2 GB de RAM o más y 20 GB de disco (Hetzner, DigitalOcean,
  Lightsail, Vultr…). Al crearlo, añade tu llave SSH (`cat ~/.ssh/id_ed25519.pub`).
- Un dominio o subdominio (p. ej. `hangar.miempresa.com`) con un registro **A** a la IP del VPS.
- En tu Mac: Docker Desktop (para probar) y `ssh`/`rsync` (ya vienen).

## 2. Primer despliegue (≈ 20 minutos)

```bash
# 0) Prueba en tu Mac el MISMO stack de producción (Caddy, respaldos, tareas):
make produccion-local          # → https://localhost (aviso de certificado local: normal)
make parar

# 1) Prepara el VPS una sola vez: Docker, firewall (22/80/443), swap, actualizaciones
#    automáticas y /opt/hangar/.env con SECRET_KEY y contraseñas de base aleatorias.
./desplegar.sh preparar root@IP_DEL_VPS hangar.miempresa.com tu@correo.com

# 2) Apunta el DNS (registro A) del dominio a IP_DEL_VPS y espera a que resuelva:
dig +short hangar.miempresa.com

# 3) Despliega. Respalda antes, sube el código, construye, arranca, espera a que esté sano
#    y (la primera vez) muestra el usuario y la contraseña temporal del superadministrador.
./desplegar.sh root@IP_DEL_VPS
```

> **Guarda una copia de `/opt/hangar/.env`** fuera del servidor (gestor de contraseñas).
> `SECRET_KEY` cifra la contraseña SMTP guardada en la app: si se pierde, hay que volver a escribirla.

En el primer arranque se crea solo el **superadministrador** (sin empresa: es quien administra la
plataforma). Su usuario es `SUPERADMIN_USUARIO` (por defecto `superadmin`) y su contraseña temporal
es `SUPERADMIN_PASSWORD` o, si lo dejaste vacío, una aleatoria que `./desplegar.sh` muestra al
terminar (también sale en `docker compose logs app | grep -A3 Superadministrador`).

Abre `https://TU_DOMINIO`, entra con esos datos y la app te obliga a **cambiar la contraseña** antes
de dejarte hacer nada más. Si se pierde, se restablece con `manage.py crear-admin` (tabla de abajo).
Por seguridad, en el servidor la pantalla de acceso nunca ofrece «crear superadministrador»: así
nadie puede reclamar la plataforma abriendo la página antes que tú.
El superadministrador entra a su **Panel de clientes**
(`/admin`): ahí crea las empresas, sus usuarios (administradores, técnicos, pilotos), las activa o
desactiva y ve su actividad, sin ver los datos operativos de ninguna. Con «Entrar» puede ver la app
como esa empresa para dar soporte, y «Volver al panel» lo saca. Cada administrador de empresa crea
en *Ajustes › Usuarios de la app* las cuentas de su propia gente.

## 2b. Servidor compartido (el de Jaraba: Rocky Linux + Nginx del host, junto a CERNIVA)

Si el servidor ya tiene otras apps y su propio Nginx con Certbot en 80/443, **no** uses
`./desplegar.sh preparar` (instala paquetes con apt, activa ufw y abriría Caddy en 80/443).
En su lugar:

```bash
# 1) Una vez: crea /opt/hangar/.env (claves aleatorias + COMPOSE_FILE) y comprueba Docker/puerto.
./desplegar.sh preparar-compartido root@IP hangar.tudominio.com tu@correo.com      # puerto 8082

# 2) Sube, construye y arranca. Caddy no se levanta; la app queda en 127.0.0.1:8082.
./desplegar.sh root@IP
```

3) En el servidor, el Nginx del host (plantilla en `servidor/nginx-hangar.conf`):

```bash
cp /opt/hangar/servidor/nginx-hangar.conf /etc/nginx/conf.d/hangar.conf
sed -i 's/DOMINIO/hangar.tudominio.com/' /etc/nginx/conf.d/hangar.conf
nginx -t && systemctl reload nginx
certbot --nginx -d hangar.tudominio.com
```

Con Cloudflare: registro A a la IP del servidor; si Certbot falla la validación, pon la nube en
gris, saca el certificado y vuelve a naranja (SSL/TLS en *Full (strict)*).

`docker-compose.servidor.yml` es lo único distinto: apaga Caddy y publica la app sólo en
`127.0.0.1`. Gracias a `COMPOSE_FILE` en el `.env`, en `/opt/hangar` basta `docker compose …`
sin `-f`. Todo lo demás de esta guía (respaldos, `manage.py`, restaurar) es igual.

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

Desde tu Mac:

| Tarea | Comando |
|---|---|
| Publicar cambios | `./desplegar.sh root@IP` (o `make desplegar SERVIDOR=root@IP`) |
| Estado de los contenedores | `./desplegar.sh root@IP estado` |
| Logs de la app en vivo | `./desplegar.sh root@IP logs` |
| Copia de seguridad ya | `./desplegar.sh root@IP respaldo` |
| Bajar las copias a tu Mac | `./desplegar.sh root@IP traer-respaldos` |

En el servidor (`ssh root@IP` y `cd /opt/hangar`):

| Tarea | Comando |
|---|---|
| Logs de cualquier servicio | `docker compose logs -f caddy` (o `db`, `respaldos`, `tareas`) |
| Listar empresas | `docker compose exec app python manage.py empresas` |
| Crear una empresa | `docker compose exec app python manage.py crear-empresa "Nombre"` |
| Restablecer clave de un admin de empresa | `docker compose exec app python manage.py crear-admin NOMBRE "Empresa"` |
| Crear / restablecer un superadministrador | `docker compose exec app python manage.py crear-admin NOMBRE` |
| Listar usuarios | `docker compose exec app python manage.py usuarios` |
| Completar clima y dosis desde la bitácora (sólo campos vacíos) | `docker compose exec app python manage.py completar-bitacora /tmp/bitacora.xlsx "Empresa"` |
| Foto del estado del día a mano | `docker compose exec app python manage.py fotos-estado` |
| Más workers (más CPU) | cambia `WEB_CONCURRENCY` en `.env` y `docker compose up -d` |

**Respaldos.** El servicio `respaldos` guarda cada día a las 03:00 en `/opt/hangar/respaldos/`
la base (`hangar_FECHA.sql.gz`) y los archivos subidos (`archivos_FECHA.tar.gz`), 14 días
(`DIAS_RESPALDO` en `.env`). La foto diaria de la flota la hace el servicio `tareas`: ya no hace
falta `crontab`. Una copia que sólo está en el mismo VPS no protege si el VPS se pierde:
baja las copias con `traer-respaldos` cada semana, o activa los *snapshots* del proveedor.

**Restaurar** una copia (en el servidor, `cd /opt/hangar`):

```bash
docker compose stop app tareas
gunzip -c respaldos/hangar_FECHA.sql.gz | docker compose exec -T db psql -U postgres -d hangar -v ON_ERROR_STOP=1
docker compose run --rm -v "$PWD/respaldos:/r:ro" --entrypoint sh -u root app \
  -c "tar -xzf /r/archivos_FECHA.tar.gz -C /app/datos && chown -R hangar:hangar /app/datos"
docker compose start app tareas
```

> **PostgreSQL 15 o superior** es obligatorio (las imágenes Docker usan 16). Las claves foráneas
> compuestas usan `ON DELETE SET NULL (columna)`, que no existe en versiones anteriores.

## 5. Probar en tu computador

**Con Docker Desktop (recomendado):** doble clic en `probar-local.command` (macOS) o, en una terminal:

```bash
make local        # o: docker compose -f docker-compose.local.yml up --build
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

Pruebas (usan una base aparte). Con Docker basta `make pruebas`; sin Docker:

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
- **Rol de base sin privilegios**: la app se conecta como `hangar`, que NO es superusuario ni
  tiene `BYPASSRLS` (un superusuario se salta la RLS y vería todas las empresas). El superusuario
  `postgres` sólo lo usan los respaldos. Lo crea `db/01-rol-app.sh` la primera vez que arranca el volumen.
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
