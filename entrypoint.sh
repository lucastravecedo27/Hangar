#!/bin/sh
# Espera a la base de datos, aplica el esquema y siembra catálogos; luego arranca lo que se le pida.
set -e
for i in $(seq 1 30); do
  if python manage.py init >/tmp/init.log 2>&1; then cat /tmp/init.log; break; fi
  echo "esperando a la base de datos ($i)…"; sleep 2
  [ "$i" = 30 ] && { cat /tmp/init.log; exit 1; }
done
exec "$@"
