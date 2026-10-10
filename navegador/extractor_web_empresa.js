// Extrae la web (dominio) de una empresa desde https://www.linkedin.com/company/<id>/about/
// (empresa_id viene de Sales Navigator; LinkedIn redirige el id numérico a la URL de la empresa).
// Síncrono: antes, `computer wait` 3-4 s tras navegar. Devuelve JSON: {empresa, web}
// Se lee el texto ("Website\n\nhttps://...") porque el HTML de LinkedIn cambia (ya no hay <dt>/<h1>).
{
  const empresa = document.title.replace(/:.*$|\s*\|\s*LinkedIn.*$/g, '').trim();
  const lineas = document.body.innerText.split('\n').map(s => s.trim()).filter(Boolean);
  const i = lineas.findIndex(s => /^(website|sitio web|web)$/i.test(s));
  let web = i >= 0 ? lineas[i + 1] : '';
  if (!/^(https?:\/\/)?[\w-]+(\.[\w-]+)+/i.test(web || '')) {
    const a = [...document.querySelectorAll('main a[href^="http"]')]
      .find(x => !/linkedin\.com|lnkd\.in|bing\.com|microsoft\.com|google\./.test(x.href));
    web = a ? a.href : '';
  }
  JSON.stringify({empresa, web});
}
