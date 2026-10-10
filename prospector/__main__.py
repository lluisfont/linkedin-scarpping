"""CLI: python -m prospector <comando>

  importar  data/raw/lote.json [...] --busqueda ETIQUETA   añade leads del navegador a la base
  emails    [--busqueda E] [--limite N] [--verificar]      busca emails (Hunter, luego Prospeo)
  verificar [--busqueda E] [--limite N]                    verifica emails ya encontrados
  sin-dominio [--busqueda E]                               empresas sin dominio conocido
  dominio   "Empresa" empresa.com                          fija el dominio de una empresa
  excel     [--busqueda E] [--salida ruta.xlsx]            genera la hoja Excel
  estado                                                   resumen de la base y créditos
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from . import almacen, config
from .emails import enriquecer, pendientes, verificar_lead
from .excel import exportar
from .hunter import ClaveInvalida, Hunter, HunterError, SinCreditos
from .prospeo import Prospeo


def _filtrar(leads, busqueda):
    return [l for l in leads if not busqueda or busqueda in l.get("busqueda", "").split(" | ")]


def cmd_importar(a):
    leads = almacen.cargar_leads()
    total_nuevos = 0
    for ruta in a.archivos:
        meta, brutos = almacen.leer_lote(Path(ruta))
        etiqueta = a.busqueda or meta.get("busqueda") or Path(ruta).stem
        lote = [n for b in brutos if (n := almacen.normalizar_lead(b, etiqueta))]
        nuevos, act = almacen.fusionar(leads, lote)
        almacen.registrar_busqueda(meta, etiqueta, len(lote), nuevos)
        descartados = len(brutos) - len(lote)
        print(f"{ruta}: {len(lote)} leads ({nuevos} nuevos, {act} ya existían"
              + (f", {descartados} descartados sin nombre" if descartados else "") + ")")
        total_nuevos += nuevos
    almacen.guardar_leads(leads)
    print(f"Base: {len(leads)} leads · +{total_nuevos} nuevos")


def _proveedores(sin_prospeo: bool):
    hunter = Hunter(config.hunter_api_key())
    clave_p = os.environ.get("PROSPEO_API_KEY", "").strip()
    prospeo = Prospeo(clave_p) if clave_p and not sin_prospeo else None
    return hunter, prospeo


def _creditos_hunter(hunter: Hunter) -> str:
    try:
        req = hunter.cuenta().get("requests", {})
        s, v = req.get("searches", {}), req.get("verifications", {})
        return (f"Hunter · búsquedas {s.get('used', '?')}/{s.get('available', '?')}"
                f" · verificaciones {v.get('used', '?')}/{v.get('available', '?')}")
    except HunterError as e:
        return f"Hunter · no se pudo leer la cuenta ({e})"


def cmd_emails(a):
    leads = almacen.cargar_leads()
    cola = pendientes(leads, a.busqueda, a.reintentar)
    if a.limite:
        cola = cola[: a.limite]
    if a.simular:
        for l in cola:
            print(f"- {l['nombre']} · {l.get('empresa', '')} · dominio={l.get('dominio') or '?'}")
        print(f"{len(cola)} leads se consultarían.")
        return
    hunter, prospeo = _proveedores(a.sin_prospeo)
    print(_creditos_hunter(hunter))
    print("Prospeo como respaldo: " + ("sí" if prospeo else "no (sin PROSPEO_API_KEY)"))
    dominios = almacen.Dominios()
    try:
        stats = enriquecer(leads, hunter=hunter, prospeo=prospeo, dominios=dominios,
                           busqueda=a.busqueda, limite=a.limite, verificar=a.verificar,
                           reintentar=a.reintentar, max_encontrados=a.max_creditos,
                           guardar=lambda: almacen.guardar_leads(leads))
    except SinCreditos as e:
        almacen.guardar_leads(leads)
        sys.exit(f"Sin créditos: {e}. Lo procesado está guardado.")
    except ClaveInvalida as e:
        sys.exit(f"Clave no válida: {e}")
    print("Resultado: " + ", ".join(f"{k}={v}" for k, v in stats.most_common()))
    print(_creditos_hunter(hunter))


def cmd_verificar(a):
    leads = almacen.cargar_leads()
    cola = [l for l in _filtrar(leads, a.busqueda)
            if l.get("email") and not l.get("email_verificado") and l.get("email_estado") != "valid"]
    if a.limite:
        cola = cola[: a.limite]
    hunter = Hunter(config.hunter_api_key())
    stats = Counter()
    try:
        for i, l in enumerate(cola, 1):
            estado = verificar_lead(l, hunter)
            stats[estado] += 1
            print(f"[{i}/{len(cola)}] {l['email']} -> {estado}")
            if i % 5 == 0:
                almacen.guardar_leads(leads)
    except (SinCreditos, ClaveInvalida) as e:
        print(f"Parado: {e}")
    finally:
        almacen.guardar_leads(leads)
    print("Resultado: " + ", ".join(f"{k}={v}" for k, v in stats.most_common()))


def cmd_sin_dominio(a):
    dominios = almacen.Dominios()
    vistas = {}
    for l in _filtrar(almacen.cargar_leads(), a.busqueda):
        emp = l.get("empresa")
        if emp and not l.get("email") and not l.get("dominio") and not dominios.get(emp):
            vistas.setdefault(almacen.norm_empresa(emp), {"empresa": emp, "empresa_id": l.get("empresa_id", "")})
    print(json.dumps(list(vistas.values()), ensure_ascii=False, indent=1))


def cmd_dominio(a):
    dominios = almacen.Dominios()
    dominios.set(a.empresa, a.dominio)
    dominios.guardar()
    leads = almacen.cargar_leads()
    n = 0
    for l in leads:
        if almacen.norm_empresa(l.get("empresa", "")) == almacen.norm_empresa(a.empresa):
            l["dominio"] = almacen.limpiar_dominio(a.dominio)
            if l.get("resultado_email") in ("no_encontrado", "sin_empresa"):
                l["resultado_email"] = ""  # se volverá a intentar con el dominio nuevo
            n += 1
    almacen.guardar_leads(leads)
    print(f"{a.empresa} -> {almacen.limpiar_dominio(a.dominio)} ({n} leads actualizados)")


def cmd_excel(a):
    leads = _filtrar(almacen.cargar_leads(), a.busqueda)
    ruta = Path(a.salida) if a.salida else config.SALIDA / (
        f"prospectos_{a.busqueda}.xlsx" if a.busqueda else "prospectos.xlsx")
    busquedas = [b for b in almacen.cargar_busquedas() if not a.busqueda or b.get("busqueda") == a.busqueda]
    final = exportar(leads, busquedas, ruta)
    con_email = sum(1 for l in leads if l.get("email"))
    print(f"Excel: {final} · {len(leads)} leads · {con_email} con email")


def cmd_estado(a):
    leads = almacen.cargar_leads()
    print(f"Leads: {len(leads)} · con email: {sum(1 for l in leads if l.get('email'))}")
    por_b = Counter(b for l in leads for b in (l.get("busqueda") or "-").split(" | "))
    for b, n in por_b.most_common():
        print(f"  {b}: {n}")
    print("Resultado email: " + ", ".join(
        f"{k or 'pendiente'}={v}" for k, v in Counter(l.get("resultado_email", "") for l in leads).most_common()))
    config.cargar_env()
    if os.environ.get("HUNTER_API_KEY"):
        print(_creditos_hunter(Hunter(os.environ["HUNTER_API_KEY"])))
    else:
        print("Hunter: falta HUNTER_API_KEY en .env")
    print("Prospeo: " + ("configurado" if os.environ.get("PROSPEO_API_KEY") else "no configurado (opcional)"))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    config.asegurar_carpetas()
    config.cargar_env()
    p = argparse.ArgumentParser(prog="prospector", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("importar")
    s.add_argument("archivos", nargs="+")
    s.add_argument("--busqueda")
    s.set_defaults(f=cmd_importar)

    s = sub.add_parser("emails")
    s.add_argument("--busqueda")
    s.add_argument("--limite", type=int)
    s.add_argument("--verificar", action="store_true", help="verificar con Hunter los que no salgan 'valid'")
    s.add_argument("--reintentar", action="store_true", help="volver a buscar los 'no_encontrado'")
    s.add_argument("--max-creditos", type=int,
                   help="parar al encontrar N emails (Hunter cobra 1 búsqueda por email encontrado)")
    s.add_argument("--sin-prospeo", action="store_true")
    s.add_argument("--simular", action="store_true", help="listar sin llamar a la API")
    s.set_defaults(f=cmd_emails)

    s = sub.add_parser("verificar")
    s.add_argument("--busqueda")
    s.add_argument("--limite", type=int)
    s.set_defaults(f=cmd_verificar)

    s = sub.add_parser("sin-dominio")
    s.add_argument("--busqueda")
    s.set_defaults(f=cmd_sin_dominio)

    s = sub.add_parser("dominio")
    s.add_argument("empresa")
    s.add_argument("dominio")
    s.set_defaults(f=cmd_dominio)

    s = sub.add_parser("excel")
    s.add_argument("--busqueda")
    s.add_argument("--salida")
    s.set_defaults(f=cmd_excel)

    s = sub.add_parser("estado")
    s.set_defaults(f=cmd_estado)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
