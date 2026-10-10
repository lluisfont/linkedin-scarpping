"""Rutas del proyecto y carga de la clave de Hunter desde .env."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
RAW = DATA / "raw"
SALIDA = RAIZ / "salida"

LEADS_CSV = DATA / "leads.csv"
BUSQUEDAS_CSV = DATA / "busquedas.csv"
DOMINIOS_JSON = DATA / "dominios.json"

SEP = ";"            # separador CSV (Excel en español)
ENCODING = "utf-8-sig"  # UTF-8 con BOM para que Excel lea bien las tildes


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Carga KEY=VALUE de .env en os.environ sin sobrescribir lo que ya exista."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def hunter_api_key() -> str:
    cargar_env()
    clave = os.environ.get("HUNTER_API_KEY", "").strip()
    if not clave:
        raise SystemExit(
            "Falta HUNTER_API_KEY. Copia .env.example a .env y pon tu clave de "
            "https://hunter.io/api-keys"
        )
    return clave


def asegurar_carpetas() -> None:
    for carpeta in (DATA, RAW, SALIDA):
        carpeta.mkdir(parents=True, exist_ok=True)
