"""CLI: python -m prospector <comando>

  importar  data/raw/lote.txt [...] --busqueda ETIQUETA [--segmento SEG]
                                                           añade contactos a la base única (sin duplicar)
  emails    [--busqueda E] [--limite N] [--verificar]      busca emails (Hunter, luego Prospeo)
  verificar [--busqueda E] [--limite N]                    verifica emails ya encontrados
  sin-dominio [--busqueda E]                               empresas sin dominio conocido
  dominio   "Empresa" empresa.com                          fija el dominio de una empresa
  excel     [--segmento S | --busqueda E] [--zona z1,z2] [--salida x]   Excel de la base o de un trozo
  estado                                                   resumen de la base y créditos
  revisar                                                  marca emails cuyo dominio no es de la empresa actual
  auditar   lista.csv|xlsx [--salida ruta.xlsx]            audita una lista externa (copia, no toca el original)
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from . import almacen, config
from .emails import (FUERA_DE_PERFIL, aplicar_regla, enriquecer, pendientes, sin_dominio_verificado,
                     verificar_lead)
from .excel import exportar
from .filtros import PERFILES, en_zona, encaja
from .hunter import ClaveInvalida, Hunter, HunterError, SinCreditos
from .prospeo import Prospeo


def _zona(etiqueta: str) -> str:
    """'rrhh-tgn-E' -> 'tgn' (convención <segmento>-<zona>-<...>)."""
    return (etiqueta.strip().split("-") + ["", ""])[1]


def _filtrar(leads, busqueda=None, segmento=None, zonas=None):
    return [l for l in leads
            if (not busqueda or busqueda in l.get("busqueda", "").split(" | "))
            and (not segmento or segmento.upper() in l.get("segmentos", "").split(" | "))
            and (not zonas or any(_zona(b) in zonas for b in l.get("busqueda", "").split(" | ")))]


def cmd_importar(a):
    leads = almacen.cargar_leads()
    antes = {l["id"]: dict(l) for l in leads}
    total_nuevos = 0
    for ruta in a.archivos:
        meta, brutos = almacen.leer_lote(Path(ruta))
        etiqueta = a.busqueda or meta.get("busqueda") or Path(ruta).stem
        segmento = (a.segmento or almacen.segmento_de(etiqueta)).upper()
        lote = [n for b in brutos if (n := almacen.normalizar_lead(b, etiqueta, segmento))]
        descartados = len(brutos) - len(lote)
        perfil = None if a.sin_filtro else (a.perfil or (segmento.lower() if segmento.lower() in PERFILES else None))
        if perfil:  # el filtro de cargo de Sales Navigator es laxo: solo entra quien encaja de verdad
            zona = (etiqueta.split("-") + [""])[1]
            fuera = [(l, motivo) for l in lote for ok, motivo in [encaja(l["cargo"], perfil)] if not ok]
            fuera += [(l, f"ubicación fuera de la zona '{zona}': {l['ubicacion']}") for l in lote
                      if not en_zona(l["ubicacion"], zona) and l not in [x for x, _ in fuera]]
            if fuera:
                ruta_ex = Path(ruta).with_name(Path(ruta).stem + "_excluidos.txt")
                ruta_ex.write_text("\n".join(f"{l['nombre']} | {l['cargo']} | {l['empresa']} | {m}"
                                             for l, m in fuera), encoding="utf-8")
                print(f"   filtro {perfil.upper()}: {len(fuera)} excluidos por cargo o ubicación → {ruta_ex}")
                ids_fuera = {l["id"] for l, _ in fuera}
                lote = [l for l in lote if l["id"] not in ids_fuera]
        nuevos, act, ids = almacen.fusionar(leads, lote)
        almacen.registrar_busqueda(meta, etiqueta, len(lote), nuevos, segmento)
        almacen.registrar_apariciones(ids, etiqueta, segmento)
        print(f"{ruta} [{segmento}]: {len(lote)} contactos → {nuevos} nuevos, {act} ya estaban en la base"
              + (f", {descartados} descartados sin nombre" if descartados else ""))
        for i in ids:
            if i in antes:  # ya conocido: de qué búsquedas venía y si ya tiene email (no se vuelve a pagar)
                p = antes[i]
                print(f"   ya en base: {p['nombre']} · {p['empresa']} · antes en {p['segmentos'] or p['busqueda']}"
                      + (f" · email {p['email']}" if p.get("email") else ""))
        total_nuevos += nuevos
    almacen.guardar_leads(leads)
    print(f"Base de contactos: {len(leads)} personas · +{total_nuevos} nuevas")


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
    objetivo = _filtrar(leads, None, a.segmento)  # mismos dicts: guardar(leads) persiste los cambios
    cola = pendientes(objetivo, a.busqueda, a.reintentar)
    if a.limite:
        cola = cola[: a.limite]
    if a.simular:
        for l in cola:
            print(f"- {l['nombre']} · {l.get('empresa', '')} · dominio={l.get('dominio') or '?'}")
        print(f"{len(cola)} leads se consultarían.")
        return
    dominios = almacen.Dominios()
    sin_verificar = {l["empresa"] for l in sin_dominio_verificado(cola, dominios)}
    if sin_verificar:
        print(f"Aviso: {len(sin_verificar)} empresas sin dominio verificado en LinkedIn "
              f"(ejecutar antes 'sin-dominio' y fijarlos con 'dominio'). Hunter las buscará por nombre "
              f"y se descartará cualquier email que no sea de la empresa actual, pero gastará crédito.")
    hunter, prospeo = _proveedores(a.sin_prospeo)
    print(_creditos_hunter(hunter))
    print("Prospeo como respaldo: " + ("sí" if prospeo else "no (sin PROSPEO_API_KEY)"))
    try:
        stats = enriquecer(objetivo, hunter=hunter, prospeo=prospeo, dominios=dominios,
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
    """Empresas de leads sin email válido cuyo dominio aún no está verificado en LinkedIn."""
    dominios = almacen.Dominios()
    vistas = {}
    for l in sin_dominio_verificado(_filtrar(almacen.cargar_leads(), None, a.segmento), dominios, a.busqueda):
        vistas.setdefault(almacen.norm_empresa(l["empresa"]),
                          {"empresa": l["empresa"], "empresa_id": l.get("empresa_id", "")})
    print(json.dumps(list(vistas.values()), ensure_ascii=False, indent=1))


def cmd_dominio(a):
    """Fija un dominio VERIFICADO (de la página de la empresa en LinkedIn o comprobado por el usuario)."""
    dominios = almacen.Dominios()
    dominios.set(a.empresa, a.dominio, verificado=True)
    dominios.guardar()
    dom = almacen.limpiar_dominio(a.dominio)
    leads = almacen.cargar_leads()
    n = 0
    for l in leads:
        if almacen.norm_empresa(l.get("empresa", "")) == almacen.norm_empresa(a.empresa):
            l["dominio"] = dom
            if l.get("resultado_email") in ("no_encontrado", "sin_empresa", "descartado"):
                l["resultado_email"] = ""  # se volverá a intentar con el dominio verificado
            n += 1
    almacen.guardar_leads(leads)
    print(f"{a.empresa} -> {dom} (verificado; {n} leads actualizados)")


def cmd_excel(a):
    """Sin filtros: la base completa (salida/base_contactos.xlsx). Con --segmento o --busqueda: ese trozo."""
    zonas = [z.strip() for z in a.zona.split(",") if z.strip()] if a.zona else None
    leads = _filtrar(almacen.cargar_leads(), a.busqueda, a.segmento, zonas)
    if not a.todos:
        leads = [l for l in leads if l.get("validacion") != FUERA_DE_PERFIL]
    if a.salida:
        ruta = Path(a.salida)
    elif a.busqueda:
        ruta = config.SALIDA / f"prospectos_{a.busqueda}.xlsx"
    elif zonas:
        ruta = config.SALIDA / f"base_contactos_{(a.segmento or 'todos').upper()}_{'-'.join(zonas)}.xlsx"
    elif a.segmento:
        ruta = config.SALIDA / f"base_contactos_{a.segmento.upper()}.xlsx"
    else:
        ruta = config.SALIDA / "base_contactos.xlsx"
    busquedas = [b for b in almacen.cargar_busquedas()
                 if (not a.busqueda or b.get("busqueda") == a.busqueda)
                 and (not a.segmento or b.get("segmento") == a.segmento.upper())
                 and (not zonas or _zona(b.get("busqueda", "")) in zonas)]
    final = exportar(leads, busquedas, ruta)
    con_email = sum(1 for l in leads if l.get("email"))
    print(f"Excel: {final} · {len(leads)} contactos · {con_email} con email")


def cmd_auditar(a):
    from .auditoria import auditar
    ruta = Path(a.archivo)
    salida = Path(a.salida) if a.salida else config.SALIDA / f"auditoria_{ruta.stem}.xlsx"
    final, stats = auditar(ruta, salida)
    print(f"Auditoría: {final}")
    print(" · ".join(f"{v}: {stats[v]}" for v in ("APTO", "PENDIENTE", "NO APTO")))


def cmd_revisar(a):
    """Vuelve a aplicar la regla 'email = empresa actual de LinkedIn' a todos los emails de la base."""
    dominios = almacen.Dominios()
    leads = almacen.cargar_leads()
    stats = Counter()
    for l in leads:
        if not l.get("email"):
            continue
        resultado = aplicar_regla(l, dominios.verificados(l.get("empresa", "")))
        stats[resultado] += 1
        if resultado == "descartado":
            print(f"DESCARTADO {l['email_descartado']:38} {l['nota'].split('Descartado: ')[-1]}")
        elif l.get("validacion") == "Revisar":
            print(f"REVISAR    {l['email']:38} {l['nota']}")
    almacen.guardar_leads(leads)
    print(f"{stats['encontrado']} emails aceptados · {stats['descartado']} descartados")


def cmd_filtrar(a):
    """Marca 'Fuera de perfil' los contactos de la base cuyo cargo no encaja con el perfil del segmento."""
    leads = almacen.cargar_leads()
    n = 0
    for l in _filtrar(leads, None, a.segmento):
        perfiles = [s.lower() for s in l.get("segmentos", "").split(" | ") if s.lower() in PERFILES]
        if not perfiles:
            continue
        motivos = [m for p in perfiles for ok, m in [encaja(l["cargo"], p)] if not ok]
        if len(motivos) == len(perfiles):  # no encaja en ninguno de sus segmentos
            if l.get("validacion") != FUERA_DE_PERFIL:
                l["validacion"] = FUERA_DE_PERFIL
                l["nota"] = " | ".join([x for x in [l.get("nota", "")] if x] + [f"Fuera de perfil: {motivos[0]}"])
                n += 1
                print(f"{l['nombre']} · {l['cargo']} → {motivos[0]}")
        elif l.get("validacion") == FUERA_DE_PERFIL:
            l["validacion"] = ""
    almacen.guardar_leads(leads)
    print(f"{n} contactos marcados Fuera de perfil")


def cmd_estado(a):
    leads = almacen.cargar_leads()
    print(f"Base de contactos ({config.DB}): {len(leads)} personas · con email: {sum(1 for l in leads if l.get('email'))}")
    por_s = Counter(s for l in leads for s in (l.get("segmentos") or "-").split(" | "))
    for s, n in por_s.most_common():
        con = sum(1 for l in leads if s in (l.get("segmentos") or "-").split(" | ") and l.get("email"))
        print(f"  segmento {s}: {n} contactos · {con} con email")
    por_b = Counter(b for l in leads for b in (l.get("busqueda") or "-").split(" | "))
    for b, n in por_b.most_common():
        print(f"    búsqueda {b}: {n}")
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
    s.add_argument("--perfil", help="filtro de cargo (rrhh); por defecto el del segmento si existe")
    s.add_argument("--sin-filtro", action="store_true", help="importar sin filtrar por cargo")
    s.add_argument("--segmento", help="RRHH, CEO... (por defecto, el prefijo de la etiqueta)")
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
    s.add_argument("--segmento", help="RRHH, CEO... (por defecto, el prefijo de la etiqueta)")
    s.set_defaults(f=cmd_emails)

    s = sub.add_parser("verificar")
    s.add_argument("--busqueda")
    s.add_argument("--limite", type=int)
    s.set_defaults(f=cmd_verificar)

    s = sub.add_parser("sin-dominio")
    s.add_argument("--busqueda")
    s.add_argument("--segmento", help="RRHH, CEO... (por defecto, el prefijo de la etiqueta)")
    s.set_defaults(f=cmd_sin_dominio)

    s = sub.add_parser("dominio")
    s.add_argument("empresa")
    s.add_argument("dominio")
    s.set_defaults(f=cmd_dominio)

    s = sub.add_parser("excel")
    s.add_argument("--todos", action="store_true", help="incluir también los marcados Fuera de perfil")
    s.add_argument("--busqueda")
    s.add_argument("--salida")
    s.add_argument("--segmento", help="RRHH, CEO... (por defecto, el prefijo de la etiqueta)")
    s.add_argument("--zona", help="zonas de las etiquetas separadas por comas, p. ej. tgn,lld,gir")
    s.set_defaults(f=cmd_excel)

    s = sub.add_parser("estado")
    s.set_defaults(f=cmd_estado)

    s = sub.add_parser("auditar", help="revisa una lista externa (CSV/XLSX): ¿email de la empresa actual?")
    s.add_argument("archivo")
    s.add_argument("--salida")
    s.set_defaults(f=cmd_auditar)

    s = sub.add_parser("revisar", help="repasa los emails de la base y marca los dudosos")
    s.set_defaults(f=cmd_revisar)

    s = sub.add_parser("filtrar", help="marca Fuera de perfil los cargos que no encajan con su segmento")
    s.add_argument("--segmento")
    s.set_defaults(f=cmd_filtrar)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
