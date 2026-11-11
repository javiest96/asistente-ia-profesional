"""Demo local de corpus fijo. Solo biblioteca temporal; nunca instala o descarga."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

CORPUS = ("centro.txt", "taller.txt", "exposicion.txt")
RAIZ = Path(__file__).resolve().parents[1]


class ErrorDemo(RuntimeError):
    pass


def sha256(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def comprobar_puerto(puerto):
    if type(puerto) is not int or not 1024 <= puerto <= 65535:
        raise ErrorDemo("El puerto debe estar entre 1024 y 65535.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", puerto))
    except OSError:
        raise ErrorDemo("El puerto está ocupado o no está disponible. Elige otro con -Puerto.") from None


def preparar_demo(repo, puerto):
    comprobar_puerto(puerto)
    corpus = repo / "demo" / "corpus"
    if (corpus.is_symlink() or corpus.is_junction()
            or corpus.parent.is_symlink() or corpus.parent.is_junction()
            or {p.name for p in corpus.iterdir()} != set(CORPUS)):
        raise ErrorDemo("El corpus debe contener exclusivamente los tres TXT ficticios previstos, sin enlaces.")
    documentos = {}
    for nombre in CORPUS:
        ruta = corpus / nombre
        if (ruta.is_symlink() or ruta.is_junction() or not ruta.is_file()
                or ruta.resolve().parent != corpus.resolve() or not 0 < ruta.stat().st_size <= 65536):
            raise ErrorDemo("El corpus de demostración no es válido.")
        texto = ruta.read_text(encoding="utf-8")
        if not texto.strip() or "\x00" in texto:
            raise ErrorDemo("El corpus debe ser TXT UTF-8 con contenido.")
        documentos[nombre] = {"sha256": sha256(ruta), "bytes": ruta.stat().st_size}
    trabajo = Path(tempfile.mkdtemp(prefix="rag-demo-h8-"))
    biblioteca = trabajo / "biblioteca"
    biblioteca.mkdir()
    for nombre, datos in documentos.items():
        ruta = biblioteca / nombre
        with ruta.open("xb") as f:
            f.write((corpus / nombre).read_bytes())
        if sha256(ruta) != datos["sha256"] or sha256(corpus / nombre) != datos["sha256"]:
            raise ErrorDemo("El corpus cambió durante la preparación; no se arrancará la demo.")
    manifiesto = {"tipo": "demo_h8_ficticia", "documentos": documentos,
                  "host": "127.0.0.1", "puerto": puerto, "subidas": False,
                  "prompt_produccion": "A", "descargas_modelos": False}
    with (trabajo / "demo.json").open("x", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=True, indent=2)
        f.write("\n")
    return biblioteca


def entorno_demo(biblioteca):
    # No heredar rutas privadas, modelos alternativos, endpoints remotos ni
    # parámetros Streamlit del terminal del operador. Solo cambia el hijo.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("RAG_", "STREAMLIT_", "PYTHON"))
           and k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "HF_TOKEN", "HF_API_TOKEN")}
    env.update(RAG_DOCUMENTOS_DIR=str(biblioteca), RAG_PERMITIR_SUBIDAS="false",
               RAG_MODELO_LLM="qwen3.5:4b", RAG_MODELO_EMBEDDINGS="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
               RAG_URL_OLLAMA="http://127.0.0.1:11434/api/generate", RAG_LOG_LEVEL="INFO",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               NO_PROXY="127.0.0.1,localhost,::1", no_proxy="127.0.0.1,localhost,::1")
    return env


def comando_demo(python, puerto):
    return [str(python), "-I", "-B", "-m", "streamlit", "run", "app.py",
            "--server.address=127.0.0.1", f"--server.port={puerto}", "--server.headless=true",
            "--server.enableCORS=true", "--server.enableXsrfProtection=true",
            "--server.enableStaticServing=false", "--server.enableAgentApi=false",
            "--server.fileWatcherType=none", "--client.showErrorDetails=none",
            "--browser.gatherUsageStats=false"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", type=int, default=8501)
    parser.add_argument("--preparar", action="store_true", help="Solo copiar corpus y mostrar plan; no iniciar Streamlit")
    args = parser.parse_args(argv)
    try:
        python = RAIZ / ".venv" / "Scripts" / "python.exe"
        if (Path(sys.prefix).resolve() != (RAIZ / ".venv").resolve()
                or sys.prefix == sys.base_prefix or not python.is_file()):
            raise ErrorDemo("Usa scripts/iniciar_demo.ps1 con la .venv original del proyecto.")
        biblioteca = preparar_demo(RAIZ, args.puerto)
        print("Biblioteca ficticia: " + str(biblioteca), flush=True)
        print(f"URL local prevista: http://127.0.0.1:{args.puerto}", flush=True)
        print("Subidas desactivadas. Modelos solo desde caché; Ollama debe estar preparado aparte.", flush=True)
        if args.preparar:
            print("Preparación terminada; no se ha iniciado Streamlit ni cargado modelos.")
            return 0
        print("Ctrl+C detiene la demo. La biblioteca temporal se conserva.", flush=True)
        # No pasar por un shell ni iniciar el servidor en segundo plano.
        return subprocess.call(comando_demo(python, args.puerto), cwd=RAIZ, env=entorno_demo(biblioteca))
    except ErrorDemo as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("No se pudo preparar o ejecutar la demo. Revisa permisos, corpus y entorno original.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Demo detenida. No se han borrado bibliotecas ni detenido Ollama.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
