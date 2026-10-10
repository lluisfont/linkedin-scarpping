// Lee un trozo de los leads guardados por extractor_salesnav_lista.js (window.__sn).
// Cambiar DESDE en cada llamada: 0, 4, 8, ... (4 leads por llamada para no superar ~1000 caracteres).
// Formato de línea (separado por |): id|nombre|cargo|empresa|empresa_id|ubicacion|tiempo_puesto
{
  const DESDE = 0;
  (window.__sn || []).slice(DESDE, DESDE + 4)
    .map(l => [l.id, l.nombre, l.cargo, l.empresa, l.empresa_id, l.ubicacion,
               l.tiempo_puesto.replace(/ in role$/, '')].map(v => String(v || '').replace(/\|/g, '/')).join('|'))
    .join('\n') || 'FIN';
}
