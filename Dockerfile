# syntax=docker/dockerfile:1
# Hangar — imagen de producción (Gunicorn + PostgreSQL vía DATABASE_URL)

# --- Etapa 1: dependencias en un entorno virtual aparte (la imagen final no lleva pip cache) ---
FROM python:3.12-slim AS dependencias
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# requirements-servidor.txt incluye requirements.txt (-r): hay que copiar los dos.
# constraints.txt fija las versiones exactas probadas: dos builds en días distintos dan lo mismo.
COPY requirements.txt requirements-servidor.txt constraints.txt ./
RUN pip install -r requirements-servidor.txt -c constraints.txt

# --- Etapa 2: el código. Los archivos copiados desde el Mac pueden llegar con permisos 600 y el
# contenedor corre sin privilegios: se abren para lectura aquí, para que el ajuste no duplique
# en otra capa los ~180 MB de láminas y modelos 3D.
FROM python:3.12-slim AS fuente
COPY . /app
RUN chmod -R a+rX /app && chmod +x /app/entrypoint.sh

# --- Etapa 3: imagen final ---
FROM python:3.12-slim
LABEL org.opencontainers.image.title="Hangar" \
      org.opencontainers.image.description="Control de mantenimiento de flota aérea agrícola"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    # Workers de Gunicorn (regla: 2 × núcleos + 1). Se cambia en .env sin reconstruir.
    WEB_CONCURRENCY=3

# Usuario sin privilegios CON carpeta personal: Gunicorn ≥ 26 abre ahí su socket de control.
RUN useradd -r -m -u 10001 -d /home/hangar hangar
COPY --from=dependencias /opt/venv /opt/venv
COPY --from=fuente /app /app
WORKDIR /app
RUN mkdir -p /app/datos && chown hangar:hangar /app/datos
USER hangar

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/login',timeout=4)" || exit 1

# El entrypoint crea/actualiza el esquema (una sola vez, antes de abrir los workers).
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--threads", "2", \
     "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
