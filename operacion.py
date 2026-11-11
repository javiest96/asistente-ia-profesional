"""Límites de proceso y logs operativos sin contenido documental."""
from contextlib import contextmanager
import logging
from threading import BoundedSemaphore

import configuracion

logger = logging.getLogger("rag")
_generaciones = BoundedSemaphore(configuracion.MAX_GENERACIONES)


class ErrorConsulta(ValueError):
    """Entrada rechazada antes de búsqueda o generación."""


class ServicioOcupado(RuntimeError):
    pass


def configurar_logging():
    # Configura solo nuestro logger, no modifica handlers del host o de Streamlit.
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(configuracion.LOG_LEVEL)
    # pypdf puede incluir objetos del documento en sus advertencias internas.
    # El lector ya devuelve nuestro error saneado; no propagamos ese diagnóstico.
    pdf_logger = logging.getLogger("pypdf")
    if not any(isinstance(h, logging.NullHandler) for h in pdf_logger.handlers):
        pdf_logger.addHandler(logging.NullHandler())
    pdf_logger.propagate = False


def validar_pregunta(pregunta):
    if not isinstance(pregunta, str) or not pregunta.strip():
        raise ErrorConsulta("Escribe una pregunta con contenido.")
    if len(pregunta) > configuracion.MAX_PREGUNTA_CARACTERES:
        raise ErrorConsulta(f"La pregunta supera el límite de {configuracion.MAX_PREGUNTA_CARACTERES} caracteres.")


@contextmanager
def limitar_generacion():
    if not _generaciones.acquire(blocking=False):
        logger.warning("generacion_ocupada")
        raise ServicioOcupado("El asistente está ocupado. Espera a que termine la consulta actual.")
    try:
        yield
    finally:
        _generaciones.release()
