#!/bin/bash
# Deja un VPS Ubuntu/Debian recién creado listo para Hangar. Se corre UNA vez, como root,
# normalmente a través de:  ./desplegar.sh preparar root@IP DOMINIO CORREO
#
#   · instala Docker y Docker Compose
#   · firewall: sólo SSH, 80 y 443
#   · 2 GB de swap si el servidor no tiene (evita que el build se quede sin memoria)
#   · actualizaciones de seguridad automáticas
#   · crea /opt/hangar/.env con SECRET_KEY y contraseñas de base aleatorias (si no existe)
set -euo pipefail

DOMINIO="${1:?uso: preparar-vps.sh DOMINIO CORREO}"
CORREO="${2:?falta el CORREO para los avisos del certificado HTTPS}"
DIR=/opt/hangar

paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "Córrelo como root (o con sudo)."; exit 1; }
export DEBIAN_FRONTEND=noninteractive

paso "Actualizando paquetes del sistema"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq curl ca-certificates ufw unattended-upgrades rsync

paso "Instalando Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker compose version

paso "Firewall: sólo SSH, HTTP y HTTPS"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable

paso "Memoria de intercambio (swap)"
if [ "$(swapon --show | wc -l)" = 0 ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap de 2 GB activado"
else
  echo "ya hay swap"
fi

paso "Actualizaciones de seguridad automáticas"
dpkg-reconfigure -f noninteractive unattended-upgrades

paso "Zona horaria America/Bogota"
timedatectl set-timezone America/Bogota || true

paso "Carpeta $DIR y archivo .env"
mkdir -p "$DIR/respaldos"
if [ -f "$DIR/.env" ]; then
  echo ".env ya existe: no se toca (las claves deben ser siempre las mismas)."
else
  # Hex: sin caracteres que rompan la DATABASE_URL (@, /, :, #…).
  SECRET=$(openssl rand -hex 32)
  PGSUPER=$(openssl rand -hex 24)
  PGAPP=$(openssl rand -hex 24)
  cat > "$DIR/.env" <<ENV
# Generado por preparar-vps.sh el $(date +%F). NUNCA subas este archivo a un repositorio.
# Guarda una copia de SECRET_KEY en un lugar seguro: cifra la contraseña SMTP guardada en la app.
DOMINIO=$DOMINIO
CORREO_TLS=$CORREO
SECRET_KEY=$SECRET
# Superusuario "postgres": sólo respaldos y mantenimiento; la app nunca lo usa.
POSTGRES_PASSWORD=$PGSUPER
# Rol "hangar" de la app, sin privilegios (Row-Level Security).
HANGAR_DB_PASSWORD=$PGAPP
# Superadministrador inicial: contraseña temporal aleatoria (sale al final de ./desplegar.sh).
SUPERADMIN_USUARIO=superadmin
SUPERADMIN_PASSWORD=
TZ=America/Bogota
# Workers de Gunicorn: 2 × núcleos + 1
WEB_CONCURRENCY=$(( $(nproc) * 2 + 1 ))
DIAS_RESPALDO=14

# Correo saliente (opcional; también se puede configurar desde Ajustes en la app).
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

IP=$(curl -fsS4 https://ifconfig.me || hostname -I | awk '{print $1}')
paso "Servidor listo"
echo "IP pública: $IP"
echo "Antes de desplegar, el DNS de $DOMINIO debe apuntar a $IP (registro A)."
