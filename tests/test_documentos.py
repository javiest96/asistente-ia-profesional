"""Solo archivos ficticios en temporales; PDFs reales pequeños, sin modelos."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import numpy as np

import configuracion
import documentos as d
from buscador_semantico import MotorRAG, ErrorIndice


def pdf_ficticio(texto=b"Texto ficticio", paginas=1, cifrado=False):
    writer = PdfWriter()
    for _ in range(paginas):
        pagina = writer.add_blank_page(width=200, height=200)
        if texto:
            fuente = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                       NameObject("/Subtype"): NameObject("/Type1"),
                                       NameObject("/BaseFont"): NameObject("/Helvetica")})
            pagina[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): fuente})})
            contenido = DecodedStreamObject()
            contenido.set_data(b"BT /F1 10 Tf 10 10 Td (" + texto + b") Tj ET")
            pagina[NameObject("/Contents")] = writer._add_object(contenido)
    if cifrado:
        writer.encrypt("clave_ficticia")
    salida = BytesIO()
    writer.write(salida)
    return salida.getvalue()


class TestDocumentos(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(self.enterContext(TemporaryDirectory(prefix="rag_documentos_")))
        self.carpeta = self.raiz / "biblioteca"

    def guardar(self, nombre="ficticio.txt", datos=b"Texto ficticio"):
        return d.guardar_documento(nombre, datos, self.carpeta)

    def test_txt_utf8_y_pdf_reales_se_guardan_y_leen(self):
        self.guardar("nota.TXT", "Información ficticia".encode())
        self.guardar("nota.PDF", pdf_ficticio())
        docs = d.leer_biblioteca(self.carpeta)
        self.assertEqual([x["nombre"] for x in docs], ["nota.TXT", "nota.PDF"])
        self.assertEqual(docs[0]["contenido"], "Información ficticia")
        self.assertIn("Texto ficticio", docs[1]["contenido"])
        self.assertFalse(list(self.carpeta.glob("*.part")))

    def test_nombres_peligrosos_rechazados_sin_crear_biblioteca(self):
        for nombre in ("../fuera.txt", "..\\fuera.txt", "/fuera.txt", "C:\\fuera.txt",
                       "C:fuera.txt", "a.txt:flujo", "CON.txt", "nul.pdf", "LPT1.txt", "COM9.txt",
                       " oculto.txt", ".oculto.txt", "a\x00.txt", "a\n.txt", "a\u202e.txt", "a?.txt",
                       "a.exe", "", "a" * 151 + ".txt", "nota.txt."):
            with self.subTest(nombre=repr(nombre)), self.assertRaises(d.ErrorDocumento):
                self.guardar(nombre)
        self.assertFalse(self.carpeta.exists())

    def test_contenido_invalido_rechazado_sin_guardar(self):
        for nombre, datos in (("vacio.txt", b""), ("espacios.txt", b"  \n"),
                              ("latin.txt", b"\xff"), ("binario.txt", b"hola\x00mundo"),
                              ("falso.pdf", b"no soy PDF"), ("roto.pdf", b"%PDF-1.7\nroto"),
                              ("protegido.pdf", pdf_ficticio(cifrado=True)),
                              ("escaneado.pdf", pdf_ficticio(texto=None))):
            with self.subTest(nombre=nombre), self.assertRaises(d.ErrorDocumento):
                self.guardar(nombre, datos)
        self.assertFalse(self.carpeta.exists())

    def test_limite_bytes_antes_de_parsear(self):
        with patch.object(configuracion, "MAX_ARCHIVO_BYTES", 5), patch.object(d, "_extraer_pdf") as leer:
            with self.assertRaises(d.ErrorDocumento):
                self.guardar("grande.pdf", b"%PDF-muy grande")
            leer.assert_not_called()
        self.assertFalse(self.carpeta.exists())

    def test_limite_paginas_y_caracteres_pdf_y_txt(self):
        with patch.object(configuracion, "MAX_PAGINAS_PDF", 1):
            with self.assertRaises(d.ErrorDocumento):
                self.guardar("largo.pdf", pdf_ficticio(paginas=2))
        with patch.object(configuracion, "MAX_CARACTERES_DOCUMENTO", 5):
            for nombre, datos in (("largo.txt", b"123456"), ("largo.pdf", pdf_ficticio(b"123456"))):
                with self.subTest(nombre=nombre), self.assertRaises(d.ErrorDocumento):
                    self.guardar(nombre, datos)
        self.assertFalse(self.carpeta.exists())

    def test_duplicado_no_sobrescribe_y_ignora_mayusculas(self):
        original = self.guardar()
        for nombre in ("ficticio.txt", "FICTICIO.TXT"):
            with self.assertRaises(d.ErrorDocumento):
                self.guardar(nombre, b"No sobrescribir")
        self.assertEqual(original.read_bytes(), b"Texto ficticio")

    def test_limite_documentos_tambien_en_lector(self):
        self.guardar("uno.txt")
        with patch.object(configuracion, "MAX_DOCUMENTOS", 1):
            with self.assertRaises(d.ErrorDocumento):
                self.guardar("dos.txt")
            self.assertFalse((self.carpeta / "dos.txt").exists())
            (self.carpeta / "externo.txt").write_bytes(b"Ficticio manual")
            with self.assertRaises(d.ErrorDocumento):
                d.leer_biblioteca(self.carpeta)

    def test_dos_guardados_concurrentes_no_sobrescriben(self):
        def intentar(contenido):
            try:
                self.guardar(datos=contenido)
                return contenido
            except d.ErrorDocumento:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(intentar, [b"Ficticio uno", b"Ficticio dos"]))
        self.assertEqual(sum(r is not None for r in resultados), 1)
        self.assertEqual((self.carpeta / "ficticio.txt").read_bytes(), next(r for r in resultados if r))
        self.assertEqual(len(list(self.carpeta.iterdir())), 1)

    def test_carrera_externa_detectada_en_publicacion(self):
        original_link = d.os.link
        def carrera(origen, destino):
            destino.write_bytes(b"Documento ficticio ajeno")
            return original_link(origen, destino)
        with patch.object(d.os, "link", side_effect=carrera), self.assertRaises(d.ErrorDocumento):
            self.guardar()
        self.assertEqual((self.carpeta / "ficticio.txt").read_bytes(), b"Documento ficticio ajeno")
        self.assertFalse(list(self.carpeta.glob("*.part")))

    def test_fallo_almacenamiento_no_publica_ni_deja_parciales(self):
        with patch.object(d.os, "fsync", side_effect=OSError("Ruta y contenido privados ficticios")):
            with self.assertRaises(d.ErrorDocumento) as error:
                self.guardar()
        self.assertNotIn("privados", str(error.exception))
        self.assertFalse(list(self.carpeta.iterdir()))

    def test_permiso_denegado_y_link_no_soportado_controlados(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError("privado")):
            with self.assertRaises(d.ErrorDocumento):
                self.guardar()
        with patch.object(d.os, "link", side_effect=OSError("Sin enlaces")):
            with self.assertRaises(d.ErrorDocumento):
                self.guardar()
        self.assertFalse((self.carpeta / "ficticio.txt").exists())
        self.assertFalse(list(self.carpeta.glob("*.part")))

    def test_enlace_fuera_de_biblioteca_rechazado(self):
        self.carpeta.mkdir()
        fuera = self.raiz / "fuera.txt"
        fuera.write_bytes(b"Ficticio externo")
        enlace = self.carpeta / "enlace.txt"
        try:
            enlace.symlink_to(fuera)
        except OSError:
            # Windows puede exigir permisos para crearlo; se prueba igual la defensa.
            enlace.write_bytes(b"Ficticio para simular enlace")
            with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda p: p == enlace):
                with self.assertRaises(d.ErrorDocumento):
                    self.guardar("enlace.txt")
                with self.assertRaises(d.ErrorDocumento):
                    d.leer_biblioteca(self.carpeta)
            self.assertEqual(fuera.read_bytes(), b"Ficticio externo")
            return
        with self.assertRaises(d.ErrorDocumento):
            self.guardar("enlace.txt")
        with self.assertRaises(d.ErrorDocumento):
            d.leer_biblioteca(self.carpeta)
        self.assertEqual(fuera.read_bytes(), b"Ficticio externo")

    def test_limites_lectura_de_archivo_existente(self):
        self.guardar()
        with patch.object(configuracion, "MAX_ARCHIVO_BYTES", 3), self.assertRaises(d.ErrorDocumento):
            d.leer_biblioteca(self.carpeta)
        with patch.object(configuracion, "MAX_CARACTERES_DOCUMENTO", 3), self.assertRaises(d.ErrorDocumento):
            d.leer_biblioteca(self.carpeta)

    def test_fallo_de_documento_conserva_instantanea_anterior(self):
        self.guardar()
        modelo = Mock()
        modelo.encode.side_effect = lambda textos: np.ones((len(textos), 2))
        motor = MotorRAG(cargador=lambda: d.leer_biblioteca(self.carpeta), fabrica_modelo=lambda: modelo)
        anterior = motor.inicializar()
        (self.carpeta / "roto.pdf").write_bytes(b"%PDF-1.7\nroto")
        with self.assertRaises(ErrorIndice):
            motor.actualizar()
        self.assertIs(motor.inicializar(), anterior)
        self.assertEqual(motor.recuperar_fragmentos("Pregunta ficticia")[0]["nombre"], "ficticio.txt")

    def test_bom_utf8_se_admite(self):
        self.guardar(datos=b"\xef\xbb\xbfTexto ficticio")
        self.assertEqual(d.leer_biblioteca(self.carpeta)[0]["contenido"], "Texto ficticio")

    def test_saltos_windows_y_mac_se_normalizan_como_read_text(self):
        self.guardar(datos=b"Ficticio\r\nDos\rTres")
        self.assertEqual(d.leer_biblioteca(self.carpeta)[0]["contenido"], "Ficticio\nDos\nTres")

    def test_cuota_no_se_supera_con_guardados_concurrentes(self):
        def intentar(nombre):
            try:
                self.guardar(nombre)
                return True
            except d.ErrorDocumento:
                return False
        with patch.object(configuracion, "MAX_DOCUMENTOS", 1), ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(intentar, ["uno.txt", "dos.txt"]))
        self.assertEqual(sum(resultados), 1)
        self.assertEqual(len(list(self.carpeta.iterdir())), 1)

    def test_publicacion_expone_solo_bytes_completos(self):
        link = d.os.link
        def comprobar(origen, destino):
            self.assertFalse(destino.exists())
            self.assertEqual(origen.read_bytes(), b"Contenido ficticio completo")
            link(origen, destino)
            self.assertEqual(destino.read_bytes(), b"Contenido ficticio completo")
        with patch.object(d.os, "link", side_effect=comprobar):
            self.guardar(datos=b"Contenido ficticio completo")
        self.assertEqual(len(list(self.carpeta.iterdir())), 1)
