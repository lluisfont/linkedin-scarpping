"""Cliente mínimo de la API v2 de Hunter.io (Email Finder, Email Verifier, Account).

Códigos de Hunter que importan aquí:
  401 clave no válida · 403 límite de velocidad (reintentar) · 429 sin créditos
  451 la persona pidió que no se traten sus datos · 202 verificación en curso
Email Finder no cobra crédito si no encuentra email.
"""
import time

import requests

BASE = "https://api.hunter.io/v2"


class HunterError(Exception):
    def __init__(self, status: int, codigo: str, detalle: str = ""):
        super().__init__(f"Hunter {status} {codigo}: {detalle}".strip())
        self.status, self.codigo, self.detalle = status, codigo, detalle


class SinCreditos(HunterError):
    pass


class ClaveInvalida(HunterError):
    pass


class EmailReclamado(HunterError):
    """451: la persona ha pedido a Hunter que no trate sus datos. No volver a buscar."""


def _error(r: requests.Response) -> tuple[str, str]:
    try:
        err = (r.json().get("errors") or [{}])[0]
        return err.get("id") or err.get("code") or "", err.get("details", "")
    except ValueError:
        return "", r.text[:200]


class Hunter:
    def __init__(self, api_key: str, session: requests.Session | None = None,
                 pausa: float = 0.15, reintentos: int = 5):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.pausa = pausa
        self.reintentos = reintentos
        self.llamadas = 0

    def _get(self, ruta: str, params: dict) -> tuple[int, dict]:
        espera = 2.0
        for intento in range(self.reintentos):
            time.sleep(self.pausa)
            try:
                r = self.session.get(f"{BASE}/{ruta}",
                                     params={**params, "api_key": self.api_key}, timeout=45)
            except requests.RequestException as e:
                if intento == self.reintentos - 1:
                    raise HunterError(0, "red", str(e)) from e
                time.sleep(espera)
                espera *= 2
                continue
            self.llamadas += 1
            if r.status_code in (200, 202, 222):
                return r.status_code, r.json() if r.content else {}
            codigo, detalle = _error(r)
            if r.status_code == 401:
                raise ClaveInvalida(401, codigo or "unauthorized", detalle)
            if r.status_code == 429:
                raise SinCreditos(429, codigo or "usage_limit", detalle)
            if r.status_code == 451:
                raise EmailReclamado(451, codigo or "claimed_email", detalle)
            if r.status_code == 404:
                return 404, {}
            if r.status_code == 403 or r.status_code >= 500:
                time.sleep(espera)
                espera *= 2
                continue
            raise HunterError(r.status_code, codigo, detalle)
        raise HunterError(403, "rate_limit", "demasiados reintentos")

    def cuenta(self) -> dict:
        return self._get("account", {})[1].get("data", {})

    def buscar_email(self, first_name: str = "", last_name: str = "", *,
                     dominio: str | None = None, empresa: str | None = None,
                     linkedin_handle: str | None = None) -> dict:
        """Devuelve el bloque `data` de Email Finder ({} si no hay resultado).

        `data["email"]` puede venir vacío aunque `data["domain"]` sí venga relleno.
        """
        params: dict = {"max_duration": 15}
        if linkedin_handle:
            params["linkedin_handle"] = linkedin_handle
        else:
            params["first_name"], params["last_name"] = first_name, last_name
        if dominio:
            params["domain"] = dominio
        elif empresa:
            params["company"] = empresa
        status, cuerpo = self._get("email-finder", params)
        return (cuerpo.get("data") or {}) if status == 200 else {}

    def verificar(self, email: str, esperas: int = 3) -> dict:
        """Devuelve `data` de Email Verifier; status: valid/invalid/accept_all/webmail/disposable/unknown."""
        for _ in range(esperas):
            status, cuerpo = self._get("email-verifier", {"email": email})
            if status == 202:  # sigue verificando; consultar de nuevo cuenta como una sola petición
                time.sleep(5)
                continue
            data = cuerpo.get("data") or {}
            if status == 222:
                data.setdefault("status", "unknown")
            return data
        return {"status": "unknown"}
