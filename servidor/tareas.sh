#!/bin/sh
# Tareas programadas de Hangar dentro de Docker (servicio "tareas" de docker-compose.yml).
# Una vez al día, a HORA_FOTO (23:50 por defecto, hora de TZ), guarda la foto del estado de la flota.
set -u
HORA_FOTO="${HORA_FOTO:-23:50}"
cd /app
while true; do
  ahora=$(date +%s)
  objetivo=$(date -d "$HORA_FOTO" +%s)
  [ "$objetivo" -le "$ahora" ] && objetivo=$(date -d "tomorrow $HORA_FOTO" +%s)
  echo "próxima foto del estado: $(date -d "@$objetivo" '+%F %R')"
  sleep $((objetivo - ahora))
  python manage.py fotos-estado || echo "ERROR: fotos-estado falló"
  sleep 61   # no repetir en el mismo minuto
done
