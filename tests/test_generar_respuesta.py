from unittest.mock import Mock, patch
import unittest

import requests

from tests.soporte import CasoBuscadorAislado, DOCUMENTOS, PREGUNTA


class TestGenerarRespuesta(CasoBuscadorAislado):
    def setUp(self):
        super().setUp()
        self.post = self.enterContext(patch("requests.post"))
        self.http = Mock()
        self.http.json.return_value = {"response": "Juega los sábados a las diez."}
        self.post.return_value = self.http
        self.contexto = [DOCUMENTOS[0]["contenido"], "Dato ficticio adicional."]

    def test_envia_pregunta_contexto_y_configuracion(self):
        respuesta = self.buscador.generar_respuesta(PREGUNTA, self.contexto)
        self.assertEqual(respuesta, "Juega los sábados a las diez.")
        self.post.assert_called_once()
        args, kwargs = self.post.call_args
        self.assertEqual(args, (self.buscador.configuracion.URL_OLLAMA,))
        self.assertEqual(kwargs["timeout"], 120)
        datos = kwargs["json"]
        self.assertEqual(datos["model"], self.buscador.MODELO_LLM)
        self.assertEqual(datos["options"], {"temperature": 0})
        self.assertIs(datos["stream"], False)
        self.assertIs(datos["think"], False)
        self.assertIn("Contexto:\n" + "\n".join(self.contexto), datos["prompt"])
        self.assertIn("Pregunta:\n" + PREGUNTA, datos["prompt"])
        self.http.raise_for_status.assert_called_once_with()

    def test_devuelve_detalles_sin_bloqueo(self):
        self.assertEqual(self.buscador.generar_respuesta(PREGUNTA, self.contexto, devolver_detalles=True), {
            "respuesta_original": "Juega los sábados a las diez.",
            "respuesta_final": "Juega los sábados a las diez.",
            "bloqueada": False,
        })

    def test_fallo_de_conexion_y_timeout(self):
        for error in (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            with self.subTest(error=error.__name__):
                self.post.side_effect = error("Fallo ficticio")
                with self.assertRaises(self.buscador.ErrorOllama):
                    self.buscador.generar_respuesta(PREGUNTA, self.contexto)

    def test_detalles_en_fallo_de_conexion(self):
        self.post.side_effect = requests.exceptions.ConnectionError("Fallo ficticio")
        with self.assertRaises(self.buscador.ErrorOllama):
            self.buscador.generar_respuesta(PREGUNTA, self.contexto, devolver_detalles=True)

    def test_http_incorrecto_no_es_respuesta(self):
        self.http.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP ficticio")
        with self.assertRaises(self.buscador.ErrorOllama):
            self.buscador.generar_respuesta(PREGUNTA, self.contexto)
        self.http.json.assert_not_called()

    def test_json_invalido(self):
        self.http.json.side_effect = ValueError("JSON ficticio inválido")
        with self.assertRaises(self.buscador.ErrorOllama):
            self.buscador.generar_respuesta(PREGUNTA, self.contexto)

    def test_esquemas_invalidos_no_son_respuestas(self):
        for datos in (None, [], "texto", {}, {"response": None}, {"response": 42},
                      {"response": ""}, {"response": "  "},
                      {"error": "fallo ficticio", "response": "texto engañoso"}):
            with self.subTest(datos=datos):
                self.http.json.return_value = datos
                with self.assertRaises(self.buscador.ErrorOllama):
                    self.buscador.generar_respuesta(PREGUNTA, self.contexto)

    def test_error_generico_de_comunicacion(self):
        self.post.side_effect = requests.exceptions.RequestException("fallo ficticio")
        with self.assertRaises(self.buscador.ErrorOllama):
            self.buscador.generar_respuesta(PREGUNTA, self.contexto)

    def test_metricas_opcionales_invalidas_no_rompen_respuesta_valida(self):
        self.http.json.return_value = {
            "response": "Respuesta ficticia válida.", "eval_count": None,
            "eval_duration": "inválido", "prompt_eval_duration": {},
            "total_duration": [], "load_duration": None,
        }
        self.assertEqual(self.buscador.generar_respuesta(PREGUNTA, self.contexto), "Respuesta ficticia válida.")

    def test_bloquea_anio_ausente_del_contexto(self):
        self.http.json.return_value = {"response": "El club se fundó en 1998."}
        self.assertEqual(self.buscador.generar_respuesta(PREGUNTA, self.contexto, devolver_detalles=True), {
            "respuesta_original": "El club se fundó en 1998.",
            "respuesta_final": "No tengo información suficiente para confirmar esa fecha.",
            "bloqueada": True,
        })

    def test_permite_anio_presente_en_contexto(self):
        self.http.json.return_value = {"response": "El club se fundó en 2020."}
        resultado = self.buscador.generar_respuesta("¿Cuándo se fundó?", ["El club ficticio se fundó en 2020."], devolver_detalles=True)
        self.assertEqual(resultado["respuesta_final"], "El club se fundó en 2020.")
        self.assertFalse(resultado["bloqueada"])


if __name__ == "__main__":
    unittest.main()
