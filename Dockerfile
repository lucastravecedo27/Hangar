# Hangar — imagen de producción (Gunicorn + PostgreSQL vía DATABASE_URL)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements-servidor.txt .
RUN pip install -r requirements-servidor.txt

COPY . .
# El permiso de ejecución se pierde al copiar la carpeta entre equipos: se fija aquí siempre.
# Los archivos copiados desde el Mac llegan con permisos 600 (solo el dueño los lee) y el
# contenedor corre como el usuario "hangar", sin privilegios: se abren para lectura a todos.
RUN chmod -R a+rX /app && chmod +x /app/entrypoint.sh \
 && useradd -r -u 10001 hangar && mkdir -p /app/datos && chown -R hangar:hangar /app/datos
USER hangar

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/login',timeout=4)" || exit 1

# El entrypoint crea/actualiza el esquema (una sola vez, antes de abrir los workers).
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
