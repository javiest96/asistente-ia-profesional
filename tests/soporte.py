"""Aislamiento de los efectos de importación del RAG sin tocar producción."""
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
import importlib.util
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
PREGUNTA = "¿Cuándo juega el Club Cometa?"
DOCUMENTOS = [
    {"nombre": "club_ficticio.txt", "contenido": "El Club Cometa juega los sábados a las diez."},
    {"nombre": "biblioteca_ficticia.pdf", "contenido": "La biblioteca del pueblo abre los lunes."},
    {"nombre": "nota_ficticia.txt", "contenido": "Una nota ficticia sobre minerales."},
]
DOCUMENTO_NUEVO = {"nombre": "nuevo_ficticio.txt", "contenido": "La piscina ficticia abre los viernes."}


def crear_modelo():
    # Oráculo numérico: no simula la calidad semántica de un modelo.
    vectores = {
        DOCUMENTOS[0]["contenido"]: [1.0, 0.0],
        DOCUMENTOS[1]["contenido"]: [3.0, 4.0],
        DOCUMENTOS[2]["contenido"]: [0.0, 1.0],
        DOCUMENTO_NUEVO["contenido"]: [0.0, 1.0],
        PREGUNTA: [1.0, 0.0],
        "consulta sin coincidencias": [-1.0, 0.0],
        "consulta piscina": [0.0, 1.0],
    }
    modelo = Mock(name="modelo_embeddings_ficticio")

    def encode(textos):
        # Un texto imprevisto falla; no se inventan vectores por defecto.
        return np.asarray([vectores[texto] for texto in textos], dtype=float).reshape(-1, 2)

    modelo.encode.side_effect = encode
    return modelo


@contextmanager
def sustituir_modulos(modulos):
    # patch.dict(sys.modules) restaura el diccionario entero y puede descargar
    # extensiones nativas importadas durante el test. Restauramos solo las claves
    # sustituidas, dejando intactos los imports normales de numpy/scipy/sklearn.
    ausente = object()
    originales = {nombre: sys.modules.get(nombre, ausente) for nombre in modulos}
    sys.modules.update(modulos)
    try:
        yield
    finally:
        for nombre, original in originales.items():
            if original is ausente:
                sys.modules.pop(nombre, None)
            else:
                sys.modules[nombre] = original


@contextmanager
def buscador_aislado(documentos=None, bloquear_sockets=True, inicializar=True):
    """Ejecuta código real en un módulo nuevo con carga y modelo simulados."""
    sentence_transformers = ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = Mock(return_value=crear_modelo())
    cargador = ModuleType("cargar_documentos")
    corpus = DOCUMENTOS if documentos is None else documentos
    cargador.cargar_documentos = Mock(side_effect=lambda: deepcopy(corpus))
    with ExitStack() as stack:
        if bloquear_sockets:
            stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Red prohibida en tests")))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP real prohibido")))
        stack.enter_context(sustituir_modulos({
            "sentence_transformers": sentence_transformers,
            "cargar_documentos": cargador,
        }))
        stack.enter_context(redirect_stdout(StringIO()))
        spec = importlib.util.spec_from_file_location("_rag_bajo_prueba", RAIZ / "buscador_semantico.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo._modelo_prueba = sentence_transformers.SentenceTransformer.return_value
        modulo._fabrica_prueba = sentence_transformers.SentenceTransformer
        modulo._cargador_prueba = cargador.cargar_documentos
        modulo._motor = modulo.MotorRAG(cargador=modulo._cargador_prueba,
                                       fabrica_modelo=modulo._fabrica_prueba)
        if inicializar:
            modulo.inicializar_indice()
        yield modulo


class CasoBuscadorAislado(unittest.TestCase):
    def setUp(self):
        self.buscador = self.enterContext(buscador_aislado())
