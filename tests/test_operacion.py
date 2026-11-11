"""Privacidad, límites y concurrencia con HTTP/modelos simulados."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, BoundedSemaphore
import tomllib
import unittest
from unittest.mock import Mock, patch

import configuracion
import operacion
import documentos
import cargar_documentos
from tests.soporte import RAIZ, PREGUNTA, buscador_aislado


class TestOperacion(unittest.TestCase):
    def test_pregunta_excesiva_se_rechaza_antes_de_trabajo_costoso(self):
        with buscador_aislado(inicializar=False) as b, patch.object(configuracion, "MAX_PREGUNTA_CARACTERES", 5):
            for funcion in (b.recuperar_fragmentos, b.recuperar_contexto, b.puntuar_documentos):
                for pregunta in ("muy larga", "  ", None):
                    with self.subTest(funcion=funcion.__name__, pregunta=pregunta), self.assertRaises(operacion.ErrorConsulta):
                        funcion(pregunta)
            with patch("requests.post") as post, self.assertRaises(operacion.ErrorConsulta):
                b.generar_respuesta("muy larga", ["Dato ficticio"])
            post.assert_not_called()
            b._cargador_prueba.assert_not_called()
            b._fabrica_prueba.assert_not_called()

    def test_concurrencia_rechaza_segunda_llamada_y_libera_al_terminar(self):
        dentro, seguir = Event(), Event()
        http = Mock()
        http.json.return_value = {"response": "Respuesta ficticia"}
        def lenta(*args, **kwargs):
            dentro.set()
            if not seguir.wait(10):
                raise TimeoutError("El test no liberó HTTP simulado")
            return http
        with buscador_aislado(inicializar=False) as b, patch.object(operacion, "_generaciones", BoundedSemaphore(1)), patch("requests.post", side_effect=lenta) as post:
            with ThreadPoolExecutor(max_workers=1) as pool:
                primera = pool.submit(b.generar_respuesta, "Pregunta ficticia", ["Dato ficticio"])
                try:
                    self.assertTrue(dentro.wait(10))
                    with self.assertRaisesRegex(b.ErrorOllama, "ocupado"):
                        b.generar_respuesta("Otra pregunta", ["Dato ficticio"])
                    self.assertEqual(post.call_count, 1)
                finally:
                    seguir.set()
                self.assertEqual(primera.result(10), "Respuesta ficticia")
            self.assertEqual(b.generar_respuesta("Otra pregunta", ["Dato ficticio"]), "Respuesta ficticia")

    def test_error_libera_plaza_y_respeta_timeout_configurado(self):
        import requests
        http = Mock()
        http.json.return_value = {"response": "Respuesta ficticia"}
        with buscador_aislado(inicializar=False) as b, patch.object(operacion, "_generaciones", BoundedSemaphore(1)), patch.object(configuracion, "OLLAMA_TIMEOUT_S", 15), patch("requests.post", side_effect=[requests.exceptions.Timeout("dato privado ficticio"), http]) as post:
            with self.assertRaises(b.ErrorOllama):
                b.generar_respuesta("Pregunta ficticia", ["Dato ficticio"])
            self.assertEqual(b.generar_respuesta("Pregunta ficticia", ["Dato ficticio"]), "Respuesta ficticia")
            self.assertEqual(post.call_args.kwargs["timeout"], 15)

    def test_logs_no_contienen_preguntas_respuestas_contextos_o_excepciones(self):
        import requests
        http = Mock()
        http.json.return_value = {"response": "RESPUESTA_PRIVADA_FICTICIA 1998"}
        stdout = StringIO()
        with buscador_aislado(inicializar=False) as b, patch("requests.post", return_value=http) as post, self.assertLogs("rag", "INFO") as logs, redirect_stdout(stdout):
            b.generar_respuesta("PREGUNTA_PRIVADA_FICTICIA", ["CONTEXTO_PRIVADO_FICTICIO"])
            post.side_effect = requests.exceptions.ConnectionError("EXCEPCION_PRIVADA_FICTICIA")
            with self.assertRaises(b.ErrorOllama):
                b.generar_respuesta("PREGUNTA_PRIVADA_FICTICIA", ["CONTEXTO_PRIVADO_FICTICIO"])
        for dato in ("PRIVADA", "PRIVADO", "1998"):
            self.assertNotIn(dato, "\n".join(logs.output))
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(any("respuesta_filtrada" in x for x in logs.output))
        self.assertTrue(any("ollama_conexion_error" in x for x in logs.output))

    def test_logging_no_duplica_handlers_ni_propaga_a_host(self):
        operacion.configurar_logging()
        n = len(operacion.logger.handlers)
        operacion.configurar_logging()
        self.assertEqual(len(operacion.logger.handlers), n)
        self.assertFalse(operacion.logger.propagate)
        self.assertFalse(logging.getLogger("pypdf").propagate)

    def test_lector_y_guardado_usan_carpeta_configurada(self):
        with TemporaryDirectory() as tmp, patch.object(configuracion, "_ruta_documentos", Path(tmp) / "corpus_ficticio"):
            ruta = documentos.guardar_documento("ficticio.txt", b"Texto ficticio")
            self.assertEqual(ruta.parent, configuracion.carpeta_documentos())
            self.assertEqual(cargar_documentos.cargar_documentos(), [{"nombre": "ficticio.txt", "contenido": "Texto ficticio"}])

    def test_config_demo_local_no_habilita_api_agente(self):
        c = tomllib.loads((RAIZ / ".streamlit/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(c["server"]["address"], "127.0.0.1")
        self.assertTrue(c["server"]["enableCORS"])
        self.assertTrue(c["server"]["enableXsrfProtection"])
        self.assertFalse(c["server"].get("enableAgentApi", False))
        self.assertEqual(c["client"]["showErrorDetails"], "none")


class TestAppProduccion(unittest.TestCase):
    def crear_app(self, archivo=None, subidas=False):
        from streamlit.testing.v1 import AppTest
        from tests.soporte import sustituir_modulos
        self.buscador = self.enterContext(buscador_aislado(bloquear_sockets=False))
        self.enterContext(sustituir_modulos({"buscador_semantico": self.buscador}))
        self.enterContext(patch.object(configuracion, "PERMITIR_SUBIDAS", subidas))
        self.carpeta = Path(self.enterContext(TemporaryDirectory(prefix="rag_app_segura_")))
        self.enterContext(patch.object(configuracion, "_ruta_documentos", self.carpeta / "biblioteca"))
        self.uploader = self.enterContext(patch("streamlit.file_uploader", return_value=archivo))
        ruta = self.carpeta / "app.py"
        ruta.write_text((RAIZ / "app.py").read_text(encoding="utf-8"), encoding="utf-8")
        return AppTest.from_file(str(ruta)).run()

    def test_demo_sin_subidas_no_muestra_uploader(self):
        app = self.crear_app()
        self.uploader.assert_not_called()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse((self.carpeta / "biblioteca").exists())

    def test_archivo_invalido_no_se_guarda_ni_actualiza(self):
        archivo = Mock(name="subida_ficticia")
        archivo.name, archivo.size = "roto.pdf", 7
        archivo.getvalue.return_value = b"no PDF"
        app = self.crear_app(archivo, subidas=True)
        with patch.object(self.buscador, "actualizar_indice") as actualizar:
            app.button[1].click().run()
            actualizar.assert_not_called()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertFalse((self.carpeta / "biblioteca").exists())

    def test_tamano_declarado_excesivo_no_copia_bytes(self):
        archivo = Mock()
        archivo.name, archivo.size = "grande.txt", configuracion.MAX_ARCHIVO_BYTES + 1
        app = self.crear_app(archivo, subidas=True)
        app.button[1].click().run()
        archivo.getvalue.assert_not_called()
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.exception), 0)

    def test_permiso_denegado_se_muestra_sin_rutas(self):
        archivo = Mock()
        archivo.name, archivo.size = "ficticio.txt", 5
        archivo.getvalue.return_value = b"Texto ficticio"
        app = self.crear_app(archivo, subidas=True)
        with patch.object(documentos.os, "link", side_effect=PermissionError("RUTA_PRIVADA")):
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertNotIn("RUTA_PRIVADA", app.error[0].value)
        self.assertFalse((self.carpeta / "biblioteca" / "ficticio.txt").exists())

    def test_guardado_valido_publica_y_actualiza(self):
        archivo = Mock()
        archivo.name, archivo.size = "ficticio.txt", 14
        archivo.getvalue.return_value = b"Texto ficticio"
        app = self.crear_app(archivo, subidas=True)
        with patch.object(self.buscador, "actualizar_indice") as actualizar:
            app.button[1].click().run()
            actualizar.assert_called_once_with()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual((self.carpeta / "biblioteca" / "ficticio.txt").read_bytes(), b"Texto ficticio")
