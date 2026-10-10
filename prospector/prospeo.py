"""Cliente mínimo de Prospeo (Enrich Person), usado como respaldo de Hunter.

POST https://api.prospeo.io/enrich-person  · cabecera X-KEY
Acepta nombre + apellido + empresa (mejor con company_website) o linkedin_url.
1 crédito por email encontrado; no cobra si no hay resultado ni al repetir en 90 días.
"""
import time

import requests

from .hunter import ClaveInvalida, HunterError, SinCreditos

URL = "https://api.prospeo.io/enrich-person"


class Prospeo:
    def __init__(self, api_key: str, session: requests.Session | None = None,
                 pausa: float = 0.3, reintentos: int = 4):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.pausa = pausa
        self.reintentos = reintentos
        self.llamadas = 0

    def buscar_email(self, *, first_name: str = "", last_name: str = "",
                     empresa: str | None = None, dominio: str | None = None,
                     linkedin_url: str | None = None) -> dict:
        """Devuelve {"email", "estado", "dominio"} o {} si no hay coincidencia."""
        datos: dict = {}
        if linkedin_url:
            datos["linkedin_url"] = linkedin_url
        if first_name and last_name:
            datos["first_name"], datos["last_name"] = first_name, last_name
        if dominio:
            datos["company_website"] = dominio
        elif empresa:
            datos["company_name"] = empresa
        espera = 2.0
        for _ in range(self.reintentos):
            time.sleep(self.pausa)
            try:
                r = self.session.post(URL, json={"data": datos},
                                      headers={"X-KEY": self.api_key}, timeout=45)
            except requests.RequestException:
                time.sleep(espera)
                espera *= 2
                continue
            self.llamadas += 1
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(espera)
                espera *= 2
                continue
            cuerpo = r.json() if r.content else {}
            if not cuerpo.get("error"):
                persona = cuerpo.get("person") or {}
                info = persona.get("email") or {}
                email = info.get("email") if info.get("revealed", True) else ""
                if not email or "*" in email:
                    return {}
                return {
                    "email": email,
                    "estado": "valid" if info.get("status") == "VERIFIED" else (info.get("status") or "").lower(),
                    "dominio": ((cuerpo.get("company") or {}).get("domain") or ""),
                }
            codigo = cuerpo.get("error_code", "")
            if codigo == "NO_MATCH":
                return {}
            if codigo == "INSUFFICIENT_CREDITS":
                raise SinCreditos(r.status_code, codigo, "Prospeo sin créditos")
            if codigo == "INVALID_API_KEY":
                raise ClaveInvalida(r.status_code, codigo, "clave de Prospeo no válida")
            raise HunterError(r.status_code, codigo or "prospeo_error", r.text[:200])
        raise HunterError(429, "rate_limit", "Prospeo: demasiados reintentos")
