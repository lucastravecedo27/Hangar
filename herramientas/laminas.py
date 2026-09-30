"""Nombres de las láminas de despiece, por modelo.

Los Excel de DJI traen las hojas con el nombre del módulo en chino («前框（1）») y repiten
nombres entre libros (el «脚架组件» del sistema de aspersión no es el del sistema de elevación).
Esta tabla les da clave estable, nombre en castellano, sistema al que pertenecen y zona — el
vocabulario único con el que se sitúa una pieza en el buscador y en la bitácora.

Clave del diccionario: (sistema del libro, título de la hoja).
Valor: (clave, nombre en castellano, zona).
"""

# Sistema al que pertenece cada libro, deducido de su nombre de archivo.
SISTEMAS = {
    "lifting": "Sistema de elevación",
    "spreading": "Sistema de esparcido",
    "remote": "Control remoto",
    "misting": "Aspersión por niebla",
    "cargador": "Carga de baterías",
    "aeronave": "Aeronave y aspersión",
}


def sistema_de_archivo(nombre_archivo):
    bajo = nombre_archivo.lower()
    # DJI titula unos libros «Lifting System» y otros «Lift System» (el DL100 del T100DB).
    if "lifting" in bajo or "lift system" in bajo:
        return "lifting"
    for etiqueta in ("spreading", "remote", "misting"):
        if etiqueta in bajo:
            return etiqueta
    if "c7000" in bajo or "c12000" in bajo or "c8000" in bajo or "c10000" in bajo:
        return "cargador"
    return "aeronave"


LAMINAS = {
    "T70P": {
        ("aeronave", "水箱组件1"): ("tanque_1", "Tanque de aspersión (1)", "Tanque de aspersión"),
        ("aeronave", "水箱组件1 (2)"): ("tanque_2", "Tanque de aspersión (2)", "Tanque de aspersión"),
        ("aeronave", "叶轮泵组件"): ("bomba", "Bomba de impulsor", "Bomba de aspersión"),
        ("aeronave", "流量计组件"): ("caudalimetro", "Caudalímetro", "Caudalímetro"),
        ("aeronave", "喷杆"): ("lanza", "Lanza de aspersión", "Lanza y aspersor"),
        ("aeronave", "分线模块"): ("placa_distribucion", "Placa de distribución principal", "Electrónica y potencia"),
        ("aeronave", "前框1"): ("marco_delantero_1", "Marco delantero (1)", "Marco delantero"),
        ("aeronave", "前框2"): ("marco_delantero_2", "Marco delantero (2)", "Marco delantero"),
        ("aeronave", "机臂3"): ("brazo", "Brazo M3", "Brazos y motores"),
        ("aeronave", "中框"): ("marco_central", "Marco central", "Marco central"),
        ("aeronave", "脚架"): ("tren", "Tren de aterrizaje", "Tren de aterrizaje"),
        ("aeronave", "桨叶"): ("helices", "Hélices", "Hélices"),
        ("misting", "喷杆"): ("lanza_niebla", "Lanza de aspersión por niebla", "Lanza y aspersor"),
        ("lifting", "空吊"): ("elevacion_cabrestante", "Cabrestante de elevación", "Sistema de elevación"),
        ("spreading", "水箱组件"): ("tolva", "Tolva de esparcido", "Tolva de esparcido"),
        ("spreading", "甩盘组件"): ("disco_esparcidor", "Disco esparcidor", "Disco esparcidor"),
        ("spreading", "绞龙组件"): ("sinfin", "Sinfín de dosificación", "Sinfín de dosificación"),
        ("remote", "整机"): ("rc_completo", "Control remoto completo", "Control remoto"),
        ("remote", "前壳"): ("rc_carcasa_delantera", "Carcasa delantera del control", "Control remoto"),
        ("remote", "后壳"): ("rc_carcasa_trasera", "Carcasa trasera del control", "Control remoto"),
    },
    "T55": {
        ("aeronave", "Front Frame Module（1）"): ("marco_delantero_1", "Marco delantero (1)", "Marco delantero"),
        ("aeronave", "Front Frame Module（2）"): ("marco_delantero_2", "Marco delantero (2)", "Marco delantero"),
        ("aeronave", "Cable Distribution Board Module"): ("placa_distribucion", "Placa de distribución principal", "Electrónica y potencia"),
        ("aeronave", "Landing Gear"): ("tren", "Tren de aterrizaje", "Tren de aterrizaje"),
        ("aeronave", "Middle Frame（1）"): ("marco_central_1", "Marco central (1)", "Marco central"),
        ("aeronave", "Middle Frame（2）"): ("marco_central_2", "Marco central (2)", "Marco central"),
        ("aeronave", "M1 Aircraft Arm"): ("brazo_m1", "Brazo M1", "Brazos y motores"),
        ("aeronave", "M3 Aircraft Arm"): ("brazo_m3", "Brazo M3", "Brazos y motores"),
        ("aeronave", "Motor"): ("motor_brazo", "Motor del brazo", "Brazos y motores"),
        ("aeronave", "Spray Tank Set"): ("tanque_1", "Conjunto del tanque de aspersión", "Tanque de aspersión"),
        ("aeronave", "Spray Tank"): ("tanque_2", "Tanque de aspersión", "Tanque de aspersión"),
        ("aeronave", "Impeller Pump Assembly"): ("bomba", "Bomba de impulsor", "Bomba de aspersión"),
        ("aeronave", "Flow Meter Module"): ("caudalimetro", "Caudalímetro", "Caudalímetro"),
        ("aeronave", "Propeller"): ("helices", "Hélices", "Hélices"),
        ("spreading", "Spreading System（1）"): ("esparcido_1", "Sistema de esparcido (1)", "Sistema de esparcido"),
        ("spreading", "Spreading System（2）"): ("esparcido_2", "Sistema de esparcido (2)", "Sistema de esparcido"),
        ("spreading", "Spreading System（3）"): ("esparcido_3", "Sistema de esparcido (3)", "Sistema de esparcido"),
        ("cargador", "C7000充电器"): ("cargador_c7000", "Cargador C7000", "Batería y cargador"),
    },
    "T100DB": {
        ("lifting", "LIFT"): ("dl100_elevacion", "Sistema de elevación DL100", "Sistema de elevación"),
    },
    "T100": {
        ("aeronave", "水箱组件（1）"): ("tanque_1", "Tanque de aspersión (1)", "Tanque de aspersión"),
        ("aeronave", "水箱组件（2）"): ("tanque_2", "Tanque de aspersión (2)", "Tanque de aspersión"),
        ("aeronave", "叶轮泵组件"): ("bomba", "Bomba de impulsor", "Bomba de aspersión"),
        ("aeronave", "流量计组件"): ("caudalimetro", "Caudalímetro", "Caudalímetro"),
        ("aeronave", "脚架组件（1）"): ("tren_1", "Tren de aterrizaje (1)", "Tren de aterrizaje"),
        ("aeronave", "脚架组件（2）"): ("tren_2", "Tren de aterrizaje (2)", "Tren de aterrizaje"),
        ("aeronave", "喷杆组件"): ("lanza", "Lanza de aspersión", "Lanza y aspersor"),
        ("aeronave", "机框连接件"): ("marco_conectores", "Conectores del marco", "Marco central"),
        ("aeronave", "分线板模块"): ("placa_distribucion", "Placa de distribución principal", "Electrónica y potencia"),
        ("aeronave", "前框（1）"): ("marco_delantero_1", "Marco delantero (1)", "Marco delantero"),
        ("aeronave", "前框（2）"): ("marco_delantero_2", "Marco delantero (2)", "Marco delantero"),
        ("aeronave", "中框&后框（1）"): ("marco_central_trasero", "Marco central y trasero", "Marco trasero"),
        ("aeronave", "大机臂"): ("brazo_grande", "Brazo principal", "Brazos y motores"),
        ("aeronave", "M1M3小机臂"): ("brazo_m1m3", "Brazo M1 / M3", "Brazos y motores"),
        ("aeronave", "机臂电机"): ("motor_brazo", "Motor del brazo", "Brazos y motores"),
        ("aeronave", "桨叶"): ("helices", "Hélices", "Hélices"),
        ("lifting", "空吊"): ("elevacion_cabrestante", "Cabrestante de elevación", "Sistema de elevación"),
        ("lifting", "机框连接件"): ("elevacion_marco", "Conectores del marco (elevación)", "Sistema de elevación"),
        ("lifting", "脚架组件（1）"): ("elevacion_tren_1", "Tren de aterrizaje de elevación (1)", "Sistema de elevación"),
        ("lifting", "脚架组件（2）"): ("elevacion_tren_2", "Tren de aterrizaje de elevación (2)", "Sistema de elevación"),
        ("spreading", "料箱组件"): ("tolva", "Tolva de esparcido", "Tolva de esparcido"),
        ("spreading", "脚架"): ("esparcido_tren_1", "Tren de aterrizaje de esparcido (1)", "Sistema de esparcido"),
        ("spreading", "脚架 (2)"): ("esparcido_tren_2", "Tren de aterrizaje de esparcido (2)", "Sistema de esparcido"),
        ("spreading", "称重模块"): ("pesaje", "Módulo de pesaje", "Sistema de esparcido"),
        ("spreading", "机框组件"): ("esparcido_marco", "Marco del sistema de esparcido", "Sistema de esparcido"),
        ("spreading", "甩盘组件"): ("disco_esparcidor", "Disco esparcidor", "Disco esparcidor"),
        ("spreading", "绞龙组件"): ("sinfin", "Sinfín de dosificación", "Sinfín de dosificación"),
        ("remote", "整机"): ("rc_completo", "Control remoto completo", "Control remoto"),
        ("remote", "前壳"): ("rc_carcasa_delantera", "Carcasa delantera del control", "Control remoto"),
        ("remote", "后壳"): ("rc_carcasa_trasera", "Carcasa trasera del control", "Control remoto"),
    },
}


def buscar(modelo, sistema, titulo):
    """Devuelve (clave, nombre_es, zona) o None si la lámina no está mapeada."""
    tabla = LAMINAS.get(modelo, {})
    # Los títulos de DJI a veces llevan espacios de sobra al final («甩盘组件 »).
    return tabla.get((sistema, titulo.strip()))


# Qué piezas con vida útil (core/modelos.py) se ven en cada lámina. Es lo que permite que al
# abrir un diagrama salga el estado de desgaste de ese módulo, y de dónde sale la zona de cada
# pieza del catálogo de mantenimiento.
PIEZAS_CATALOGO = {
    "T70P": {
        "tanque_1": ["spray_tank", "level_sensor", "vent_valve", "hose_connector"],
        "tanque_2": ["spray_tank", "hose"],
        "bomba": ["delivery_pump_kit", "pump_motor"],
        "caudalimetro": ["flowmeter"],
        "lanza": ["centrifugal_module", "hose"],
        "lanza_niebla": ["mist_sprinkler"],
        "placa_distribucion": ["cable_board", "payload_adapter", "power_module", "internal_wiring"],
        "marco_delantero_1": ["frame", "vision_binocular", "fpv_module", "sdr_antenna"],
        "marco_delantero_2": ["frame", "radar_phased", "radar_bracket", "beacon", "control_module"],
        "brazo": ["arm_lock", "arm_power_line", "esc", "motor", "internal_wiring"],
        "marco_central": ["frame", "battery_slider", "battery_connector", "rtk_module",
                          "sdr_antenna", "aerial_electronics"],
        "tren": ["landing_gear", "radar_bracket"],
        "helices": ["propellers", "propeller_clamp"],
        "elevacion_cabrestante": ["hoisting_module"],
        "tolva": [],
        "disco_esparcidor": [],
        "sinfin": [],
        "rc_completo": ["remote", "rtk_precision", "rtk_dongle"],
        "rc_carcasa_delantera": ["remote"],
        "rc_carcasa_trasera": ["remote", "remote_charger"],
    },
    "T55": {
        "marco_delantero_1": ["frame", "vision_module", "fpv_module"],
        "marco_delantero_2": ["frame", "radar_module", "spotlight"],
        "placa_distribucion": ["cable_board", "power_module", "internal_wiring"],
        "tren": ["landing_gear"],
        "marco_central_1": ["frame", "rtk_module", "aerial_electronics"],
        "marco_central_2": ["frame", "payload_board", "onboard_radiator"],
        "brazo_m1": ["arm", "esc", "internal_wiring"],
        "brazo_m3": ["arm", "esc", "internal_wiring"],
        "motor_brazo": ["motor"],
        "tanque_1": ["spray_tank", "level_sensor", "vent_valve"],
        "tanque_2": ["spray_tank", "hose"],
        "bomba": ["delivery_pump_motor"],
        "caudalimetro": ["flowmeter"],
        "helices": ["propellers"],
        "esparcido_1": ["spread_control", "spread_tank"],
        "esparcido_2": ["spread_auger", "spread_auger_motor"],
        "esparcido_3": ["spread_disk_motor", "spread_load_sensor"],
        "cargador_c7000": ["charger"],
    },
    "T100DB": {
        "dl100_elevacion": ["hoisting_module"],
    },
    "T100": {
        "tanque_1": ["spray_tank"],
        "tanque_2": ["spray_tank", "hose", "hose_connector", "level_sensor", "vent_valve"],
        "bomba": ["delivery_pump_kit", "pump_motor"],
        "caudalimetro": ["flowmeter"],
        "lanza": ["centrifugal_module", "mist_sprinkler", "hose"],
        "tren_1": ["landing_gear"],
        "tren_2": ["landing_gear", "radar_bracket"],
        "marco_conectores": ["frame", "arm_lock"],
        "placa_distribucion": ["cable_board", "payload_adapter", "power_module", "internal_wiring"],
        "marco_delantero_1": ["frame", "radar_front", "radar_bracket", "vision_quad", "fpv_module"],
        "marco_delantero_2": ["frame", "lidar", "sdr_antenna", "radar_bracket", "beacon",
                              "control_module"],
        "marco_central_trasero": ["frame", "battery_slider", "battery_connector", "rtk_module",
                                  "radar_rear", "radar_phased", "aerial_electronics"],
        "brazo_grande": ["arm_lock", "sdr_antenna", "internal_wiring"],
        "brazo_m1m3": ["arm_lock", "arm_power_line", "esc", "internal_wiring"],
        "motor_brazo": ["motor"],
        "helices": ["propellers", "propeller_clamp"],
        "elevacion_cabrestante": ["hoisting_module"],
        "elevacion_marco": ["hoisting_module"],
        "elevacion_tren_1": ["landing_gear"],
        "elevacion_tren_2": ["landing_gear"],
        "tolva": ["spread_tank"],
        "esparcido_tren_1": ["landing_gear"],
        "esparcido_tren_2": ["landing_gear"],
        "pesaje": ["spread_load_sensor"],
        "esparcido_marco": ["spread_control"],
        "disco_esparcidor": ["spread_disk", "spread_disk_motor"],
        "sinfin": ["spread_auger", "spread_auger_motor", "spread_detect_motor"],
        "rc_completo": ["remote", "rtk_precision", "rtk_dongle", "lte_module"],
        "rc_carcasa_delantera": ["remote"],
        "rc_carcasa_trasera": ["remote", "remote_charger"],
    },
}


def piezas_catalogo(modelo, clave):
    return PIEZAS_CATALOGO.get(modelo, {}).get(clave, [])
