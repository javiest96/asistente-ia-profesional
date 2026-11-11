from pathlib import Path
from pypdf import PdfReader
import configuracion
from documentos import leer_biblioteca

def cargar_documentos():

    carpeta = configuracion.carpeta_documentos(Path(__file__).resolve().parent)

    return leer_biblioteca(carpeta, lector_pdf=PdfReader)


if __name__ == "__main__":

    documentos = cargar_documentos()

    print(f"Total de documentos cargados: {len(documentos)}")

    for documento in documentos:
        print(f"Documento: {documento['nombre']}")
