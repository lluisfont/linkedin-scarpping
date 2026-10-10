// Extractor de una página de resultados de Sales Navigator (búsqueda de leads).
// La pestaña de Claude suele estar oculta (visibilityState 'hidden'): Chrome frena los timers y
// LinkedIn solo pinta las tarjetas que pasan por pantalla con un scroll REAL. Por eso, antes:
//   navigate -> wait 5 -> 6 x computer scroll down 10 ticks en [860,500]
// y este script es síncrono (sin await). Guarda los leads en window.__sn y devuelve un resumen;
// los datos se leen con extractor_salesnav_trozo.js.
{
  const T = (r, sel) => { const e = r && r.querySelector(sel); return e ? e.innerText.replace(/\s+/g, ' ').trim() : ''; };
  const seen = new Set(), leads = [];
  for (const a of document.querySelectorAll('a[href*="/sales/lead/"]')) {
    const m = a.href.match(/\/sales\/lead\/([^,?\/]+)/);
    if (!m || seen.has(m[1])) continue;
    const li = a.closest('li'); if (!li) continue;
    seen.add(m[1]);
    const txt = li.innerText.replace(/\s+/g, ' ');
    const comp = li.querySelector('a[href*="/sales/company/"]');
    leads.push({
      id: m[1],
      nombre: T(li, '[data-anonymize="person-name"]') || a.innerText.replace(/\s+/g, ' ').trim(),
      cargo: T(li, '[data-anonymize="title"]'),
      empresa: (comp ? comp.innerText.replace(/\s+/g, ' ').trim() : '') || T(li, '[data-anonymize="company-name"]'),
      empresa_id: comp ? ((comp.href.match(/\/sales\/company\/(\d+)/) || [])[1] || '') : '',
      ubicacion: T(li, '[data-anonymize="location"]'),
      tiempo_puesto: (txt.match(/\d+ (?:years?|months?|años?|meses?)(?: \d+ (?:months?|meses?))? (?:in role|en el (?:puesto|cargo))/) || [''])[0],
      url_salesnav: a.href.split('?')[0],
    });
  }
  const total = (document.body.innerText.match(/([\d.,]+\s*(?:K|mil)?\+?)\s+(?:results|resultados)/i) || [, ''])[1];
  const sig = document.querySelector('button.artdeco-pagination__button--next');
  // La herramienta corta las salidas largas (~1000 caracteres): se guardan los leads en la página
  // y se leen en trozos con extractor_salesnav_trozo.js. Aquí solo se devuelve el resumen.
  // Sin location.href: lleva sessionId y la herramienta bloquea la salida ("Cookie/query string data").
  window.__sn = leads;
  JSON.stringify({
    pagina: Number(new URLSearchParams(location.search).get('page') || 1),
    total,
    leads: leads.length,
    tarjetas: document.querySelectorAll('li.artdeco-list__item').length,
    hay_siguiente: !!(sig && !sig.disabled),
    aviso: /captcha|unusual activity|actividad inusual|restricted|restringid/i.test(document.body.innerText.slice(0, 3000)) ? 'POSIBLE AVISO/CAPTCHA: PARAR' : '',
  });
}
