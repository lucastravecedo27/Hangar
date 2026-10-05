#!/bin/bash
# Despliegue de Hangar desde tu computador a un VPS, en un solo comando.
#
#   ./desplegar.sh preparar root@IP DOMINIO CORREO   # una sola vez, con el VPS recién creado
#   ./desplegar.sh preparar-compartido root@IP DOMINIO CORREO [PUERTO]
#                                                      # una sola vez, en un servidor con otras apps
#   ./desplegar.sh root@IP                             # cada vez que quieras publicar cambios
#   ./desplegar.sh root@IP logs                        # ver los logs de la app en vivo
#   ./desplegar.sh root@IP estado                      # contenedores y salud
#   ./desplegar.sh root@IP respaldo                    # copia de seguridad inmediata
#   ./desplegar.sh root@IP traer-respaldos             # baja las copias a ./respaldos de tu Mac
#
# Sube el código con rsync (no hace falta dar acceso a GitHub al servidor), saca un respaldo
# antes de tocar nada, reconstruye la imagen, reinicia y espera a que la app responda.
set -euo pipefail
cd "$(dirname "$0")"

DIR=/opt/hangar
paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
falla() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

if [ "${1:-}" = "preparar" ]; then
  SERVIDOR="${2:?uso: ./desplegar.sh preparar root@IP DOMINIO CORREO}"
  DOMINIO="${3:?falta el DOMINIO (p. ej. hangar.miempresa.com)}"
  paso "Preparando $SERVIDOR (Docker, firewall, swap, .env)…"
  CORREO="${4:?falta el CORREO para los avisos del certificado HTTPS}"
  ssh "$SERVIDOR" "bash -s -- '$DOMINIO' '$CORREO'" < servidor/preparar-vps.sh
  echo; echo "Ahora apunta el DNS de $DOMINIO a ese servidor y corre:  ./desplegar.sh $SERVIDOR"
  exit 0
fi

# Servidor que ya tiene otras apps y su propio Nginx en 80/443 (p. ej. el de Jaraba con CERNIVA):
# no instala nada ni toca el firewall; sólo crea /opt/hangar/.env para usar docker-compose.servidor.yml.
if [ "${1:-}" = "preparar-compartido" ]; then
  SERVIDOR="${2:?uso: ./desplegar.sh preparar-compartido root@IP DOMINIO CORREO [PUERTO]}"
  DOMINIO="${3:?falta el DOMINIO (p. ej. hangar.iote.com.co)}"
  CORREO="${4:?falta el CORREO}"
  paso "Preparando $SERVIDOR (servidor compartido: sólo /opt/hangar y .env)…"
  ssh "$SERVIDOR" "bash -s -- '$DOMINIO' '$CORREO' '${5:-8082}'" < servidor/preparar-servidor-compartido.sh
  echo; echo "Ahora:  ./desplegar.sh $SERVIDOR   y después el Nginx del host (servidor/nginx-hangar.conf)."
  exit 0
fi

SERVIDOR="${1:?uso: ./desplegar.sh root@IP [logs|estado|respaldo|traer-respaldos]}"
remoto() { ssh "$SERVIDOR" "cd $DIR && $*"; }

case "${2:-desplegar}" in
  logs)            remoto docker compose logs -f --tail=100 app; exit ;;
  estado)          remoto docker compose ps; exit ;;
  respaldo)        remoto docker compose exec -T respaldos sh /servidor/respaldos.sh ahora; exit ;;
  traer-respaldos) mkdir -p respaldos && rsync -av "$SERVIDOR:$DIR/respaldos/" respaldos/; exit ;;
  desplegar)       ;;
  *)               falla "acción desconocida: $2" ;;
esac

ssh "$SERVIDOR" "test -f $DIR/.env" || falla "El servidor no tiene $DIR/.env. Corre primero: ./desplegar.sh preparar $SERVIDOR DOMINIO"

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "Aviso: hay cambios sin commit; se despliega lo que hay en la carpeta."
fi
VERSION=$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)

paso "Respaldo previo (si ya estaba corriendo)"
remoto "docker compose ps --status running --services 2>/dev/null | grep -qx respaldos && docker compose exec -T respaldos sh /servidor/respaldos.sh ahora || echo 'primera vez: nada que respaldar'"

paso "Subiendo código a $SERVIDOR:$DIR"
# .env, respaldos y datos viven SÓLO en el servidor: se excluyen, así --delete nunca los borra.
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '.env' --exclude 'datos/' --exclude 'respaldos/' --exclude '.DS_Store' \
  ./ "$SERVIDOR:$DIR/"

paso "Construyendo y arrancando (versión $VERSION)"
remoto "HANGAR_VERSION=$VERSION docker compose up -d --build --remove-orphans && docker image prune -f >/dev/null"

paso "Esperando a que la app esté sana"
for i in $(seq 1 40); do
  salud=$(remoto "docker inspect -f '{{.State.Health.Status}}' \$(docker compose ps -q app)" 2>/dev/null || true)
  [ "$salud" = healthy ] && break
  [ "$i" = 40 ] && { remoto docker compose logs --tail=60 app; falla "La app no quedó sana. Arriba los últimos logs."; }
  sleep 3
done

# Primer despliegue: el superadministrador recién creado y su contraseña temporal.
remoto "docker compose logs app 2>/dev/null | grep -A3 'Superadministrador creado' | tail -4" || true

DOMINIO=$(ssh "$SERVIDOR" "grep '^DOMINIO=' $DIR/.env | cut -d= -f2")
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$DOMINIO/login" || true)
remoto docker compose ps
if [ "$CODIGO" = 200 ]; then
  printf '\n\033[1;32m✓ Hangar %s publicado en https://%s\033[0m\n' "$VERSION" "$DOMINIO"
else
  echo; echo "La app está sana, pero https://$DOMINIO respondió '$CODIGO'."
  echo "Si es el primer despliegue: revisa que el DNS apunte al servidor y mira 'docker compose logs caddy'."
fi
