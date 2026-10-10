# linkedin-scrapper

Sistema de prospección: Claude navega LinkedIn / Sales Navigator con Claude in Chrome, el CLI
`python -m prospector` busca emails (Hunter.io, Prospeo de respaldo) y genera el Excel.

- Procedimiento completo: skill `prospeccion-linkedin` (`.claude/skills/prospeccion-linkedin/SKILL.md`).
- Método de navegación y problemas conocidos: `docs/metodo_navegacion_linkedin.md`.
- Extractores JS para `javascript_tool`: `navegador/`.
- Datos: `data/leads.csv` (base, `;`, UTF-8 BOM), `data/raw/` (JSON de cada página), `data/dominios.json`
  (caché empresa→dominio, editable), `data/busquedas.csv`. Excel en `salida/`.
- Claves en `.env` (`HUNTER_API_KEY`, `PROSPEO_API_KEY` opcional). Nunca pedirlas por chat ni escribirlas en código.
- Tests: `python -m unittest discover -s tests`.
