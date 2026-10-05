#!/bin/sh
# Copias de seguridad de Hangar (corre en el contenedor "respaldos", imagen postgres:16-alpine).
#   respaldos.sh programar  -> deja cron a las 03:00 todos los días (lo que usa docker-compose)
#   respaldos.sh ahora      -> una copia inmediata:  docker compose exec respaldos sh /servidor/respaldos.sh ahora
# Cada copia son dos archivos en ./respaldos del servidor:
#   hangar_FECHA.sql.gz       base de datos completa (pg_dump)
#   archivos_FECHA.tar.gz     fotos y PDF que subieron los usuarios (volumen appdatos)
set -eu

copia() {
  sello=$(date +%F_%H%M)
  destino=/respaldos
  mkdir -p "$destino"
  echo "[$(date '+%F %T')] respaldo $sello…"
  pg_dump --clean --if-exists | gzip -9 > "$destino/.hangar_$sello.sql.gz"
  mv "$destino/.hangar_$sello.sql.gz" "$destino/hangar_$sello.sql.gz"
  tar -czf "$destino/.archivos_$sello.tar.gz" -C /appdatos .
  mv "$destino/.archivos_$sello.tar.gz" "$destino/archivos_$sello.tar.gz"
  find "$destino" -name 'hangar_*.sql.gz' -mtime +"${DIAS_RESPALDO:-14}" -delete
  find "$destino" -name 'archivos_*.tar.gz' -mtime +"${DIAS_RESPALDO:-14}" -delete
  echo "[$(date '+%F %T')] listo: $(du -h "$destino/hangar_$sello.sql.gz" | cut -f1) base, $(du -h "$destino/archivos_$sello.tar.gz" | cut -f1) archivos"
}

case "${1:-ahora}" in
  ahora) copia ;;
  programar)
    # crond de busybox lee un archivo por usuario dentro de la carpeta -c
    mkdir -p /tmp/crontabs
    echo "0 3 * * * sh /servidor/respaldos.sh ahora" > /tmp/crontabs/root
    echo "respaldos programados a las 03:00 ($TZ), se guardan ${DIAS_RESPALDO:-14} días"
    exec crond -f -l 8 -c /tmp/crontabs -L /dev/stdout
    ;;
  *) echo "uso: respaldos.sh [ahora|programar]"; exit 1 ;;
esac
