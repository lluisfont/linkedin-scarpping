"""Filtros de cargo: el filtro de título de Sales Navigator es laxo (cuela profesores de másters de RRHH,
analistas, consultores...). Aquí se decide con reglas fijas si un cargo encaja con el perfil pedido."""
import re

from .nombres import normalizar

PERFILES = {
    "rrhh": {
        # Frases que por sí solas confirman "director/a de RRHH" (ganan a las exclusiones blandas).
        "fuertes": [
            r"\b(hr|rrhh|human resources|people|personas|people & culture|people and culture)\s+"
            r"(director|directora)\b",
            r"\b(director|directora)\s+(de\s+|del\s+|of\s+)?(rrhh|recursos humanos|human resources|hr|"
            r"personas|people|organizacion y personas|personas y organizacion|capital humano)\b",
            r"\b(head|jefe|jefa|vp|vice ?president)\s+(of\s+|de\s+)?(hr|rrhh|human resources|recursos humanos|"
            r"people|personas)\b",
            r"\b(chro|cpo|hrd|chief people officer|chief human resources officer|chief people & culture officer|"
            r"chief people and culture officer)\b",
            # Máximo responsable de RRHH con otro título (habitual en empresas medianas)
            r"\b(responsable|manager|gerente|jefe|jefa|cap)\s+(de\s+|del\s+|of\s+)?(rrhh|rr hh|recursos humanos|"
            r"recursos humans|human resources|hr|personas|persones|personal|people|people & culture|"
            r"people and culture)\b",
            r"\b(hr|rrhh|human resources|people|people & culture|people and culture)\s+manager\b",
            r"\b(director|directora)\s+(de\s+)?(recursos humans|persones)\b",
        ],
        # Cargo de RRHH en general (necesita además un término de dirección).
        "area": r"\b(rrhh|recursos humanos|recursos humans|persones|human resources|hr|people|personas|talent|talento|capital humano|"
                r"human capital|organizacion y personas|people & culture|people and culture)\b",
        # Nunca son director de RRHH de su empresa.
        "duras": [
            r"\b(profesor|profesora|professor|tutor|teacher|docente|lecturer|mentor|(?<!internal )coach|"
            r"academic|academico|academica|postgrado|riesgos|juridicas|compensation & benefits|"
            r"formador|formadora)\b",
            r"\b(consultant|consultor|consultora|advisor|asesor|asesora|freelance|headhunter|"
            r"recruiter|reclutador|reclutadora)\b",
            r"\b(student|estudiante|becari[oa]|intern|assistant|asistente|tecnic[oa]|administrativ[oa])\b",
            # RRHH que se presta a clientes (consultoras/outsourcing) y responsables de HRBP
            r"\b(client solutions|client services|clientes|for clients|apoyo|soporte|support to|"
            r"self employed|pmo)\b",
        ],
        # Área seguida de una función concreta ("People Analytics", "HR Legal"): excluye siempre.
        "funcion_del_area": r"\b(hr|rrhh|people|personas|human resources|culture)\s+(analytics|legal|compliance|"
                            r"relations|data|systems|tech|technology|it|operations analytics|experience|"
                            r"business partners?|bp|partners?|partnership|projects?|development|hris|intelligence|planning|generalists?|transformation|services)\b",
        # Funciones concretas dentro de RRHH: excluyen salvo frase fuerte.
        "blandas": [
            r"\b(analytics|analyst|analista|payroll|nomina|nominas|legal|abogad[oa]|lawyer|total rewards|"
            r"compensation|compensacion|benefits|c&b|comp&ben|retribucion|learning|formacion|desarrollo|talent acquisition|talent adquisition|talent adquistion|adquisicion de talento|"
            r"talent management|gestion del talento|program management|programme management|project management|"
            r"employer branding|business partner|labour relations|relaciones laborales|"
            r"administracion de personal|administracion de personas|seleccion|recruitment|hrbp|hris|programas?|programs?)\b",
        ],
    },
}
_DIRECCION = (r"\b(director|directora|dir|head|jefe|jefa|chief|vp|vice ?president|vicepresident[ea]|chro|cpo|"
              r"global head)\b")


ZONAS = {  # ubicación aceptada por zona de búsqueda ('' = sin ubicación visible, se acepta)
    "bcn": r"barcelona|catalu|catalonia|cataluna|spain|espana",
}


def en_zona(ubicacion: str, zona: str) -> bool:
    patron = ZONAS.get(zona)
    texto = normalizar(ubicacion or "")
    return not patron or not texto or bool(re.search(patron, texto))


def encaja(cargo: str, perfil: str) -> tuple[bool, str]:
    """(True, '') si el cargo es de dirección del perfil pedido; (False, motivo) si no."""
    if perfil not in PERFILES:
        raise SystemExit(f"Perfil de filtro desconocido: {perfil}. Disponibles: {', '.join(PERFILES)}")
    reglas = PERFILES[perfil]
    texto = normalizar(cargo or "")
    if not texto:
        return False, "sin cargo"
    for patron in reglas["duras"]:
        m = re.search(patron, texto)
        if m:
            return False, f"no es director/a de {perfil.upper()} ('{m.group(0)}')"
    m = re.search(reglas["funcion_del_area"], texto)
    if m:
        return False, f"función concreta, no dirección de {perfil.upper()} ('{m.group(0)}')"
    if any(re.search(p, texto) for p in reglas["fuertes"]):
        return True, ""
    for patron in reglas["blandas"]:
        m = re.search(patron, texto)
        if m:
            return False, f"función concreta, no dirección de {perfil.upper()} ('{m.group(0)}')"
    if not re.search(reglas["area"], texto):
        return False, f"cargo fuera del área {perfil.upper()}"
    if not re.search(_DIRECCION, texto):
        return False, "no es cargo de dirección (manager/responsable)"
    return True, ""
