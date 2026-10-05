#!/bin/bash
# Prepara /opt/hangar en un servidor que YA está en producción con otras apps (Rocky/RHEL o
# Debian/Ubuntu, con Docker y Nginx del host ya instalados). A diferencia de preparar-vps.sh,
# NO toca paquetes del sistema, firewall, swap, zona horaria ni Nginx: sólo comprueba y crea .env.
#   Normalmente se corre con:  ./desplegar.sh preparar-compartido root@IP DOMINIO CORREO
set -euo pipefail

DOMINIO="${1:?uso: preparar-servidor-compartido.sh DOMINIO CORREO [PUERTO]}"
CORREO="${2:?falta el CORREO}"
PUERTO="${3:-8082}"
DIR=/opt/hangar

paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
falla() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" = 0 ] || falla "Córrelo como root (o con sudo)."

paso "Comprobando lo que ya debe tener el servidor"
command -v docker >/dev/null || falla "No hay Docker."
docker compose version || falla "No hay el plugin 'docker compose'."
command -v nginx >/dev/null && echo "nginx del host: $(nginx -v 2>&1)" || echo "Aviso: no veo nginx en el host."
if ! command -v rsync >/dev/null; then
  echo "Instalando rsync (lo usa ./desplegar.sh para subir el código)…"
  if command -v dnf >/dev/null; then dnf install -y -q rsync; else apt-get install -y -qq rsync; fi
fi
if ss -ltn "( sport = :$PUERTO )" | grep -q LISTEN; then
  ss -ltnp "( sport = :$PUERTO )"
  falla "El puerto $PUERTO ya está ocupado. Vuelve a correrlo con otro puerto como 3er parámetro."
fi
echo "puerto $PUERTO libre"
if command -v getsebool >/dev/null; then
  getsebool httpd_can_network_connect || true
  echo "(debe estar 'on' para que Nginx pueda reenviar a 127.0.0.1:$PUERTO; si no: setsebool -P httpd_can_network_connect 1)"
fi

paso "Carpeta $DIR y archivo .env"
mkdir -p "$DIR/respaldos"
if [ -f "$DIR/.env" ]; then
  echo ".env ya existe: no se toca (las claves deben ser siempre las mismas)."
  grep -q '^COMPOSE_FILE=' "$DIR/.env" || echo "OJO: a ese .env le falta COMPOSE_FILE=docker-compose.yml:docker-compose.servidor.yml"
else
  SECRET=$(openssl rand -hex 32)
  PGSUPER=$(openssl rand -hex 24)
  PGAPP=$(openssl rand -hex 24)
  cat > "$DIR/.env" <<ENV
# Generado por preparar-servidor-compartido.sh el $(date +%F). NUNCA lo subas a un repositorio.
# Guarda una copia de SECRET_KEY en un lugar seguro: cifra la contraseña SMTP guardada en la app.

# Servidor compartido: sin Caddy, la app en 127.0.0.1:HANGAR_PUERTO detrás del Nginx del host.
COMPOSE_FILE=docker-compose.yml:docker-compose.servidor.yml
HANGAR_PUERTO=$PUERTO

DOMINIO=$DOMINIO
# Caddy no corre aquí, pero docker-compose.yml lo exige definido.
CORREO_TLS=$CORREO
SECRET_KEY=$SECRET
# Superusuario "postgres": sólo respaldos y mantenimiento; la app nunca lo usa.
POSTGRES_PASSWORD=$PGSUPER
# Rol "hangar" de la app, sin privilegios (Row-Level Security).
HANGAR_DB_PASSWORD=$PGAPP
SUPERADMIN_USUARIO=superadmin
SUPERADMIN_PASSWORD=
TZ=America/Bogota
# Servidor compartido con otras apps: 3 workers bastan para empezar.
WEB_CONCURRENCY=3
DIAS_RESPALDO=14

SMTP_SERVIDOR=
SMTP_PUERTO=587
SMTP_USUARIO=
SMTP_PASSWORD=
SMTP_REMITENTE=
SMTP_NOMBRE=Hangar · Control de flota aérea agrícola
SMTP_SEGURIDAD=starttls
ENV
  chmod 600 "$DIR/.env"
  echo ".env creado con claves aleatorias."
fi

paso "Listo"
echo "Siguiente: ./desplegar.sh <servidor>   (desde tu Mac)"
echo "Luego Nginx del host: servidor/nginx-hangar.conf -> /etc/nginx/conf.d/hangar.conf, nginx -t, reload, certbot."
