"""Búsqueda de emails para los leads: Hunter (nombre + dominio/empresa) y Prospeo de respaldo."""
from collections import Counter
from typing import Callable

from .almacen import Dominios, ahora, es_handle_publico, handle_linkedin, norm_empresa
from .hunter import ClaveInvalida, EmailReclamado, Hunter, HunterError, SinCreditos
from .nombres import candidatos
from .prospeo import Prospeo

# resultado_email que no se reintentan salvo con --reintentar
FINALES = {"encontrado", "no_encontrado", "nombre_incompleto", "sin_empresa", "excluido_451"}


# TLD que no levantan sospecha para contactos en España; otro código de país (.cz, .at, .br...) sí.
_TLD_NORMALES = {"com", "es", "cat", "eu", "net", "org", "info", "io", "co", "group", "global", "biz"}


def motivo_dudoso(lead: dict) -> str:
    """Detecta emails cuyo dominio probablemente no es el de la empresa ('' si parece correcto).

    Hunter, cuando busca por nombre de empresa, a veces elige una filial de otro país
    (culligan.cz) o una empresa distinta (meetproducerx.com para Mandarin Oriental).
    """
    email, estado = lead.get("email", ""), lead.get("email_estado", "")
    if not email or "@" not in email:
        return ""
    dominio = email.split("@", 1)[1].lower()
    partes = dominio.split(".")
    tld, base = partes[-1], "".join(partes[:-1]).replace("-", "")
    palabras = [p for p in norm_empresa(lead.get("empresa", "")).split() if len(p) >= 3]
    coincide = any(p in base or base in p for p in palabras) if palabras else True
    if tld not in _TLD_NORMALES and estado != "valid":
        return f"Revisar: dominio de otro país (.{tld})"
    if not coincide and estado != "valid":
        return f"Revisar: el dominio {dominio} no se parece a {lead.get('empresa', '')}"
    score = lead.get("email_score", "")
    if score.isdigit() and int(score) < 60:
        return f"Revisar: confianza baja ({score})"
    return ""


def _encontrado(lead: dict, email: str, fuente: str, score="", estado="") -> str:
    lead.update(email=email, email_fuente=fuente, email_score=str(score or ""),
                email_estado=estado or "", resultado_email="encontrado", fecha_email=ahora())
    motivo = motivo_dudoso(lead)
    if motivo:
        lead.update(validacion="Revisar", nota=f"{lead.get('nota', '')} | {motivo}".strip(" |"))
    return "encontrado"


def _con_hunter(lead: dict, hunter: Hunter, dominios: Dominios) -> str | None:
    empresa = lead.get("empresa", "")
    dom = lead.get("dominio") or dominios.get(empresa)
    handle = handle_linkedin(lead.get("url_linkedin", ""))
    handle = handle if es_handle_publico(handle) else ""

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
            dom = data["domain"]
            dominios.set(empresa, dom)
        if dom:
            lead["dominio"] = dom
        if data.get("email"):
            estado = (data.get("verification") or {}).get("status") or ""
            return _encontrado(lead, data["email"], "hunter", data.get("score"), estado)

    if handle:
        data = hunter.buscar_email(linkedin_handle=handle)
        if data.get("domain") and not lead.get("dominio"):
            lead["dominio"] = data["domain"]
        if data.get("email"):
            estado = (data.get("verification") or {}).get("status") or ""
            return _encontrado(lead, data["email"], "hunter", data.get("score"), estado)
    return None


def _con_prospeo(lead: dict, prospeo: Prospeo, dominios: Dominios) -> str | None:
    url = lead.get("url_linkedin", "")
    publico = es_handle_publico(handle_linkedin(url))
    cands = candidatos(lead.get("nombre", ""))
    empresa = lead.get("empresa", "")
    dom = lead.get("dominio") or dominios.get(empresa)
    if not publico and not (cands and (dom or empresa)):
        return None
    first, last = cands[0] if cands else ("", "")
    res = prospeo.buscar_email(first_name=first, last_name=last, empresa=empresa,
                               dominio=dom or None, linkedin_url=url if publico else None)
    if res.get("dominio") and empresa and not dom:
        dominios.set(empresa, res["dominio"])
        lead["dominio"] = res["dominio"]
    if res.get("email"):
        return _encontrado(lead, res["email"], "prospeo", "", res.get("estado", ""))
    return None


def buscar_email_lead(lead: dict, hunter: Hunter | None, prospeo: Prospeo | None,
                      dominios: Dominios) -> str:
    """Rellena los campos de email del lead y devuelve el resultado."""
    if not candidatos(lead.get("nombre", "")) and not es_handle_publico(handle_linkedin(lead.get("url_linkedin", ""))):
        lead["resultado_email"] = "nombre_incompleto"
        return "nombre_incompleto"
    try:
        for proveedor, funcion in ((hunter, _con_hunter), (prospeo, _con_prospeo)):
            if proveedor is not None and funcion(lead, proveedor, dominios):
                return "encontrado"
    except EmailReclamado:
        lead.update(resultado_email="excluido_451", fecha_email=ahora(),
                    nota=(lead.get("nota", "") + " | Pidió no tratar sus datos (451)").strip(" |"))
        return "excluido_451"
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
            if max_encontrados is not None and stats["encontrado"] >= max_encontrados:
                log(f"Tope de {max_encontrados} emails encontrados (= créditos) alcanzado.")
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
            log(f"[{i}/{len(cola)}] {lead['nombre']} · {lead.get('empresa', '')} -> "
                f"{lead.get('email') or resultado} {lead.get('email_estado', '')}".rstrip())
            if i % 5 == 0:
                dominios.guardar()
                guardar()
    except KeyboardInterrupt:
        log("Interrumpido: guardando lo procesado.")
    finally:
        dominios.guardar()
        guardar()
    return stats
