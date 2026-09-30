"""Plantillas de modelos de avión agrícola.

Una plantilla es el punto de partida: al dar de alta el primer avión de un modelo, la empresa
recibe una COPIA propia del modelo con este catálogo, y sobre esa copia edita límites,
tolerancias e ítems según su programa de mantenimiento aprobado. La plantilla del sistema no se
toca desde la app.

TODOS los valores de esta plantilla son de REFERENCIA (`referencia=True`): no sustituyen el
manual del fabricante, las directivas vigentes ni el programa de mantenimiento aprobado por la
autoridad. La pantalla de catálogo los marca como «confirmar».

Contadores del avión:
  · hobbs        tiempo con el motor encendido (lo que se anota como tiempo de vuelo)
  · tach         horas de motor según el tacómetro; con él se suele llevar el TBO
  · aterrizajes  ciclos de tren y estructura
  · arranques    ciclos de motor de arranque
"""

NOTA_REF = "Valor de referencia: confirmar con el manual del fabricante y el programa de mantenimiento aprobado."

CESSNA_188A = {
    "clave": "C188A",
    "tipo_activo": "avion",
    "fabricante": "Cessna",
    "nombre": "Cessna 188A AGwagon (plantilla)",
    "contadores": ["hobbs", "tach", "aterrizajes", "arranques"],
    "descripcion": "Monomotor agrícola de ala baja y tren convencional. Motor Continental O-470-R "
                   "(230 hp), tolva de 200 galones US. Plantilla con valores de referencia.",
    "catalogo": [
        # --- Inspecciones periódicas (se repiten: al cumplir, el contador vuelve a cero) ---
        {"clave": "insp_50h", "modulo": "Inspecciones", "nombre": "Inspección de 50 h", "tipo_item": "inspeccion",
         "contador": "hobbs", "limite": 50, "tolerancia": 5, "referencia": True,
         "nota": "Cambio de aceite y filtro, revisión de sistema de aspersión y controles. " + NOTA_REF},
        {"clave": "insp_100h", "modulo": "Inspecciones", "nombre": "Inspección de 100 h", "tipo_item": "inspeccion",
         "contador": "hobbs", "limite": 100, "tolerancia": 10, "referencia": True,
         "nota": "Inspección completa de célula, motor, hélice y sistemas. RAC 4.2.4.5(b): se puede exceder "
                 "hasta 10 h para llegar al lugar de la inspección, y el exceso cuenta para las siguientes 100 h. "
                 "RAC 137.53(c)(1): obligatoria para operar sobre zonas pobladas. " + NOTA_REF},
        {"clave": "insp_anual", "modulo": "Inspecciones", "nombre": "Inspección anual", "tipo_item": "inspeccion",
         "contador": "hobbs", "meses": 12, "referencia": True,
         "nota": "RAC 91.1110(b): cada 12 meses calendario, con certificación de conformidad de mantenimiento "
                 "(RAC 43.400/43.405) y lista de verificación (RAC 43.310)."},
        {"clave": "pitot_estatica", "modulo": "Inspecciones", "nombre": "Prueba de sistema pitot-estática y transponder",
         "tipo_item": "inspeccion", "contador": "hobbs", "meses": 24, "referencia": True,
         "nota": "RAC 91.877: sistema altimétrico cada 24 meses (RAC 43 Apéndice 3) y transpondedor cada 24 meses "
                 "(RAC 43 Apéndice 4), si el fabricante no fija otro intervalo."},
        {"clave": "insp_elt", "modulo": "Inspecciones", "nombre": "Inspección del ELT",
         "tipo_item": "inspeccion", "contador": "hobbs", "meses": 12, "referencia": True,
         "nota": "RAC 91.877: transmisor de localización de emergencia cada 12 meses. RAC 91.830: ELT "
                 "obligatorio (406 y 121,5 MHz)."},
        {"clave": "brujula", "modulo": "Inspecciones", "nombre": "Compensación de la brújula magnética",
         "tipo_item": "inspeccion", "contador": "hobbs", "meses": 24, "referencia": True,
         "nota": "RAC 91.877: brújula magnética cada 24 meses si el fabricante no fija otro intervalo."},
        {"clave": "peso_balance", "modulo": "Inspecciones", "nombre": "Revisión de peso y balance",
         "tipo_item": "inspeccion", "contador": "hobbs", "meses": 60, "referencia": True, "nota": NOTA_REF},
        # --- Motor (Continental O-470-R) ---
        {"clave": "motor", "modulo": "Motor", "nombre": "Motor Continental O-470-R (overhaul)",
         "contador": "tach", "limite": 1500, "meses": 144, "serializada": True, "referencia": True,
         "nota": "TBO por horas o por calendario, lo que ocurra primero. " + NOTA_REF},
        {"clave": "magneto_izq", "modulo": "Motor", "nombre": "Magneto izquierdo (inspección interna)",
         "contador": "tach", "limite": 500, "serializada": True, "referencia": True, "nota": NOTA_REF},
        {"clave": "magneto_der", "modulo": "Motor", "nombre": "Magneto derecho (inspección interna)",
         "contador": "tach", "limite": 500, "serializada": True, "referencia": True, "nota": NOTA_REF},
        {"clave": "aceite", "modulo": "Motor", "nombre": "Aceite y filtro de aceite",
         "contador": "tach", "limite": 50, "meses": 4, "referencia": True, "nota": NOTA_REF},
        {"clave": "bujias", "modulo": "Motor", "nombre": "Bujías (limpieza y rotación)",
         "contador": "tach", "limite": 100, "referencia": True, "nota": NOTA_REF},
        {"clave": "filtro_aire", "modulo": "Motor", "nombre": "Filtro de aire de inducción",
         "contador": "tach", "limite": 100, "meses": 12, "referencia": True,
         "nota": "En operación agrícola con polvo conviene acortar el intervalo. " + NOTA_REF},
        {"clave": "motor_arranque", "modulo": "Motor", "nombre": "Motor de arranque",
         "contador": "tach", "contador_ciclos": "arranques", "limite_ciclos": 3000, "serializada": True,
         "referencia": True, "nota": NOTA_REF},
        {"clave": "mangueras_motor", "modulo": "Motor", "nombre": "Mangueras de combustible y aceite del motor",
         "contador": "tach", "meses": 60, "referencia": True, "nota": NOTA_REF},
        # --- Hélice ---
        {"clave": "helice", "modulo": "Hélice", "nombre": "Hélice (overhaul)",
         "contador": "tach", "limite": 2000, "meses": 72, "serializada": True, "referencia": True, "nota": NOTA_REF},
        # --- Célula y tren ---
        {"clave": "tren_principal", "modulo": "Célula y tren", "nombre": "Tren principal y frenos (inspección)",
         "contador": "hobbs", "contador_ciclos": "aterrizajes", "limite_ciclos": 500, "referencia": True,
         "nota": NOTA_REF},
        {"clave": "rueda_cola", "modulo": "Célula y tren", "nombre": "Rueda de cola y resorte",
         "contador": "hobbs", "contador_ciclos": "aterrizajes", "limite_ciclos": 500, "referencia": True,
         "nota": NOTA_REF},
        {"clave": "cables_mando", "modulo": "Célula y tren", "nombre": "Cables de mando (tensión y desgaste)",
         "contador": "hobbs", "limite": 100, "referencia": True, "nota": NOTA_REF},
        {"clave": "arnes", "modulo": "Célula y tren", "nombre": "Arnés y cinturones de seguridad",
         "contador": "hobbs", "meses": 12, "referencia": True, "nota": NOTA_REF},
        # --- Sistema de aplicación ---
        {"clave": "bomba_aspersion", "modulo": "Sistema de aspersión", "nombre": "Bomba de aspersión (revisión)",
         "contador": "hobbs", "limite": 100, "referencia": True, "nota": NOTA_REF},
        {"clave": "boquillas", "modulo": "Sistema de aspersión", "nombre": "Boquillas, filtros y válvula de corte",
         "contador": "hobbs", "limite": 50, "referencia": True, "nota": NOTA_REF},
        {"clave": "tolva", "modulo": "Sistema de aspersión", "nombre": "Tolva y compuerta de descarga",
         "contador": "hobbs", "limite": 100, "referencia": True, "nota": NOTA_REF},
        # --- Equipo de emergencia ---
        {"clave": "elt_bateria", "modulo": "Emergencia", "nombre": "Batería del ELT",
         "contador": "hobbs", "meses": 24, "referencia": True, "nota": NOTA_REF},
        {"clave": "extintor", "modulo": "Emergencia", "nombre": "Extintor (inspección)",
         "contador": "hobbs", "meses": 12, "referencia": True, "nota": NOTA_REF},
    ],
}

PLANTILLAS = [CESSNA_188A]
