"""H8: nunca instala paquetes, crea venvs ni carga modelos."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO, BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import runpy
import warnings
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from scripts import comprobar_entorno as c

RAIZ = Path(__file__).resolve().parents[1]


class TestInstalacion(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(self.enterContext(TemporaryDirectory(prefix="h8_unitario_")))
        self.plataforma = {"python": "3.14.10", "arquitectura": "x64", "sistema": "Windows"}
        self.enterContext(patch.object(c, "comprobar_plataforma", return_value=self.plataforma))
        self.enterContext(patch.object(c.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(40*1024**3, 0, 40*1024**3)))
        self.prohibido = self.enterContext(patch.object(c.subprocess, "run", side_effect=AssertionError("No ejecutar herramientas en tests")))
        self.enterContext(patch.object(c.subprocess, "Popen", side_effect=AssertionError("No iniciar procesos en tests")))

    def preparacion(self):
        codigo = self.raiz / "codigo"
        codigo.mkdir()
        (codigo / c.LOCK).write_text("torch==1.0\npypdf==2.0\n", encoding="utf-8")
        (codigo / "app.py").write_text("# Aplicación ficticia\n", encoding="utf-8")
        with zipfile.ZipFile(self.raiz / "codigo.zip", "w") as z:
            for p in codigo.iterdir():
                z.write(p, p.name)
        paquetes = {"torch": "1.0", "pypdf": "2.0"}
        c.escribir_nuevo(self.raiz / "preparacion.json", {
            "tipo": "h8_instalacion", "esquema": 1, "plataforma": self.plataforma, "commit": "a" * 40,
            "codigo_zip_sha256": c.sha256(self.raiz / "codigo.zip"),
            "lock_sha256": c.sha256(codigo / c.LOCK), "paquetes": paquetes,
            "orquestador_sha256": c.sha256(c.__file__)})
        return paquetes

    def rueda(self, nombre, version):
        carpeta = self.raiz / "ruedas"
        carpeta.mkdir(exist_ok=True)
        ruta = carpeta / f"{nombre}-{version}-py3-none-any.whl"
        with zipfile.ZipFile(ruta, "w") as z:
            z.writestr(f"{nombre}-{version}.dist-info/METADATA", f"Name: {nombre}\nVersion: {version}\n")
        return ruta

    def descarga_simulada(self):
        self.preparacion()
        def pip(*args, **kwargs):
            self.rueda("torch", "1.0")
            self.rueda("pypdf", "2.0")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(c, "ejecutar", side_effect=pip) as ejecutar:
            c.descargar(self.raiz, autorizado=True)
        return ejecutar

    def test_autorizaciones_bloquean_antes_de_cualquier_accion(self):
        for funcion in (c.descargar, c.recuperar, c.validar):
            with self.subTest(funcion=funcion.__name__), self.assertRaises(c.ErrorValidacion), patch.object(c, "cargar_preparacion") as cargar:
                funcion(self.raiz)
            cargar.assert_not_called()
        self.prohibido.assert_not_called()
        self.assertFalse(list(self.raiz.iterdir()))

    def test_cli_preparar_usa_head_por_defecto(self):
        with patch.object(c, "preparar", return_value=self.raiz) as preparar, redirect_stdout(StringIO()):
            self.assertEqual(c.main([]), 0)
        self.assertEqual(preparar.call_args.args[1], "HEAD")

    def test_cli_conserva_commit_explicito(self):
        with patch.object(c, "preparar", return_value=self.raiz) as preparar, redirect_stdout(StringIO()):
            self.assertEqual(c.main(["--commit", "revision_ficticia"]), 0)
        self.assertEqual(preparar.call_args.args[1], "revision_ficticia")

    def test_head_sin_primer_commit_no_crea_temporal(self):
        with patch.object(c.importlib.util, "find_spec", return_value=object()), patch.object(c, "ejecutar", side_effect=c.ErrorValidacion("comando_fallido")) as ejecutar, patch.object(c.tempfile, "mkdtemp") as crear:
            with self.assertRaises(c.ErrorValidacion):
                c.preparar(self.raiz, "HEAD")
        crear.assert_not_called()
        self.assertEqual(ejecutar.call_args.args[0], ["git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"])

    def test_cli_no_admite_autorizacion_de_otro_modo(self):
        with redirect_stderr(StringIO()), patch.object(c, "preparar") as preparar:
            self.assertEqual(c.main(["--modo", "preparar", "--autorizar-descargas"]), 1)
        preparar.assert_not_called()

    def test_preparar_exporta_solo_con_git_y_no_crea_instalacion(self):
        def git(args, **kwargs):
            if "rev-parse" in args:
                return subprocess.CompletedProcess(args, 0, "a" * 40, "")
            if "ls-tree" in args:
                return subprocess.CompletedProcess(args, 0, c.LOCK + "\napp.py\n", "")
            with zipfile.ZipFile(args[args.index("--output") + 1], "w") as z:
                z.writestr(c.LOCK, "torch==1.0\npypdf==2.0\n")
                z.writestr("app.py", "# ficticio\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(c.tempfile, "mkdtemp", return_value=str(self.raiz)), patch.object(c, "ejecutar", side_effect=git) as ejecutar:
            self.assertEqual(c.preparar(self.raiz, "a5e3ee0"), self.raiz)
        self.assertTrue(all(llamada.args[0][0] == "git" for llamada in ejecutar.call_args_list))
        self.assertFalse((self.raiz / ".venv").exists())
        self.assertFalse((self.raiz / "ruedas").exists())
        informe = json.loads((self.raiz / "preparacion.json").read_text())
        self.assertFalse(informe["instalacion_realizada"])
        self.assertFalse(informe["descargas_realizadas"])

    def test_lock_rechaza_urls_rangos_y_duplicados(self):
        for texto in ("torch>=1\npypdf==2", "torch @ https://usuario:clave@ejemplo.invalid/a.whl", "torch==1\ntorch==1\npypdf==2", ""):
            with self.subTest(texto=texto), self.assertRaises(c.ErrorValidacion):
                c.requisitos(texto)

    def test_exportacion_rechaza_privados_secretos_y_rutas(self):
        for nombre in ("Documentos/privado.txt", "Informes/respuestas.json", ".venv/python.exe",
                       ".env", ".env.local", ".streamlit/secrets.toml", "../fuera.py", "/fuera.py", "a\\b.py", "tmp.part"):
            with self.subTest(nombre=nombre), self.assertRaises(c.ErrorValidacion):
                c.comprobar_nombre_exportado(nombre)
        for nombre in (".env.example", "app.py", "evaluacion/documentos/club_cometa.txt"):
            c.comprobar_nombre_exportado(nombre)

    def test_zip_no_extrae_archivos_antes_de_validar_todos(self):
        ruta = self.raiz / "invalido.zip"
        with zipfile.ZipFile(ruta, "w") as z:
            z.writestr("app.py", "# ficticio")
            z.writestr("../fuera.txt", "ficticio")
        with self.assertRaises(c.ErrorValidacion):
            c.extraer_archivo(ruta, self.raiz / "salida")
        self.assertFalse((self.raiz / "salida").exists())

    def test_codigo_modificado_o_anadido_se_rechaza(self):
        self.preparacion()
        c.cargar_preparacion(self.raiz)
        extra = self.raiz / "codigo" / "modulo_ajeno.py"
        extra.write_text("# ficticio", encoding="utf-8")
        with self.assertRaises(c.ErrorValidacion):
            c.cargar_preparacion(self.raiz)

    def test_ruedas_hashes_y_comando_solo_binario(self):
        ejecutar = self.descarga_simulada()
        args = ejecutar.call_args.args[0]
        self.assertIn("download", args)
        self.assertIn("--only-binary=:all:", args)
        self.assertNotIn("install", args)
        manifiesto = json.loads((self.raiz / "ruedas.json").read_text())
        self.assertEqual(set(manifiesto["paquetes"]), {"torch", "pypdf"})
        for p in manifiesto["paquetes"].values():
            self.assertEqual(p["sha256"], c.sha256(self.raiz / "ruedas" / p["archivo"]))
        self.assertEqual((self.raiz / "requirements-hashed.txt").read_text().count("--hash=sha256:"), 2)

    def test_ruedas_faltantes_ajenas_o_fuentes_se_rechazan(self):
        esperados = self.preparacion()
        self.rueda("torch", "1.0")
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(self.raiz / "ruedas", esperados)
        self.rueda("pypdf", "2.0")
        self.rueda("ajeno", "1.0")
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(self.raiz / "ruedas", esperados)
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(self.raiz / "ruedas", {**esperados, "ajeno": "2.0"})

    def rueda_con_metadatos(self, entradas):
        carpeta = self.raiz / "ruedas"
        carpeta.mkdir()
        with warnings.catch_warnings(record=True):
            with zipfile.ZipFile(carpeta / "torch-1.0-py3-none-any.whl", "w") as z:
                for nombre, texto in entradas:
                    z.writestr(nombre, texto)
        return carpeta

    def test_metadata_principal_y_varios_anidados_se_aceptan(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n"),
            ("torch/_vendor/uno-2.0.dist-info/METADATA", "Name: uno\nVersion: 2.0\n"),
            ("torch/_vendor/dos-3.0.dist-info/METADATA", "Name: dos\nVersion: 3.0\n")])
        self.assertEqual(set(c.manifiesto_ruedas(carpeta, {"torch": "1.0"})), {"torch"})

    def test_solo_metadata_anidados_se_rechazan(self):
        carpeta = self.rueda_con_metadatos([
            ("torch/_vendor/torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n")])
        with self.assertRaisesRegex(c.ErrorValidacion, "rueda_sin_metadatos_unicos"):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_dos_metadata_principales_se_rechazan(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n"),
            ("otro-1.0.dist-info/METADATA", "Name: otro\nVersion: 1.0\n")])
        with self.assertRaisesRegex(c.ErrorValidacion, "rueda_sin_metadatos_unicos"):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_metadata_principal_duplicado_no_se_deduplica(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n"),
            ("torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n")])
        with self.assertRaisesRegex(c.ErrorValidacion, "rueda_sin_metadatos_unicos"):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_nombre_principal_incompatible_se_rechaza(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: incorrecto\nVersion: 1.0\n")])
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_version_principal_incompatible_se_rechaza(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 2.0\n")])
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_metadata_anidado_correcto_no_suplanta_principal_incorrecto(self):
        carpeta = self.rueda_con_metadatos([
            ("torch-1.0.dist-info/METADATA", "Name: incorrecto\nVersion: 9.0\n"),
            ("torch/_vendor/torch-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n")])
        with self.assertRaises(c.ErrorValidacion):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def test_directorio_principal_incompatible_se_rechaza(self):
        carpeta = self.rueda_con_metadatos([
            ("ajeno-1.0.dist-info/METADATA", "Name: torch\nVersion: 1.0\n")])
        with self.assertRaisesRegex(c.ErrorValidacion, "estructura_de_distribucion_incompatible"):
            c.manifiesto_ruedas(carpeta, {"torch": "1.0"})

    def preparar_recuperacion_ficticia(self):
        padre = self.raiz
        origen = padre / "origen"
        origen.mkdir()
        self.raiz = origen
        self.preparacion()
        self.rueda("torch", "1.0")
        self.rueda("pypdf", "2.0")
        with zipfile.ZipFile(origen / "ruedas" / "torch-1.0-py3-none-any.whl", "a") as z:
            z.writestr("torch/_vendor/otro-1.0.dist-info/METADATA", "Name: otro\nVersion: 1.0\n")
        anterior = json.loads((origen / "preparacion.json").read_text())
        anterior["orquestador_sha256"] = "0" * 64  # Huella histórica, no compatible para ejecutar.
        (origen / "preparacion.json").write_text(json.dumps(anterior), encoding="utf-8")
        c.escribir_nuevo(origen / "descarga.json", {"estado": "error", "codigo": "rueda_sin_metadatos_unicos"})
        destino = padre / "destino"
        destino.mkdir()
        self.raiz = destino
        self.preparacion()
        return origen, destino

    def test_recuperacion_offline_conserva_origen_y_verifica_copias(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        antes = c.huellas_archivos(origen)
        with self.assertRaises(c.ErrorValidacion):
            c.cargar_preparacion(origen)  # La protección histórica NO se relaja.
        with patch.object(c, "ejecutar", side_effect=AssertionError("Sin herramientas ni pip")):
            c.recuperar(destino, origen, autorizado=True)
        self.assertEqual(c.huellas_archivos(origen), antes)
        self.assertEqual(c.manifiesto_ruedas(origen / "ruedas", {"torch": "1.0", "pypdf": "2.0"}),
                         c.manifiesto_ruedas(destino / "ruedas", {"torch": "1.0", "pypdf": "2.0"}))
        r = json.loads((destino / "recuperacion.json").read_text())
        self.assertEqual(r["estado"], "ok")
        self.assertTrue(r["integridad_local_verificada"])
        self.assertFalse(r["autenticidad_independiente_verificada"])
        self.assertFalse(r["internet_utilizado"])
        self.assertFalse((destino / "descarga.json").exists())
        self.assertTrue((destino / "requirements-hashed.txt").exists())
        self.assertFalse((destino / ".venv").exists())

    def test_recuperacion_no_elude_huella_actual_del_destino(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        p = json.loads((destino / "preparacion.json").read_text())
        p["orquestador_sha256"] = "f" * 64
        (destino / "preparacion.json").write_text(json.dumps(p), encoding="utf-8")
        with self.assertRaisesRegex(c.ErrorValidacion, "preparacion_modificada_o_incompatible"):
            c.recuperar(destino, origen, autorizado=True)
        self.assertFalse((destino / "ruedas").exists())

    def test_recuperacion_rechaza_lock_de_origen_distinto(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        (origen / "codigo" / c.LOCK).write_text("torch==9.0\npypdf==2.0\n", encoding="utf-8")
        with self.assertRaises(c.ErrorValidacion):
            c.recuperar(destino, origen, autorizado=True)
        self.assertFalse((destino / "ruedas").exists())

    def test_recuperacion_no_sobrescribe_ni_reintenta(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        c.recuperar(destino, origen, autorizado=True)
        antes = c.huellas_archivos(destino)
        with self.assertRaises(c.ErrorValidacion):
            c.recuperar(destino, origen, autorizado=True)
        self.assertEqual(c.huellas_archivos(destino), antes)

    def test_copia_corrupta_se_detecta_sin_manifiesto_exitoso(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        copiar = c.shutil.copyfileobj
        def corromper(entrada, salida, **kwargs):
            copiar(entrada, salida, **kwargs)
            salida.write(b"alteracion_ficticia")
        with patch.object(c.shutil, "copyfileobj", side_effect=corromper), self.assertRaises(c.ErrorValidacion):
            c.recuperar(destino, origen, autorizado=True)
        self.assertFalse((destino / "ruedas.json").exists())
        self.assertEqual(json.loads((destino / "recuperacion.json").read_text())["estado"], "error")

    def test_validacion_admite_recuperacion_sin_simular_descarga(self):
        origen, destino = self.preparar_recuperacion_ficticia()
        c.recuperar(destino, origen, autorizado=True)
        def comando(args, **kwargs):
            if "unittest" in args:
                return subprocess.CompletedProcess(args, 0, "", "Ran 179 tests in 1.0s\nOK")
            return subprocess.CompletedProcess(args, 0, '{"tensor_cpu":true}', "")
        with patch.object(c, "ejecutar", side_effect=comando), patch.object(c, "comprobar_streamlit", return_value={"inferencia": False}):
            c.validar(destino, autorizado=True)
        self.assertEqual(json.loads((destino / "validacion.json").read_text())["estado"], "ok")
        self.assertFalse((destino / "descarga.json").exists())

    def test_no_sobrescribe_una_descarga_ni_crea_venv(self):
        self.descarga_simulada()
        with patch.object(c, "ejecutar") as ejecutar, self.assertRaises(c.ErrorValidacion):
            c.descargar(self.raiz, autorizado=True)
        ejecutar.assert_not_called()
        self.assertFalse((self.raiz / ".venv").exists())

    def test_instalacion_usa_hashes_sin_red_y_python_explicito(self):
        self.descarga_simulada()
        def comando(args, **kwargs):
            if "unittest" in args:
                return subprocess.CompletedProcess(args, 0, "", "Ran 179 tests in 1.0s\nOK")
            return subprocess.CompletedProcess(args, 0, '{"tensor_cpu":true}', "")
        with patch.object(c, "ejecutar", side_effect=comando) as ejecutar, patch.object(c, "comprobar_streamlit", return_value={"inferencia": False}):
            c.validar(self.raiz, autorizado=True)
        llamadas = [x.args[0] for x in ejecutar.call_args_list]
        instalar = next(a for a in llamadas if "install" in a)
        for opcion in ("--no-index", "--no-deps", "--only-binary=:all:", "--require-hashes"):
            self.assertIn(opcion, instalar)
        self.assertEqual(instalar[0], str(self.raiz / ".venv" / "Scripts" / "python.exe"))
        llamada_tests = next(x for x in ejecutar.call_args_list if "unittest" in x.args[0])
        self.assertNotIn("RAG_DOCUMENTOS_DIR", llamada_tests.kwargs["env"])
        self.assertIn("RAG_DOCUMENTOS_DIR", ejecutar.call_args_list[0].kwargs["env"])
        resultado = json.loads((self.raiz / "validacion.json").read_text())
        self.assertEqual(resultado["estado"], "ok")
        self.assertEqual(resultado["comprobaciones"]["tests"]["cantidad"], 179)

    def test_venv_existente_nunca_se_reutiliza(self):
        self.descarga_simulada()
        (self.raiz / ".venv").mkdir()
        with patch.object(c, "ejecutar") as ejecutar, self.assertRaises(c.ErrorValidacion):
            c.validar(self.raiz, autorizado=True)
        ejecutar.assert_not_called()

    def test_rueda_alterada_impide_instalacion(self):
        self.descarga_simulada()
        ruta = next((self.raiz / "ruedas").glob("*.whl"))
        with zipfile.ZipFile(ruta, "a") as z:
            z.writestr("ficticio.txt", "Cambio")
        with patch.object(c, "ejecutar") as ejecutar, self.assertRaises(c.ErrorValidacion):
            c.validar(self.raiz, autorizado=True)
        ejecutar.assert_not_called()

    def test_requirements_hashed_alterado_impide_instalacion(self):
        self.descarga_simulada()
        (self.raiz / "requirements-hashed.txt").write_text("torch==9.0\n", encoding="utf-8")
        with patch.object(c, "ejecutar") as ejecutar, self.assertRaises(c.ErrorValidacion):
            c.validar(self.raiz, autorizado=True)
        ejecutar.assert_not_called()

    def streamlit_simulado(self, estado="ready"):
        proc = unittest.mock.Mock()
        proc.poll.return_value = None
        primera = {"status": estado, "session_id": "ficticia", "actions": [{"key": "actualizar", "label": "Actualizar biblioteca"}]}
        segunda = {"status": "ready", "tree": "Biblioteca actualizada correctamente."}
        respuestas = [b"ok", b"{}", json.dumps(primera).encode(), json.dumps(segunda).encode()]
        opener = unittest.mock.Mock()
        opener.open.side_effect = [BytesIO(x) for x in respuestas]
        popen = self.enterContext(patch.object(c.subprocess, "Popen", return_value=proc))
        self.enterContext(patch.object(c.urllib.request, "build_opener", return_value=opener))
        sock = self.enterContext(patch.object(c.socket, "socket"))
        sock.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 12345)
        return proc, popen

    def test_arranque_streamlit_solo_loopback_sin_modelos(self):
        proc, popen = self.streamlit_simulado()
        resultado = c.comprobar_streamlit(self.raiz / "python_ficticio.exe", self.raiz)
        self.assertFalse(resultado["inferencia"])
        self.assertIn("--server.address=127.0.0.1", popen.call_args.args[0])
        self.assertEqual(popen.call_args.kwargs["env"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(popen.call_args.kwargs["env"]["RAG_URL_OLLAMA"], "http://127.0.0.1:1/api/generate")
        proc.terminate.assert_called_once_with()

    def test_error_de_app_detiene_solo_su_proceso(self):
        proc, _ = self.streamlit_simulado(estado="error")
        with self.assertRaises(c.ErrorValidacion):
            c.comprobar_streamlit(self.raiz / "python_ficticio.exe", self.raiz)
        proc.terminate.assert_called_once_with()

    def test_importar_no_ejecuta_herramientas_ni_crea_carpetas(self):
        with patch.object(c.tempfile, "mkdtemp", side_effect=AssertionError("No crear carpetas")):
            runpy.run_path(str(RAIZ / "scripts/comprobar_entorno.py"), run_name="_solo_importar_h8")
        self.prohibido.assert_not_called()

    def test_entorno_sin_configuracion_privada_y_sin_servicios_modelos(self):
        with patch.dict(c.os.environ, {"RAG_DOCUMENTOS_DIR": "privado", "PIP_INDEX_URL": "https://usuario:secreto@ejemplo.invalid", "PYTHONPATH": "otro", "HF_TOKEN": "secreto"}):
            env = c.entorno_aislado(self.raiz)
        self.assertEqual(env["RAG_DOCUMENTOS_DIR"], str(self.raiz / "biblioteca-vacia"))
        self.assertNotIn("PIP_INDEX_URL", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("HF_TOKEN", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")

    def test_entorno_tests_no_impone_carpeta_ni_hereda_la_del_operador(self):
        with patch.dict(c.os.environ, {"RAG_DOCUMENTOS_DIR": "carpeta_privada_ficticia"}):
            env = c.entorno_tests(self.raiz)
        self.assertNotIn("RAG_DOCUMENTOS_DIR", env)
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")
        self.assertEqual(env["RAG_URL_OLLAMA"], "http://127.0.0.1:1/api/generate")
        self.assertEqual(env["RAG_PERMITIR_SUBIDAS"], "false")
        self.assertEqual(env["HF_HOME"], str(self.raiz / "cache-modelos-vacia"))
        self.assertEqual(c.entorno_aislado(self.raiz)["RAG_DOCUMENTOS_DIR"], str(self.raiz / "biblioteca-vacia"))

    def test_errores_de_herramientas_no_revelan_salida(self):
        self.prohibido.side_effect = None
        self.prohibido.return_value = subprocess.CompletedProcess([], 1, "PREGUNTA_PRIVADA", "https://user:SECRETO@host No matching distribution found")
        with self.assertRaises(c.ErrorValidacion) as error:
            c.ejecutar(["ficticio"], cwd=self.raiz, env={})
        self.assertEqual(error.exception.codigo, "rueda_o_version_no_disponible")
        self.assertNotIn("SECRETO", str(error.exception))
        self.assertNotIn("PRIVADA", str(error.exception))


class TestAislamientoSuite(unittest.TestCase):
    # Ejecutar los siete tests ORIGINALES sin cambiarlos, en procesos nuevos.
    # No hay instalaciones; AppTest usa modelos/HTTP simulados y carpetas ficticias.
    CODIGO = """
import contextlib,io,json,sys,unittest
sys.path.insert(0,sys.argv[1])
loader=unittest.TestLoader()
suite=unittest.TestSuite([
 loader.loadTestsFromName('tests.test_app_robustez.TestAppRobustez.test_documento_guardado_con_indice_fallido'),
 loader.loadTestsFromName('tests.test_cargar_documentos')])
resultado=unittest.TestResult()
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
 suite.run(resultado)
print(json.dumps({'tests':resultado.testsRun,'fallos':[t.id() for t,_ in resultado.failures],
                  'errores':[t.id() for t,_ in resultado.errors]}))
"""

    def ejecutar_siete(self, perfil):
        import sys
        with TemporaryDirectory(prefix="h8_siete_ficticios_") as tmp:
            raiz = Path(tmp)
            env = perfil(raiz)
            r = subprocess.run([sys.executable, "-I", "-B", "-c", self.CODIGO, str(RAIZ)],
                               env=env, cwd=RAIZ, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, "No se pudo ejecutar la regresión aislada")
            resumen = json.loads(r.stdout)
            archivos = [p.name for p in (raiz / "biblioteca-vacia").iterdir()] if (raiz / "biblioteca-vacia").is_dir() else []
            return resumen, archivos

    def test_perfil_global_reproduce_exactamente_siete_fallos(self):
        resumen, archivos = self.ejecutar_siete(c.entorno_aislado)
        self.assertEqual(resumen["tests"], 7)
        self.assertEqual(len(resumen["fallos"]), 6)
        self.assertTrue(all(x.startswith("tests.test_cargar_documentos.") for x in resumen["fallos"]))
        self.assertEqual(resumen["errores"], ["tests.test_app_robustez.TestAppRobustez.test_documento_guardado_con_indice_fallido"])
        self.assertEqual(archivos, ["nuevo_ficticio.txt"])

    def test_perfil_tests_pasa_los_siete_sin_biblioteca_compartida(self):
        resumen, archivos = self.ejecutar_siete(c.entorno_tests)
        self.assertEqual(resumen, {"tests": 7, "fallos": [], "errores": []})
        self.assertEqual(archivos, [])


class TestWrapperPowerShell(unittest.TestCase):
    @unittest.skipUnless(shutil.which("powershell.exe"), "Solo Windows PowerShell")
    def test_wrapper_transmite_head_y_commit_explicito_sin_exportar(self):
        with TemporaryDirectory(prefix="h9_wrapper_commit_") as tmp:
            interprete = Path(tmp) / "interprete_ficticio.ps1"
            interprete.write_text("ConvertTo-Json -InputObject @($args) -Compress; exit 0", encoding="utf-8")
            for commit in (None, "revision_ficticia"):
                with self.subTest(commit=commit):
                    comando = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(RAIZ / "scripts" / "validar_instalacion.ps1"), "-Python", str(interprete)]
                    if commit is not None:
                        comando += ["-Commit", commit]
                    resultado = subprocess.run(comando, capture_output=True, text=True, timeout=30)
                    self.assertEqual(resultado.returncode, 0)
                    argumentos = json.loads(resultado.stdout)
                    self.assertEqual(argumentos[argumentos.index("--commit") + 1], commit or "HEAD")
                    self.assertIn("--repositorio", argumentos)
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, {interprete.name})

    def test_plataforma_no_windows_se_rechaza_sin_instalar(self):
        with patch.object(c.platform, "system", return_value="Linux"), self.assertRaises(c.ErrorValidacion):
            c.comprobar_plataforma()

    @unittest.skipUnless(shutil.which("powershell.exe"), "Solo Windows PowerShell")
    def test_sintaxis_y_barrera_sin_autorizacion(self):
        ruta = RAIZ / "scripts" / "validar_instalacion.ps1"
        # Parsear no ejecuta el script. Argumentos estructurados, sin interpolación del shell.
        codigo = "$t=$null; $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:H8_SCRIPT_PATH,[ref]$t,[ref]$e); if($e.Count){exit 1}"
        env = dict(c.os.environ, H8_SCRIPT_PATH=str(ruta))
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", codigo], env=env, capture_output=True)
        self.assertEqual(r.returncode, 0, "Error de sintaxis PowerShell")
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ruta), "-Modo", "Descargar", "-DirectorioTrabajo", "no-existe"], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
