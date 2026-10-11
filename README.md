# Prospección LinkedIn → Email → Excel

```
Sales Navigator / perfiles ──(Claude in Chrome + extractores JS)──► data/raw/*.json
        │
        ▼  python -m prospector importar --busqueda <segmento>-<zona>
   data/contactos.db  BASE DE CONTACTOS ÚNICA (todas las búsquedas y segmentos: RRHH, CEO...)
                      una ficha por persona, con las búsquedas/segmentos en que ha aparecido
        │
        ▼  python -m prospector emails      Hunter.io (nombre + dominio/empresa)
        │                                   └─ si no encuentra: Prospeo (opcional)
        ▼  python -m prospector excel
   salida/base_contactos.xlsx  (o por segmento / por búsqueda)
```

## Puesta en marcha
1. `pip install -r requirements.txt`
2. Copia `.env.example` a `.env` y pon tu `HUNTER_API_KEY` (y `PROSPEO_API_KEY` si quieres respaldo).
3. Chrome con la extensión **Claude in Chrome** conectada y LinkedIn/Sales Navigator con la sesión iniciada.
4. Comprueba: `python -m prospector estado`

## Uso con Claude (lo normal)
Abre Claude Code en esta carpeta y pídelo en lenguaje natural, o con la skill:

> /prospeccion-linkedin director de recursos humanos en Barcelona, empresas de más de 1000 empleados, 100 leads

> /prospeccion-linkedin saca nombre, empresa y email de estas URLs: …

Claude construye la búsqueda en Sales Navigator, extrae página a página (guarda cada página al momento),
busca los emails y genera el Excel. Si prefieres control total de los filtros, monta la búsqueda en
Sales Navigator y pega la URL.

## Comandos del CLI
| Comando | Qué hace |
|---|---|
| `importar data/raw/x.txt --busqueda rrhh-bcn [--segmento RRHH]` | Añade contactos a la base única; los que ya estaban no se duplican (se les añade la búsqueda y el segmento) |
| `emails --busqueda ETQ [--limite N] [--verificar] [--reintentar] [--simular]` | Busca emails |
| `verificar --busqueda ETQ` | Verifica con Hunter los emails ya encontrados |
| `sin-dominio --busqueda ETQ` | Empresas sin dominio conocido (para buscar su web en LinkedIn) |
| `dominio "Empresa" empresa.com` | Fija el dominio de una empresa (mejora mucho los aciertos) |
| `excel [--segmento CEO] [--busqueda ETQ]` | Excel de la base completa, de un segmento o de una búsqueda |
| `revisar` | Vuelve a aplicar la regla "email = empresa actual de LinkedIn" a toda la base |
| `auditar lista.csv` | Audita una lista externa con la misma regla (no toca el original) |
| `estado` | Resumen de la base y créditos de Hunter |

## Cómo se buscan los emails
- Hunter Email Finder con varias combinaciones del nombre (nombres compuestos, dos apellidos, partículas
  "de la"): Hunter **no cobra** si no encuentra, así que probar combinaciones es gratis.
- Primero por **dominio** (caché en `data/dominios.json`, editable a mano). Si no se conoce, por nombre de
  empresa; el dominio que devuelve Hunter se guarda para los siguientes contactos de esa empresa.
- Si hay URL pública `/in/...`, también por `linkedin_handle`.
- Respaldo con Prospeo (nombre + empresa o URL de LinkedIn) si está configurado.
- Estados en el Excel: `valid` (verde), `accept_all`/`webmail` (amarillo: el servidor acepta todo, riesgo
  medio), `unknown` (gris), `invalid` (rojo). `--verificar` gasta créditos de verificación.
- `excluido_451`: la persona pidió a Hunter que no se traten sus datos. No se vuelve a buscar.

## Avisos
- **LinkedIn** prohíbe el acceso automatizado en sus condiciones: existe riesgo de restricción de la cuenta.
  El sistema trabaja a ritmo moderado y se para ante cualquier aviso o CAPTCHA (no los evita).
- Visitar perfiles deja rastro; las páginas de resultados de Sales Navigator no.
- **RGPD**: emails profesionales para prospección B2B suelen ampararse en el interés legítimo, pero hay que
  informar al contacto en el primer mensaje (art. 14: origen de los datos y cómo oponerse) y respetar las bajas.

## Base de contactos
- Una sola base para todo (`data/contactos.db`, SQLite). Cada persona es una ficha única por su ID de LinkedIn.
- Si alguien sale en una búsqueda de RRHH y luego en otra de CEOs, sigue siendo una ficha: se actualizan
  cargo y empresa, se añade el segmento y se conserva el email (no se vuelve a pagar en Hunter).
- Para guardar la base fuera del proyecto (p. ej. en OneDrive, con copia de seguridad), en `.env`:
  `PROSPECTOR_DATA=C:\Users\<usuario>\OneDrive\Prospeccion`
