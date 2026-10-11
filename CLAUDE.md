# linkedin-scrapper

Sistema de prospección: Claude navega LinkedIn / Sales Navigator con Claude in Chrome, el CLI
`python -m prospector` busca emails (Hunter.io, Prospeo de respaldo) y genera el Excel.

- Procedimiento completo: skill `prospeccion-linkedin` (`.claude/skills/prospeccion-linkedin/SKILL.md`).
- Método de navegación y problemas conocidos: `docs/metodo_navegacion_linkedin.md`.
- Extractores JS para `javascript_tool`: `navegador/`.
- Datos: `data/contactos.db` = BASE DE CONTACTOS ÚNICA (SQLite: contactos, busquedas, apariciones) para todas
  las búsquedas y segmentos (RRHH, CEO...). `data/raw/` (lotes de cada página), `data/dominios.json`
  (dominios; los verificados en LinkedIn van marcados). Excel en `salida/`. `PROSPECTOR_DATA` en `.env`
  cambia la carpeta de datos.
- Regla: un email solo vale si es del dominio de la empresa actual en LinkedIn (`prospector/emails.py`).
- Claves en `.env` (`HUNTER_API_KEY`, `PROSPEO_API_KEY` opcional). Nunca pedirlas por chat ni escribirlas en código.
- Tests: `python -m unittest discover -s tests`.
