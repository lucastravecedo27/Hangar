#!/bin/bash
# Arranca el servidor local y abre Hangar como aplicación: sin barra de direcciones, sin
# pestañas y a pantalla completa. Al cerrar la ventana se apaga el servidor.
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
PUERTO=8901

# Todo lo que hace el arranque queda registrado: si algo falla al hacer doble clic, el motivo
# está aquí en vez de perderse en silencio.
mkdir -p "$RAIZ/datos"
REGISTRO="$RAIZ/datos/arranque.log"
echo "--- $(date '+%Y-%m-%d %H:%M:%S') arrancando Hangar ---" >> "$REGISTRO"
registrar(){ echo "$(date '+%H:%M:%S') $*" >> "$REGISTRO"; }
URL="http://localhost:$PUERTO"
PERFIL="$RAIZ/datos/navegador"

PID_SERVIDOR="$RAIZ/datos/servidor.pid"

# Mata TODO servidor de Hangar que siga vivo: el de un arranque anterior que no se cerró bien, y
# el nuestro al terminar. Se identifica por la ruta de app.py, no sólo por el puerto, para no
# tocar jamás un proceso ajeno que casualmente estuviera escuchando en el 8901.
matar_servidores(){
  local objetivos=""
  # 1) El PID que dejó anotado el arranque anterior.
  if [ -f "$PID_SERVIDOR" ]; then
    local viejo; viejo="$(cat "$PID_SERVIDOR" 2>/dev/null)"
    if [ -n "$viejo" ] && ps -p "$viejo" -o command= 2>/dev/null | grep -q "$RAIZ/app.py"; then
      objetivos="$objetivos $viejo"
    fi
  fi
  # 2) Cualquier python ejecutando NUESTRO app.py por ruta absoluta (así lo arranca este script).
  objetivos="$objetivos $(pgrep -f "$RAIZ/app.py" 2>/dev/null | grep -vx -e "$$" -e "$PPID")"
  # 3) Quien ocupe el puerto. No basta con mirar la línea de comandos: los arranques antiguos
  #    (y el «Iniciar App.command») lanzaban `python app.py` con ruta RELATIVA, así que ahí no
  #    aparece la carpeta. Se confirma comparando el directorio de trabajo del proceso.
  for p in $(lsof -nP -tiTCP:$PUERTO -sTCP:LISTEN 2>/dev/null); do
    ps -p "$p" -o command= 2>/dev/null | grep -q "app\.py" || continue
    local cwd; cwd="$(lsof -a -d cwd -Fn -p "$p" 2>/dev/null | sed -n 's/^n//p' | head -1)"
    [ "$cwd" = "$RAIZ" ] && objetivos="$objetivos $p"
    # La versión anterior de Hangar (antes de unificar) también usaba este puerto.
    ps -p "$p" -o command= 2>/dev/null | grep -q "Plantilla app /app.py" && objetivos="$objetivos $p"
    case "$cwd" in *"/Plantilla app "*) objetivos="$objetivos $p";; esac
  done

  objetivos="$(echo $objetivos | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u | tr '\n' ' ')"
  [ -z "$(echo $objetivos)" ] && { rm -f "$PID_SERVIDOR"; return 0; }
  registrar "cerrando servidor(es) anterior(es): $(echo $objetivos)"
  kill $objetivos >/dev/null 2>&1
  # Esperar a que suelten el puerto; si alguno se resiste, KILL.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep .2
    kill -0 $objetivos >/dev/null 2>&1 || break
  done
  kill -9 $objetivos >/dev/null 2>&1
  rm -f "$PID_SERVIDOR"
  return 0
}

# Apaga SÓLO el servidor que levantó esta ejecución.
#
# Al salir no se puede usar `matar_servidores`: ese barrido mata cualquier python que esté
# sirviendo la app, incluido el de OTRO arranque más reciente. Pasaba al abrir el icono con la
# app ya abierta: el arranque nuevo cerraba la ventana del viejo, el script viejo se despertaba,
# veía que ya no tenía ventana y apagaba de paso el servidor recién levantado. Resultado: la app
# se quedaba muerta. El barrido global sigue haciéndose al ARRANCAR, que es donde tiene sentido.
apagar_mi_servidor(){
  [ -z "$SERVIDOR" ] && return 0
  kill "$SERVIDOR" >/dev/null 2>&1
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep .2
    kill -0 "$SERVIDOR" >/dev/null 2>&1 || break
  done
  kill -9 "$SERVIDOR" >/dev/null 2>&1
  # El archivo de PID sólo se borra si sigue siendo el nuestro: si otro arranque ya escribió el
  # suyo, borrarlo dejaría al siguiente sin saber a quién cerrar.
  [ "$(cat "$PID_SERVIDOR" 2>/dev/null)" = "$SERVIDOR" ] && rm -f "$PID_SERVIDOR"
  return 0
}

# Cerrar el servidor también si la app se interrumpe, no sólo al cerrar la ventana.
limpiar(){
  [ -n "$CHROME" ] && kill "$CHROME" >/dev/null 2>&1
  apagar_mi_servidor
  return 0
}
trap limpiar EXIT INT TERM

aviso(){ osascript -e "display dialog \"$1\" buttons {\"Entendido\"} default button 1 with title \"Hangar\"" >/dev/null 2>&1; }

# --- Entorno de Python ---
if [ ! -d ".venv" ]; then
  PY="$(command -v python3 || true)"
  if [ -z "$PY" ]; then
    aviso "Falta Python 3. Instálalo desde python.org o con las Herramientas de línea de comandos de Xcode y vuelve a abrir Hangar."
    exit 1
  fi
  "$PY" -m venv .venv || { aviso "No pude crear el entorno de Python."; exit 1; }
fi
registrar "python: $(./.venv/bin/python --version 2>&1)"

# Instalar dependencias SÓLO cuando hace falta. Antes se llamaba a pip en cada arranque, y aunque
# no hubiera nada que instalar salía a consultar PyPI: con la red lenta eso añadía más de veinte
# segundos de espera con la pantalla en blanco. Ahora se guarda una huella de requirements.txt y
# se comprueba que los paquetes importan; si ambas cosas cuadran, pip no se ejecuta.
HUELLA="$RAIZ/datos/.dependencias"
ESPERADA="$(shasum requirements.txt 2>/dev/null | cut -d' ' -f1)"
if [ "$(cat "$HUELLA" 2>/dev/null)" = "$ESPERADA" ] \
   && ./.venv/bin/python -c "import flask, werkzeug, openpyxl, cryptography" >/dev/null 2>&1; then
  registrar "dependencias al día (sin pip)"
else
  registrar "instalando dependencias"
  if ./.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt >>"$REGISTRO" 2>&1; then
    echo "$ESPERADA" > "$HUELLA"
    registrar "dependencias instaladas"
  else
    registrar "pip falló; se sigue con lo que haya instalado"
  fi
fi

# --- Servidor: siempre uno nuevo ---
# Nunca se reaprovecha un servidor que ya estuviera corriendo. Uno viejo tiene en memoria el
# código y las plantillas de la versión anterior (con el modo depuración apagado Flask las
# cachea), así que la app se abría sin los últimos cambios. Se mata lo que haya y se arranca
# limpio, que cuesta menos de un segundo.
matar_servidores
registrar "levantando el servidor"
# Ruta ABSOLUTA a propósito: así el proceso se puede identificar luego con `pgrep -f` y matarlo
# sin ambigüedad, cosa imposible cuando la línea de comandos sólo decía «app.py».
# Primera vez tras unificar: se copian los datos de la versión anterior (la ruta la deja anotada
# la instalación en datos/.migrar-desde). Se hace al arrancar para no perder nada de lo que se
# haya registrado en la versión anterior hasta el último momento.
if [ ! -f "$RAIZ/datos/hangar.db" ] && [ -f "$RAIZ/datos/.migrar-desde" ]; then
  ORIGEN="$(cat "$RAIZ/datos/.migrar-desde")"
  if [ -f "$ORIGEN" ]; then
    registrar "migrando datos desde $ORIGEN"
    if ./.venv/bin/python "$RAIZ/manage.py" migrar-sqlite "$ORIGEN" 1 >>"$REGISTRO" 2>&1; then
      rm -f "$RAIZ/datos/.migrar-desde"; registrar "migración completa"
    else
      aviso "No pude copiar los datos de la versión anterior. El detalle está en datos/arranque.log."
    fi
  fi
fi

# Escritorio: SQLite, sólo accesible desde este equipo y en el puerto de siempre.
HANGAR_APP=1 HOST=127.0.0.1 PUERTO=$PUERTO ./.venv/bin/python "$RAIZ/app.py" >"$RAIZ/datos/servidor.log" 2>&1 &
SERVIDOR=$!
echo "$SERVIDOR" > "$PID_SERVIDOR"
LISTO=0
for _ in $(seq 1 60); do
  if curl -s -o /dev/null --max-time 1 "$URL/login"; then LISTO=1; break; fi
  # Si el proceso se cayó (puerto ocupado, error de importación…), no esperar los 18 segundos.
  kill -0 "$SERVIDOR" 2>/dev/null || break
  sleep .3
done
if [ "$LISTO" != "1" ]; then
  registrar "el servidor no respondió"
  aviso "Hangar no pudo arrancar el servidor. Revisa $RAIZ/datos/servidor.log"
  exit 1
fi
registrar "servidor listo en $URL (pid $SERVIDOR)"

# --- Navegador en modo aplicación ---
# --app quita barra de direcciones, pestañas y menús del navegador; el perfil propio evita que
# la ventana se cuelgue de una sesión de Chrome ya abierta (ahí se ignoraría la pantalla completa).
NAVEGADORES=(
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
  "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"
)
NAVEGADOR=""
for n in "${NAVEGADORES[@]}"; do [ -x "$n" ] && NAVEGADOR="$n" && break; done
registrar "navegador: ${NAVEGADOR:-ninguno}"

# La ventana arranca maximizada, no en pantalla completa: en macOS «--start-fullscreen» abre un
# Space aparte y el sistema no siempre te lleva a él, así que la app parecía no arrancar.
# Maximizada ocupa toda la pantalla, sigue sin barra de direcciones ni pestañas, y la pantalla
# completa de verdad se activa con la tecla F o el botón de la barra lateral.
# HANGAR_PANTALLA_COMPLETA=1 recupera el comportamiento anterior si se prefiere.
MODO_PANTALLA="--start-maximized"
[ -n "$HANGAR_PANTALLA_COMPLETA" ] && MODO_PANTALLA="--start-fullscreen"

if [ -n "$NAVEGADOR" ]; then
  # Una instancia previa con este mismo perfil se queda con la petición y el lanzador termina al
  # instante; se cierra antes para que la ventana nueva sea siempre visible.
  # Ojo: `pkill -f` casa también con este propio script (el patrón está en su línea de comandos),
  # así que se buscan los PID y se excluyen el nuestro y el de nuestro padre.
  ANTERIORES="$(pgrep -f -- "--user-data-dir=$PERFIL" 2>/dev/null | grep -vx -e "$$" -e "$PPID")"
  if [ -n "$ANTERIORES" ]; then
    registrar "cerrando instancia previa: $(echo $ANTERIORES)"
    echo "$ANTERIORES" | xargs kill 2>/dev/null
    # Hay que ESPERAR a que suelten el perfil, no dar por hecho que un segundo basta. Mientras
    # el perfil siga tomado, el Chrome nuevo le pasa la petición al viejo y se cierra al
    # instante; el vigilante de más abajo lo leía como «el usuario cerró la ventana» y apagaba
    # Hangar recién arrancado. Es lo que hacía que abrir el icono con la app ya abierta la
    # dejara muerta.
    for _ in $(seq 1 25); do
      sleep .2
      pgrep -f -- "--user-data-dir=$PERFIL" >/dev/null 2>&1 || break
    done
    pgrep -f -- "--user-data-dir=$PERFIL" >/dev/null 2>&1 && {
      registrar "la instancia previa no se cerró; se fuerza"
      pgrep -f -- "--user-data-dir=$PERFIL" | xargs kill -9 2>/dev/null
      sleep 1
    }
  fi

  "$NAVEGADOR" \
    --app="$URL" \
    --user-data-dir="$PERFIL" \
    $MODO_PANTALLA \
    --no-first-run \
    --no-default-browser-check \
    --disable-features=Translate,MediaRouter \
    --window-size=1600,1000 >/dev/null 2>&1 &
  CHROME=$!
  registrar "chrome lanzado (pid $CHROME) con $MODO_PANTALLA"

  # Traerla al frente: recién abierta puede quedar detrás de otras ventanas.
  sleep 2
  osascript -e 'tell application "Google Chrome" to activate' >/dev/null 2>&1 || true

  # Antes de vigilar, esperar a que la ventana exista de verdad: Chrome tarda un par de segundos
  # en levantar sus procesos de renderizado y sin esta espera el vigilante concluía que no hay
  # ventana antes de que hubiera dado tiempo a abrirla.
  for _ in $(seq 1 30); do
    [ -n "$(pgrep -P "$CHROME" -f -- "--type=renderer" 2>/dev/null)" ] && break
    kill -0 "$CHROME" 2>/dev/null || break
    sleep .5
  done
  registrar "ventana lista"

  # En macOS, Chrome sigue vivo aunque se cierre su última ventana, así que esperar al proceso no
  # basta. Cada ventana abierta tiene procesos de renderizado hijos: cuando no queda ninguno
  # durante dos comprobaciones seguidas, la ventana se cerró y toca apagar todo.
  sin_ventanas=0
  while kill -0 "$CHROME" 2>/dev/null; do
    sleep 3
    if [ -z "$(pgrep -P "$CHROME" -f -- "--type=renderer" 2>/dev/null)" ]; then
      sin_ventanas=$((sin_ventanas + 1))
      [ "$sin_ventanas" -ge 2 ] && break
    else
      sin_ventanas=0
    fi
  done
  registrar "sin ventanas: cerrando Hangar"
  kill "$CHROME" >/dev/null 2>&1
else
  # Sin navegador basado en Chromium: se abre en el predeterminado y la app avisa de cómo
  # ponerla a pantalla completa.
  open "$URL?modoapp=1"
  aviso "Hangar se abrió en tu navegador. Para verlo como aplicación a pantalla completa instala Google Chrome, Edge o Brave y vuelve a abrir el icono. Mientras tanto pulsa el botón «Pantalla completa» de la barra lateral."
  # Sin ventana propia que vigilar no se puede saber cuándo termina: el servidor se deja vivo y
  # con su PID anotado, y el próximo arranque lo matará antes de levantar el suyo.
  trap - EXIT INT TERM
  exit 0
fi

# La ventana se cerró: se apaga el servidor. El `trap` haría lo mismo al salir, pero se hace
# aquí de forma explícita para que quede anotado en el registro.
registrar "ventana cerrada"
apagar_mi_servidor
registrar "servidor detenido"
