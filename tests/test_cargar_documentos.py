from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import cargar_documentos


class TestCargarDocumentos(unittest.TestCase):
    def setUp(self):
        temporal = self.enterContext(TemporaryDirectory(prefix="rag_tests_"))
        raiz = Path(temporal)
        self.carpeta = raiz / "Documentos"
        self.carpeta.mkdir()
        # Redirige solo la ruta base del módulo a un árbol temporal.
        self.enterContext(patch.object(cargar_documentos, "__file__", str(raiz / "cargar_documentos.py")))
        self.lector = self.enterContext(patch.object(cargar_documentos, "PdfReader"))

    def test_txt_utf8_con_tildes(self):
        contenido = "La biblioteca ficticia abre el miércoles.\nInformación de prueba."
        (self.carpeta / "biblioteca.txt").write_text(contenido, encoding="utf-8")
        self.assertEqual(cargar_documentos.cargar_documentos(), [{"nombre": "biblioteca.txt", "contenido": contenido}])
        self.lector.assert_not_called()

    def test_ignora_extensiones_ajenas(self):
        (self.carpeta / "nota.csv").write_text("dato ficticio", encoding="utf-8")
        self.assertEqual(cargar_documentos.cargar_documentos(), [])
        self.lector.assert_not_called()

    def test_carpeta_vacia(self):
        self.assertEqual(cargar_documentos.cargar_documentos(), [])

    def test_carpeta_ausente(self):
        self.carpeta.rmdir()  # Solo la carpeta temporal vacía creada por este test.
        self.assertEqual(cargar_documentos.cargar_documentos(), [])

    def test_pdf_une_paginas_y_admite_none(self):
        archivo = self.carpeta / "horario_ficticio.pdf"
        archivo.write_bytes(b"PDF ficticio: el lector esta simulado")
        paginas = [Mock(), Mock(), Mock()]
        for pagina, texto in zip(paginas, ["Primera página ficticia.", None, "Última página ficticia."]):
            pagina.extract_text.return_value = texto
        self.lector.return_value.pages = paginas
        self.assertEqual(cargar_documentos.cargar_documentos(), [{
            "nombre": archivo.name,
            "contenido": "Primera página ficticia.\n\nÚltima página ficticia.",
        }])
        self.lector.assert_called_once_with(archivo)
        for pagina in paginas:
            pagina.extract_text.assert_called_once_with()

    def test_omite_pdf_sin_texto(self):
        (self.carpeta / "sin_texto.pdf").write_bytes(b"PDF ficticio")
        self.lector.return_value.pages = [Mock(extract_text=Mock(return_value=None))]
        self.assertEqual(cargar_documentos.cargar_documentos(), [])


if __name__ == "__main__":
    unittest.main()
