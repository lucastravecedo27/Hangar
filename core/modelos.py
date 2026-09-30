"""Registro de modelos de dron: qué modelos maneja la app y con qué datos cuenta cada uno.

Hasta ahora la app era de un solo modelo (T50) y el catálogo de piezas, las láminas de despiece
y el modelo 3D estaban escritos a pelo. Aquí viven ahora los cinco modelos de la flota, cada uno
con sus propias fuentes:

    · `diagramas`  -> core/diagramas/<archivo>.json, las láminas y el despiece completo
    · `imagenes`   -> subcarpeta de static_shell/diagramas donde están esas láminas
    · `modelo3d`   -> GLB del despiece, si el fabricante lo ha entregado
    · `catalogo`   -> piezas con vida útil, que son las que generan alertas de mantenimiento

Un modelo puede tener unas fuentes y otras no: el T50 tiene despiece 3D y lista de vida útil en
horas, el T100 y el T70P tienen láminas y su tabla de mantenimiento V1.1 y el T55 sólo garantías.
La app funciona con lo que haya y lo dice en pantalla.
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DIAGRAMAS = Path(__file__).resolve().parent / "diagramas"
DIR_IMAGENES = RAIZ / "static_shell" / "diagramas"
DIR_MODELOS_3D = RAIZ / "static_shell" / "modelos"


# ---------- Piezas con vida útil ----------
# Formato: (clave, módulo, nombre, vida útil en horas, vida útil en meses, nota, malla 3D)
# `vida_horas` a 0 significa que el fabricante no publica vida en horas para esa pieza; entonces
# manda el plazo en meses. Si están los dos, salta la alerta con el que se cumpla primero, que es
# como lo escribe DJI en sus tablas de garantía.

# T50/T25 — «T25&T50 Recommended Maintenance List» (DJI).
CATALOGO_T50 = [
    ("hose", "Sistema de aspersión", "Manguera de aspersión", 700, 0, "Revisar desgaste/roturas. Limpiar a diario con agua y detergente.", None),
    ("spray_tank", "Sistema de aspersión", "Tanque de aspersión", 700, 0, "Limpieza diaria con agua limpia, purgar la bomba.", "tanque"),
    ("hose_connector", "Sistema de aspersión", "Conector de manguera", 700, 0, "Verificar sellado; el aire que entra causa fallas.", None),
    ("motor", "Propulsión", "Motor", 700, 0, "Revisar holgura de rotor/estátor. Cada 100h o 1 mes.", "motor"),
    ("propeller_adapter", "Propulsión", "Adaptador de hélice", 700, 0, "Inspección visual diaria antes de operar.", None),
    ("esc", "Propulsión", "ESC (controlador de velocidad)", 700, 0, "Limpiar y revisar corrosión cada 6 meses.", None),
    ("propellers", "Propulsión", "Hélices", 700, 0, "Revisar deformación o rotura cada 100h/mes.", "helice"),
    ("propeller_gasket", "Propulsión", "Empaque de hélice", 300, 0, "Revisar desgaste cada 50h o medio mes.", None),
    ("arm_bolt", "Estructura", "Tornillería del brazo", 700, 0, "Revisar holgura al plegar el brazo.", None),
    ("arm_connector", "Estructura", "Conector de brazo (M1-M4)", 700, 0, "Revisar fisuras o deformación.", "brazo"),
    ("battery_slider", "Batería", "Riel de batería", 700, 0, "Reemplazar cada 2000 inserciones o revisar cada mes.", None),
    ("arm_fixing_screw", "Estructura", "Tornillos de fijación del brazo (x16)", 700, 0, "Revisar holgura del marco delantero/trasero.", None),
    ("landing_gear_screw", "Tren de aterrizaje", "Tornillos del tren de aterrizaje (x10 c/lado)", 700, 0, "Revisar holgura y desplazamiento.", "tren"),
    ("remote", "Control remoto", "Control remoto", 700, 0, "Revisar estado físico y encendido.", "control"),
    ("battery", "Batería", "Batería estándar", 700, 0, "Cada 700h o 1500 ciclos. Carga/descarga completa cada 3 meses.", "bateria"),
    ("charger", "Batería", "Cargador", 700, 0, "Revisar golpes, limpiar terminales y ventilador.", "cargador"),
    ("delivery_pump_kit", "Sistema de aspersión", "Bomba de suministro (cubierta/impulsor/manguito)", 500, 0, "Revisar eje roto, desgaste o fusión.", "bomba"),
    ("delivery_pump_motor", "Sistema de aspersión", "Motor de bomba de suministro", 700, 0, "Revisar corrosión en el puerto del motor.", None),
    ("centrifugal_module", "Sistema de aspersión", "Módulo aspersor centrífugo", 500, 0, "Revisar disco giratorio y tapa inferior del motor.", "aspersor"),
    ("centrifugal_motor", "Sistema de aspersión", "Motor de aspersor centrífugo", 700, 0, "Revisar corrosión del puerto del motor.", None),
    ("filter_level", "Sistema de aspersión", "Filtro y medidor de nivel", 700, 0, "Limpiar filtro y medidor de nivel de líquido.", "filtro"),
    ("flowmeter", "Sistema de aspersión", "Caudalímetro", 700, 0, "Revisar corrosión y encendido.", "caudalimetro"),
    ("radar_bracket", "Estructura", "Soporte de radar", 700, 0, "Revisar los 6 tornillos de fijación.", None),
    ("radar_front", "Radar", "Radar delantero", 700, 0, "Revisar defectos cosméticos y corrosión del puerto.", "radar_d"),
    ("radar_rear", "Radar", "Radar trasero", 700, 0, "Revisar defectos cosméticos y corrosión del puerto.", "radar_t"),
    ("rf_module", "Electrónica", "Módulo RF", 700, 0, "Limpiar y revisar corrosión.", None),
    ("aerial_electronics", "Electrónica", "Módulo de electrónica aérea", 700, 0, "Limpiar y revisar corrosión.", None),
    ("cable_board", "Electrónica", "Placa de distribución de cables", 700, 0, "Limpiar y revisar corrosión.", None),
    ("spraying_module", "Sistema de aspersión", "Módulo del sistema de aspersión", 700, 0, "Limpiar y revisar corrosión.", None),
    ("power_module", "Electrónica", "Módulo de distribución de potencia", 700, 0, "Limpiar con alcohol >=95%.", None),
    ("weight_sensor", "Sistema de aspersión", "Sensor de peso (x3)", 700, 0, "Revisar cable y firmeza de conexión.", None),
    ("aircraft_connector", "Estructura", "Conector de aeronave", 700, 0, "Revisar holgura o corrosión.", None),
    ("sdr_antenna", "Posicionamiento", "Antena SDR", 700, 0, "Limpiar y revisar corrosión.", "antena"),
    ("rtk_module", "Posicionamiento", "Módulo RTK", 700, 0, "Limpiar y revisar corrosión.", "rtk"),
    ("aircraft_cable", "Estructura", "Cableado de la aeronave", 700, 0, "Revisar roturas y sellos de conectores.", None),
    ("front_frame", "Estructura", "Marco delantero", 700, 0, "Revisar fisuras o roturas.", "marco_d"),
    ("rear_frame", "Estructura", "Marco trasero", 700, 0, "Revisar fisuras o roturas.", "marco_t"),
    ("middle_frame", "Estructura", "Marco central", 700, 0, "Revisar fisuras o roturas.", "marco_c"),
]

# T100 y T70P — «Maintenance Period Suggestion V1.1» (DJI). Es la tabla que manda para estos
# dos modelos: da para cada pieza el ciclo máximo de sustitución (casi siempre «700 hours/36
# months») y cada cuánto hay que inspeccionarla, que va en la nota. La bomba es la excepción:
# cabezal a las 500 h y motor a las 1000 h.
#
# Sólo se cronometran las horas de vuelo, como en el T50: el tope de 36 meses se deja fuera a
# propósito (decisión del 2026-09-26), para que las alertas de toda la flota salgan del mismo
# contador.
#
# Es el mismo tipo de documento que la «Recommended Maintenance List» del T50: horas de uso, no
# garantía. Las piezas que la tabla no recoge (cargadores, accesorios del control remoto, baliza,
# radar trasero, cargas de esparcido y elevación) no llevan plazo, igual que en el T50 no se
# cronometra lo que DJI no lista. La batería tampoco: DJI la limita a 1500 ciclos, y la app no
# cuenta ciclos.
_700 = (700, 0)

def _pieza(clave, modulo, nombre, plazo, nota, malla):
    horas, meses = plazo
    return (clave, modulo, nombre, horas, meses, nota, malla)

# Piezas comunes a los dos modelos, tal como las escribe la tabla de DJI.
_MANTENIMIENTO_T = [
    _pieza("aerial_electronics", "Electrónica", "Módulo de electrónica aérea (con barómetro)", _700,
           "DJI: inspección cada 6 meses. Desmontar, limpiar y revisar corrosión; comprobar que enciende y funciona.", "marco_t"),
    _pieza("cable_board", "Electrónica", "Placa de control de carga útil (distribución de cables)", _700,
           "DJI: inspección cada 6 meses. Limpiar y revisar corrosión; comprobar que enciende y funciona.", "marco_t"),
    _pieza("payload_adapter", "Electrónica", "Placa adaptadora de carga útil", _700,
           "DJI: inspección cada 6 meses. Limpiar y revisar corrosión; comprobar que enciende y funciona.", "marco_t"),
    _pieza("power_module", "Electrónica", "Placa de distribución de potencia y su conector", _700,
           "DJI: inspección mensual. Si la batería entra o sale con dificultad, limpiar los orificios de "
           "guía con bastoncillo y lubricante seco; limpiar el borne y el resorte con alcohol si hay cardenillo.", "marco_t"),
    _pieza("battery_slider", "Estructura", "Guía de la batería", _700,
           "DJI: revisión en cada jornada. Cambiar si la almohadilla está gastada hasta el plástico, falta un "
           "rodillo o se atasca, el gancho metálico está deformado o las pestañas laterales están rotas.", "bateria"),
    _pieza("battery_connector", "Batería", "Conector de la batería", _700,
           "DJI: inspección mensual. Limpiar con alcohol el borne y la lengüeta; cambiar el conector si la "
           "lengüeta está hundida o ennegrecida.", "bateria"),
    _pieza("frame", "Estructura", "Marco central, marcos delantero y trasero y tornillería", _700,
           "DJI: tornillería y conectores de brazo cada mes (par 30 kgf·cm con fijador de rosca medio; holgura "
           "brazo-conector máx. 2 mm); fisuras y corrosión del marco cada 6 meses.", "marco_c"),
    _pieza("arm_lock", "Estructura", "Brazos, palanca de bloqueo y perno de pliegue", _700,
           "DJI: revisión en cada jornada del recubrimiento y el tubo de carbono; palanca sin deformar y con el "
           "segundo enganche firme. Perno de pliegue cada mes: apretar la tuerca autoblocante a 20 kgf·cm.", "brazo"),
    _pieza("arm_power_line", "Estructura", "Cable de potencia del brazo", _700,
           "DJI: primera inspección a los 100 vuelos y después cada 100 h o cada mes. Revisar que no haya "
           "desgastado la cinta protectora en los cuatro conectores de brazo ni haya aislante a la vista.", "brazo"),
    _pieza("motor", "Propulsión", "Motor", _700,
           "DJI: primera inspección a los 100 vuelos y después cada 100 h o cada mes, y siempre tras un error de "
           "motor bloqueado o de temperatura. Sin tirones al girarlo, sin holgura en la base, tapa sin deformar.", "motor"),
    _pieza("esc", "Propulsión", "ESC (controlador de velocidad)", _700,
           "DJI: inspección cada 6 meses. Limpiar y revisar corrosión y holgura; ante error HMS, prueba cruzada con otro ESC.", "motor"),
    _pieza("propellers", "Propulsión", "Hélices", _700,
           "DJI: primera inspección a los 100 vuelos y después cada 100 h o cada mes. Cambiar si está deformada o "
           "fisurada; si tiene holgura, revisar el orificio (fisuras u ovalado) y cambiar la arandela.", "helice"),
    _pieza("propeller_clamp", "Propulsión", "Pinza de hélice", _700,
           "DJI: primera inspección a los 100 vuelos y después cada 100 h o cada mes. Apretar los tornillos a "
           "60 kgf·cm y limpiar la holgura; cambiarla si sigue bailando.", "helice"),
    _pieza("sdr_antenna", "Posicionamiento", "Antena SDR", _700,
           "DJI: inspección cada 6 meses. Limpiar y revisar corrosión; comprobar que funciona.", "antena"),
    _pieza("rtk_module", "Posicionamiento", "Módulo de antena RTK", _700,
           "DJI: inspección cada 6 meses. Limpiar y revisar corrosión; comprobar que funciona.", "rtk"),
    _pieza("fpv_module", "Percepción", "Módulo FPV", _700,
           "DJI: inspección cada 12 meses. Cambiar si está deformado o dañado.", "marco_d"),
    _pieza("radar_phased", "Radar", "Radar delantero de matriz en fase activa", _700,
           "DJI: inspección cada 6 meses. Golpes, corrosión en el conector y errores HMS (prueba cruzada con otro radar).", "radar_d"),
    _pieza("radar_bracket", "Radar", "Soportes del radar", _700,
           "DJI: inspección mensual del travesaño, el soporte y la base del radar. Tornillos flojos: cambiar y "
           "apretar a 15 kgf·cm con fijador de rosca medio.", "radar_d"),
    _pieza("landing_gear", "Tren de aterrizaje", "Tren de aterrizaje y su tornillería", _700,
           "DJI: tornillos cada mes (20 kgf·cm con fijador de rosca medio); fisuras del tren cada 12 meses.", "tren"),
    _pieza("delivery_pump_kit", "Sistema de aspersión", "Cabezal de la bomba de impulsor", (500, 0),
           "DJI: cambiar el cabezal cada 500 h. Inspección cada 100 h o cada mes: ejes rotos, desgaste o "
           "fundido en carcasa, ventilador y manguito; cambiar el anillo de sellado. Limpiar tras cada jornada.", "bomba"),
    _pieza("pump_motor", "Sistema de aspersión", "Motor de la bomba de impulsor", (1000, 0),
           "DJI: cambiar el motor cada 1000 h. Revisar corrosión en el conector y polvo pegado en el ventilador.", "bomba"),
    _pieza("centrifugal_module", "Sistema de aspersión", "Aspersor centrífugo", _700,
           "DJI: inspección cada 100 h o cada mes. Desgaste del disco inferior y de la tapa del motor, corrosión "
           "del conector (cambiar el anillo de sellado) y fijador de rosca en los tornillos de la lanza.", "aspersor"),
    _pieza("mist_sprinkler", "Sistema de aspersión", "Aspersor de niebla", _700,
           "DJI: inspección cada 100 h o cada mes. Prueba de caudal: el abanico de niebla debe salir uniforme.", "aspersor"),
    _pieza("flowmeter", "Sistema de aspersión", "Caudalímetro", _700,
           "DJI: inspección mensual. Limpiar y revisar corrosión; comprobar que funciona.", "caudalimetro"),
    _pieza("level_sensor", "Sistema de aspersión", "Filtro y medidor de nivel continuo", _700,
           "DJI: antes de cada jornada. Vaciar el tanque, sacar el filtro y limpiarlo; manguera del medidor "
           "bien sujeta (si se soltó, recalibrar) y sensor sin daños.", "filtro"),
    _pieza("vent_valve", "Sistema de aspersión", "Válvula solenoide de venteo", _700,
           "DJI: antes de cada jornada. Debe oírse al abrir y cerrar; si no sale agua, soltar la manguera antes "
           "de la válvula: si entonces sale, la válvula está atascada o averiada.", "aspersor"),
    _pieza("hose", "Sistema de aspersión", "Manguera de aspersión", _700,
           "DJI: antes de cada jornada. Tuberías de los brazos sin desgaste, pinzamientos ni fisuras. Tras la "
           "jornada, pasar agua limpia con detergente por todo el circuito.", "tanque"),
    _pieza("hose_connector", "Sistema de aspersión", "Racores de manguera", _700,
           "DJI: antes de cada jornada. Sin fugas ni fisuras en los racores del tanque: una entrada de aire "
           "falsea la dosis aplicada.", "tanque"),
    _pieza("spray_tank", "Sistema de aspersión", "Tanque de aspersión", _700,
           "DJI: inspección cada 6 meses. Aclarar con agua limpia al menos dos veces tras cada jornada.", "tanque"),
    _pieza("remote", "Control remoto", "Control remoto inteligente", _700,
           "DJI: inspección mensual. Limpiar y revisar corrosión; comprobar que enciende y funciona.", None),
    _pieza("battery", "Batería", "Batería inteligente", (0, 0),
           "DJI: vida de 1500 ciclos. Inspección cada 100 ciclos o cada mes: hinchada o deformada más de 2 mm "
           "no se usa; limpiar bornes con alcohol ≥95 %; cargar y descargar al menos una vez cada 3 meses.", "bateria"),
]

def _con(comunes, *, fuera=(), cambios=None, extra=()):
    """Lista de un modelo a partir de la común: quita, renombra o añade piezas."""
    cambios = cambios or {}
    salida = []
    for p in comunes:
        if p[0] in fuera:
            continue
        if p[0] in cambios:
            p = tuple(cambios[p[0]].get(i, v) for i, v in enumerate(p))
        salida.append(p)
    return salida + list(extra)

# Piezas que la tabla de mantenimiento no recoge. Igual que en el T50, sólo se cronometra lo que
# DJI da en horas de uso: estas no llevan plazo (se revisan, no cuentan horas) y la garantía queda
# en la nota como dato, no como vida útil.
_GARANTIA_T = [
    ("control_module", "Electrónica", "Módulo de control", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", "marco_t"),
    ("beacon", "Electrónica", "Baliza de señalización", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", "marco_d"),
    ("internal_wiring", "Estructura", "Cableado interno de la aeronave", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 3 meses). Revisar roturas y sellos.", "marco_c"),
    ("external_wiring", "Estructura", "Cableado externo de la aeronave", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa a diario, no se cronometra (garantía 15 días).", "marco_c"),
    ("charger", "Batería", "Cargador inteligente C12000", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses). Limpiar terminales y ventilador.", None),
    ("car_charger", "Batería", "Cargador de coche CC15000", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
    ("remote_charger", "Control remoto", "Cargador portátil 65 W", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
    ("rtk_precision", "Control remoto", "Módulo RTK de alta precisión", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
    ("rtk_dongle", "Control remoto", "Adaptador RTK Dongle", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
]

CATALOGO_T100 = _con(
    _MANTENIMIENTO_T,
    cambios={"spray_tank": {2: "Tanque de aspersión (100 L)"},
             "battery": {2: "Batería inteligente DB2160"}},
    extra=[
        _pieza("vision_quad", "Percepción", "Sistema de visión de cuatro ojos", _700,
               "DJI: inspección cada 12 meses. Cambiar si está deformado; limpiar las lentes antes de cada jornada.", "marco_d"),
        _pieza("radar_front", "Radar", "Radar inferior delantero", _700,
               "DJI: inspección cada 6 meses. Golpes, corrosión en el conector y errores HMS.", "radar_d"),
        _pieza("lidar", "Radar", "Radar láser (LiDAR)", _700,
               "DJI: revisión en cada jornada. Aclarar con agua, soplar con aire comprimido y secar con paño sin "
               "pelusa; nunca limpiacristales ni desmontar la cúpula.", "radar_d"),
        ("radar_rear", "Radar", "Radar trasero de punto ciego", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", "radar_t"),
        ("heat_sink", "Batería", "Disipador refrigerado por aire", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
        ("lte_module", "Control remoto", "Módulo de transmisión mejorada 4G", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
        *_GARANTIA_T,
        # Sistema de esparcido y elevación: la tabla de mantenimiento del T100 no los recoge.
        ("spread_control", "Sistema de esparcido", "Módulo de control de esparcido", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
        ("spread_detect_motor", "Sistema de esparcido", "Motor de detección de material", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 6 meses).", None),
        ("spread_disk_motor", "Sistema de esparcido", "Motor del disco esparcidor", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 6 meses).", None),
        ("spread_auger_motor", "Sistema de esparcido", "Motor del sinfín", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 6 meses).", None),
        ("spread_load_sensor", "Sistema de esparcido", "Módulo del sensor de carga", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 3 meses). Revisar cable y firmeza de conexión.", None),
        ("spread_tank", "Sistema de esparcido", "Tolva de esparcido", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se limpia tras cada jornada, no se cronometra (garantía 15 días).", None),
        ("spread_disk", "Sistema de esparcido", "Disco esparcidor", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa a diario, no se cronometra (garantía 15 días).", None),
        ("spread_auger", "Sistema de esparcido", "Sinfín de dosificación", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa a diario, no se cronometra (garantía 15 días).", None),
        ("hoisting_module", "Sistema de elevación", "Módulo de elevación", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses). Revisar fatiga de cuerda, gancho y marco.", None),
    ],
)

# Lo que sólo trae la tabla del T70P: su segunda hoja («维修必检项», revisiones obligatorias en
# taller) añade qué mirar tras un accidente y el código de recambio de cada pieza. Se añade a la
# nota común para que el técnico tenga el código a mano al pedirla.
def _nota(clave, extra):
    comun = next(p[5] for p in _MANTENIMIENTO_T if p[0] == clave)
    return {5: comun + " " + extra}

CATALOGO_T70P = _con(
    _MANTENIMIENTO_T,
    cambios={"spray_tank": {2: "Tanque de aspersión (70 L)"},
             "battery": {2: "Batería inteligente DB1580 / DB2160"},
             "radar_phased": {2: "Radares delantero y trasero"},
             "battery_slider": _nota("battery_slider",
                 "Recambio: guía derecha BC.AG.SS001039, izquierda BC.AG.SS001040."),
             "power_module": _nota("power_module",
                 "Recambio: módulo de placa de distribución de potencia BC.AG.SS001023."),
             "arm_lock": _nota("arm_lock",
                 "Recambio: módulo de hebilla BC.AG.SS000701. Reparar el panel del brazo con adhesivo rojo."),
             "frame": _nota("frame",
                 "Revisión obligatoria tras cualquier accidente. Piezas de fijación de brazo M1 "
                 "YC.JG.ZS006122, M2 YC.JG.ZS006121, M3 YC.JG.ZS006124, M4 YC.JG.ZS006123. Tornillos "
                 "doblados, pasados, rotos u oxidados se cambian; los de zonas controladas, con adhesivo azul."),
             "motor": _nota("motor",
                 "Revisión obligatoria tras cualquier accidente. Cambiar la tapa si hay 3-4 salidas de aire "
                 "seguidas deformadas o tapadas, o si la rotura pasa del orificio del tornillo. Recambio: "
                 "motor BC.AG.SS001048, tapa superior YC.JG.ZS006183, tapa inferior YC.JG.ZS006180."),
             "arm_power_line": _nota("arm_power_line",
                 "Recambio: potencia delantero YC.XC.DD000796, trasero YC.XC.DD000797; señal trasero "
                 "YC.XC.XX001392 (el delantero, YC.XC.XX001391, no sale en las láminas)."),
             "propellers": _nota("propellers",
                 "Al montar, apretar los tornillos de hélice con llave M8 a 150 kgf·cm. Ojo con el código: "
                 "la tabla de mantenimiento cita YC.JG.XW000240/241, pero el despiece de junio de 2025 trae "
                 "CW YC.JG.XW000454 y CCW YC.JG.XW000453; pedir por el del despiece."),
             "propeller_clamp": _nota("propeller_clamp",
                 "Recambio: pinza YC.JG.QX004522, rodamiento YC.JG.ZS006832, base YC.JG.QX004523, eje "
                 "YC.JG.QX004524. La arandela y la almohadilla de la tabla (ZS006404, MY001850) salen en "
                 "el despiece actual como YC.JG.ZS008218 y YC.JG.ZS007564.")},
    extra=[
        _pieza("vision_binocular", "Percepción", "Sistema de visión binocular ojo de pez", _700,
               "DJI: inspección cada 12 meses. Cambiar si está deformado; limpiar las lentes cada jornada.", "marco_d"),
        ("heat_sink", "Batería", "Disipador refrigerado por aire DB2160", 0, 0, "Sin horas de uso en la tabla de mantenimiento DJI: se revisa, no se cronometra (garantía 12 meses).", None),
        *_GARANTIA_T,
    ],
)

# T55 — «T55 Main Components Warranty Period List» (DJI). Se toma la columna «Global (Excl.
# Europe)»; en Europa DJI duplica todos estos plazos, así que si algún dron es de importación
# europea hay que ajustar su ficha a mano.
CATALOGO_T55 = [
    ("aerial_electronics", "Electrónica", "Módulo de electrónica aérea", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("cable_board", "Electrónica", "Módulo de placa de distribución de cables", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("power_module", "Electrónica", "Módulo de placa de distribución de potencia", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("payload_board", "Electrónica", "Placa de control de carga útil", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("spotlight", "Electrónica", "Foco de navegación nocturna", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("motor", "Propulsión", "Motor", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("esc", "Propulsión", "Módulo ESC", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("radar_module", "Radar", "Módulo de radar", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("vision_module", "Percepción", "Módulo del sensor de visión", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("fpv_module", "Percepción", "Módulo FPV", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("rtk_module", "Posicionamiento", "Módulo de antena RTK", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("arm", "Estructura", "Brazo de la aeronave", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("frame", "Estructura", "Marco de la aeronave (marco central y conector de brazo)", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("delivery_pump_motor", "Sistema de aspersión", "Motor de la bomba de impulsor", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("centrifugal_motor", "Sistema de aspersión", "Motor del aspersor centrífugo", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("mist_motor", "Sistema de aspersión", "Motor del aspersor de niebla", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("onboard_radiator", "Batería", "Radiador de batería a bordo", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("battery", "Batería", "Batería inteligente DB1580 / DB1050", 0, 12, "Garantía DJI: 1500 ciclos o 12 meses, lo que ocurra primero.", None),
    ("heat_sink", "Batería", "Disipador refrigerado por aire", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("charger", "Batería", "Cargador inteligente", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("generator", "Batería", "Estación de carga con generador inverter", 0, 12, "Garantía DJI: 12 meses o 1000 h de uso acumulado, lo que ocurra primero.", None),
    ("remote", "Control remoto", "Control remoto inteligente", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("remote_charger", "Control remoto", "Cargador portátil 65 W", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("rtk_dongle", "Control remoto", "RTK Dongle y su adaptador", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("cellular_dongle", "Control remoto", "DJI Cellular Dongle", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("remote_battery", "Control remoto", "Batería inteligente WB37 y su centro de carga", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("vent_valve", "Sistema de aspersión", "Válvula solenoide", 0, 3, "Pieza de desgaste: garantía DJI 3 meses (6 en Europa).", None),
    ("flowmeter", "Sistema de aspersión", "Módulo del caudalímetro", 0, 3, "Pieza de desgaste: garantía DJI 3 meses (6 en Europa).", None),
    ("level_sensor", "Sistema de aspersión", "Módulo del medidor de nivel", 0, 3, "Pieza de desgaste: garantía DJI 3 meses (6 en Europa).", None),
    ("internal_wiring", "Estructura", "Cableado interno de la aeronave", 0, 3, "Garantía DJI 3 meses (6 en Europa).", None),
    ("external_wiring", "Estructura", "Cableado externo y cables de carga", 0, 0, "Consumible: revisión diaria. Garantía DJI 15 días.", None),
    ("propellers", "Propulsión", "Hélices y pinza de hélice", 0, 0, "Consumible: revisión diaria. Garantía DJI 15 días.", None),
    ("landing_gear", "Tren de aterrizaje", "Tren de aterrizaje", 0, 0, "Consumible: revisión diaria. Garantía DJI 15 días.", None),
    ("hose", "Sistema de aspersión", "Manguera de aspersión", 0, 0, "Consumible: revisión diaria. Garantía DJI 15 días.", None),
    ("spray_tank", "Sistema de aspersión", "Tanque de aspersión", 0, 0, "Consumible: limpieza diaria. Garantía DJI 15 días.", None),
    ("spread_control", "Sistema de esparcido", "Placa de control de carga (esparcido)", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("spread_auger_motor", "Sistema de esparcido", "Motor del sinfín", 0, 6, "Garantía DJI 6 meses (12 en Europa).", None),
    ("spread_disk_motor", "Sistema de esparcido", "Motor del disco esparcidor", 0, 6, "Garantía DJI 6 meses (12 en Europa).", None),
    ("spread_load_sensor", "Sistema de esparcido", "Módulo del sensor de peso", 0, 3, "Garantía DJI 3 meses (6 en Europa).", None),
    ("spread_auger", "Sistema de esparcido", "Sinfín de dosificación", 0, 0, "Consumible: revisión diaria. Garantía DJI 15 días.", None),
    ("spread_tank", "Sistema de esparcido", "Tolva de esparcido", 0, 0, "Consumible: limpieza tras cada jornada. Garantía DJI 15 días.", None),
    ("lift_control", "Sistema de elevación", "Placa de control de carga (elevación)", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("lift_force_sensor", "Sistema de elevación", "Módulo del sensor de fuerza de tres ejes", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("lift_crossbeam", "Sistema de elevación", "Travesaño en T", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("lift_release", "Sistema de elevación", "Soltador de cuerda de emergencia", 0, 12, "Garantía DJI 12 meses (24 en Europa).", None),
    ("lift_rope", "Sistema de elevación", "Cuerda de elevación", 0, 0, "Consumible: revisar fatiga antes de cada izado. Garantía DJI 15 días.", None),
    ("lift_hook", "Sistema de elevación", "Gancho de elevación", 0, 0, "Consumible: revisar antes de cada izado. Garantía DJI 15 días.", None),
]


MODELOS = [
    {
        "clave": "T70P",
        "nombre": "DJI Agras T70P",
        "familia": "Agras",
        "tanque": "70 L de aspersión",
        "descripcion": "Plataforma 2025 de cuatro rotores. La flota lo opera en configuración "
                       "de fumigación.",
        "diagramas": "t70p.json",
        "imagenes": "t70p",
        "modelo3d": "t70p-despiece.glb",
        "catalogo": CATALOGO_T70P,
        "vida_en": "horas",
        "fuente_vida": "Ciclos de sustitución DJI del T70P (Maintenance Period Suggestion V1.1): "
                       "700 h de vuelo por pieza; la bomba, 500 h el cabezal y "
                       "1000 h el motor.",
        # La flota sólo fumiga: las láminas de las cargas de esparcido y elevación se dejan
        # fuera para que el despiece no ofrezca recambios de equipos que no se montan.
        "sistemas_ocultos": ["Sistema de esparcido", "Sistema de elevación"],
    },
    {
        "clave": "T100",
        "nombre": "DJI Agras T100",
        "familia": "Agras",
        "tanque": "100 L de aspersión · 150 L de esparcido (100 kg) · 80 kg de carga",
        "descripcion": "Plataforma 2025 de cuatro rotores con sistemas intercambiables de "
                       "aspersión, esparcido y elevación.",
        "diagramas": "t100.json",
        "imagenes": "t100",
        # El archivo aún no está; en cuanto se deje aquí, la Vista 3D lo carga sin tocar código.
        "modelo3d": "t100-despiece.glb",
        "catalogo": CATALOGO_T100,
        "vida_en": "horas",
        "fuente_vida": "Ciclos de sustitución DJI del T100 (Maintenance Period Suggestion V1.1): "
                       "700 h de vuelo por pieza; la bomba, 500 h el cabezal y "
                       "1000 h el motor.",
    },
    {
        "clave": "T50",
        "nombre": "DJI Agras T50",
        "familia": "Agras",
        "tanque": "40 L de aspersión · 50 L de esparcido",
        "descripcion": "Plataforma de cuatro rotores con aspersión y esparcido.",
        "diagramas": "t50.json",
        "imagenes": "",
        "modelo3d": "t50-despiece.glb",
        "modelo3d_alt": "t50.glb",
        "catalogo": CATALOGO_T50,
        "vida_en": "horas",
        "fuente_vida": "«T25&T50 Recommended Maintenance List» (DJI): vida útil en horas de vuelo.",
    },
    {
        "clave": "T55",
        "nombre": "DJI Agras T55",
        "familia": "Agras",
        "tanque": "50 L de aspersión · 80 L de esparcido (55 kg) · 40 kg de carga",
        "descripcion": "Plataforma de doble batería (DB1050/DB1580) con aspersión, esparcido y elevación.",
        "diagramas": "t55.json",
        "imagenes": "t55",
        "modelo3d": "t55-despiece.glb",
        "catalogo": CATALOGO_T55,
        "vida_en": "meses",
        "fuente_vida": "«T55 Main Components Warranty Period List» (DJI), columna global fuera "
                       "de Europa. En Europa DJI duplica todos estos plazos.",
    },
    {
        "clave": "T100DB",
        "nombre": "DJI Agras T100 doble batería",
        "familia": "Agras",
        "tanque": "90 L de aspersión",
        "descripcion": "Variante del T100 con doble batería y elevador DL100. Con doble batería el depósito baja a 90 L.",
        "diagramas": "t100db.json",
        "imagenes": "t100db",
        "modelo3d": "t100db-despiece.glb",
        # Es un T100 con otro sistema de baterías: comparte célula, aspersión y control remoto,
        # y lo propio suyo es el elevador DL100. Por eso hereda las láminas y el catálogo del
        # T100 y sólo añade lo que cambia.
        "hereda": "T100",
        "catalogo": CATALOGO_T100,
        "vida_en": "horas",
        "fuente_vida": "Ciclos de sustitución DJI del T100 (Maintenance Period Suggestion V1.1), "
                       "que comparte célula con esta variante.",
    },
]

POR_CLAVE = {m["clave"]: m for m in MODELOS}
# El modelo con el que se dan de alta los equipos nuevos y el que abre las pantallas de despiece.
PREDETERMINADO = MODELOS[0]["clave"]


def modelo(clave):
    """Ficha del modelo, o la del predeterminado si la clave no está registrada."""
    return POR_CLAVE.get(clave) or POR_CLAVE[PREDETERMINADO]


def claves():
    return [m["clave"] for m in MODELOS]


def catalogo(clave):
    return modelo(clave)["catalogo"]


def ruta_diagramas(clave):
    return DIR_DIAGRAMAS / modelo(clave)["diagramas"]


def archivos_3d(clave):
    """Archivos GLB de un modelo, en orden de preferencia y sólo los que existen de verdad.

    Un modelo puede traer dos: el despiece completo y uno ligero de respaldo por si el grande
    falla al cargar. Devuelve las URL tal y como las pide el visor.
    """
    ficha = modelo(clave)
    salida = []
    for campo in ("modelo3d", "modelo3d_alt"):
        archivo = ficha.get(campo)
        if archivo and (DIR_MODELOS_3D / archivo).exists():
            salida.append(f"/static_shell/modelos/{archivo}")
    return salida


# Aviones: fichas de los modelos que no son drones DJI (las plantillas de core/aeronaves.py y los
# modelos que la empresa cree a partir de ellas). Se guardan igual que los drones:
#   · `diagramas` / `imagenes`: láminas generadas con herramientas/laminas_cessna.py
#     (core/diagramas/c188a.json + static_shell/diagramas/c188a/).
#   · `modelo3d`: GLB del despiece, una COPIA en static_shell/modelos/. El original de Claude Design
#     y sus versiones anteriores viven en «Informacion Drones/C188/3D»; al recibir uno nuevo se
#     revisa (herramientas/cessna_3d/LEEME.txt) y se copia aquí con el mismo nombre.
# El visor los trata en «modo avión»: sistema (MOD_*) → grupo (FIG_*) → pieza.
AVIONES = {
    "C188A": {"nombre": "Cessna 188A AGwagon", "diagramas": "c188a.json", "imagenes": "c188a",
              "modelo3d": "c188-despiece.glb",
              "fuente": "Catálogo ilustrado de piezas Cessna P694-12"},
}


def archivos_3d_extra(clave):
    """GLB de un avión (o de un modelo propio creado desde su plantilla), como archivos_3d()."""
    archivo = (AVIONES.get(clave) or {}).get("modelo3d")
    if archivo and (DIR_MODELOS_3D / archivo).exists():
        return [f"/static_shell/modelos/{archivo}"]
    return []


def ruta_modelo3d(clave):
    archivo = modelo(clave)["modelo3d"]
    return DIR_MODELOS_3D / archivo if archivo else None


def url_imagen(clave, imagen):
    """URL de una lámina. Las del T50 viven en la raíz por historia; el resto, en su carpeta."""
    if not imagen:
        return None
    carpeta = modelo(clave)["imagenes"]
    return f"/static_shell/diagramas/{carpeta + '/' if carpeta else ''}{imagen}"


def _laminas_avion(clave):
    ficha = AVIONES[clave]
    ruta = DIR_DIAGRAMAS / ficha["diagramas"]
    try:
        modulos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    except (ValueError, OSError):
        return []
    for m in modulos:
        m["imagen_url"] = f"/static_shell/diagramas/{ficha['imagenes']}/{m['imagen']}" if m.get("imagen") else None
        m.setdefault("piezas_catalogo", [])
    return modulos


def _laminas_propias(clave):
    """Láminas escritas en el JSON de ese modelo, ya normalizadas.

    El JSON del T50 se escribió antes de que existieran los campos `sistema` y `zona`, así que
    se rellenan aquí para que todos los modelos se lean igual desde la API.
    """
    if clave in AVIONES:
        return _laminas_avion(clave)
    ruta = ruta_diagramas(clave)
    if not ruta.exists():
        return []
    try:
        modulos = json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    for m in modulos:
        m.setdefault("sistema", "Aeronave y aspersión")
        m["zona"] = m.get("zona") or ZONA_DE_MODULO_T50.get(m["clave"]) or m["nombre"]
        m["imagen_url"] = url_imagen(clave, m.get("imagen"))
        m.setdefault("piezas_catalogo", [])
    return modulos


def cargar_diagramas(clave):
    """Láminas de un modelo, incluidas las que hereda de la plataforma de la que sale.

    El T100DB es un T100 con otro sistema de baterías: comparte célula, aspersión y control
    remoto, y lo propio suyo es el elevador DL100. En vez de duplicar 30 láminas idénticas,
    hereda las del T100 y añade las suyas, que ganan si repiten clave.
    """
    if clave in AVIONES:
        return _laminas_avion(clave)
    ficha = modelo(clave)
    ocultos = set(ficha.get("sistemas_ocultos") or [])
    propias = [m for m in _laminas_propias(clave) if m["sistema"] not in ocultos]
    padre = ficha.get("hereda")
    if not padre:
        return propias
    suyas = {m["clave"] for m in propias}
    heredadas = [m for m in _laminas_propias(padre)
                 if m["clave"] not in suyas and m["sistema"] not in ocultos]
    return propias + heredadas


def con_laminas(clave, base=None):
    """Clave con láminas propias para un modelo: la suya, o la de la plantilla de la que sale
    (el Cessna de una empresa es una copia de la plantilla C188A y comparte sus láminas)."""
    for c in (clave, base):
        if c and (c in POR_CLAVE or c in AVIONES):
            return c
    return None


def resumen(clave):
    """Ficha del modelo con lo que la app sabe de él, para pintar el selector de modelos."""
    if clave in AVIONES:
        laminas = cargar_diagramas(clave)
        archivos = archivos_3d_extra(clave)
        return {"clave": clave, "nombre": AVIONES[clave]["nombre"], "tipo": "avion", "tanque": None,
                "descripcion": AVIONES[clave]["fuente"], "vida_en": "horas y meses",
                "fuente_vida": AVIONES[clave]["fuente"], "n_laminas": len(laminas),
                "n_despiece": sum(len(x.get("partes") or []) for x in laminas), "n_catalogo": 0,
                "tiene_diagramas": bool(laminas), "tiene_3d": bool(archivos), "archivos_3d": archivos,
                "sistemas": sorted({x["sistema"] for x in laminas})}
    m = modelo(clave)
    laminas = cargar_diagramas(clave)
    archivos = archivos_3d(clave)
    return {
        "clave": m["clave"],
        "nombre": m["nombre"],
        "tipo": m.get("tipo", "dron"),
        "tanque": m["tanque"],
        "descripcion": m["descripcion"],
        "vida_en": m["vida_en"],
        "fuente_vida": m["fuente_vida"],
        "n_laminas": len(laminas),
        "n_despiece": sum(len(x.get("partes") or []) for x in laminas),
        "n_catalogo": len(m["catalogo"]),
        "tiene_diagramas": bool(laminas),
        "tiene_3d": bool(archivos),
        "archivos_3d": archivos,
        "sistemas": sorted({x["sistema"] for x in laminas}),
    }


def todos_resumidos():
    return [resumen(c) for c in claves()]


# ---------- Zonas ----------
# La zona es la ubicación canónica de una pieza y sale en todas partes: buscador, bitácora, ficha
# del diagrama y panel del 3D. Los modelos nuevos la traen en su propio JSON (la escribe
# `herramientas/laminas.py` al extraer las láminas); el T50 se mapea aquí porque su JSON es
# anterior a ese campo.
ZONA_DE_MODULO_T50 = {
    "brazo_m1": "Brazos y motores",
    "brazo_m3": "Brazos y motores",
    "helices": "Hélices",
    "lanza": "Lanza y aspersor",
    "aspersor": "Lanza y aspersor",
    "tanque_1": "Tanque de aspersión",
    "tanque_2": "Tanque de aspersión",
    "bomba": "Bomba de aspersión",
    "caudalimetro": "Caudalímetro",
    "cubierta_frontal": "Marco delantero",
    "marco_delantero": "Marco delantero",
    "marco_central": "Marco central",
    "marco_trasero": "Marco trasero",
    "radar_delantero": "Radar delantero",
    "radar_trasero": "Radar trasero",
    "placa_distribucion": "Electrónica y potencia",
    "radiador": "Electrónica y potencia",
    "cableado": "Cableado",
    "tren": "Tren de aterrizaje",
}

# Accesorios que no salen en ninguna lámina de la aeronave.
ZONA_SUELTA = {
    "battery": "Batería y cargador",
    "charger": "Batería y cargador",
    "car_charger": "Batería y cargador",
    "heat_sink": "Batería y cargador",
    "remote": "Control remoto",
    "remote_charger": "Control remoto",
    "rtk_precision": "Control remoto",
    "rtk_dongle": "Control remoto",
    "lte_module": "Control remoto",
    "hoisting_module": "Sistema de elevación",
}
