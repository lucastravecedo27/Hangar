"""Configuración por variables de entorno.

Todo lo que cambia entre el portátil y el servidor sale de aquí: la base de datos, la clave de
sesión, si las cookies exigen HTTPS… Nada de esto se escribe en el código ni en la base.
Un archivo `.env` en la raíz se lee al arrancar (sin pisar variables ya definidas).
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_dotenv(ruta=RAIZ / ".env"):
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        os.environ.setdefault(clave, valor)


_cargar_dotenv()


def _bool(nombre, defecto=False):
    v = os.environ.get(nombre)
    if v is None:
        return defecto
    return v.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# --- Base de datos ---
# Escritorio (por defecto): SQLite en datos/hangar.db, sin instalar nada.
# Servidor: DATABASE_URL=postgresql://usuario:clave@host:5432/hangar (lo pone docker-compose).
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{RAIZ / 'datos' / 'hangar.db'}"
MOTOR = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgres"
ES_ESCRITORIO = MOTOR == "sqlite"
ZONA_HORARIA = os.environ.get("TZ", "America/Bogota")

# --- Sesión y seguridad ---
SECRET_KEY = os.environ.get("SECRET_KEY")            # si falta, se genera y guarda en datos/secret.key
ENTORNO = os.environ.get("HANGAR_ENTORNO", "produccion")   # produccion | desarrollo
DEPURAR = ENTORNO == "desarrollo" and _bool("HANGAR_DEBUG", False)
# En el escritorio la app corre en http://127.0.0.1: exigir HTTPS a la cookie impediría entrar.
COOKIE_SEGURA = _bool("COOKIE_SEGURA", ENTORNO == "produccion" and not ES_ESCRITORIO)
HORAS_SESION = int(os.environ.get("HORAS_SESION", "12"))
MAX_SUBIDA_MB = int(os.environ.get("MAX_SUBIDA_MB", "20"))
INTENTOS_LOGIN = int(os.environ.get("INTENTOS_LOGIN", "8"))          # por usuario/IP en 15 min
MINUTOS_BLOQUEO_LOGIN = int(os.environ.get("MINUTOS_BLOQUEO_LOGIN", "15"))
LONGITUD_MINIMA_PASSWORD = int(os.environ.get("LONGITUD_MINIMA_PASSWORD", "8"))
# Detrás de Caddy/Nginx: cuántos proxies hay delante para fiarse de X-Forwarded-*
PROXIES_DELANTE = int(os.environ.get("PROXIES_DELANTE", "1"))

# --- Correo: si se definen aquí mandan sobre lo guardado en Ajustes ---
SMTP_ENV = {
    "servidor": os.environ.get("SMTP_SERVIDOR"),
    "puerto": os.environ.get("SMTP_PUERTO"),
    "usuario": os.environ.get("SMTP_USUARIO"),
    "password": os.environ.get("SMTP_PASSWORD"),
    "remitente": os.environ.get("SMTP_REMITENTE"),
    "nombre_remitente": os.environ.get("SMTP_NOMBRE"),
    "seguridad": os.environ.get("SMTP_SEGURIDAD"),
    "responder_a": os.environ.get("SMTP_RESPONDER_A"),
}

PUERTO = int(os.environ.get("PUERTO", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0")
