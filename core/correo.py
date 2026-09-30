"""Envío de correo de las órdenes de trabajo y de servicio.

La app queda lista para conectar: la configuración SMTP se guarda en la tabla `meta` desde
Ajustes y, mientras no exista, todo lo que se "envía" se guarda en la cola (`correo_cola`)
con estado pendiente. Al configurar el servidor se puede reintentar la cola completa.
"""
import base64
import hashlib
import json
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from cryptography.fernet import Fernet, InvalidToken

from core import config
from core import db as core_db


def _fernet():
    """Cifrado simétrico con una clave derivada de la SECRET_KEY de la app."""
    from flask import current_app
    clave = hashlib.sha256(current_app.config["SECRET_KEY"].encode()).digest()
    return Fernet(base64.urlsafe_b64encode(clave))


def _cifrar(texto):
    return "enc:" + _fernet().encrypt(texto.encode()).decode() if texto else ""


def _descifrar(texto):
    if not texto:
        return ""
    if not str(texto).startswith("enc:"):
        return texto  # valor antiguo sin cifrar
    try:
        return _fernet().decrypt(texto[4:].encode()).decode()
    except InvalidToken:
        return ""

CLAVE_CONFIG = "correo:smtp"
CAMPOS = ("servidor", "puerto", "usuario", "password", "remitente", "nombre_remitente", "seguridad", "responder_a")
DEFECTOS = {"servidor": "", "puerto": 587, "usuario": "", "password": "", "remitente": "",
            "nombre_remitente": "Hangar · Control de flota aérea agrícola", "seguridad": "starttls", "responder_a": ""}


def leer_config(con):
    """Lo guardado en Ajustes, con la contraseña descifrada; las variables SMTP_* del entorno
    (si están definidas) mandan sobre lo guardado."""
    guardado = core_db.meta_get(con, CLAVE_CONFIG)
    cfg = dict(DEFECTOS)
    if guardado:
        cfg.update(json.loads(guardado))
    cfg["password"] = _descifrar(cfg.get("password"))
    for k, v in config.SMTP_ENV.items():
        if v not in (None, ""):
            cfg[k] = v
    cfg["desde_entorno"] = any(v not in (None, "") for v in config.SMTP_ENV.values())
    cfg["configurado"] = bool(cfg.get("servidor") and cfg.get("remitente"))
    return cfg


def guardar_config(con, datos):
    cfg = dict(DEFECTOS)
    anterior = leer_config(con)
    cfg.update({k: anterior.get(k) for k in CAMPOS if anterior.get(k) is not None})
    for k in CAMPOS:
        if k in datos:
            cfg[k] = datos[k]
    # Dejar la contraseña como estaba si el formulario la manda vacía (no se devuelve al cliente).
    if not datos.get("password"):
        cfg["password"] = anterior.get("password") or ""
    cfg["puerto"] = int(cfg.get("puerto") or 587)
    a_guardar = {k: cfg[k] for k in CAMPOS}
    a_guardar["password"] = _cifrar(cfg.get("password") or "")
    core_db.meta_set(con, CLAVE_CONFIG, json.dumps(a_guardar))
    return leer_config(con)


def config_publica(con):
    """La misma configuración sin la contraseña, para pintarla en Ajustes."""
    cfg = leer_config(con)
    cfg["password"] = ""
    cfg["tiene_password"] = bool(leer_config(con).get("password"))
    return cfg


def _conectar(cfg):
    puerto = int(cfg.get("puerto") or 587)
    seguridad = (cfg.get("seguridad") or "starttls").lower()
    if seguridad == "ssl":
        servidor = smtplib.SMTP_SSL(cfg["servidor"], puerto, timeout=20, context=ssl.create_default_context())
    else:
        servidor = smtplib.SMTP(cfg["servidor"], puerto, timeout=20)
        if seguridad == "starttls":
            servidor.starttls(context=ssl.create_default_context())
    if cfg.get("usuario"):
        servidor.login(cfg["usuario"], cfg.get("password") or "")
    return servidor


def _mensaje(cfg, para, asunto, cuerpo_html):
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr((cfg.get("nombre_remitente") or "Hangar", cfg["remitente"]))
    msg["To"] = para
    if cfg.get("responder_a"):
        msg["Reply-To"] = cfg["responder_a"]
    texto = cuerpo_html
    for etiqueta in ("</p>", "</tr>", "</div>", "<br>", "<br/>"):
        texto = texto.replace(etiqueta, "\n")
    import re
    msg.set_content(re.sub(r"<[^>]+>", "", texto).strip())
    msg.add_alternative(cuerpo_html, subtype="html")
    return msg


def encolar(con, para, asunto, cuerpo_html, referencia=None):
    cur = con.execute(
        "INSERT INTO correo_cola(para, asunto, cuerpo, referencia) VALUES(?,?,?,?)",
        (para, asunto, cuerpo_html, referencia),
    )
    con.commit()
    return cur.lastrowid


def enviar(con, para, asunto, cuerpo_html, referencia=None):
    """Encola y trata de enviar. Devuelve el estado para que la interfaz lo muestre tal cual."""
    correo_id = encolar(con, para, asunto, cuerpo_html, referencia)
    cfg = leer_config(con)
    if not cfg["configurado"]:
        return {"ok": False, "estado": "pendiente", "id": correo_id,
                "motivo": "Correo sin configurar: la orden quedó en la bandeja de salida. "
                          "Configúralo en Ajustes › Correo y reenvíala."}
    return _despachar(con, correo_id, cfg)


def _despachar(con, correo_id, cfg):
    fila = con.execute("SELECT * FROM correo_cola WHERE id=?", (correo_id,)).fetchone()
    if not fila:
        return {"ok": False, "estado": "error", "motivo": "El correo ya no existe en la cola."}
    try:
        with _conectar(cfg) as servidor:
            servidor.send_message(_mensaje(cfg, fila["para"], fila["asunto"], fila["cuerpo"]))
    except Exception as exc:  # red, credenciales, servidor caído…
        con.execute("UPDATE correo_cola SET estado='error', error=?, intentos=intentos+1 WHERE id=?",
                    (f"{type(exc).__name__}: {exc}", correo_id))
        con.commit()
        return {"ok": False, "estado": "error", "id": correo_id, "motivo": f"No se pudo enviar: {exc}"}
    con.execute("UPDATE correo_cola SET estado='enviado', error=NULL, intentos=intentos+1, "
                "enviado=datetime('now') WHERE id=?", (correo_id,))
    con.commit()
    return {"ok": True, "estado": "enviado", "id": correo_id, "motivo": "Correo enviado."}


def reintentar_pendientes(con):
    cfg = leer_config(con)
    if not cfg["configurado"]:
        return {"ok": False, "enviados": 0, "motivo": "Correo sin configurar."}
    filas = con.execute("SELECT id FROM correo_cola WHERE estado!='enviado' ORDER BY id").fetchall()
    enviados = sum(1 for f in filas if _despachar(con, f["id"], cfg)["ok"])
    return {"ok": True, "enviados": enviados, "total": len(filas),
            "motivo": f"{enviados} de {len(filas)} correo(s) enviados."}


def probar(con, destino):
    cfg = leer_config(con)
    if not cfg["configurado"]:
        return {"ok": False, "motivo": "Falta el servidor SMTP o el remitente."}
    cuerpo = ("<p>Prueba de configuración de correo de <b>Hangar</b>.</p>"
              "<p>Si recibes este mensaje, las órdenes de trabajo y de servicio ya se pueden enviar "
              "automáticamente al personal asignado.</p>")
    return enviar(con, destino, "Hangar · prueba de correo", cuerpo, referencia="prueba")
