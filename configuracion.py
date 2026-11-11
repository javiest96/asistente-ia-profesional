"""Configuración de arranque. No lee .env ni crea carpetas o conexiones."""
import os
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent


def _texto(nombre, defecto):
    valor = os.environ.get(nombre, defecto).strip()
    if not valor or any(ord(c) < 32 for c in valor):
        raise ValueError(f"Configuración inválida: {nombre}")
    return valor


def _entero(nombre, defecto, maximo):
    try:
        valor = int(_texto(nombre, str(defecto)))
    except ValueError:
        raise ValueError(f"{nombre} debe ser un entero positivo") from None
    if not 1 <= valor <= maximo:
        raise ValueError(f"{nombre} debe estar entre 1 y {maximo}")
    return valor


def _booleano(nombre, defecto=False):
    valor = _texto(nombre, str(defecto)).lower()
    if valor not in ("true", "false", "1", "0"):
        raise ValueError(f"{nombre} debe ser true o false")
    return valor in ("true", "1")


MODELO_LLM = _texto("RAG_MODELO_LLM", "qwen3.5:4b")
MODELO_EMBEDDINGS = _texto("RAG_MODELO_EMBEDDINGS", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
URL_OLLAMA = _texto("RAG_URL_OLLAMA", "http://127.0.0.1:11434/api/generate")
try:
    _url = urlsplit(URL_OLLAMA)
    if (_url.scheme not in ("http", "https") or not _url.hostname or _url.username is not None
            or _url.password is not None or _url.query or _url.fragment or _url.path != "/api/generate"):
        raise ValueError
    _url.port
except ValueError:
    raise ValueError("RAG_URL_OLLAMA debe ser una URL HTTP(S) sin credenciales y con ruta /api/generate") from None

# Una ruta relativa configurada se resuelve desde el proyecto, nunca desde cwd.
_ruta_documentos = os.environ.get("RAG_DOCUMENTOS_DIR")
if _ruta_documentos is not None:
    _ruta_documentos = Path(_texto("RAG_DOCUMENTOS_DIR", "Documentos")).expanduser()
    if not _ruta_documentos.is_absolute():
        _ruta_documentos = RAIZ / _ruta_documentos
    _ruta_documentos = _ruta_documentos.resolve()


def carpeta_documentos(base=None):
    """Una misma ruta para lector e interfaz; base permite ejecutar copias aisladas."""
    return _ruta_documentos if _ruta_documentos is not None else Path(base or RAIZ).resolve() / "Documentos"


OLLAMA_TIMEOUT_S = _entero("RAG_OLLAMA_TIMEOUT_S", 120, 600)
MAX_ARCHIVO_MB = _entero("RAG_MAX_ARCHIVO_MB", 10, 100)
MAX_ARCHIVO_BYTES = MAX_ARCHIVO_MB * 1024 * 1024
MAX_PAGINAS_PDF = _entero("RAG_MAX_PAGINAS_PDF", 100, 1000)
MAX_CARACTERES_DOCUMENTO = _entero("RAG_MAX_CARACTERES_DOCUMENTO", 200_000, 2_000_000)
MAX_DOCUMENTOS = _entero("RAG_MAX_DOCUMENTOS", 50, 500)
MAX_PREGUNTA_CARACTERES = _entero("RAG_MAX_PREGUNTA_CARACTERES", 2000, 10_000)
MAX_GENERACIONES = _entero("RAG_MAX_GENERACIONES", 1, 4)
PERMITIR_SUBIDAS = _booleano("RAG_PERMITIR_SUBIDAS")
LOG_LEVEL = _texto("RAG_LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    raise ValueError("RAG_LOG_LEVEL inválido")
