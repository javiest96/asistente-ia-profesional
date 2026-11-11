"""H8: orquestación estándar, sin imports de IA ni efectos al importar.

Preparar no crea un venv. Descargar y validar requieren autorizaciones distintas.
Los registros son propios y acotados: nunca guardan stdout/stderr de herramientas.
"""
import argparse
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.request
import zipfile

LOCK = "requirements-windows-py314.lock.txt"
MINIMO_LIBRE = 10 * 1024**3  # Umbral prudente estimado, no cálculo exacto.


class ErrorValidacion(RuntimeError):
    def __init__(self, codigo, retorno=None):
        self.codigo = codigo
        self.retorno = retorno
        super().__init__(codigo)


def sha256(ruta):
    h = hashlib.sha256()
    with Path(ruta).open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_nuevo(ruta, datos):
    with Path(ruta).open("x", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=True, indent=2, allow_nan=False)
        f.write("\n")


def comprobar_plataforma():
    if (platform.system() != "Windows" or sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 14)
            or platform.machine().lower() not in ("amd64", "x86_64")
            or sys.maxsize <= 2**32 or sysconfig.get_config_var("Py_GIL_DISABLED")
            or sys.prefix != sys.base_prefix):
        raise ErrorValidacion("requiere_python_base_windows_cpython_314_x64_convencional")
    return {"python": platform.python_version(), "arquitectura": "x64", "sistema": "Windows"}


def entorno_aislado(raiz):
    env = {k: v for k, v in os.environ.items()
           if k.upper() != "VIRTUAL_ENV" and not k.upper().startswith(("RAG_", "PYTHON", "PIP_", "HF_", "TRANSFORMERS_", "SENTENCE_TRANSFORMERS_", "STREAMLIT_"))}
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1",
               HF_HOME=str(raiz / "cache-modelos-vacia"), HF_HUB_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", TRANSFORMERS_OFFLINE="1",
               RAG_DOCUMENTOS_DIR=str(raiz / "biblioteca-vacia"), RAG_PERMITIR_SUBIDAS="false",
               RAG_URL_OLLAMA="http://127.0.0.1:1/api/generate", CUDA_VISIBLE_DEVICES="-1")
    return env


def entorno_tests(raiz):
    """La suite gestiona sus propias bibliotecas por test, no una ruta global.

    Mantener barreras de red/modelos, pero dejar que los fixtures basados en
    __file__ y los que parchean configuracion elijan sus carpetas aisladas.
    """
    env = entorno_aislado(raiz)
    env.pop("RAG_DOCUMENTOS_DIR", None)
    return env


def categoria_error(texto):
    # Solo categorías conocidas; nunca devuelve líneas originales de pip/tests.
    if "No matching distribution found" in texto or "Could not find a version" in texto:
        return "rueda_o_version_no_disponible"
    if "ResolutionImpossible" in texto or "conflicting dependencies" in texto:
        return "conflicto_dependencias"
    if "CERTIFICATE_VERIFY_FAILED" in texto:
        return "certificado_tls"
    if "timed out" in texto or "ConnectionError" in texto or "ProxyError" in texto:
        return "conexion_o_timeout"
    return "comando_fallido"


def ejecutar(args, *, cwd, env, timeout=120):
    try:
        r = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ErrorValidacion("timeout_comando") from None
    except OSError:
        raise ErrorValidacion("no_se_pudo_iniciar_comando") from None
    if r.returncode:
        raise ErrorValidacion(categoria_error(r.stdout + r.stderr), r.returncode)
    return r


def requisitos(texto):
    paquetes = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)", linea)
        if not m:
            raise ErrorValidacion("lock_debe_contener_solo_versiones_exactas")
        nombre = re.sub(r"[-_.]+", "-", m[1]).lower()
        if nombre in paquetes:
            raise ErrorValidacion("paquete_duplicado_en_lock")
        paquetes[nombre] = m[2]
    if not paquetes or "torch" not in paquetes or "pypdf" not in paquetes:
        raise ErrorValidacion("lock_incompleto")
    return paquetes


def comprobar_nombre_exportado(nombre):
    partes = PurePosixPath(nombre).parts
    if (not partes or PurePosixPath(nombre).is_absolute() or ".." in partes
            or "\\" in nombre or ":" in nombre
            or any(p.lower() in ("documentos", "informes", ".venv", "venv", ".git", "__pycache__") for p in partes)
            or any(p.lower().startswith(".env") and p != ".env.example" for p in partes)
            or partes[-1].lower() in ("secrets.toml",) or nombre.endswith((".pyc", ".part"))):
        # La batería ficticia H5 es la única excepción del nombre documentos.
        if nombre not in {"evaluacion/documentos/" + p for p in
                          ("club_cometa.txt", "club_faro.txt", "biblioteca_luna.txt", "normas_cometa.txt")}:
            raise ErrorValidacion("archivo_no_permitido_en_exportacion")


def extraer_archivo(archivo, destino):
    with zipfile.ZipFile(archivo) as z:
        for item in z.infolist():
            nombre = item.filename.rstrip("/")
            # El directorio padre de los cuatro TXT ficticios también es válido.
            if not (item.is_dir() and nombre == "evaluacion/documentos"):
                comprobar_nombre_exportado(nombre)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ErrorValidacion("enlaces_no_permitidos_en_exportacion")
        z.extractall(destino)


def preparar(repo, commit):
    plataforma = comprobar_plataforma()
    if importlib.util.find_spec("pip") is None:
        raise ErrorValidacion("pip_no_disponible_en_python_base")
    env = entorno_aislado(Path(tempfile.gettempdir()))
    r = ejecutar(["git", "rev-parse", "--verify", "--end-of-options", commit + "^{commit}"], cwd=repo, env=env)
    revision = r.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ErrorValidacion("commit_no_valido")
    # Revisar la lista antes de exportar: no copiar secretos/documentos ignorados.
    nombres = ejecutar(["git", "ls-tree", "-r", "--name-only", revision], cwd=repo, env=env).stdout.splitlines()
    for nombre in nombres:
        comprobar_nombre_exportado(nombre)
    raiz = Path(tempfile.mkdtemp(prefix="rag-h8-"))
    try:
        env = entorno_aislado(raiz)
        archivo = raiz / "codigo.zip"
        ejecutar(["git", "archive", "--format=zip", "--output", str(archivo), revision], cwd=repo, env=env)
        fuente = raiz / "codigo"
        fuente.mkdir()
        extraer_archivo(archivo, fuente)
        paquetes = requisitos((fuente / LOCK).read_text(encoding="utf-8"))
        datos = {"esquema": 1, "tipo": "h8_instalacion", "commit": revision,
                 "plataforma": plataforma, "codigo_zip_sha256": sha256(archivo),
                 "lock_sha256": sha256(fuente / LOCK), "paquetes": paquetes,
                 "orquestador_sha256": sha256(__file__),
                 "espacio_libre_gib": round(shutil.disk_usage(raiz).free / 1024**3, 2),
                 "estimacion": {"descarga_gib": "1-3", "venv_gib": "3-7", "libre_recomendado_gib": "10-20"},
                 "instalacion_realizada": False, "descargas_realizadas": False}
        escribir_nuevo(raiz / "preparacion.json", datos)
        return raiz
    except Exception:
        escribir_nuevo(raiz / "preparacion.error.json", {"estado": "error", "codigo": "preparacion_incompleta"})
        print("Preparacion incompleta conservada en: " + str(raiz), file=sys.stderr)
        raise


def cargar_preparacion(raiz):
    plataforma = comprobar_plataforma()
    raiz = Path(raiz).resolve(strict=True)
    if any(p.is_symlink() or p.is_junction() for p in (raiz / "codigo", raiz / "ruedas")):
        raise ErrorValidacion("carpetas_de_preparacion_no_deben_ser_enlaces")
    datos = json.loads((raiz / "preparacion.json").read_text(encoding="utf-8"))
    if (datos.get("tipo") != "h8_instalacion" or datos.get("esquema") != 1
            or datos.get("plataforma") != plataforma
            or datos.get("orquestador_sha256") != sha256(__file__)
            or datos.get("codigo_zip_sha256") != sha256(raiz / "codigo.zip")
            or datos.get("lock_sha256") != sha256(raiz / "codigo" / LOCK)):
        raise ErrorValidacion("preparacion_modificada_o_incompatible")
    # No validar código alterado después de la exportación.
    with zipfile.ZipFile(raiz / "codigo.zip") as z:
        esperados = {i.filename for i in z.infolist() if not i.is_dir()}
        actuales = {p.relative_to(raiz / "codigo").as_posix() for p in (raiz / "codigo").rglob("*") if p.is_file()}
        if actuales != esperados or any(p.is_symlink() or p.is_junction() for p in (raiz / "codigo").rglob("*")):
            raise ErrorValidacion("codigo_exportado_modificado")
        for item in z.infolist():
            if not item.is_dir():
                p = raiz / "codigo" / item.filename
                if p.is_symlink() or sha256(p) != hashlib.sha256(z.read(item)).hexdigest():
                    raise ErrorValidacion("codigo_exportado_modificado")
    if requisitos((raiz / "codigo" / LOCK).read_text(encoding="utf-8")) != datos["paquetes"]:
        raise ErrorValidacion("lock_modificado")
    return raiz, datos


def manifiesto_ruedas(carpeta, esperados):
    encontrados = {}
    for ruta in sorted(carpeta.iterdir()):
        if not ruta.is_file() or ruta.is_symlink() or ruta.suffix != ".whl":
            raise ErrorValidacion("solo_se_admiten_ruedas")
        with zipfile.ZipFile(ruta) as z:
            # Los metadatos vendorizados NO identifican la distribución principal.
            # Mantener la lista (no un set) detecta entradas ZIP duplicadas.
            metadatos = [n for n in z.namelist()
                         if n.count("/") == 1 and "\\" not in n
                         and n.endswith(".dist-info/METADATA")]
            if len(metadatos) != 1:
                raise ErrorValidacion("rueda_sin_metadatos_unicos")
            info = BytesParser().parsebytes(z.read(metadatos[0]))
            if len(info.get_all("Name", [])) != 1 or len(info.get_all("Version", [])) != 1:
                raise ErrorValidacion("metadatos_principales_invalidos")
        nombre = re.sub(r"[-_.]+", "-", info.get("Name", "")).lower()
        version = info.get("Version")
        directorio = metadatos[0].split("/")[0][:-len(".dist-info")]
        nombre_directorio, separador, version_directorio = directorio.rpartition("-")
        partes_rueda = ruta.name[:-len(".whl")].split("-")
        if (not separador or re.sub(r"[-_.]+", "-", nombre_directorio).lower() != nombre
                or version_directorio != version or len(partes_rueda) not in (5, 6)
                or re.sub(r"[-_.]+", "-", partes_rueda[0]).lower() != nombre
                or partes_rueda[1] != version):
            raise ErrorValidacion("estructura_de_distribucion_incompatible")
        if nombre in encontrados or esperados.get(nombre) != version:
            raise ErrorValidacion("ruedas_no_coinciden_con_lock")
        encontrados[nombre] = {"version": version, "archivo": ruta.name,
                               "sha256": sha256(ruta), "bytes": ruta.stat().st_size}
    if set(encontrados) != set(esperados):
        raise ErrorValidacion("faltan_ruedas_del_lock")
    return encontrados


def iniciar_fase(raiz, nombre):
    if (raiz / (nombre + ".json")).exists():
        raise ErrorValidacion("fase_ya_ejecutada_usar_otra_preparacion")
    escribir_nuevo(raiz / (nombre + ".inicio.json"), {"estado": "iniciada"})
    if shutil.disk_usage(raiz).free < MINIMO_LIBRE:
        raise ErrorValidacion("espacio_libre_inferior_a_10_gib")


def guardar_manifiestos(raiz, paquetes):
    escribir_nuevo(raiz / "ruedas.json", {"paquetes": paquetes})
    with (raiz / "requirements-hashed.txt").open("x", encoding="utf-8") as f:
        for nombre, p in sorted(paquetes.items()):
            f.write(f'{nombre}=={p["version"]} --hash=sha256:{p["sha256"]}\n')
    return {"estado": "ok", "ruedas": len(paquetes),
            "bytes": sum(p["bytes"] for p in paquetes.values()),
            "requirements_hashed_sha256": sha256(raiz / "requirements-hashed.txt")}


def comprobar_adquisicion_nueva(raiz):
    if any((raiz / p).exists() for p in (
            "ruedas", "ruedas.json", "requirements-hashed.txt", "descarga.json",
            "descarga.inicio.json", "recuperacion.json", "recuperacion.inicio.json")):
        raise ErrorValidacion("adquisicion_ya_iniciada_usar_preparacion_nueva")


def descargar(raiz, autorizado=False):
    if not autorizado:
        raise ErrorValidacion("descarga_no_autorizada")
    raiz, datos = cargar_preparacion(raiz)
    comprobar_adquisicion_nueva(raiz)
    iniciar_fase(raiz, "descarga")
    resultado = {"estado": "error"}
    try:
        ruedas = raiz / "ruedas"
        ruedas.mkdir()
        ejecutar([sys.executable, "-I", "-B", "-m", "pip", "download", "--only-binary=:all:",
                  "--no-cache-dir", "--index-url", "https://pypi.org/simple", "--dest", str(ruedas),
                  "-r", str(raiz / "codigo" / LOCK)], cwd=raiz, env=entorno_aislado(raiz), timeout=3600)
        paquetes = manifiesto_ruedas(ruedas, datos["paquetes"])
        # La instalación exigirá los hashes, no solo la presencia del manifiesto.
        resultado = guardar_manifiestos(raiz, paquetes)
    except ErrorValidacion as exc:
        resultado.update(codigo=exc.codigo, retorno=exc.retorno)
        raise
    finally:
        escribir_nuevo(raiz / "descarga.json", resultado)


def huellas_archivos(raiz):
    salida = {}
    for p in sorted(raiz.rglob("*")):
        if p.is_symlink() or p.is_junction():
            raise ErrorValidacion("origen_de_recuperacion_con_enlaces")
        if p.is_file():
            salida[p.relative_to(raiz).as_posix()] = sha256(p)
    return salida


def recuperar(raiz, origen=None, autorizado=False):
    """Adquisición offline en un destino nuevo; el origen nunca se ejecuta ni escribe.

    La preparación de destino debe tener la huella actual. La del origen es
    evidencia histórica de entrada, no una preparación compatible para ejecutar.
    """
    if not autorizado:
        raise ErrorValidacion("recuperacion_no_autorizada")
    raiz, datos = cargar_preparacion(raiz)
    if origen is None:
        raise ErrorValidacion("falta_preparacion_origen")
    origen = Path(origen)
    if origen.is_symlink() or origen.is_junction():
        raise ErrorValidacion("origen_de_recuperacion_con_enlaces")
    origen = origen.resolve(strict=True)
    if origen == raiz or origen in raiz.parents or raiz in origen.parents:
        raise ErrorValidacion("origen_y_destino_deben_ser_independientes")
    comprobar_adquisicion_nueva(raiz)
    antes = huellas_archivos(origen)
    anterior = json.loads((origen / "preparacion.json").read_text(encoding="utf-8"))
    fallo = json.loads((origen / "descarga.json").read_text(encoding="utf-8"))
    if (anterior.get("tipo") != "h8_instalacion" or anterior.get("esquema") != 1
            or not re.fullmatch(r"[0-9a-f]{40,64}", str(anterior.get("commit", "")))
            or anterior.get("commit") != datos.get("commit")
            or anterior.get("paquetes") != datos["paquetes"]
            or anterior.get("lock_sha256") != datos["lock_sha256"]
            or sha256(origen / "codigo" / LOCK) != datos["lock_sha256"]
            or anterior.get("codigo_zip_sha256") != sha256(origen / "codigo.zip")
            or fallo.get("estado") != "error" or fallo.get("codigo") != "rueda_sin_metadatos_unicos"):
        raise ErrorValidacion("origen_no_corresponde_a_recuperacion_esperada")
    paquetes = manifiesto_ruedas(origen / "ruedas", datos["paquetes"])
    iniciar_fase(raiz, "recuperacion")
    resultado = {"estado": "error", "tipo": "recuperacion_offline", "internet_utilizado": False,
                 "autenticidad_independiente_verificada": False,
                 "origen_directorio": origen.name, "origen_commit": anterior["commit"],
                 "orquestador_origen_sha256": anterior.get("orquestador_sha256"),
                 "orquestador_actual_sha256": sha256(__file__),
                 "archivos_origen_sha256": antes}
    try:
        destino = raiz / "ruedas"
        destino.mkdir()
        for p in paquetes.values():
            # Creación exclusiva, sin copiar atributos ni ejecutar la rueda.
            with (origen / "ruedas" / p["archivo"]).open("rb") as entrada, (destino / p["archivo"]).open("xb") as salida:
                shutil.copyfileobj(entrada, salida, length=1024 * 1024)
        copiados = manifiesto_ruedas(destino, datos["paquetes"])
        if copiados != paquetes or huellas_archivos(origen) != antes:
            raise ErrorValidacion("origen_o_copia_modificados_durante_recuperacion")
        resultado.update(guardar_manifiestos(raiz, copiados))
        resultado.update(integridad_local_verificada=True, origen_intacto=True)
    except ErrorValidacion as exc:
        resultado.update(codigo=exc.codigo, retorno=exc.retorno)
        raise
    except (OSError, ValueError, zipfile.BadZipFile):
        resultado.update(codigo="recuperacion_archivo_no_valido")
        raise ErrorValidacion("recuperacion_archivo_no_valido") from None
    finally:
        escribir_nuevo(raiz / "recuperacion.json", resultado)


SMOKE = """
import importlib,json,sys,platform
from pathlib import Path
from importlib.metadata import version
for nombre in ('numpy','sklearn','torch','transformers','sentence_transformers','streamlit','requests','pypdf'):
    importlib.import_module(nombre)
import torch
assert (torch.tensor([1.0],device='cpu')+1).item()==2
assert Path(sys.prefix).resolve()==Path(sys.argv[1]).resolve() and sys.prefix!=sys.base_prefix
esperados=json.loads(sys.argv[2])
assert all(version(n)==v for n,v in esperados.items())
print(json.dumps({'python':platform.python_version(),'torch':torch.__version__,'cuda_compilada':torch.version.cuda,'tensor_cpu':True,'versiones':{n:version(n) for n in esperados},'pip':version('pip')}))
"""


def comprobar_streamlit(python, raiz):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    env = entorno_aislado(raiz)
    args = [str(python), "-I", "-B", "-m", "streamlit", "run", "app.py",
            "--server.address=127.0.0.1", f"--server.port={puerto}", "--server.headless=true",
            "--server.fileWatcherType=none", "--server.enableAgentApi=true"]
    proc = subprocess.Popen(args, cwd=raiz / "codigo", env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    base = f"http://127.0.0.1:{puerto}"
    def solicitud(ruta, datos=None):
        req = urllib.request.Request(base + ruta, data=None if datos is None else json.dumps(datos).encode(),
                                     headers={"Content-Type": "application/json"})
        # No pasar loopback por un proxy del operador.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10) as r:
            return r.read()
    try:
        for _ in range(80):
            if proc.poll() is not None:
                raise ErrorValidacion("streamlit_termino_antes_de_arrancar")
            try:
                if solicitud("/_stcore/health") == b"ok":
                    break
            except OSError:
                pass
            time.sleep(.25)
        else:
            raise ErrorValidacion("streamlit_no_disponible")
        solicitud("/_stcore/agent/openapi.json")
        primera = json.loads(solicitud("/_stcore/agent/interact", {}))
        if primera.get("status") != "ready":
            raise ErrorValidacion("streamlit_interfaz_no_disponible")
        actualizar = next(a["key"] for a in primera["actions"] if "Actualizar" in a.get("label", ""))
        segunda = json.loads(solicitud("/_stcore/agent/interact", {
            "session_id": primera["session_id"], "trigger": {"key": actualizar}}))
        if segunda.get("status") != "ready" or "Biblioteca actualizada correctamente." not in json.dumps(segunda, ensure_ascii=False):
            raise ErrorValidacion("streamlit_actualizacion_vacia_fallida")
        return {"estado": "ok", "loopback": True, "biblioteca_vacia": True, "inferencia": False}
    finally:
        if proc.poll() is None:
            proc.terminate()  # Solo el proceso que este procedimiento ha iniciado.
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def validar(raiz, autorizado=False):
    if not autorizado:
        raise ErrorValidacion("instalacion_no_autorizada")
    raiz, datos = cargar_preparacion(raiz)
    registros = [p for p in (raiz / "descarga.json", raiz / "recuperacion.json") if p.is_file()]
    if len(registros) != 1:
        raise ErrorValidacion("requiere_una_adquisicion_verificada_unica")
    descarga = json.loads(registros[0].read_text(encoding="utf-8"))
    ruedas = manifiesto_ruedas(raiz / "ruedas", datos["paquetes"])
    if (descarga.get("estado") != "ok" or ruedas != json.loads((raiz / "ruedas.json").read_text())["paquetes"]
            or sha256(raiz / "requirements-hashed.txt") != descarga.get("requirements_hashed_sha256")):
        raise ErrorValidacion("descarga_incompleta_o_modificada")
    iniciar_fase(raiz, "validacion")
    resultado = {"estado": "error", "comprobaciones": {}}
    fase = "crear_venv"
    try:
        venv = raiz / ".venv"
        if venv.exists():
            raise ErrorValidacion("venv_destino_ya_existe")
        if venv.is_symlink() or venv.is_junction():
            raise ErrorValidacion("venv_destino_ya_existe")
        biblioteca = raiz / "biblioteca-vacia"
        if biblioteca.exists() and (not biblioteca.is_dir() or any(biblioteca.iterdir())):
            raise ErrorValidacion("biblioteca_de_prueba_no_vacia")
        env = entorno_aislado(raiz)
        ejecutar([sys.executable, "-I", "-B", "-m", "venv", str(venv)], cwd=raiz, env=env)
        python = venv / "Scripts" / "python.exe"
        fase = "instalar"
        ejecutar([str(python), "-I", "-B", "-m", "pip", "install", "--no-index", "--no-cache-dir",
                  "--only-binary=:all:", "--no-deps", "--require-hashes", "--find-links", str(raiz / "ruedas"),
                  "-r", str(raiz / "requirements-hashed.txt")], cwd=raiz, env=env, timeout=1800)
        fase = "pip_check"
        ejecutar([str(python), "-I", "-B", "-m", "pip", "check"], cwd=raiz, env=env)
        resultado["comprobaciones"][fase] = "ok"
        fase = "imports_y_cpu"
        r = ejecutar([str(python), "-I", "-B", "-c", SMOKE, str(venv), json.dumps(datos["paquetes"])], cwd=raiz, env=env)
        resultado["comprobaciones"][fase] = json.loads(r.stdout)
        fase = "tests"
        r = ejecutar([str(python), "-I", "-B", "-m", "unittest", "discover", "-s", str(raiz / "codigo"),
                      "-t", str(raiz / "codigo"), "-p", "test_*.py", "-q"], cwd=raiz, env=entorno_tests(raiz), timeout=600)
        cantidad = re.search(r"Ran (\d+) tests?", r.stderr + r.stdout)
        if cantidad is None or int(cantidad[1]) < 179:
            raise ErrorValidacion("tests_incompletos")
        resultado["comprobaciones"][fase] = {"estado": "ok", "cantidad": int(cantidad[1])}
        fase = "streamlit_vacio"
        resultado["comprobaciones"][fase] = comprobar_streamlit(python, raiz)
        resultado["estado"] = "ok"
    except ErrorValidacion as exc:
        resultado.update(fase_error=fase, codigo=exc.codigo, retorno=exc.retorno)
        raise
    finally:
        escribir_nuevo(raiz / "validacion.json", resultado)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--modo", choices=("preparar", "descargar", "recuperar", "validar"), default="preparar")
    p.add_argument("--repositorio", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--directorio", type=Path)
    p.add_argument("--autorizar-descargas", action="store_true")
    p.add_argument("--autorizar-instalacion", action="store_true")
    p.add_argument("--origen", type=Path)
    p.add_argument("--autorizar-recuperacion", action="store_true")
    args = p.parse_args(argv)
    try:
        if ((args.autorizar_descargas and args.modo != "descargar")
                or (args.autorizar_instalacion and args.modo != "validar")
                or (args.autorizar_recuperacion and args.modo != "recuperar")
                or (args.origen is not None and args.modo != "recuperar")):
            raise ErrorValidacion("autorizacion_no_corresponde_al_modo")
        if args.modo == "preparar":
            if args.directorio:
                raise ErrorValidacion("preparar_crea_directorio_temporal_nuevo")
            raiz = preparar(args.repositorio, args.commit)
        else:
            if args.directorio is None:
                raise ErrorValidacion("falta_directorio_de_preparacion")
            raiz = args.directorio
            if args.modo == "descargar":
                descargar(raiz, args.autorizar_descargas)
            elif args.modo == "recuperar":
                recuperar(raiz, args.origen, args.autorizar_recuperacion)
            else:
                validar(raiz, args.autorizar_instalacion)
        print(json.dumps({"modo": args.modo, "estado": "ok", "directorio_trabajo": str(raiz)}, ensure_ascii=True))
        return 0
    except ErrorValidacion as exc:
        print(json.dumps({"estado": "error", "codigo": exc.codigo, "retorno": exc.retorno}), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile):
        print('{"estado":"error","codigo":"archivo_o_resultado_no_valido"}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('{"estado":"cancelado","codigo":"interrumpido_por_operador"}', file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
