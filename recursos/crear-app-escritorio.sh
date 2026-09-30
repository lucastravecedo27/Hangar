#!/bin/bash
# Crea la aplicación "Hangar" y deja su acceso directo en el Escritorio.
#
# Se construye con `osacompile`, que genera un paquete con un ejecutable real (el «applet» de
# AppleScript). Un bundle cuyo ejecutable es un script de shell lo rechaza LaunchServices sin
# mostrar ningún aviso: el doble clic no hace nada. Con el applet arranca siempre.
#
# La app vive en /Applications (o ~/Applications) a propósito: el Escritorio está sincronizado
# con iCloud y Google Drive, y un paquete .app dentro de una carpeta gestionada por un
# «file provider» tampoco arranca. En el Escritorio va sólo un alias.
set -e
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
LANZADOR="$RAIZ/recursos/lanzar.sh"

if [ -w /Applications ]; then
  DESTINO="/Applications"
else
  DESTINO="$HOME/Applications"
  mkdir -p "$DESTINO"
fi
APP="$DESTINO/Hangar.app"

rm -rf "$HOME/Desktop/Hangar.app" "$APP"

# El applet ejecuta el lanzador de forma SÍNCRONA y sigue vivo mientras dure la ventana de la app.
# Con «nohup ... &» el applet terminaba al instante y macOS se llevaba por delante el proceso en
# segundo plano: el doble clic no hacía nada. El «with timeout» evita que AppleScript corte a los
# dos minutos, que es su límite por omisión.
FUENTE="$(mktemp /tmp/hangar_XXXX.applescript)"
cat > "$FUENTE" <<APPLESCRIPT
on run
	with timeout of 86400 seconds
		do shell script quoted form of "$LANZADOR" & " > /dev/null 2>&1 || true"
	end timeout
end run
APPLESCRIPT

osacompile -o "$APP" "$FUENTE"
rm -f "$FUENTE"

# Icono propio. No basta con sobrescribir applet.icns: osacompile deja también un Assets.car con
# el icono del applet y una clave CFBundleIconName que lo apunta, y en macOS moderno el catálogo
# de assets gana sobre CFBundleIconFile (el resultado era un icono en blanco). Se borra el
# catálogo, se quita CFBundleIconName y se instala el icns con nombre propio.
rm -f "$APP/Contents/Resources/applet.icns" "$APP/Contents/Resources/Assets.car"
cp "$RAIZ/recursos/hangar.icns" "$APP/Contents/Resources/hangar.icns"

# Nombre y datos del paquete.
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Hangar" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleName string Hangar" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName Hangar" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string Hangar" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier co.hangaruav.escritorio" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string co.hangaruav.escritorio" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 1.1" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile hangar" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string hangar" "$PLIST"

xattr -cr "$APP" 2>/dev/null || true

# VOLVER A FIRMAR: osacompile deja el paquete firmado, y cambiar el icono o el Info.plist rompe
# esa firma. Con la firma rota LaunchServices se niega a abrir la app y no muestra ningún aviso
# (el doble clic simplemente no hace nada), aunque el binario sí funcione si se ejecuta a mano.
codesign --remove-signature "$APP" >/dev/null 2>&1 || true
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
codesign --verify --deep "$APP" >/dev/null 2>&1 && echo "firma correcta" || echo "AVISO: no se pudo firmar el paquete"

touch "$APP"

# La caché de iconos de macOS guarda el icono anterior (el blanco) por ruta; sin vaciarla el
# Escritorio y el Dock siguen mostrando el viejo aunque el paquete ya sea correcto.
rm -rf "$HOME/Library/Caches/com.apple.iconservices.store" 2>/dev/null || true
find /private/var/folders -maxdepth 4 -name com.apple.iconservices -type d -user "$(id -un)" \
  -exec rm -rf {} + 2>/dev/null || true
killall iconservicesagent >/dev/null 2>&1 || true
killall iconservicesd >/dev/null 2>&1 || true

LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$APP" >/dev/null 2>&1

# Alias en el Escritorio apuntando a la app real.
osascript >/dev/null 2>&1 <<ALIAS || true
tell application "Finder"
	set elEscritorio to path to desktop folder as alias
	try
		delete (every item of elEscritorio whose name is "Hangar" or name is "Hangar alias")
	end try
	make new alias file at elEscritorio to (POSIX file "$APP" as alias)
	set name of result to "Hangar"
	set desktop position of (item "Hangar" of elEscritorio) to {1180, 60}
end tell
ALIAS

killall Finder >/dev/null 2>&1 || true

echo "Aplicación: $APP"
echo "Acceso directo: $HOME/Desktop/Hangar"
