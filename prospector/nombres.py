"""Limpieza de nombres de LinkedIn y generación de (nombre, apellido) para Hunter.

Los nombres en España suelen llevar dos apellidos, nombres compuestos
(Juan Carlos, María José) y partículas (de la Fuente). Hunter construye el
email a partir de nombre + apellido, así que se prueban varias combinaciones:
si una no encuentra nada, Hunter no cobra crédito.
"""
import re
import unicodedata

_TITULOS = {
    "mba", "emba", "phd", "dr", "dra", "lic", "ing", "msc", "mrs", "mr", "ms",
    "cpa", "pmp", "cipd", "chrp", "shrm-cp", "shrm-scp", "llm", "sr", "sra", "jr",
}
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "i", "da", "das", "do", "dos",
               "van", "von", "der", "di", "le", "el"}
# Palabras que, en 2.ª posición, suelen ser parte de un nombre compuesto.
_SEGUNDOS_NOMBRES = {
    "jose", "maria", "luis", "luisa", "carmen", "antonio", "manuel", "jesus",
    "angel", "angeles", "pablo", "carlos", "ignacio", "isabel", "pilar", "dolores",
    "elena", "eugenia", "victoria", "rosa", "teresa", "francisco", "javier",
    "miguel", "ramon", "josep", "carles", "lluis", "montserrat", "merce",
    "mercedes", "fernando", "andres", "alberto", "enrique", "eduardo", "gabriel",
    "jorge", "joan", "ana", "belen", "cristina", "lourdes", "paz", "sol", "mar",
    "inmaculada", "concepcion", "rocio", "esther", "jordi", "pau", "marc",
}
_NO_NOMBRES = {"linkedin member", "miembro de linkedin", "usuario de linkedin"}


def normalizar(texto: str) -> str:
    """minúsculas y sin tildes."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def limpiar(nombre: str) -> str:
    """Quita emojis, títulos, paréntesis y coletillas: 'Ana Pérez, MBA 🚀' -> 'Ana Pérez'."""
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", nombre or "")
    s = s.split(",")[0]
    s = re.split(r"\s[|·–—/-]\s", s)[0]
    s = "".join(c if (c.isalpha() or c in " .'-") else " " for c in s)
    tokens = [t for t in s.split() if normalizar(t).strip(".") not in _TITULOS]
    return " ".join(tokens)


def es_valido(nombre: str) -> bool:
    return bool(limpiar(nombre)) and normalizar(nombre) not in _NO_NOMBRES


def es_incompleto(nombre: str) -> bool:
    """True si falta el apellido o está abreviado ('Ana M.')."""
    tokens = limpiar(nombre).split()
    return len(tokens) < 2 or len(tokens[-1].rstrip(".")) <= 1


def partir(nombre: str) -> tuple[str, list[str]]:
    """Devuelve (nombre de pila, [apellido1, apellido2...]). Ignora iniciales sueltas."""
    tokens = [t for t in limpiar(nombre).split() if len(t.rstrip(".")) > 1]
    if len(tokens) < 2:
        return " ".join(tokens), []
    n_pila = 2 if len(tokens) >= 3 and normalizar(tokens[1]) in _SEGUNDOS_NOMBRES else 1
    grupos, actual = [], []
    for t in tokens[n_pila:]:
        actual.append(t)
        if normalizar(t) not in _PARTICULAS:
            grupos.append(" ".join(actual))
            actual = []
    if actual:
        grupos.append(" ".join(actual))
    return " ".join(tokens[:n_pila]), grupos


def candidatos(nombre: str, maximo: int = 3) -> list[tuple[str, str]]:
    """Combinaciones (first_name, last_name) a probar en Hunter, de más a menos probable."""
    pila, apellidos = partir(nombre)
    if not pila or not apellidos:
        return []
    primero = pila.split()[0]
    opciones = [
        (pila, apellidos[0]),
        (primero, apellidos[0]),
        (pila, " ".join(apellidos)),
    ]
    vistos, salida = set(), []
    for op in opciones:
        if op not in vistos:
            vistos.add(op)
            salida.append(op)
    return salida[:maximo]
