"""Ciclo de vida, validación y concurrencia sin modelos ni documentos reales."""
import builtins
import importlib.util
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Event
from unittest.mock import Mock, patch

import numpy as np

from tests.soporte import RAIZ, DOCUMENTOS, DOCUMENTO_NUEVO, PREGUNTA, buscador_aislado


class TestInicializacion(unittest.TestCase):
    def test_import_no_carga_bibliotecas_pesadas_ni_documentos(self):
        importar = builtins.__import__
        prohibidos = {"sentence_transformers", "cargar_documentos", "numpy", "sklearn", "requests", "pypdf"}

        def control(nombre, *args, **kwargs):
            if nombre.split(".")[0] in prohibidos:
                raise AssertionError("Importación costosa: " + nombre)
            return importar(nombre, *args, **kwargs)

        spec = importlib.util.spec_from_file_location("_rag_import_ligero", RAIZ / "buscador_semantico.py")
        modulo = importlib.util.module_from_spec(spec)
        with patch("builtins.__import__", side_effect=control):
            spec.loader.exec_module(modulo)
        self.assertIsNone(modulo._motor._indice)
        self.assertIsNone(modulo._motor._modelo)

    def test_inicializacion_explicita_idempotente(self):
        with buscador_aislado(inicializar=False) as b:
            b._cargador_prueba.assert_not_called()
            b._fabrica_prueba.assert_not_called()
            primero = b.inicializar_indice()
            self.assertIs(b.inicializar_indice(), primero)
            b.recuperar_fragmentos(PREGUNTA)
            b._cargador_prueba.assert_called_once_with()
            b._fabrica_prueba.assert_called_once_with()

    def test_primera_busqueda_inicializa(self):
        with buscador_aislado(inicializar=False) as b:
            self.assertEqual(b.recuperar_fragmentos(PREGUNTA)[0]["nombre"], DOCUMENTOS[0]["nombre"])
            self.assertEqual(b.inicializar_indice().version, 1)

    def test_vacio_no_carga_modelo(self):
        with buscador_aislado(documentos=[], inicializar=False) as b:
            indice = b.inicializar_indice()
            self.assertEqual(indice.version, 1)
            self.assertEqual(b.recuperar_fragmentos(PREGUNTA), [])
            b._fabrica_prueba.assert_not_called()

    def test_fallo_inicial_permite_reintento(self):
        with buscador_aislado(inicializar=False) as b:
            b._fabrica_prueba.side_effect = RuntimeError("Fallo ficticio de modelo")
            with self.assertRaises(b.ErrorIndice):
                b.inicializar_indice()
            self.assertIsNone(b._motor._indice)
            b._fabrica_prueba.side_effect = None
            self.assertEqual(b.inicializar_indice().version, 1)

    def test_fabrica_predeterminada_conserva_modelo(self):
        with buscador_aislado(inicializar=False) as b:
            b._crear_modelo()
            b._fabrica_prueba.assert_called_once_with(
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )

    def test_motor_predeterminado_resuelve_dependencias_solo_al_inicializar(self):
        with buscador_aislado(inicializar=False) as b:
            motor = b.MotorRAG()
            b._fabrica_prueba.assert_not_called()
            b._cargador_prueba.assert_not_called()
            self.assertEqual(motor.inicializar().version, 1)
            b._cargador_prueba.assert_called_once_with()
            b._fabrica_prueba.assert_called_once_with(
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            )

    def test_generar_respuesta_no_inicializa_indice(self):
        with buscador_aislado(inicializar=False) as b:
            http = Mock()
            http.json.return_value = {"response": "Texto ficticio válido"}
            with patch("requests.post", return_value=http):
                self.assertEqual(b.generar_respuesta(PREGUNTA, ["Contexto ficticio"]), "Texto ficticio válido")
            b._cargador_prueba.assert_not_called()
            b._fabrica_prueba.assert_not_called()


class TestIndiceAtomico(unittest.TestCase):
    def test_fallo_lectura_conserva_identidad_y_version(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            b._cargador_prueba.side_effect = OSError("Lectura ficticia fallida")
            with self.assertRaises(b.ErrorIndice) as error:
                b.actualizar_indice()
            self.assertIsInstance(error.exception.__cause__, OSError)
            self.assertIs(b.inicializar_indice(), anterior)
            self.assertEqual(b.recuperar_fragmentos(PREGUNTA)[0]["nombre"], DOCUMENTOS[0]["nombre"])

    def test_fallo_segundo_encode_no_publica_cambios_parciales(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            codificar = b._modelo_prueba.encode.side_effect
            b._modelo_prueba.encode.side_effect = [np.ones((3, 2)), RuntimeError("Segundo encode fallido")]
            with self.assertRaises(b.ErrorIndice):
                b.actualizar_indice()
            self.assertIs(b.inicializar_indice(), anterior)
            np.testing.assert_array_equal(anterior.embeddings_documentos, [[1, 0], [3, 4], [0, 1]])
            b._modelo_prueba.encode.side_effect = codificar
            b.actualizar_indice()
            self.assertEqual(b.inicializar_indice().version, anterior.version + 1)

    def test_fallo_fragmentacion_conserva_indice(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            with patch.object(b, "preparar_fragmentos", side_effect=ValueError("Fragmentación fallida")):
                with self.assertRaises(b.ErrorIndice):
                    b.actualizar_indice()
            self.assertIs(b.inicializar_indice(), anterior)

    def test_rechaza_matrices_invalidas(self):
        casos = [np.ones(3), np.ones((2, 2)), np.ones((3, 0)),
                 np.full((3, 2), np.nan), np.full((3, 2), np.inf)]
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            for matriz in casos:
                with self.subTest(forma=matriz.shape, valores=matriz.tolist()):
                    b._modelo_prueba.encode.side_effect = lambda textos: matriz
                    with self.assertRaises(b.ErrorIndice):
                        b.actualizar_indice()
                    self.assertIs(b.inicializar_indice(), anterior)

    def test_rechaza_dimensiones_incompatibles(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            b._modelo_prueba.encode.side_effect = [np.ones((3, 2)), np.ones((3, 3))]
            with self.assertRaises(b.ErrorIndice):
                b.actualizar_indice()
            self.assertIs(b.inicializar_indice(), anterior)

    def test_instantanea_no_admite_mutaciones(self):
        with buscador_aislado() as b:
            indice = b.inicializar_indice()
            with self.assertRaises(FrozenInstanceError):
                indice.version = 99
            with self.assertRaises(TypeError):
                indice.fragmentos[0]["contenido"] = "Alterado"
            with self.assertRaises(TypeError):
                indice.documentos_cargados[0]["nombre"] = "Alterado"
            for matriz in (indice.embeddings_documentos, indice.embeddings_fragmentos):
                with self.assertRaises(ValueError):
                    matriz[0, 0] = 99
                with self.assertRaises(ValueError):
                    matriz.setflags(write=True)

    def test_no_conserva_alias_del_corpus_ni_vectores(self):
        with buscador_aislado() as b:
            corpus = [dict(d) for d in DOCUMENTOS]
            vectores = np.ones((3, 2))
            b._cargador_prueba.side_effect = None
            b._cargador_prueba.return_value = corpus
            b._modelo_prueba.encode.side_effect = lambda textos: vectores
            b.actualizar_indice()
            indice = b.inicializar_indice()
            corpus[0]["contenido"] = "Modificación posterior"
            vectores[:] = 99
            self.assertEqual(indice.documentos[0], DOCUMENTOS[0]["contenido"])
            np.testing.assert_array_equal(indice.embeddings_fragmentos, np.ones((3, 2)))

    def test_vacio_es_version_valida_y_no_reinicializa(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            b._cargador_prueba.side_effect = None
            b._cargador_prueba.return_value = []
            b.actualizar_indice()
            vacio = b.inicializar_indice()
            self.assertEqual(vacio.version, anterior.version + 1)
            self.assertEqual(vacio.fragmentos, ())
            self.assertEqual(vacio.embeddings_fragmentos.shape, (0, 0))
            self.assertEqual(b.puntuar_documentos(PREGUNTA), [])
            self.assertIs(b.inicializar_indice(), vacio)

    def test_error_de_consulta_no_destruye_indice(self):
        with buscador_aislado() as b:
            anterior = b.inicializar_indice()
            codificar = b._modelo_prueba.encode.side_effect
            b._modelo_prueba.encode.side_effect = RuntimeError("Fallo de consulta")
            with self.assertRaises(b.ErrorIndice):
                b.recuperar_fragmentos(PREGUNTA)
            self.assertIs(b.inicializar_indice(), anterior)
            b._modelo_prueba.encode.side_effect = codificar
            self.assertEqual(len(b.recuperar_fragmentos(PREGUNTA)), 2)

    def test_diagnostico_conserva_textos_y_puntuaciones(self):
        with buscador_aislado() as b:
            pares = b.puntuar_documentos(PREGUNTA)
            self.assertEqual([p[0] for p in pares], [d["contenido"] for d in DOCUMENTOS])
            np.testing.assert_allclose([p[1] for p in pares], [1, .6, 0])
            self.assertEqual(b.recuperar_contexto(PREGUNTA), [d["contenido"] for d in DOCUMENTOS[:2]])


class TestConcurrencia(unittest.TestCase):
    def test_inicializaciones_concurrentes_cargan_una_vez(self):
        with buscador_aislado(inicializar=False) as b:
            dentro, seguir = Event(), Event()

            def cargar():
                dentro.set()
                if not seguir.wait(10):
                    raise TimeoutError("Test no liberó la carga")
                return [dict(d) for d in DOCUMENTOS]

            b._cargador_prueba.side_effect = cargar
            with ThreadPoolExecutor(max_workers=2) as pool:
                primero = pool.submit(b.inicializar_indice)
                try:
                    self.assertTrue(dentro.wait(10))
                    segundo = pool.submit(b.inicializar_indice)
                finally:
                    seguir.set()
                self.assertIs(primero.result(10), segundo.result(10))
            b._cargador_prueba.assert_called_once_with()
            b._fabrica_prueba.assert_called_once_with()

    def test_consulta_usa_una_version_mientras_se_publica_otra(self):
        for metodo in ("recuperar_fragmentos", "recuperar_contexto", "puntuar_documentos"):
            with self.subTest(metodo=metodo), buscador_aislado() as b:
                capturada, seguir = Event(), Event()
                similitudes = b._motor._similitudes

                def pausar(consulta, matriz):
                    capturada.set()
                    if not seguir.wait(10):
                        raise TimeoutError("Test no liberó la consulta")
                    return similitudes(consulta, matriz)

                with patch.object(b._motor, "_similitudes", side_effect=pausar):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        consulta = pool.submit(getattr(b, metodo), PREGUNTA)
                        try:
                            self.assertTrue(capturada.wait(10))
                            b._cargador_prueba.side_effect = None
                            b._cargador_prueba.return_value = [dict(DOCUMENTO_NUEVO)]
                            b.actualizar_indice()
                        finally:
                            seguir.set()
                        resultado = consulta.result(10)
                if metodo == "recuperar_fragmentos":
                    self.assertEqual(resultado[0]["nombre"], DOCUMENTOS[0]["nombre"])
                elif metodo == "recuperar_contexto":
                    self.assertEqual(resultado[0], DOCUMENTOS[0]["contenido"])
                else:
                    self.assertEqual(resultado[0][0], DOCUMENTOS[0]["contenido"])
                self.assertEqual(b.inicializar_indice().version, 2)
                self.assertEqual(b.recuperar_fragmentos("consulta piscina")[0]["nombre"], DOCUMENTO_NUEVO["nombre"])

    def test_actualizaciones_serializadas_y_consultas_durante_construccion(self):
        with buscador_aislado() as b:
            dentro, seguir, segundo_intenta = Event(), Event(), Event()
            llamadas = []

            def cargar():
                llamadas.append(1)
                if len(llamadas) == 1:
                    dentro.set()
                    if not seguir.wait(10):
                        raise TimeoutError("Test no liberó actualización")
                return [dict(DOCUMENTO_NUEVO)]

            def segundo():
                segundo_intenta.set()
                b.actualizar_indice()

            b._cargador_prueba.side_effect = cargar
            with ThreadPoolExecutor(max_workers=2) as pool:
                primera = pool.submit(b.actualizar_indice)
                try:
                    self.assertTrue(dentro.wait(10))
                    segunda = pool.submit(segundo)
                    self.assertTrue(segundo_intenta.wait(10))
                    self.assertEqual(len(llamadas), 1)
                    self.assertEqual(b.recuperar_fragmentos(PREGUNTA)[0]["nombre"], DOCUMENTOS[0]["nombre"])
                finally:
                    seguir.set()
                primera.result(10)
                segunda.result(10)
            self.assertEqual(len(llamadas), 2)
            self.assertEqual(b.inicializar_indice().version, 3)


class TestCLI(unittest.TestCase):
    def test_diagnostico_real_del_evaluador_usa_api_coherente(self):
        # El antiguo bloque AST se sustituye por la entrada real de diagnóstico.
        import json
        from evaluacion.ejecutor import main_diagnostico, cargar_bateria
        from evaluacion.metricas import posiciones
        modelo = Mock()
        modelo.encode.side_effect = lambda textos: np.ones((len(textos), 2))
        with patch("evaluacion.ejecutor._modelo_local", return_value=modelo), patch("buscador_semantico.cargar_documentos", side_effect=AssertionError("No leer privados")), patch("requests.sessions.Session.request", side_effect=AssertionError("No HTTP")), patch("builtins.print") as mostrar:
            main_diagnostico(["--real", "--caso", "P03"])
            mostrar.assert_called_once()
            resultado = json.loads(mostrar.call_args.args[0])
        self.assertEqual(resultado["id"], "P03")
        self.assertEqual(resultado["estado"], "ok")
        self.assertEqual(len(resultado["fragmentos"]), 2)
        _, documentos, _ = cargar_bateria()
        corpus = {d["nombre"]: d["contenido"] for d in documentos}
        for fragmento in resultado["fragmentos"]:
            self.assertTrue(posiciones(corpus[fragmento["nombre"]], fragmento["contenido"]))

    def test_cli_vacia_no_genera(self):
        with buscador_aislado(documentos=[]) as b:
            with patch("builtins.input", side_effect=[PREGUNTA, "salir"]), patch.object(b, "generar_respuesta") as generar:
                b._ejecutar_cli()
                generar.assert_not_called()

    def test_cli_normal_usa_funciones_publicas(self):
        with buscador_aislado() as b:
            with patch("builtins.input", side_effect=[PREGUNTA, "salir"]), patch.object(b, "generar_respuesta", return_value="Respuesta ficticia") as generar:
                b._ejecutar_cli()
                generar.assert_called_once_with(PREGUNTA, [DOCUMENTOS[0]["contenido"]])

    def test_cli_captura_error_indice(self):
        with buscador_aislado() as b:
            with patch("builtins.input", side_effect=[PREGUNTA, "salir"]), patch.object(b, "recuperar_contexto", side_effect=b.ErrorIndice("Error ficticio")), patch("builtins.print") as mostrar:
                b._ejecutar_cli()
                self.assertTrue(any(c.args[0] == "ERROR:" for c in mostrar.call_args_list))

    def test_cli_captura_error_ollama(self):
        with buscador_aislado() as b:
            with patch("builtins.input", side_effect=[PREGUNTA, "salir"]), patch.object(b, "generar_respuesta", side_effect=b.ErrorOllama("Error ficticio")), patch("builtins.print") as mostrar:
                b._ejecutar_cli()
                self.assertTrue(any(c.args[0] == "ERROR:" for c in mostrar.call_args_list))
