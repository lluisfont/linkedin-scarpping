# Método de navegación por LinkedIn y Sales Navigator con el navegador del usuario

Documento técnico del procedimiento usado para buscar y validar perfiles de LinkedIn desde Claude, usando el Chrome del usuario con su sesión iniciada (LinkedIn Premium + Sales Navigator).

---

## 1. Requisitos

| Elemento | Detalle |
|---|---|
| Navegador | Chrome del usuario con la extensión **Claude in Chrome** conectada |
| Sesión | El usuario tiene LinkedIn abierto y con la sesión iniciada. Claude **no** inicia sesión ni introduce contraseñas |
| Cuenta | Premium y Sales Navigator (Sales Navigator solo es necesario para el método B) |
| Herramientas de Claude | `tabs_context_mcp`, `navigate`, `javascript_tool`, `computer` (wait / hover / screenshot), `browser_batch`, `tabs_close_mcp` |
| Almacenamiento | Resultados en CSV en una carpeta local del usuario (`;` como separador, UTF-8 con BOM para Excel) |

---

## 2. Reglas de uso

- Claude trabaja en **su propio grupo de pestañas** (`tabs_context_mcp` con `createIfEmpty: true`). No toca las pestañas del usuario.
- Comparte las cookies del perfil de Chrome, así que la sesión de LinkedIn ya está activa en la pestaña nueva.
- **No se simula comportamiento humano para engañar a la detección de bots** ni se evitan CAPTCHAs. Se trabaja a ritmo moderado (pausas de 2–6 s entre páginas) y **se para en cuanto aparezca un aviso, un CAPTCHA o un límite**.
- Las normas de LinkedIn prohíben el acceso automatizado. **El riesgo de restricción de la cuenta existe** y lo asume el titular.
- **Visitar un perfil deja rastro:** la persona verá "X ha visto tu perfil" salvo que el usuario active el modo privado (Configuración → Visibilidad → Opciones de visualización de perfil).
- Al terminar, Claude cierra su pestaña (`tabs_close_mcp`).

---

## 3. Método A — Búsqueda de personas en LinkedIn (sin Sales Navigator)

**Uso:** encontrar la URL `/in/` de un contacto a partir de nombre + apellido (+ empresa si el nombre es común).

### URL
```
https://www.linkedin.com/search/results/people/?keywords=Nombre%20Apellido%20Empresa
```

### Extractor (JavaScript ejecutado en la página)
```javascript
await new Promise(r=>setTimeout(r,3000));
{
  const seen=new Set(); const out=[];
  for (const a of document.querySelectorAll('main a[href*="/in/"]')) {
    const h=a.href.split('?')[0]; if(seen.has(h)) continue;
    let c=a; for(let i=0;i<8&&c&&c.innerText.length<60;i++) c=c.parentElement;
    const t=c?c.innerText.replace(/\s+/g,' '):'';
    if(!/•/.test(t)) continue;                       // solo tarjetas de resultado (llevan "• 2nd")
    if(out.some(o=>o.endsWith(t.slice(0,120)))) continue; // evita duplicados de "mutual connections"
    seen.add(h); out.push(h.replace('https://www.linkedin.com','')+' | '+t.slice(0,120));
  }
  out.slice(0,4).join('\n') || 'SIN RESULTADOS: '+document.title;
}
```
Devuelve: `/in/url | Nombre • grado Titular Ubicación`.

### Consejos de búsqueda
- Nombre poco común → solo nombre + apellido.
- Nombre común (Ana Martínez, Laura Gómez) → añadir empresa de origen. Si sale con la empresa como palabra clave, es que la empresa aparece en su historial: señal fuerte.
- Si no sale nada con empresa, repetir sin empresa; también probar variantes (Paco → Francisco, Nacho → Ignacio, sin acentos).

---

## 4. Método B — Búsqueda en Sales Navigator

**Ventajas:** muestra cargo y empresa actuales, ubicación y antigüedad en el puesto ("6 years in role"), útil para confirmar identidad.

### URL
```
https://www.linkedin.com/sales/search/people?keywords=Nombre%20Apellido
```
Sales Navigator redirige a `?query=...&sessionId=...`.

### Problema detectado y solución
Los resultados de Sales Navigator **no se pintan en el DOM hasta que la pestaña recibe una interacción**. Si se lee justo tras navegar, el extractor devuelve vacío aunque haya resultados.

Solución, por cada búsqueda:
1. `navigate` a la URL
2. `computer wait` 5 s
3. `computer hover` en cualquier punto (p. ej. `[700,190]`). Esto fuerza el renderizado. Un `screenshot` a escala 0.1 también sirve, pero a veces falla con "Script injection timed out"
4. Ejecutar el extractor con un pequeño bucle de espera

### Extractor
```javascript
for (let k=0;k<8&&!document.querySelector('a[href*="/sales/lead/"]');k++)
  await new Promise(r=>setTimeout(r,500));
{
  const seen=new Set(); const out=[];
  for (const a of document.querySelectorAll('a[href*="/sales/lead/"]')) {
    const h=a.href.split('?')[0]; if(seen.has(h)) continue; seen.add(h);
    let c=a; for(let i=0;i<10&&c&&!c.matches('li');i++) c=c.parentElement;
    out.push('/in/'+h.split('/sales/lead/')[1].split(',')[0]+' | '+
      (c?c.innerText.replace(/\s+/g,' ').replace(/^Add .*? to selection /,'')
         .replace(/\d+ (years?|months?) in (role|company)/g,'').slice(0,140):''));
  }
  out.slice(0,3).join('\n') || 'SIN RESULTADOS';
}
```

### Del lead de Sales Navigator a la URL pública
El enlace del lead es `/sales/lead/ACwAA...,NAME_SEARCH,xxxx`. El identificador `ACwAA...` funciona como URL pública:
```
https://www.linkedin.com/in/ACwAA...
```
LinkedIn redirige al perfil con su URL personalizada.

**Nota:** si el extractor devuelve solo el identificador, la herramienta lo bloquea ("Base64 encoded data"). Siempre hay que devolverlo junto con texto.

---

## 5. Método C — Validar un perfil por su URL

**Uso:** comprobar empresa y cargo actuales de contactos que ya tienen URL.

### Extractor
```javascript
await new Promise(r=>setTimeout(r,2500));
location.pathname.startsWith('/404') ? '404' :
  location.pathname+' | '+(document.querySelector('main section')||{innerText:'?'})
    .innerText.replace(/\s+/g,' ').split('Contact info')[0].slice(0,220);
```
La tarjeta superior devuelve: `Nombre · grado  Titular  Empresa actual · Universidad  Ubicación`.

### Comportamientos observados
| Caso | Qué pasa | Acción |
|---|---|---|
| URL antigua con redirección | `location.pathname` cambia a la URL nueva | Guardar la URL nueva |
| URL caducada | Redirige a `/404/` (≈ 25–40 % en URLs de 2017) | Buscar por nombre (método A o B) |
| URL reasignada | La URL sin hash puede ser ahora de otra persona con el mismo nombre | Marcar como dudoso si el perfil no encaja (país, sector) |
| Perfil "In remembrance" | Persona fallecida | Excluir |
| "Retired", "Jubilado", "Former…" | Ya no está en activo | Excluir |
| Empresa que ya no existe (absorbida) | Perfil desactualizado | Marcar con ❓ |

---

## 6. Ejecución por lotes (`browser_batch`)

| Método | Contactos por lote | Motivo |
|---|---|---|
| A — búsqueda LinkedIn | 6 | ≈ 60 s por lote |
| C — validar perfil | 6 | Con 10 se superó el tiempo máximo de la herramienta |
| B — Sales Navigator | 3–4 | Cada búsqueda necesita más espera (5 s + hover + bucle) |

Estructura de cada elemento del lote:
```
navigate → (wait 2–6 s variable) → javascript_tool (extractor)
```
Si un lote falla a medias, se relanza solo desde el elemento que falló.

Tiempos reales medidos: ≈ 10–15 s por contacto en búsqueda, ≈ 8–12 s por perfil validado.

---

## 7. Clasificación de coincidencias

| Estado | Criterio |
|---|---|
| **Confirmado** | Misma empresa que en origen; nombre completo poco común que coincide con el email; o la URL contiene la empresa |
| **Probable** | Nombre exacto + perfil de RRHH + misma zona; o aparece al buscar con la empresa de origen |
| **Dudoso** | Nombre muy común; apellido oculto ("Ana M."); varios candidatos; o perfil que no encaja (otro país, otro sector) |
| **No encontrado** | Ningún resultado razonable tras 1–2 búsquedas |

"Cambió de empresa" se marca cuando la empresa actual no coincide con la de origen.

---

## 8. Registro de resultados

- Se escribe en CSV **después de cada lote** (no al final), para no perder trabajo si se corta la sesión.
- Columnas usadas: `Idx; URL; Estado; Empresa actual; Titular actual; Ubicación actual; Nota`.
- Un script en Python cruza después estos resultados con la base principal (por email, o por URL si no hay email) y recalcula los filtros.
- Cada cierto número de lotes se manda al usuario un mensaje corto de avance (n.º revisados, confirmados, probables, dudosos, no encontrados; si ha habido avisos).

---

## 9. Problemas encontrados y soluciones

| Problema | Solución |
|---|---|
| La pestaña de Claude no ve las pestañas abiertas por el usuario | Crear grupo propio con `createIfEmpty: true`; la sesión se comparte igual |
| `get_page_text` falla en búsqueda de LinkedIn | Usar el extractor JavaScript |
| Lote demasiado largo → "did not respond in time" | Reducir a 3–6 contactos por lote |
| Sales Navigator devuelve vacío | Esperar 5 s + `hover` antes del extractor |
| `screenshot` falla con "Script injection timed out" | Usar `hover` en su lugar |
| Salida bloqueada por "Base64 encoded data" | Devolver el ID junto con texto |
| Nombres con tildes en la URL | Codificar (`%C3%A1`…); `navigate` lo acepta |
| URLs antiguas `/pub/nombre/xx/yyy/zzz` | Siguen redirigiendo en algunos casos; navegar a la URL completa |
