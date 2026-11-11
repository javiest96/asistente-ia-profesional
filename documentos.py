"""Entrada documental acotada, para una biblioteca local y un solo proceso."""
from io import BytesIO
import logging
import os
from pathlib import Path
import tempfile
from threading import RLock
import unicodedata

import configuracion

_biblioteca = RLock()
logger = logging.getLogger("rag")


class ErrorDocumento(ValueError):
    """Mensaje público sin nombres, rutas ni contenido del documento."""


def validar_nombre(nombre):
    if (not isinstance(nombre, str) or not nombre or len(nombre) > 150
            or nombre != nombre.strip() or nombre.startswith(".")
            or any(c in nombre for c in '/\\:<>"|?*')
            or any(unicodedata.category(c).startswith("C") for c in nombre)
            or nombre.endswith((".", " "))):
        raise ErrorDocumento("Nombre de archivo no válido. Usa un nombre sencillo sin rutas.")
    reservado = nombre.split(".", 1)[0].rstrip(" .").upper()
    if reservado in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ErrorDocumento("El nombre de archivo está reservado por el sistema.")
    if Path(nombre).suffix.lower() not in (".txt", ".pdf"):
        raise ErrorDocumento("Solo se admiten documentos TXT y PDF.")
    return nombre


def _texto_valido(texto, permitir_vacio=False):
    if len(texto) > configuracion.MAX_CARACTERES_DOCUMENTO:
        raise ErrorDocumento("El contenido extraído supera el límite de caracteres permitido.")
    if "\x00" in texto:
        raise ErrorDocumento("El documento contiene datos binarios no admitidos.")
    if not permitir_vacio and not texto.strip():
        raise ErrorDocumento("El documento no contiene texto extraíble. Para PDF escaneados se necesita OCR.")
    return texto


def _extraer_pdf(origen, lector_pdf=None, permitir_vacio=False):
    try:
        if lector_pdf is None:
            from pypdf import PdfReader
            lector_pdf = PdfReader
        lector = lector_pdf(origen)
        if lector.is_encrypted is True:
            raise ErrorDocumento("No se admiten PDF cifrados o protegidos con contraseña.")
        if len(lector.pages) > configuracion.MAX_PAGINAS_PDF:
            raise ErrorDocumento("El PDF supera el límite de páginas permitido.")
        paginas = []
        total = 0
        for pagina in lector.pages:
            texto = pagina.extract_text() or ""
            total += len(texto) + bool(paginas)
            if total > configuracion.MAX_CARACTERES_DOCUMENTO:
                raise ErrorDocumento("El contenido extraído supera el límite de caracteres permitido.")
            paginas.append(texto)
        return _texto_valido("\n".join(paginas).strip(), permitir_vacio)
    except ErrorDocumento:
        raise
    except Exception:
        raise ErrorDocumento("No se pudo leer el PDF. Comprueba que sea válido y no esté dañado.") from None


def validar_documento(nombre, datos):
    """Valida una subida sin crear carpetas ni guardar bytes en la biblioteca."""
    validar_nombre(nombre)
    if not isinstance(datos, bytes) or not datos:
        raise ErrorDocumento("El archivo está vacío o no tiene un formato válido.")
    if len(datos) > configuracion.MAX_ARCHIVO_BYTES:
        raise ErrorDocumento("El archivo supera el tamaño máximo permitido.")
    if Path(nombre).suffix.lower() == ".pdf":
        if not datos.startswith(b"%PDF-"):
            raise ErrorDocumento("El archivo no tiene una cabecera PDF válida.")
        return _extraer_pdf(BytesIO(datos))
    try:
        texto = datos.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise ErrorDocumento("El TXT debe estar codificado en UTF-8.") from None
    return _texto_valido(texto)


def _comprobar_carpeta(carpeta):
    if carpeta.is_symlink() or carpeta.is_junction():
        raise ErrorDocumento("La carpeta de documentos no puede ser un enlace.")
    if carpeta.exists() and not carpeta.is_dir():
        raise ErrorDocumento("La carpeta de documentos no es válida.")


def _archivos(carpeta):
    _comprobar_carpeta(carpeta)
    if not carpeta.exists():
        return []
    archivos = sorted((p for p in carpeta.iterdir() if p.suffix.lower() in (".txt", ".pdf")),
                      key=lambda p: (p.suffix.lower() != ".txt", p.name.casefold()))
    if len(archivos) > configuracion.MAX_DOCUMENTOS:
        raise ErrorDocumento("La biblioteca supera el límite de documentos permitido.")
    return archivos


def _ruta_segura(carpeta, nombre):
    validar_nombre(nombre)
    destino = carpeta / nombre
    if (destino.is_symlink() or destino.is_junction()
            or destino.resolve().parent != carpeta.resolve()):
        raise ErrorDocumento("El documento debe permanecer dentro de la biblioteca, sin enlaces.")
    return destino


def guardar_documento(nombre, datos, carpeta=None):
    """Publicación completa sin sobrescritura; elimina solo el temporal propio.

    os.link falla si ya existe el destino. No se usa replace ni se borran documentos.
    Requiere un sistema local con enlaces duros (NTFS/ext4); no hay fallback inseguro.
    """
    validar_documento(nombre, datos)
    carpeta = Path(carpeta) if carpeta is not None else configuracion.carpeta_documentos()
    temporal = None
    try:
        with _biblioteca:
            archivos = _archivos(carpeta)
            destino = _ruta_segura(carpeta, nombre)
            if destino.exists() or nombre.casefold() in {p.name.casefold() for p in archivos}:
                raise ErrorDocumento("Ya existe un documento con ese nombre.")
            if len(archivos) >= configuracion.MAX_DOCUMENTOS:
                raise ErrorDocumento("Se ha alcanzado el límite de documentos de la biblioteca.")
            carpeta.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=carpeta, prefix=".rag-", suffix=".part", delete=False) as archivo:
                temporal = Path(archivo.name)
                archivo.write(datos)
                archivo.flush()
                os.fsync(archivo.fileno())
            try:
                os.link(temporal, destino)
            except FileExistsError:
                raise ErrorDocumento("Ya existe un documento con ese nombre.") from None
            logger.info("documento_guardado")
            return destino
    except OSError:
        logger.warning("documento_guardado_error")
        raise ErrorDocumento("No se pudo guardar el documento. Comprueba permisos, espacio y sistema de archivos.") from None
    finally:
        if temporal is not None:
            try:
                temporal.unlink(missing_ok=True)
            except OSError:
                # Puede quedar un .part; nunca se indexa ni se muestra su ruta.
                logger.warning("documento_temporal_limpieza_error")


def leer_biblioteca(carpeta, lector_pdf=None):
    """Lee un conjunto acotado; cualquier error conserva el índice anterior.

    PDF existentes sin texto siguen omitiéndose como antes. Las nuevas subidas
    sin texto se rechazan antes de publicarse.
    """
    carpeta = Path(carpeta)
    try:
        with _biblioteca:
            documentos = []
            for archivo in _archivos(carpeta):
                _ruta_segura(carpeta, archivo.name)
                if not archivo.is_file() or archivo.stat().st_size > configuracion.MAX_ARCHIVO_BYTES:
                    raise ErrorDocumento("Un documento no es un archivo válido o supera el tamaño permitido.")
                if archivo.suffix.lower() == ".pdf":
                    contenido = _extraer_pdf(archivo, lector_pdf, permitir_vacio=True)
                    if not contenido:
                        logger.warning("documento_sin_texto_omitido")
                        continue
                else:
                    with archivo.open("rb") as f:
                        datos = f.read(configuracion.MAX_ARCHIVO_BYTES + 1)
                    if len(datos) > configuracion.MAX_ARCHIVO_BYTES:
                        raise ErrorDocumento("El archivo supera el tamaño máximo permitido.")
                    try:
                        contenido = _texto_valido(datos.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"), permitir_vacio=True)
                    except UnicodeDecodeError:
                        raise ErrorDocumento("Un TXT de la biblioteca no está codificado en UTF-8.") from None
                documentos.append({"nombre": archivo.name, "contenido": contenido})
            return documentos
    except OSError:
        raise ErrorDocumento("No se pudo leer la biblioteca. Comprueba los permisos de almacenamiento.") from None
