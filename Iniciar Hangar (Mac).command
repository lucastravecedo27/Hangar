#!/bin/bash
# Doble clic: levanta Hangar en http://localhost:8000 usando Postgres.app (sin Docker).
# La primera vez crea el entorno de Python, la base "hangar_local" y carga los datos de datos/app.db.
cd "$(dirname "$0")"
PG="/Applications/Postgres.app/Contents/Versions/latest/bin"
export PATH="$PG:$PATH"
echo "== Hangar · arranque local =="

PY=$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)
echo "Python: $PY ($($PY --version 2>&1))"
if [ ! -d .venv-local ]; then
  echo "Creando entorno de Python (solo la primera vez)…"
  "$PY" -m venv .venv-local || { echo "No pude crear el entorno de Python"; read -n1; exit 1; }
fi
source .venv-local/bin/activate
pip install -q --upgrade pip >/dev/null 2>&1
pip install -q -r requirements.txt || { echo "Falló la instalación de dependencias"; read -n1; exit 1; }

# Base de datos: usuario hangar SIN superusuario (así se aplica el aislamiento por empresa).
psql -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='hangar'" | grep -q 1 || \
  psql -d postgres -c "CREATE ROLE hangar LOGIN PASSWORD 'hangar';"
NUEVA=0
psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='hangar_local'" | grep -q 1 || \
  { psql -d postgres -c "CREATE DATABASE hangar_local OWNER hangar;"; NUEVA=1; }

export DATABASE_URL="postgresql://hangar:hangar@localhost:5432/hangar_local"
export HANGAR_ENTORNO=desarrollo COOKIE_SEGURA=0 PROXIES_DELANTE=0 TZ=America/Bogota
export SECRET_KEY="solo-para-pruebas-locales"

python manage.py init || { echo "Falló la preparación del esquema"; read -n1; exit 1; }
if [ "$NUEVA" = "1" ] && [ -f datos/app.db ]; then
  echo "Cargando tus datos desde datos/app.db…"
  python manage.py migrar-sqlite datos/app.db
fi
python - <<'PY'
from core import db
con = db.conectar(db.TODAS)
emp = con.execute("SELECT id FROM empresas ORDER BY id LIMIT 1").fetchone()
if not emp:
    eid = db.crear_empresa(con, "Empresa principal")
else:
    eid = emp["id"]
if not db.usuario_por_nombre(con, "admin_local"):
    db.crear_usuario(con, "admin_local", "hangar2026", "admin", nombre="Administrador local", empresa_id=eid)
    print("Usuario creado: admin_local / hangar2026")
# Superadministrador de la plataforma: usuarios, perfiles, permisos y correo de cada empresa.
if not db.usuario_por_nombre(con, "super_local"):
    db.crear_usuario(con, "super_local", "hangar2026", db.ROL_SUPERADMIN, nombre="Plataforma", empresa_id=None)
    print("Usuario creado: super_local / hangar2026 (panel de clientes)")
con.close()
PY

# Completa en las operaciones ya cargadas las ha programadas, dosis y clima de la bitácora
# (sólo campos vacíos: se puede correr siempre sin pisar correcciones hechas a mano).
BITACORA="../Informacion /Datos de Bitacora (7).xlsx"
if [ -f "$BITACORA" ]; then
  python manage.py completar-bitacora "$BITACORA" || echo "(no pude completar la bitácora; sigo)"
fi
# Foto del estado de hoy para la disponibilidad histórica.
python manage.py fotos-estado || true

( sleep 4 && open "http://localhost:8000" ) &
echo ""
echo "Hangar corriendo en http://localhost:8000"
echo "  Empresa:     admin_local / hangar2026"
echo "  Plataforma:  super_local / hangar2026  (usuarios, permisos y correo de cada empresa)"
echo "Para detenerla: cierra esta ventana o pulsa Ctrl+C."
# --reload: cuando Claude actualiza el código en esta carpeta, la app se reinicia sola.
python -m flask --app app run --host 127.0.0.1 --port 8000 --reload
