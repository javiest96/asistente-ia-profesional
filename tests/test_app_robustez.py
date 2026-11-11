"""Regresiones de interfaz con el RAG aislado y sin archivos personales."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

from tests.soporte import RAIZ, PREGUNTA, buscador_aislado, sustituir_modulos


class TestAppRobustez(unittest.TestCase):
    def crear_app(self, documentos=None):
        # AppTest/asyncio usa socketpair local en Windows. HTTP sigue bloqueado;
        # el modelo y el corpus son simulados antes de cargar la interfaz.
        buscador = self.enterContext(buscador_aislado(documentos=documentos, bloquear_sockets=False))
        self.enterContext(sustituir_modulos({"buscador_semantico": buscador}))
        self.raiz_app = Path(self.enterContext(TemporaryDirectory(prefix="rag_app_tests_")))
        ruta_app = self.raiz_app / "app.py"
        ruta_app.write_text((RAIZ / "app.py").read_text(encoding="utf-8"), encoding="utf-8")
        app = AppTest.from_file(str(ruta_app)).run()
        self.assertEqual(len(app.exception), 0)
        return app, buscador

    def test_inicio_sin_documentos(self):
        app, buscador = self.crear_app(documentos=[])
        self.assertEqual(len(app.error), 0)
        buscador._modelo_prueba.encode.assert_not_called()

    def test_busqueda_vacia_no_llama_a_ollama(self):
        app, buscador = self.crear_app(documentos=[])
        with patch.object(buscador, "generar_respuesta") as generar:
            app.text_input[0].set_value(PREGUNTA).run()
            app.button[1].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.warning[0].value, "No he encontrado información suficiente.")
            generar.assert_not_called()

    def test_actualizar_biblioteca_vacia(self):
        app, buscador = self.crear_app(documentos=[])
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 1)
        buscador._modelo_prueba.encode.assert_not_called()

    def test_error_se_muestra_como_error_sin_respuesta(self):
        app, _ = self.crear_app()
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("fallo simulado")):
            app.text_input[0].set_value(PREGUNTA).run()
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertIn("No se puede conectar", app.error[0].value)
        self.assertFalse(any("Respuesta de nuestra IA" in h.value for h in app.subheader))

    def test_exito_sigue_mostrando_respuesta(self):
        app, buscador = self.crear_app()
        with patch.object(buscador, "generar_respuesta", return_value="Respuesta ficticia correcta."):
            app.text_input[0].set_value(PREGUNTA).run()
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertTrue(any("Respuesta ficticia correcta." in m.value for m in app.markdown))

    def test_actualizacion_fallida_no_muestra_exito(self):
        app, buscador = self.crear_app()
        anterior = buscador.inicializar_indice()
        buscador._cargador_prueba.side_effect = OSError("Carga fallida ficticia")
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.success), 0)
        self.assertIs(buscador.inicializar_indice(), anterior)

    def test_error_de_busqueda_muestra_error_sin_respuesta(self):
        app, buscador = self.crear_app()
        with patch.object(buscador, "recuperar_fragmentos", side_effect=buscador.ErrorIndice("Búsqueda fallida")):
            app.text_input[0].set_value(PREGUNTA).run()
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertFalse(any("Respuesta de nuestra IA" in h.value for h in app.subheader))

    def test_documento_guardado_con_indice_fallido(self):
        archivo = SimpleNamespace(name="nuevo_ficticio.txt", getvalue=lambda: b"Contenido ficticio")
        with patch("configuracion.PERMITIR_SUBIDAS", True), patch("streamlit.file_uploader", return_value=archivo):
            app, buscador = self.crear_app()
            anterior = buscador.inicializar_indice()
            buscador._cargador_prueba.side_effect = OSError("Carga fallida ficticia")
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertIn("Documento guardado", app.error[0].value)
        self.assertEqual(len(app.success), 0)
        self.assertIs(buscador.inicializar_indice(), anterior)
        self.assertEqual((self.raiz_app / "Documentos" / archivo.name).read_bytes(), b"Contenido ficticio")


if __name__ == "__main__":
    unittest.main()
