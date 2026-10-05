# PostgreSQL con el script que crea el rol sin privilegios de la app. Se copia dentro de la imagen
# (y no con un volumen) para que el permiso de ejecución no dependa de cómo se copió la carpeta.
FROM postgres:16-alpine
COPY --chmod=755 01-rol-app.sh /docker-entrypoint-initdb.d/
