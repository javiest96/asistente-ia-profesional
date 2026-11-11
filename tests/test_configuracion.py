"""Configuración aislada del entorno del operador, sin modelos ni archivos privados."""
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[1]


def cargar_configuracion(variables=None):
    spec = importlib.util.spec_from_file_location("_config_prueba", RAIZ / "configuracion.py")
    modulo = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, variables or {}, clear=True):
        spec.loader.exec_module(modulo)
    return modulo


class TestConfiguracion(unittest.TestCase):
    def test_defectos_seguros_y_modelos_actuales(self):
        c = cargar_configuracion()
        self.assertFalse(c.PERMITIR_SUBIDAS)
        self.assertEqual(c.MODELO_LLM, "qwen3.5:4b")
        self.assertEqual(c.MODELO_EMBEDDINGS, "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self.assertEqual(c.URL_OLLAMA, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(c.MAX_GENERACIONES, 1)

    def test_ruta_explicita_compartida_y_sin_creacion(self):
        with TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "biblioteca"
            c = cargar_configuracion({"RAG_DOCUMENTOS_DIR": str(ruta)})
            self.assertEqual(c.carpeta_documentos(), ruta)
            self.assertEqual(c.carpeta_documentos(Path(tmp) / "otra_base"), ruta)
            self.assertFalse(ruta.exists())

    def test_ruta_relativa_desde_proyecto_no_cwd(self):
        c = cargar_configuracion({"RAG_DOCUMENTOS_DIR": "corpus_demo"})
        self.assertEqual(c.carpeta_documentos(), RAIZ / "corpus_demo")

    def test_valores_invalidos_no_revelan_su_contenido(self):
        for variable, valor in (("RAG_MAX_ARCHIVO_MB", "secreto"), ("RAG_MAX_DOCUMENTOS", "0"),
                                ("RAG_MAX_GENERACIONES", "5"), ("RAG_PERMITIR_SUBIDAS", "si"),
                                ("RAG_LOG_LEVEL", "secreto"), ("RAG_MODELO_LLM", ""),
                                ("RAG_URL_OLLAMA", "http://usuario:secreto@localhost/api/generate"),
                                ("RAG_URL_OLLAMA", "http://@localhost/api/generate"),
                                ("RAG_URL_OLLAMA", "file:///api/generate"),
                                ("RAG_URL_OLLAMA", "http://localhost:invalido/api/generate")):
            with self.subTest(variable=variable), self.assertRaises(ValueError) as error:
                cargar_configuracion({variable: valor})
            self.assertNotIn("secreto", str(error.exception))

    def test_sobrescribe_limites_y_booleanos(self):
        c = cargar_configuracion({"RAG_MAX_ARCHIVO_MB": "2", "RAG_PERMITIR_SUBIDAS": "true",
                                 "RAG_OLLAMA_TIMEOUT_S": "15"})
        self.assertEqual(c.MAX_ARCHIVO_BYTES, 2 * 1024 * 1024)
        self.assertTrue(c.PERMITIR_SUBIDAS)
        self.assertEqual(c.OLLAMA_TIMEOUT_S, 15)
