import sys
import unittest
from copy import deepcopy
from types import ModuleType
from unittest.mock import patch

import numpy as np

from tests.soporte import (
    CasoBuscadorAislado, DOCUMENTOS, DOCUMENTO_NUEVO, PREGUNTA, buscador_aislado,
)


class TestBusquedaSemantica(CasoBuscadorAislado):
    def test_orden_y_limite_predeterminado(self):
        resultados = self.buscador.recuperar_fragmentos(PREGUNTA)
        self.assertEqual([r["nombre"] for r in resultados], [d["nombre"] for d in DOCUMENTOS[:2]])
        np.testing.assert_allclose([r["similitud"] for r in resultados], [1.0, 0.6])

    def test_limite_configurable(self):
        resultados = self.buscador.recuperar_fragmentos(PREGUNTA, limite=1)
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["nombre"], DOCUMENTOS[0]["nombre"])

    def test_ampliar_limite_y_bajar_umbral(self):
        resultados = self.buscador.recuperar_fragmentos(PREGUNTA, limite=3, umbral=0)
        self.assertEqual([r["nombre"] for r in resultados], [d["nombre"] for d in DOCUMENTOS])

    def test_incluye_umbral_exacto_y_excluye_inferiores(self):
        resultados = self.buscador.recuperar_fragmentos(PREGUNTA, umbral=1.0)
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["similitud"], 1.0)

    def test_umbral_intermedio(self):
        resultados = self.buscador.recuperar_fragmentos(PREGUNTA, umbral=0.7)
        self.assertEqual([r["nombre"] for r in resultados], [DOCUMENTOS[0]["nombre"]])

    def test_sin_coincidencias(self):
        self.assertEqual(self.buscador.recuperar_fragmentos("consulta sin coincidencias"), [])

    def test_limite_cero(self):
        self.assertEqual(self.buscador.recuperar_fragmentos(PREGUNTA, limite=0), [])

    def test_fuente_contenido_y_copia_independiente(self):
        original = [dict(f) for f in self.buscador.inicializar_indice().fragmentos]
        resultado = self.buscador.recuperar_fragmentos(PREGUNTA)[0]
        self.assertEqual(resultado["contenido"], DOCUMENTOS[0]["contenido"])
        self.assertEqual(resultado["nombre"], DOCUMENTOS[0]["nombre"])
        self.assertIsInstance(resultado["similitud"], float)
        resultado["contenido"] = "Texto alterado solo por el test"
        self.assertEqual([dict(f) for f in self.buscador.inicializar_indice().fragmentos], original)

    def test_actualizacion_sustituye_corpus_y_embeddings(self):
        self.buscador._cargador_prueba.side_effect = None
        self.buscador._cargador_prueba.return_value = [deepcopy(DOCUMENTO_NUEVO)]
        self.buscador.actualizar_indice()
        indice = self.buscador.inicializar_indice()
        self.assertEqual([dict(d) for d in indice.documentos_cargados], [DOCUMENTO_NUEVO])
        self.assertEqual(list(indice.documentos), [DOCUMENTO_NUEVO["contenido"]])
        self.assertEqual([dict(f) for f in indice.fragmentos], [DOCUMENTO_NUEVO])
        self.assertEqual([f["contenido"] for f in indice.fragmentos], [DOCUMENTO_NUEVO["contenido"]])
        np.testing.assert_array_equal(indice.embeddings_documentos, [[0, 1]])
        np.testing.assert_array_equal(indice.embeddings_fragmentos, [[0, 1]])
        resultado = self.buscador.recuperar_fragmentos("consulta piscina")
        self.assertEqual([r["nombre"] for r in resultado], [DOCUMENTO_NUEVO["nombre"]])

    def test_carga_solo_corpus_y_modelo_simulados(self):
        self.assertEqual([dict(d) for d in self.buscador.inicializar_indice().documentos_cargados], DOCUMENTOS)
        self.buscador._cargador_prueba.assert_called_once_with()
        self.buscador._fabrica_prueba.assert_called_once_with()
        self.assertEqual(self.buscador._modelo_prueba.encode.call_count, 2)

    def test_http_real_bloqueado(self):
        with self.assertRaisesRegex(AssertionError, "HTTP real prohibido"):
            self.buscador.generar_respuesta(PREGUNTA, [DOCUMENTOS[0]["contenido"]])


class TestAislamiento(unittest.TestCase):
    def test_importacion_y_actualizacion_vacias_sin_encode(self):
        with buscador_aislado(documentos=[]) as buscador:
            buscador._modelo_prueba.encode.assert_not_called()
            self.assertEqual(buscador.recuperar_fragmentos(PREGUNTA), [])
            self.assertEqual(buscador.recuperar_contexto(PREGUNTA), [])
            buscador.actualizar_indice()
            buscador._modelo_prueba.encode.assert_not_called()
            self.assertEqual(buscador.recuperar_fragmentos(PREGUNTA), [])

    def test_documentos_sin_texto_no_generan_fragmentos(self):
        with buscador_aislado(documentos=[{"nombre": "vacio.txt", "contenido": ""}]) as buscador:
            self.assertEqual(buscador.recuperar_fragmentos(PREGUNTA), [])

    def test_transicion_indice_con_datos_a_vacio_y_vuelta(self):
        with buscador_aislado() as buscador:
            buscador._cargador_prueba.side_effect = None
            buscador._cargador_prueba.return_value = []
            buscador.actualizar_indice()
            self.assertEqual(buscador.recuperar_fragmentos(PREGUNTA), [])
            self.assertEqual(buscador.recuperar_contexto(PREGUNTA), [])
            buscador._cargador_prueba.return_value = deepcopy(DOCUMENTOS)
            buscador.actualizar_indice()
            self.assertEqual(buscador.recuperar_fragmentos(PREGUNTA)[0]["nombre"], DOCUMENTOS[0]["nombre"])

    def test_restaura_modulos_y_no_comparte_indice(self):
        originales = {nombre: ModuleType(nombre) for nombre in ("sentence_transformers", "cargar_documentos")}
        with patch.dict(sys.modules, originales):
            with buscador_aislado() as primero:
                primero._cargador_prueba.side_effect = None
                primero._cargador_prueba.return_value = []
                primero.actualizar_indice()
            for nombre, modulo in originales.items():
                self.assertIs(sys.modules[nombre], modulo)
            with buscador_aislado() as segundo:
                self.assertEqual([dict(f) for f in segundo.inicializar_indice().fragmentos], DOCUMENTOS)
                self.assertIsNot(primero, segundo)

    def test_restaura_http_y_modulos_tras_excepcion(self):
        import requests
        request_original = requests.sessions.Session.request
        originales = {nombre: sys.modules.get(nombre) for nombre in ("sentence_transformers", "cargar_documentos")}
        with self.assertRaisesRegex(RuntimeError, "fallo ficticio"):
            with buscador_aislado():
                raise RuntimeError("fallo ficticio")
        self.assertIs(requests.sessions.Session.request, request_original)
        for nombre, modulo in originales.items():
            self.assertIs(sys.modules.get(nombre), modulo)


if __name__ == "__main__":
    unittest.main()
