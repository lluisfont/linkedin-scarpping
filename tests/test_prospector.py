import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

from prospector import almacen
from prospector.emails import buscar_email_lead, enriquecer
from prospector.excel import exportar
from prospector.hunter import Hunter, SinCreditos
from prospector.nombres import candidatos, es_incompleto, limpiar, partir
from prospector.prospeo import Prospeo


class Resp:
    def __init__(self, status, cuerpo):
        self.status_code, self._cuerpo = status, cuerpo
        self.content = b"x"
        self.text = json.dumps(cuerpo)

    def json(self):
        return self._cuerpo


class FakeSession:
    """Devuelve respuestas según una función (url, params|json) -> Resp y registra las llamadas."""

    def __init__(self, fn):
        self.fn, self.llamadas = fn, []

    def get(self, url, params=None, timeout=None):
        self.llamadas.append((url, dict(params or {})))
        return self.fn(url, params)

    def post(self, url, json=None, headers=None, timeout=None):
        self.llamadas.append((url, json))
        return self.fn(url, json)


class TestNombres(unittest.TestCase):
    def test_limpiar(self):
        self.assertEqual(limpiar("Ana Pérez García, MBA 🚀"), "Ana Pérez García")
        self.assertEqual(limpiar("Dr. Juan López (He/Him)"), "Juan López")
        self.assertEqual(limpiar("Marta Ruiz | HR Director"), "Marta Ruiz")

    def test_partir(self):
        self.assertEqual(partir("Ana García López"), ("Ana", ["García", "López"]))
        self.assertEqual(partir("María José de la Fuente Ruiz"), ("María José", ["de la Fuente", "Ruiz"]))
        self.assertEqual(partir("Juan Carlos"), ("Juan", ["Carlos"]))

    def test_candidatos(self):
        self.assertEqual(candidatos("Juan Carlos Pérez Gómez"), [
            ("Juan Carlos", "Pérez"), ("Juan", "Pérez"), ("Juan Carlos", "Pérez Gómez")])
        self.assertEqual(candidatos("Laura Martí"), [("Laura", "Martí")])
        self.assertEqual(candidatos("Ana M."), [])

    def test_incompleto(self):
        self.assertTrue(es_incompleto("Ana M."))
        self.assertFalse(es_incompleto("Ana Martí"))


class TestAlmacen(unittest.TestCase):
    def test_fusionar_y_dedupe(self):
        leads = []
        a = almacen.normalizar_lead({"id": "ACwAA1", "nombre": "Ana Martí", "cargo": "HR Director",
                                     "empresa": "Seat S.A."}, "rrhh")
        n, _ = almacen.fusionar(leads, [a])
        self.assertEqual(n, 1)
        self.assertEqual(leads[0]["url_linkedin"], "https://www.linkedin.com/in/ACwAA1")
        # mismo lead desde un perfil público: se fusiona por nombre+empresa y gana la URL personalizada
        b = almacen.normalizar_lead({"url": "https://www.linkedin.com/in/ana-marti/", "nombre": "Ana Martí",
                                     "empresa": "SEAT SA", "cargo": "Chief People Officer"}, "perfiles")
        n, act = almacen.fusionar(leads, [b])
        self.assertEqual((n, act, len(leads)), (0, 1, 1))
        self.assertEqual(leads[0]["url_linkedin"], "https://www.linkedin.com/in/ana-marti")
        self.assertEqual(leads[0]["cargo"], "Chief People Officer")
        self.assertEqual(leads[0]["busqueda"], "rrhh | perfiles")

    def test_descarta_miembro_anonimo(self):
        self.assertIsNone(almacen.normalizar_lead({"id": "x", "nombre": "LinkedIn Member"}, "b"))

    def test_csv_ida_y_vuelta(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "leads.csv"
            lead = almacen.normalizar_lead({"id": "1", "nombre": "Pep Solé", "cargo": "Dir; RRHH"}, "b")
            almacen.guardar_leads([lead], ruta)
            self.assertEqual(almacen.cargar_leads(ruta)[0]["cargo"], "Dir; RRHH")

    def test_lote_txt_de_trozos(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "p1.txt"
            ruta.write_text("# pagina: 1\n# total: 247\nACwAAA1|Ana Martí|HR Director|Seat|248021|Barcelona|9 months\nFIN\n",
                            encoding="utf-8")
            meta, leads = almacen.leer_lote(ruta)
            self.assertEqual((meta["pagina"], meta["total"]), ("1", "247"))
            self.assertEqual(leads[0]["empresa_id"], "248021")
            self.assertTrue(leads[0]["url_salesnav"].startswith("https://www.linkedin.com/sales/lead/ACwAAA1"))

    def test_dominio(self):
        self.assertEqual(almacen.limpiar_dominio("https://www.Seat.es/es/"), "seat.es")
        self.assertEqual(almacen.norm_empresa("Banco Sabadell, S.A."), "banco sabadell")


def _hunter(fn):
    s = FakeSession(fn)
    return Hunter("k", session=s, pausa=0), s


class TestEmails(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dominios = almacen.Dominios(Path(self.tmp.name) / "dominios.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _lead(self, nombre="Juan Carlos Pérez Gómez", empresa="Acme S.L."):
        return almacen.normalizar_lead({"id": "ACwAA9", "nombre": nombre, "empresa": empresa}, "b")

    def test_prueba_combinaciones_y_cachea_dominio(self):
        def fn(url, p):
            if p.get("first_name") == "Juan":
                return Resp(200, {"data": {"email": "juan.perez@acme.com", "score": 91, "domain": "acme.com",
                                           "verification": {"status": "valid"}}})
            return Resp(200, {"data": {"email": None, "domain": "acme.com"}})
        hunter, s = _hunter(fn)
        lead = self._lead()
        self.assertEqual(buscar_email_lead(lead, hunter, None, self.dominios), "encontrado")
        self.assertEqual((lead["email"], lead["email_score"], lead["email_estado"]),
                         ("juan.perez@acme.com", "91", "valid"))
        # 1.ª llamada por empresa; la 2.ª ya usa el dominio aprendido
        self.assertEqual(s.llamadas[0][1].get("company"), "Acme S.L.")
        self.assertEqual(s.llamadas[1][1].get("domain"), "acme.com")
        self.assertEqual(self.dominios.get("ACME SL"), "acme.com")

    def test_motivo_dudoso(self):
        from prospector.emails import motivo_dudoso
        base = {"email_estado": "accept_all", "email_score": "83"}
        self.assertIn("otro país", motivo_dudoso({**base, "email": "a@culligan.cz", "empresa": "Culligan International"}))
        self.assertIn("no se parece", motivo_dudoso({**base, "email": "s@meetproducerx.com",
                                                     "empresa": "Mandarin Oriental Hotel Group"}))
        self.assertEqual(motivo_dudoso({**base, "email": "t@thegbfoods.com", "empresa": "GBfoods"}), "")
        # un dominio raro pero verificado como 'valid' no se marca
        self.assertEqual(motivo_dudoso({"email": "b@fhp-ww.com", "email_estado": "valid", "email_score": "90",
                                        "empresa": "Freudenberg Home & Cleaning Solucions"}), "")

    def test_451_excluye(self):
        hunter, _ = _hunter(lambda u, p: Resp(451, {"errors": [{"id": "claimed_email"}]}))
        lead = self._lead("Laura Martí")
        self.assertEqual(buscar_email_lead(lead, hunter, None, self.dominios), "excluido_451")

    def test_prospeo_respaldo(self):
        hunter, _ = _hunter(lambda u, p: Resp(200, {"data": {"email": None}}))
        sp = FakeSession(lambda u, j: Resp(200, {"error": False, "person": {"email": {
            "email": "laura@acme.com", "status": "VERIFIED", "revealed": True}}, "company": {"domain": "acme.com"}}))
        prospeo = Prospeo("k", session=sp, pausa=0)
        lead = self._lead("Laura Martí")
        self.assertEqual(buscar_email_lead(lead, hunter, prospeo, self.dominios), "encontrado")
        self.assertEqual((lead["email"], lead["email_fuente"], lead["email_estado"]),
                         ("laura@acme.com", "prospeo", "valid"))
        self.assertEqual(sp.llamadas[0][1]["data"]["company_name"], "Acme S.L.")

    def test_sin_creditos_para_y_guarda(self):
        hunter, _ = _hunter(lambda u, p: Resp(429, {"errors": [{"id": "too_many_requests"}]}))
        leads = [self._lead("Laura Martí")]
        guardado = mock.Mock()
        with self.assertRaises(SinCreditos):
            enriquecer(leads, hunter=hunter, prospeo=None, dominios=self.dominios,
                       guardar=guardado, log=lambda *_: None)
        guardado.assert_called()

    def test_no_reintenta_no_encontrados(self):
        hunter, s = _hunter(lambda u, p: Resp(200, {"data": {"email": None}}))
        leads = [self._lead("Laura Martí")]
        enriquecer(leads, hunter=hunter, prospeo=None, dominios=self.dominios, log=lambda *_: None)
        self.assertEqual(leads[0]["resultado_email"], "no_encontrado")
        n = len(s.llamadas)
        enriquecer(leads, hunter=hunter, prospeo=None, dominios=self.dominios, log=lambda *_: None)
        self.assertEqual(len(s.llamadas), n)


class TestExcel(unittest.TestCase):
    def test_exportar(self):
        lead = almacen.normalizar_lead({"id": "ACwAA1", "nombre": "Ana Martí", "empresa": "Seat"}, "rrhh")
        lead.update(email="ana@seat.es", email_estado="valid", email_score="95")
        with tempfile.TemporaryDirectory() as d:
            ruta = exportar([lead], [{"busqueda": "rrhh", "url": "u"}], Path(d) / "p.xlsx")
            wb = load_workbook(ruta)
            self.assertEqual(wb.sheetnames, ["Prospectos", "Resumen", "Búsquedas"])
            ws = wb["Prospectos"]
            self.assertEqual(ws["E2"].value, "ana@seat.es")
            self.assertEqual(ws["G2"].value, 95)
            self.assertEqual(ws["J2"].hyperlink.target, "https://www.linkedin.com/in/ACwAA1")


if __name__ == "__main__":
    unittest.main()
