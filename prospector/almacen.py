"""Base de contactos única (SQLite: data/contactos.db) para TODAS las búsquedas y perfiles.

- contactos   : una fila por persona (id = ID de LinkedIn). Nunca se duplica: si reaparece en otra
                búsqueda se actualiza y se le añade la búsqueda/segmento.
- busquedas   : historial de cada página/lote importado (segmento, etiqueta, URL, totales).
- apariciones : en qué búsquedas ha salido cada persona y cuándo.
Los segmentos (RRHH, CEO, ...) agrupan búsquedas: hoy RRHH, mañana CEOs, todo en la misma base.
"""
import csv
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import config
from .nombres import es_valido, normalizar, partir

CAMPOS = [
    "id", "nombre", "nombre_pila", "apellidos", "cargo", "empresa", "empresa_id",
    "ubicacion", "tiempo_puesto", "url_linkedin", "url_salesnav", "segmentos", "busqueda",
    "fecha_alta", "ultima_vez", "dominio", "email", "email_score", "email_estado", "email_fuente",
    "email_verificado", "resultado_email", "fecha_email", "validacion", "nota", "email_descartado",
]
CAMPOS_BUSQUEDA = ["fecha", "segmento", "busqueda", "origen", "url", "pagina", "total_resultados",
                   "leads_en_lote", "nuevos"]
# Campos que se refrescan si llega un dato nuevo no vacío; el resto solo se rellena si está vacío.
_REFRESCABLES = {"cargo", "empresa", "empresa_id", "ubicacion", "tiempo_puesto", "url_salesnav", "ultima_vez"}
_SUFIJOS_EMPRESA = {"sa", "sl", "slu", "sau", "sll", "sociedad", "anonima", "limitada",
                    "inc", "ltd", "llc", "gmbh", "plc", "bv", "nv", "spa", "srl"}


def ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------- CSV (exportaciones y migración) ----------

def _leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with ruta.open(encoding=config.ENCODING, newline="") as f:
        return list(csv.DictReader(f, delimiter=config.SEP))


def _escribir_csv(ruta: Path, filas: list[dict], campos: list[str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", encoding=config.ENCODING, newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=config.SEP, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in campos})
    try:
        tmp.replace(ruta)
    except PermissionError as e:
        raise SystemExit(f"No puedo escribir {ruta}: ¿está abierto en Excel? Ciérralo y repite.") from e


# ---------- base SQLite ----------

def segmento_de(etiqueta: str) -> str:
    """Convención de etiquetas <segmento>-<zona>-<...>: 'rrhh-bcn-1000' -> 'RRHH', 'ceo-madrid' -> 'CEO'."""
    return (etiqueta or "").split("-")[0].strip().upper()


def _insert_busqueda_sql() -> str:
    return (f"INSERT INTO busquedas ({', '.join(CAMPOS_BUSQUEDA)}) "
            f"VALUES ({', '.join('?' * len(CAMPOS_BUSQUEDA))})")


def conectar(db: Path | None = None) -> sqlite3.Connection:
    db = db or config.DB
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    columnas = ", ".join(f'"{c}" TEXT' for c in CAMPOS if c != "id")
    columnas_b = ", ".join(f'"{c}" TEXT' for c in CAMPOS_BUSQUEDA)
    con.executescript(f"""
        CREATE TABLE IF NOT EXISTS contactos (id TEXT PRIMARY KEY, {columnas});
        CREATE TABLE IF NOT EXISTS busquedas (n INTEGER PRIMARY KEY AUTOINCREMENT, {columnas_b});
        CREATE TABLE IF NOT EXISTS apariciones (
            contacto_id TEXT, busqueda TEXT, segmento TEXT, fecha TEXT,
            PRIMARY KEY (contacto_id, busqueda));
        CREATE INDEX IF NOT EXISTS ix_apar_seg ON apariciones(segmento);
    """)
    # columnas añadidas a CAMPOS en versiones posteriores
    existentes = {r["name"] for r in con.execute("PRAGMA table_info(contactos)")}
    for c in CAMPOS:
        if c not in existentes:
            con.execute(f'ALTER TABLE contactos ADD COLUMN "{c}" TEXT')
    if db == config.DB:
        _migrar_csv(con)
    return con


def _migrar_csv(con: sqlite3.Connection) -> None:
    """Pasa la base antigua (data/leads.csv + busquedas.csv) a SQLite una sola vez."""
    if not config.LEADS_CSV.exists() or con.execute("SELECT COUNT(*) FROM contactos").fetchone()[0]:
        return
    leads = _leer_csv(config.LEADS_CSV)
    for l in leads:
        etiquetas = [e for e in l.get("busqueda", "").split(" | ") if e]
        l["segmentos"] = l.get("segmentos") or " | ".join(dict.fromkeys(segmento_de(e) for e in etiquetas))
        l["ultima_vez"] = l.get("ultima_vez") or l.get("fecha_alta", "")
    _upsert(con, leads)
    for l in leads:
        for e in [e for e in l.get("busqueda", "").split(" | ") if e]:
            con.execute("INSERT OR IGNORE INTO apariciones VALUES (?,?,?,?)",
                        (l["id"], e, segmento_de(e), l.get("fecha_alta", "")))
    for b in _leer_csv(config.BUSQUEDAS_CSV):
        b["segmento"] = b.get("segmento") or segmento_de(b.get("busqueda", ""))
        con.execute(_insert_busqueda_sql(), [b.get(c, "") for c in CAMPOS_BUSQUEDA])
    con.commit()
    for ruta in (config.LEADS_CSV, config.BUSQUEDAS_CSV):
        if ruta.exists():
            ruta.replace(ruta.with_name(ruta.name + ".migrado"))


def _upsert(con: sqlite3.Connection, leads: list[dict]) -> None:
    cols = ", ".join(f'"{c}"' for c in CAMPOS)
    con.executemany(f"INSERT OR REPLACE INTO contactos ({cols}) VALUES ({', '.join('?' * len(CAMPOS))})",
                    [[str(l.get(c, "") or "") for c in CAMPOS] for l in leads])


def cargar_leads(db: Path | None = None) -> list[dict]:
    with closing(conectar(db)) as con:
        return [{c: (r[c] or "") for c in CAMPOS}
                for r in con.execute("SELECT * FROM contactos ORDER BY fecha_alta, rowid")]


def guardar_leads(leads: list[dict], db: Path | None = None) -> None:
    with closing(conectar(db)) as con:
        _upsert(con, leads)
        con.commit()


def registrar_apariciones(ids: list[str], busqueda: str, segmento: str, db: Path | None = None) -> None:
    with closing(conectar(db)) as con:
        con.executemany("INSERT OR IGNORE INTO apariciones VALUES (?,?,?,?)",
                        [(i, busqueda, segmento, ahora()) for i in ids])
        con.commit()


def norm_empresa(empresa: str) -> str:
    t = re.sub(r"[^\w\s]", " ", normalizar(empresa).replace(".", ""))
    return " ".join(p for p in t.split() if p not in _SUFIJOS_EMPRESA)


def _clave_persona(lead: dict) -> str:
    return f"{normalizar(lead.get('nombre', ''))}|{norm_empresa(lead.get('empresa', ''))}"


def handle_linkedin(url: str) -> str:
    """'https://www.linkedin.com/in/ana-perez-123/' -> 'ana-perez-123'."""
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def es_handle_publico(handle: str) -> bool:
    """Los IDs internos de Sales Navigator (ACwAA...) no son la URL personalizada."""
    return bool(handle) and not handle.startswith("ACw")


def normalizar_lead(bruto: dict, busqueda: str, segmento: str | None = None) -> dict | None:
    """Convierte un registro del extractor del navegador al formato de la base."""
    nombre = (bruto.get("nombre") or "").strip()
    if not es_valido(nombre):
        return None
    url = (bruto.get("url_linkedin") or bruto.get("url") or "").split("?")[0].rstrip("/")
    lead_id = (bruto.get("id") or "").strip()
    if lead_id and not url:
        url = f"https://www.linkedin.com/in/{lead_id}"
    if not lead_id:
        lead_id = handle_linkedin(url)
    if not lead_id:
        return None
    pila, apellidos = partir(nombre)
    return {
        "id": lead_id,
        "nombre": nombre,
        "nombre_pila": pila,
        "apellidos": " ".join(apellidos),
        "cargo": (bruto.get("cargo") or bruto.get("titular") or "").strip(),
        "empresa": (bruto.get("empresa") or "").strip(),
        "empresa_id": str(bruto.get("empresa_id") or "").strip(),
        "ubicacion": (bruto.get("ubicacion") or "").strip(),
        "tiempo_puesto": (bruto.get("tiempo_puesto") or "").strip(),
        "url_linkedin": url,
        "url_salesnav": (bruto.get("url_salesnav") or "").split("?")[0],
        "dominio": (bruto.get("dominio") or "").strip().lower(),
        "segmentos": segmento if segmento is not None else segmento_de(busqueda),
        "busqueda": busqueda,
        "fecha_alta": ahora(),
        "ultima_vez": ahora(),
        "validacion": (bruto.get("validacion") or "").strip(),
        "nota": (bruto.get("nota") or "").strip(),
    }


def fusionar(leads: list[dict], nuevos: list[dict]) -> tuple[int, int, list[str]]:
    """Añade o actualiza contactos (por id y, si no, por nombre+empresa).

    Devuelve (nuevos, ya_existían, id en la base de cada contacto del lote).
    """
    por_id = {l["id"]: l for l in leads}
    por_persona = {_clave_persona(l): l for l in leads}
    n_nuevos = n_act = 0
    ids: list[str] = []
    for nuevo in nuevos:
        existente = por_id.get(nuevo["id"]) or por_persona.get(_clave_persona(nuevo))
        if existente is None:
            fila = {c: nuevo.get(c, "") for c in CAMPOS}
            leads.append(fila)
            por_id[fila["id"]] = fila
            por_persona[_clave_persona(fila)] = fila
            ids.append(fila["id"])
            n_nuevos += 1
            continue
        ids.append(existente["id"])
        for campo, valor in nuevo.items():
            if campo in ("id", "fecha_alta") or not valor:
                continue
            if campo in ("busqueda", "segmentos"):
                etiquetas = [e for e in existente.get(campo, "").split(" | ") if e]
                if valor not in etiquetas:
                    existente[campo] = " | ".join(etiquetas + [valor])
            elif campo == "url_linkedin":
                # una URL personalizada /in/ana-perez gana a la de ID interno /in/ACwAA...
                if es_handle_publico(handle_linkedin(valor)) or not existente.get(campo):
                    existente[campo] = valor
            elif campo in _REFRESCABLES or not existente.get(campo):
                existente[campo] = valor
        n_act += 1
    return n_nuevos, n_act, ids


CAMPOS_TROZO = ["id", "nombre", "cargo", "empresa", "empresa_id", "ubicacion", "tiempo_puesto"]


def leer_lote(ruta: Path) -> tuple[dict, list[dict]]:
    """Lee un lote del navegador.

    .json: {"origen", "url", "pagina", "total", "leads": [...]} o una lista de leads.
    .txt : líneas de extractor_salesnav_trozo.js (id|nombre|cargo|empresa|empresa_id|ubicacion|tiempo).
           Las líneas que empiezan por # son metadatos: '# pagina: 1', '# total: 247'.
    """
    texto = ruta.read_text(encoding="utf-8-sig")
    if ruta.suffix.lower() == ".txt":
        meta: dict = {"origen": "salesnav_lista"}
        leads = []
        for linea in texto.splitlines():
            linea = linea.strip()
            if not linea or linea == "FIN":
                continue
            if linea.startswith("#"):
                clave, _, valor = linea[1:].partition(":")
                meta[clave.strip()] = valor.strip()
                continue
            valores = linea.split("|")
            lead = dict(zip(CAMPOS_TROZO, valores + [""] * (len(CAMPOS_TROZO) - len(valores))))
            if lead["id"].startswith("ACw") and "," not in lead["id"]:
                lead["url_salesnav"] = f"https://www.linkedin.com/sales/lead/{lead['id']},NAME_SEARCH"
            leads.append(lead)
        return meta, leads
    contenido = json.loads(texto)
    if isinstance(contenido, list):
        return {}, contenido
    return contenido, contenido.get("leads") or []


# ---------- búsquedas ----------

def registrar_busqueda(meta: dict, busqueda: str, n_lote: int, n_nuevos: int,
                       segmento: str | None = None, db: Path | None = None) -> None:
    fila = {
        "fecha": ahora(), "segmento": segmento if segmento is not None else segmento_de(busqueda),
        "busqueda": busqueda, "origen": meta.get("origen", ""), "url": meta.get("url", ""),
        "pagina": meta.get("pagina", ""), "total_resultados": meta.get("total", ""),
        "leads_en_lote": n_lote, "nuevos": n_nuevos,
    }
    with closing(conectar(db)) as con:
        con.execute(_insert_busqueda_sql(), [str(fila[c]) for c in CAMPOS_BUSQUEDA])
        con.commit()


def cargar_busquedas(db: Path | None = None) -> list[dict]:
    with closing(conectar(db)) as con:
        return [{c: (r[c] or "") for c in CAMPOS_BUSQUEDA}
                for r in con.execute("SELECT * FROM busquedas ORDER BY n")]


# ---------- dominios ----------

class Dominios:
    """Caché empresa -> dominio en data/dominios.json (editable a mano).

    Dos tipos de entrada:
      "empresa": "dominio.com"                                   -> lo propuso Hunter (NO verificado)
      "empresa": {"dominio": "x.com", "verificados": ["x.com", "y.com"]}  -> sacado de la página de la
          empresa en LinkedIn o fijado por el usuario. Solo estos dominios validan un email que no
          se parezca al nombre de la empresa.
    """

    def __init__(self, ruta: Path = config.DOMINIOS_JSON):
        self.ruta = ruta
        self.datos: dict = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}

    def get(self, empresa: str) -> str:
        valor = self.datos.get(norm_empresa(empresa), "") if empresa else ""
        return valor.get("dominio", "") if isinstance(valor, dict) else valor

    def verificados(self, empresa: str) -> list[str]:
        valor = self.datos.get(norm_empresa(empresa)) if empresa else None
        return list(valor.get("verificados", [])) if isinstance(valor, dict) else []

    def es_verificado(self, empresa: str) -> bool:
        return bool(self.verificados(empresa))

    def set(self, empresa: str, dominio: str, verificado: bool = False) -> None:
        clave = norm_empresa(empresa)
        if not clave:
            return
        dom = limpiar_dominio(dominio)
        if verificado:
            previos = self.verificados(empresa)
            self.datos[clave] = {"dominio": dom, "verificados": sorted(set(previos + [dom]))}
        elif not self.es_verificado(empresa):  # una propuesta de Hunter nunca pisa un dominio verificado
            self.datos[clave] = dom

    def borrar(self, empresa: str) -> None:
        if not self.es_verificado(empresa):
            self.datos.pop(norm_empresa(empresa), None)

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.datos, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")


def limpiar_dominio(valor: str) -> str:
    """'https://www.Empresa.com/es/' -> 'empresa.com'."""
    d = re.sub(r"^[a-z]+://", "", (valor or "").strip().lower())
    d = d.split("/")[0].split("?")[0]
    return d[4:] if d.startswith("www.") else d
