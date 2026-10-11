---
name: prospeccion-linkedin
description: Busca profesionales en LinkedIn Sales Navigator (p. ej. "director de RRHH en Barcelona en empresas de más de 1000 empleados") o extrae perfiles concretos por URL, busca su email con Hunter.io (Prospeo de respaldo) y lo guarda todo en Excel. Usar cuando el usuario pida buscar contactos, leads o prospectos en LinkedIn, sacar emails de perfiles o generar la hoja de prospectos.
---

# Prospección LinkedIn → email → Excel

El navegador lo maneja Claude con **Claude in Chrome**, usando la sesión de LinkedIn del usuario.
Los emails y el Excel los hace el CLI de Python `python -m prospector` (desde la raíz del proyecto).
Método de navegación completo y sus problemas conocidos: `docs/metodo_navegacion_linkedin.md`.

## Reglas (no negociables)
- No iniciar sesión ni escribir contraseñas. Si LinkedIn no tiene la sesión abierta, pedir al usuario que la abra.
- Trabajar en un grupo de pestañas propio (`tabs_context_mcp` con `createIfEmpty: true`) y cerrarlo al terminar.
- Ritmo moderado: 3–6 s variables entre páginas. **Parar en cuanto aparezca un CAPTCHA, un aviso de
  actividad inusual o un límite** (el extractor lo indica en `aviso`) y avisar al usuario. No intentar resolverlo ni esquivarlo.
- Guardar después de cada página o lote, nunca solo al final.
- Visitar perfiles deja rastro ("X ha visto tu perfil"). Las páginas de resultados de Sales Navigator no.

## 0. Preparación
1. Cargar de una vez las herramientas de Chrome con ToolSearch:
   `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__find`
2. `python -m prospector estado` → comprueba la clave de Hunter y los créditos. Si falta `HUNTER_API_KEY`,
   pedir al usuario que la ponga en `.env` (no pedir que la pegue en el chat).
3. Elegir una **etiqueta** corta para la búsqueda (`rrhh-bcn-1000`). Se usa en archivos, en la base y en el Excel.

## Modo A — Búsqueda de un conjunto de profesionales (Sales Navigator)

1. **Traducir la petición a filtros** con `navegador/salesnav_filtros.md`: cargo (con variantes ES/EN y de género),
   tamaño de empresa, región, función, nivel. Si el usuario ha pegado una URL de Sales Navigator, usarla tal cual.
   Región sin id en `config/geo_ids.json` → resolverla con la interfaz como explica ese archivo y guardarla.
2. **Primera página**: navegar y comprobar con una captura que los chips de filtros son los esperados.
   Decir al usuario el total de resultados.
3. **Cuántas páginas**: por defecto hasta 4 páginas (≈100 leads) salvo que el usuario pida otra cifra.
   Si el total es enorme (>500), proponer afinar filtros antes de seguir.
4. **Por cada página**, un único `browser_batch`:
   1. navigate (`&page=N` a partir de la 2.ª) → `computer wait` 3–6 s variable
   2. **6 × `computer scroll` down 10 ticks en [860,500]**. La pestaña está oculta para Chrome: solo un scroll
      real hace que LinkedIn pinte las tarjetas. No usar scroll ni `await setTimeout` dentro del JS (se cuelga 45 s).
   3. `javascript_tool` con `navegador/extractor_salesnav_lista.js` → resumen `{leads, tarjetas, hay_siguiente, aviso}`
   4. 7 × `javascript_tool` con `navegador/extractor_salesnav_trozo.js` con `DESDE` = 0, 4, 8 … 24
      (la herramienta corta las salidas de más de ~1000 caracteres; 4 leads por llamada caben)
   - Si `aviso` no está vacío → PARAR y avisar.
   - Si `leads` < `tarjetas` − 3, hacer otra pasada de scroll (arriba y abajo) y repetir el paso 3.
   - Pegar las líneas de los trozos con Write en `data/raw/<etiqueta>_p<N>.txt` (cabecera opcional
     `# pagina: N` y `# total: X`). Descartar ahí los que claramente no encajan con lo pedido.
   - `python -m prospector importar data/raw/<etiqueta>_p<N>.txt --busqueda <etiqueta>`
   - Si `hay_siguiente` es false o ya hay suficientes leads → terminar.
5. Cerrar la pestaña (`tabs_close_mcp`).

Salidas bloqueadas por la herramienta: no devolver `location.href` (lleva `sessionId` → "Cookie/query string
data") ni IDs `ACwAA…` sueltos ("Base64 encoded data"); junto a nombres y cargos pasan bien.
Región resuelta y guardada: Barcelona = `107025191` (ver `config/geo_ids.json`).

## Modo B — Perfiles concretos (lista de URLs /in/)

Lotes de 6 perfiles por `browser_batch`: navigate → wait 2–6 s → `javascript_tool` con `navegador/extractor_perfil.js`.
Juntar los `leads` del lote en `data/raw/<etiqueta>_perfiles_<n>.json` con la forma
`{"origen":"perfil","leads":[...]}` e importar igual que arriba. Excluir los marcados como fallecido/jubilado
(no importarlos o dejar la nota). Para localizar la URL a partir de un nombre, usar los métodos A/B de
`docs/metodo_navegacion_linkedin.md`.

## Emails (Hunter → Prospeo)

**REGLA INNEGOCIABLE: la empresa actual de LinkedIn es la única válida.** Un email solo se entrega si su
dominio es el de esa empresa. Un buzón `valid` de una empresa anterior (p. ej. `jvillalonga@lacaixa.es` de
alguien que hoy está en Longtown HR) NO es un contacto válido. El código lo impone (`aplicar_regla`): un email
de otro dominio va a `email_descartado` con el motivo y `email` queda vacío. Nunca saltarse esto a mano.

1. **Primero, dominios verificados en LinkedIn (obligatorio, antes de gastar créditos):**
   - `python -m prospector sin-dominio --busqueda <etiqueta>` → empresas sin dominio verificado, con `empresa_id`.
   - Para cada una (lotes de 6, wait 3–4 s entre páginas): navigate
     `https://www.linkedin.com/company/<empresa_id>/about/` → `computer wait 4` → `javascript_tool` con
     `navegador/extractor_web_empresa.js` (devuelve solo el dominio) →
     `python -m prospector dominio "<Empresa tal cual en la base>" <dominio>` (lo marca como verificado).
   - Si LinkedIn da la web del grupo (Leroy Merlin → adeo.com), usar el dominio del país (`leroymerlin.es`) solo
     si coincide con el nombre de la empresa; si no, dejar el del LinkedIn.
   - Empresas sin `empresa_id`: buscar la página de la empresa en LinkedIn por nombre.
2. `python -m prospector emails --busqueda <etiqueta> --simular` → cuántos se consultarán. Cada email encontrado
   cuesta 1 crédito (también si luego se descarta). Respetar el tope del usuario con `--max-creditos N`.
3. `python -m prospector emails --busqueda <etiqueta> [--max-creditos N]` (añadir `--verificar` si se pide;
   gasta créditos de verificación). Hunter busca en el dominio verificado y prueba variantes del nombre (no cobra
   si no encuentra); si falla y hay `PROSPEO_API_KEY`, prueba Prospeo.
4. `python -m prospector revisar` → vuelve a aplicar la regla a toda la base (por ejemplo tras fijar dominios).
5. Informar de los descartados: un descartado indica que Hunter dio un email de otra empresa.

## Auditar listas externas
`python -m prospector auditar <archivo.csv|xlsx>` → `salida/auditoria_<archivo>.xlsx` con veredicto por fila
(APTO / PENDIENTE / NO APTO) según la misma regla. No modifica el original.

## Excel
`python -m prospector excel --busqueda <etiqueta>` → `salida/prospectos_<etiqueta>.xlsx`
(o sin `--busqueda` para la base completa → `salida/prospectos.xlsx`). Hojas: Prospectos, Resumen, Búsquedas.

## Informe final al usuario
Leads encontrados, con email (y cuántos `valid` / `accept_all`), no encontrados, avisos de LinkedIn si los hubo,
créditos de Hunter restantes y la ruta del Excel.
