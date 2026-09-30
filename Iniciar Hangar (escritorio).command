#!/bin/bash
# Arranca Hangar en este Mac con el mismo lanzador que Hangar.app (puerto 8901, sólo este equipo,
# entorno virtual y dependencias al día, migración de datos la primera vez).
exec "$(dirname "$0")/recursos/lanzar.sh"
