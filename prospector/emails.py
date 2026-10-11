"""Búsqueda de emails para los leads: Hunter (nombre + dominio/empresa) y Prospeo de respaldo.

REGLA: la empresa actual de LinkedIn es la única válida. Un email solo se acepta si su dominio
corresponde a esa empresa (por nombre, siglas o un dominio verificado en LinkedIn). Si no, se
guarda en `email_descartado` con el motivo y la columna `email` queda vacía. Que el buzón exista
('valid') no basta: puede ser el de una empresa anterior que aún recibe correo.
"""
from collections import Counter
from typing import Callable

from .almacen import Dominios, ahora, es_handle_publico, handle_linkedin, norm_empresa
from .hunter import ClaveInvalida, EmailReclamado, Hunter, HunterError, SinCreditos
from .nombres import candidatos
from .prospeo import Prospeo

# resultado_email que no se reintentan salvo con --reintentar
FINALES = {"encontrado", "no_encontrado", "nombre_incompleto", "sin_empresa", "excluido_451", "descartado"}

# TLD que no levantan sospecha para contactos en España; otro código de país (.cz, .at, .br...) sí.
_TLD_NORMALES = {"com", "es", "cat", "eu", "net", "org", "info", "io", "co", "group", "global", "biz"}
# Dominios personales o de proveedores/colegios profesionales: no son el email de la empresa.
DOMINIOS_PERSONALES = {
    "gmail.com", "hotmail.com", "hotmail.es", "outlook.com", "outlook.es", "yahoo.com", "yahoo.es",
    "live.com", "msn.com", "icloud.com", "me.com", "telefonica.net", "movistar.es", "infonegocio.com",
    "terra.es", "ya.com", "wanadoo.es", "orange.es", "vodafone.es", "ono.com", "icab.cat", "coac.net",
    "protonmail.com", "gmx.com", "gmx.es", "netvisao.pt",
}
_PARTICULAS_EMPRESA = {"de", "del", "la", "las", "los", "el", "i", "y", "and", "of", "the", "et", "d", "l"}


def _dominio(email: str) -> str:
    return email.split("@", 1)[1].lower().strip() if email and "@" in email else ""


def _en_verificados(dom: str, verificados: list[str]) -> bool:
    return any(dom == v or dom.endswith("." + v) for v in verificados or [])


def dominio_coincide(email: str, empresa: str, verificados: list[str] | None = None) -> bool:
    """True si el dominio del email corresponde a la empresa: dominio verificado, nombre o siglas."""
    dom = _dominio(email)
    if not dom:
        return False
    if _en_verificados(dom, verificados):
        return True
    etiquetas = [e.replace("-", "") for e in dom.split(".")[:-1]]
    base = "".join(etiquetas)
    todas = norm_empresa(empresa).split()
    if any(len(p) >= 3 and (p in base or base in p) for p in todas):
        return True
    # palabras de 2 letras solo como inicio de etiqueta: "DF Electric" -> df-sa.es
    if any(len(p) == 2 and any(e.startswith(p) for e in etiquetas) for p in todas):
        return True
    # Siglas: Procter & Gamble -> pg.com, Deutsche Bank -> db.com, Fundació Bosch i Gimpera -> fbg.ub.es
    siglas = "".join(p[0] for p in todas if p not in _PARTICULAS_EMPRESA)
    return len(siglas) >= 2 and any(len(e) >= 2 and siglas.startswith(e) for e in etiquetas)


def motivo_rechazo(email: str, empresa: str, verificados: list[str] | None = None) -> str:
    """Motivo por el que el email NO es de la empresa actual ('' si es aceptable). Bloqueante."""
    dom = _dominio(email)
    if not dom:
        return ""
    if not empresa:
        return "sin empresa actual en LinkedIn para comprobar el dominio"
    if dom in DOMINIOS_PERSONALES:
        return f"email personal o no corporativo ({dom})"
    if not dominio_coincide(email, empresa, verificados):
        return f"el dominio {dom} no corresponde a la empresa actual en LinkedIn ({empresa})"
    tld = dom.rsplit(".", 1)[-1]
    if tld not in _TLD_NORMALES and not _en_verificados(dom, verificados):
        return f"dominio de otro país (.{tld}), no verificado para {empresa}"
    return ""


def motivo_revisar(lead: dict) -> str:
    """Avisos no bloqueantes sobre un email que sí es de la empresa actual."""
    score = lead.get("email_score", "")
    if score.isdigit() and int(score) < 60:
        return f"Revisar: confianza baja ({score})"
    return ""


def aplicar_regla(lead: dict, verificados: list[str] | None = None) -> str:
    """Aplica la regla al email del lead. Devuelve 'encontrado' o 'descartado'."""
    notas = [p for p in lead.get("nota", "").split(" | ")
             if p and not p.startswith(("Revisar:", "Descartado:"))]
    motivo = motivo_rechazo(lead.get("email", ""), lead.get("empresa", ""), verificados)
    if motivo:
        lead.update(email_descartado=lead["email"], email="", email_score="", email_estado="",
                    resultado_email="descartado", validacion="")
        lead["nota"] = " | ".join(notas + [f"Descartado: {motivo}"])
        return "descartado"
    aviso = motivo_revisar(lead)
    lead["validacion"] = "Revisar" if aviso else ("" if lead.get("validacion") == "Revisar" else lead.get("validacion", ""))
    lead["nota"] = " | ".join(notas + ([aviso] if aviso else []))
    return "encontrado"


def _encontrado(lead: dict, email: str, fuente: str, score, estado, dominios: Dominios) -> str:
    lead.update(email=email, email_fuente=fuente, email_score=str(score or ""),
                email_estado=estado or "", resultado_email="encontrado", fecha_email=ahora())
    return aplicar_regla(lead, dominios.verificados(lead.get("empresa", "")))


def _aprender_dominio(lead: dict, dominio: str, dominios: Dominios) -> None:
    """Guarda en caché el dominio que propone el proveedor solo si cuadra con el nombre de la empresa."""
    empresa = lead.get("empresa", "")
    if dominio and empresa and not dominios.get(empresa) and dominio_coincide("x@" + dominio, empresa):
        dominios.set(empresa, dominio)


def _con_hunter(lead: dict, hunter: Hunter, dominios: Dominios) -> str | None:
    empresa = lead.get("empresa", "")
    # Prioridad: dominio verificado en LinkedIn > caché (solo guarda dominios que cuadran con el nombre)
    # > dominio del lead si cuadra con el nombre (los antiguos pudo ponerlos Hunter mal: seatbus.org).
    dom = ""
    for posible in (dominios.get(empresa), lead.get("dominio")):
        if posible and (dominios.es_verificado(empresa) or dominio_coincide("x@" + posible, empresa)):
            dom = posible
            break
    handle = handle_linkedin(lead.get("url_linkedin", ""))
    handle = handle if es_handle_publico(handle) else ""
    resultado = None

    for first, last in candidatos(lead.get("nombre", "")):
        if not dom and not empresa:
            break
        try:
            data = hunter.buscar_email(first, last, dominio=dom or None,
                                       empresa=None if dom else empresa)
        except HunterError as e:
            if e.codigo != "invalid_domain" or not dom or not empresa:
                raise
            dominios.borrar(empresa)  # dominio de la caché erróneo: probar con el nombre de empresa
            dom = ""
            data = hunter.buscar_email(first, last, empresa=empresa)
        if data.get("domain") and not dom:
            _aprender_dominio(lead, data["domain"], dominios)
            dom = dominios.get(empresa)  # solo si cuadraba con la empresa; si no, sigue por nombre
            if dom:
                lead["dominio"] = dom
        if data.get("email"):
            estado = (data.get("verification") or {}).get("status") or ""
            resultado = _encontrado(lead, data["email"], "hunter", data.get("score"), estado, dominios)
            if resultado == "encontrado":
                return resultado
            break  # dominio equivocado: otras variantes del nombre darían el mismo dominio

    if handle:
        data = hunter.buscar_email(linkedin_handle=handle)
        if data.get("email"):
            estado = (data.get("verification") or {}).get("status") or ""
            resultado = _encontrado(lead, data["email"], "hunter", data.get("score"), estado, dominios)
    return resultado


def _con_prospeo(lead: dict, prospeo: Prospeo, dominios: Dominios) -> str | None:
    url = lead.get("url_linkedin", "")
    publico = es_handle_publico(handle_linkedin(url))
    cands = candidatos(lead.get("nombre", ""))
    empresa = lead.get("empresa", "")
    dom = dominios.get(empresa) if dominios.es_verificado(empresa) else ""
    if not publico and not (cands and (dom or empresa)):
        return None
    first, last = cands[0] if cands else ("", "")
    res = prospeo.buscar_email(first_name=first, last_name=last, empresa=empresa,
                               dominio=dom or None, linkedin_url=url if publico else None)
    if res.get("dominio"):
        _aprender_dominio(lead, res["dominio"], dominios)
    if res.get("email"):
        return _encontrado(lead, res["email"], "prospeo", "", res.get("estado", ""), dominios)
    return None


def buscar_email_lead(lead: dict, hunter: Hunter | None, prospeo: Prospeo | None,
                      dominios: Dominios) -> str:
    """Rellena los campos de email del lead y devuelve el resultado."""
    if not candidatos(lead.get("nombre", "")) and not es_handle_publico(handle_linkedin(lead.get("url_linkedin", ""))):
        lead["resultado_email"] = "nombre_incompleto"
        return "nombre_incompleto"
    descartado = False
    try:
        for proveedor, funcion in ((hunter, _con_hunter), (prospeo, _con_prospeo)):
            if proveedor is None:
                continue
            resultado = funcion(lead, proveedor, dominios)
            if resultado == "encontrado":
                return "encontrado"
            descartado = descartado or resultado == "descartado"
    except EmailReclamado:
        lead.update(resultado_email="excluido_451", fecha_email=ahora(),
                    nota=(lead.get("nota", "") + " | Pidió no tratar sus datos (451)").strip(" |"))
        return "excluido_451"
    if descartado:
        lead.update(resultado_email="descartado", fecha_email=ahora())
        return "descartado"
    resultado = "no_encontrado" if (lead.get("empresa") or lead.get("dominio")) else "sin_empresa"
    lead.update(resultado_email=resultado, fecha_email=ahora())
    return resultado


def verificar_lead(lead: dict, hunter: Hunter) -> str:
    data = hunter.verificar(lead["email"])
    estado = data.get("status", "unknown")
    lead.update(email_estado=estado, email_verificado=ahora())
    if data.get("score") is not None and not lead.get("email_score"):
        lead["email_score"] = str(data["score"])
    return estado


def pendientes(leads: list[dict], busqueda: str | None = None, reintentar: bool = False) -> list[dict]:
    salida = []
    for l in leads:
        if busqueda and busqueda not in l.get("busqueda", "").split(" | "):
            continue
        if l.get("email"):
            continue
        if l.get("resultado_email") in FINALES and not reintentar:
            continue
        if l.get("resultado_email") == "excluido_451":
            continue
        salida.append(l)
    return salida


def sin_dominio_verificado(leads: list[dict], dominios: Dominios, busqueda: str | None = None) -> list[dict]:
    """Leads pendientes de email cuya empresa aún no tiene dominio verificado en LinkedIn."""
    return [l for l in pendientes(leads, busqueda, reintentar=True)
            if l.get("empresa") and not dominios.es_verificado(l["empresa"])]


def enriquecer(leads: list[dict], *, hunter: Hunter | None, prospeo: Prospeo | None,
               dominios: Dominios, busqueda: str | None = None, limite: int | None = None,
               verificar: bool = False, reintentar: bool = False,
               max_encontrados: int | None = None,
               guardar: Callable[[], None] = lambda: None,
               log: Callable[[str], None] = print) -> Counter:
    cola = pendientes(leads, busqueda, reintentar)
    if limite:
        cola = cola[:limite]
    stats: Counter = Counter()
    log(f"Leads a procesar: {len(cola)}")
    try:
        for i, lead in enumerate(cola, 1):
            # un email descartado también ha gastado crédito en Hunter
            if max_encontrados is not None and stats["encontrado"] + stats["descartado"] >= max_encontrados:
                log(f"Tope de {max_encontrados} créditos alcanzado.")
                break
            try:
                resultado = buscar_email_lead(lead, hunter, prospeo, dominios)
                if resultado == "encontrado" and verificar and hunter and lead.get("email_estado") != "valid":
                    verificar_lead(lead, hunter)
            except (SinCreditos, ClaveInvalida):
                raise
            except HunterError as e:
                resultado = "error"
                lead.update(resultado_email="error", nota=f"{lead.get('nota', '')} | {e}".strip(" |"))
            stats[resultado] += 1
            detalle = lead.get("email") or (f"DESCARTADO {lead.get('email_descartado')}" if resultado == "descartado" else resultado)
            log(f"[{i}/{len(cola)}] {lead['nombre']} · {lead.get('empresa', '')} -> "
                f"{detalle} {lead.get('email_estado', '')}".rstrip())
            if i % 5 == 0:
                dominios.guardar()
                guardar()
    except KeyboardInterrupt:
        log("Interrumpido: guardando lo procesado.")
    finally:
        dominios.guardar()
        guardar()
    return stats
