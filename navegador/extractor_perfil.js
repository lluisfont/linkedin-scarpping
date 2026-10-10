// Extractor de un perfil público de LinkedIn (/in/...). Método C del documento.
// Devuelve JSON: {origen:'perfil', leads:[{url_linkedin, nombre, cargo, empresa, ubicacion, nota}]}
await new Promise(r => setTimeout(r, 2500));
{
  const limpio = e => e ? e.innerText.replace(/\s+/g, ' ').trim() : '';
  const top = document.querySelector('main section');
  const nombre = limpio(top && top.querySelector('h1'));
  const titular = limpio(top && top.querySelector('.text-body-medium'));
  const ubicacion = limpio(top && top.querySelector('.text-body-small.inline.t-black--light.break-words, span.text-body-small.inline'));
  // Empresa actual: botón de la tarjeta superior ("Current company"/"Empresa actual") o 1.ª experiencia.
  let empresa = '';
  const btn = top && top.querySelector('button[aria-label*="ompany"], button[aria-label*="mpresa"]');
  if (btn) empresa = (btn.getAttribute('aria-label').split(':')[1] || limpio(btn)).replace(/\.\s*Click.*$/i, '').trim();
  if (!empresa) {
    const exp = document.querySelector('#experience');
    const bloque = exp && exp.closest('section');
    const item = bloque && bloque.querySelector('li');
    if (item) {
      const spans = [...item.querySelectorAll('span[aria-hidden="true"]')].map(s => s.innerText.trim());
      empresa = (spans[1] || '').split('·')[0].trim();
    }
  }
  const texto = limpio(top).slice(0, 300);
  let nota = '';
  if (location.pathname.startsWith('/404')) nota = '404';
  else if (/In remembrance|En memoria/i.test(texto)) nota = 'Fallecido: excluir';
  else if (/\b(retired|jubilad[oa])\b/i.test(texto)) nota = 'Jubilado: excluir';
  JSON.stringify({
    origen: 'perfil',
    url: location.href,
    leads: nota === '404' ? [] : [{
      url_linkedin: 'https://www.linkedin.com' + location.pathname.replace(/\/$/, ''),
      nombre, cargo: titular, empresa, ubicacion, nota,
    }],
    texto_tarjeta: texto,
  });
}
