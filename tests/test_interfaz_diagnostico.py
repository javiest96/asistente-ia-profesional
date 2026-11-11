"""Fase C: HTTP simulado y AppTest con datos ficticios; nunca llama a Ollama."""
from io import StringIO
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from tests.soporte import buscador_aislado, PREGUNTA
import tests.test_operacion as apoyo


class TestDiagnosticoHTTP(unittest.TestCase):
    def test_400_404_500_503_registran_codigo_duracion_e_incidencia_sin_contenido(self):
        ids = set()
        for codigo in (400, 404, 500, 503):
            with self.subTest(codigo=codigo), buscador_aislado(inicializar=False) as b:
                response = requests.Response()
                response.status_code = codigo
                response._content = b"CUERPO_PRIVADO_FICTICIO"
                response.url = "http://usuario:CLAVE_FICTICIA@127.0.0.1/api/generate"
                self.assertFalse(bool(response))  # No perder Response por ser falsy.
                error = requests.exceptions.HTTPError("EXCEPCION_PRIVADA_FICTICIA", response=response)
                http = Mock()
                http.raise_for_status.side_effect = error
                stdout = StringIO()
                with patch("requests.post", return_value=http) as post, patch.object(b, "perf_counter", side_effect=[10.0, 12.5]), self.assertLogs("rag", "WARNING") as logs, redirect_stdout(stdout):
                    with self.assertRaises(b.ErrorOllama) as capturado:
                        b.generar_respuesta("PREGUNTA_PRIVADA_FICTICIA", ["DOCUMENTO_PRIVADO_FICTICIO"])
                post.assert_called_once()  # No reintentos ocultos.
                http.json.assert_not_called()
                registro = next(r for r in logs.records if r.msg.startswith("ollama_http_error"))
                self.assertEqual(registro.estado_http, codigo)
                self.assertEqual(registro.duracion_s, 2.5)
                self.assertRegex(registro.incidencia, r"^[0-9a-f]{32}$")
                self.assertNotIn(registro.incidencia, ids)
                ids.add(registro.incidencia)
                self.assertIn(registro.incidencia, str(capturado.exception))
                self.assertIn(f"HTTP {codigo}", str(capturado.exception))
                self.assertIsNone(capturado.exception.__cause__)
                texto = "\n".join(logs.output) + str(capturado.exception) + stdout.getvalue()
                for secreto in ("PRIVADA", "PRIVADO", "CLAVE_FICTICIA", "usuario", "api/generate"):
                    self.assertNotIn(secreto, texto)
                self.assertIsNone(registro.exc_info)

    def test_estado_http_de_respuesta_si_excepcion_no_la_incluye(self):
        with buscador_aislado(inicializar=False) as b:
            http = Mock(status_code=503)
            http.raise_for_status.side_effect = requests.exceptions.HTTPError("no registrar")
            with patch("requests.post", return_value=http), self.assertLogs("rag", "WARNING") as logs, self.assertRaises(b.ErrorOllama):
                b.generar_respuesta("Pregunta ficticia", ["Contexto ficticio"])
            self.assertEqual(logs.records[0].estado_http, 503)

    def test_error_sin_estado_no_rompe_el_diagnostico(self):
        with buscador_aislado(inicializar=False) as b:
            with patch("requests.post", side_effect=requests.exceptions.HTTPError("privado ficticio")), self.assertLogs("rag", "WARNING") as logs:
                with self.assertRaisesRegex(b.ErrorOllama, "HTTP desconocido"):
                    b.generar_respuesta("Pregunta ficticia", ["Contexto ficticio"])
            self.assertIsNone(logs.records[0].estado_http)

    def test_payload_rag_conserva_opciones_y_diferencias_con_directa(self):
        with buscador_aislado(inicializar=False) as b:
            http = Mock()
            http.json.return_value = {"response": "Respuesta ficticia"}
            with patch("requests.post", return_value=http) as post:
                b.generar_respuesta("Pregunta ficticia", ["Evidencia ficticia"])
            args, kwargs = post.call_args
            self.assertEqual(args, (b.configuracion.URL_OLLAMA,))
            self.assertEqual(set(kwargs["json"]), {"model", "prompt", "stream", "think", "options"})
            self.assertEqual(kwargs["json"]["model"], "qwen3.5:4b")
            self.assertEqual(kwargs["json"]["options"], {"temperature": 0})
            self.assertFalse(kwargs["json"]["stream"])
            self.assertFalse(kwargs["json"]["think"])
            self.assertEqual(kwargs["timeout"], 120)


class TestInterfazPersistente(unittest.TestCase):
    def crear(self):
        self.apoyo = apoyo.TestAppProduccion("test_guardado_valido_publica_y_actualiza")
        self.addCleanup(self.apoyo.doCleanups)
        archivo = SimpleNamespace(name="estado_ficticio.txt", size=14, getvalue=lambda: b"Texto ficticio")
        app = self.apoyo.crear_app(archivo, subidas=True)
        return app, self.apoyo.buscador

    def test_guardado_e_indice_se_confirman_y_persisten_al_escribir(self):
        app, b = self.crear()
        with patch.object(b, "actualizar_indice") as actualizar:
            app.button[1].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Documento guardado correctamente.", app.success[0].value)
            self.assertIn("Índice actualizado.", app.success[0].value)
            self.assertTrue(app.session_state["estado_biblioteca"]["guardado"])
            self.assertEqual(app.session_state["estado_biblioteca"]["indice"], "actualizado")
            app.text_input[0].set_value(PREGUNTA).run()
            actualizar.assert_called_once_with()
        self.assertEqual(len(app.success), 1)
        self.assertIn("Índice actualizado.", app.success[0].value)

    def test_indicador_se_abre_antes_de_indexar_y_finaliza_completo(self):
        app, b = self.crear()
        eventos = []
        estado = Mock()
        estado.__enter__ = Mock(return_value=estado)
        estado.__exit__ = Mock(return_value=False)
        def abrir(*args, **kwargs):
            eventos.append("indicador")
            self.assertIn("Documento guardado", args[0])
            return estado
        def indexar():
            self.assertEqual(eventos, ["indicador"])
            eventos.append("indexar")
        with patch("streamlit.status", side_effect=abrir), patch.object(b, "actualizar_indice", side_effect=indexar):
            app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(eventos, ["indicador", "indexar"])
        estado.update.assert_called_once_with(label="Índice actualizado", state="complete", expanded=False)

    def test_fallo_de_indice_conserva_documento_instantanea_y_aviso(self):
        app, b = self.crear()
        anterior = b.inicializar_indice()
        b._cargador_prueba.side_effect = OSError("Fallo ficticio de indexación")
        app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 0)
        self.assertIn("Documento guardado", app.error[0].value)
        self.assertIn("versión anterior se conserva", app.error[0].value)
        self.assertIs(b.inicializar_indice(), anterior)
        self.assertTrue((self.apoyo.carpeta / "biblioteca" / "estado_ficticio.txt").exists())
        llamadas = b._cargador_prueba.call_count
        app.text_input[0].set_value(PREGUNTA).run()
        self.assertEqual(b._cargador_prueba.call_count, llamadas)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(app.session_state["estado_biblioteca"]["indice"], "error")

    def test_actualizacion_manual_reemplaza_el_aviso_de_error(self):
        app, b = self.crear()
        with patch.object(b, "actualizar_indice", side_effect=b.ErrorIndice("Error ficticio")):
            app.button[1].click().run()
        self.assertEqual(len(app.error), 1)
        with patch.object(b, "actualizar_indice"):
            app.button[0].click().run()
        self.assertEqual(len(app.error), 0)
        self.assertEqual(app.success[0].value, "Biblioteca actualizada correctamente.")
        self.assertEqual(app.session_state["estado_biblioteca"]["indice"], "actualizado")

    def test_primer_indice_fallido_no_afirma_que_existe_uno_anterior(self):
        app, b = self.crear()
        b._motor._indice = None
        b._cargador_prueba.side_effect = OSError("Carga ficticia fallida")
        app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Documento guardado", app.error[0].value)
        self.assertIn("inicializar el índice", app.error[0].value)
        self.assertNotIn("versión anterior", app.error[0].value)
        self.assertIsNone(b._motor._indice)

    def test_duplicado_reemplaza_exito_y_no_reindexa(self):
        app, b = self.crear()
        with patch.object(b, "actualizar_indice") as actualizar:
            app.button[1].click().run()
            app.button[1].click().run()
            actualizar.assert_called_once_with()
        self.assertEqual(len(app.success), 0)
        self.assertIn("Ya existe", app.error[0].value)
        self.assertFalse(app.session_state["estado_biblioteca"]["guardado"])

    def test_rechazo_http_se_muestra_como_error_con_id_y_sin_respuesta(self):
        app, b = self.crear()
        response = requests.Response()
        response.status_code = 503
        http = Mock()
        http.raise_for_status.side_effect = requests.exceptions.HTTPError("ficticio", response=response)
        app.text_input[0].set_value(PREGUNTA).run()
        with patch("requests.post", return_value=http), self.assertLogs("rag", "WARNING") as logs:
            app.button[2].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("HTTP 503", app.error[0].value)
        self.assertIn(logs.records[0].incidencia, app.error[0].value)
        self.assertFalse(any("Respuesta de nuestra IA" in x.value for x in app.subheader))
