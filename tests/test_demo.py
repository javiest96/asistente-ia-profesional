"""Lanzador de demo: corpus ficticio y subprocess simulado; nunca modelos."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import demo_local as d

RAIZ = Path(__file__).resolve().parents[1]


class TestDemo(unittest.TestCase):
    def setUp(self):
        self.temporal = Path(self.enterContext(TemporaryDirectory(prefix="h8_demo_tests_")))
        self.repo = self.temporal / "proyecto"
        self.corpus = self.repo / "demo" / "corpus"
        self.corpus.mkdir(parents=True)
        for nombre in d.CORPUS:
            (self.corpus / nombre).write_bytes((RAIZ / "demo" / "corpus" / nombre).read_bytes())
        crear_temporal = d.tempfile.mkdtemp
        self.enterContext(patch.object(d.tempfile, "mkdtemp", side_effect=lambda **kw: crear_temporal(dir=self.temporal, **kw)))
        self.enterContext(patch.object(d, "comprobar_puerto"))
        self.no_servidor = self.enterContext(patch.object(d.subprocess, "call", side_effect=AssertionError("No iniciar servidor/modelos")))

    def test_solo_copia_corpus_ficticio_a_carpeta_nueva(self):
        privado = self.repo / "Documentos"
        privado.mkdir()
        (privado / "no_copiar.txt").write_text("Dato centinela ficticio", encoding="utf-8")
        biblioteca = d.preparar_demo(self.repo, 8501)
        self.assertNotEqual(biblioteca, privado)
        self.assertEqual({p.name for p in biblioteca.iterdir()}, set(d.CORPUS))
        for nombre in d.CORPUS:
            self.assertEqual((biblioteca / nombre).read_bytes(), (self.corpus / nombre).read_bytes())
        manifiesto = json.loads((biblioteca.parent / "demo.json").read_text())
        self.assertFalse(manifiesto["subidas"])
        self.assertEqual(manifiesto["host"], "127.0.0.1")
        for nombre, datos in manifiesto["documentos"].items():
            self.assertEqual(datos["sha256"], d.sha256(biblioteca / nombre))
        self.no_servidor.assert_not_called()

    def test_dos_preparaciones_no_reutilizan_ni_borran_biblioteca(self):
        primera = d.preparar_demo(self.repo, 8501)
        segunda = d.preparar_demo(self.repo, 8501)
        self.assertNotEqual(primera, segunda)
        self.assertEqual(len(list(primera.iterdir())), 3)
        self.assertEqual(len(list(segunda.iterdir())), 3)

    def test_corpus_con_archivos_ajenos_se_rechaza(self):
        (self.corpus / "no_copiar.txt").write_text("Ficticio", encoding="utf-8")
        with self.assertRaises(d.ErrorDemo):
            d.preparar_demo(self.repo, 8501)
        self.no_servidor.assert_not_called()

    def test_corpus_con_enlaces_se_rechaza(self):
        enlazado = self.corpus / "centro.txt"
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda p: p == enlazado):
            with self.assertRaises(d.ErrorDemo):
                d.preparar_demo(self.repo, 8501)

    def test_cambio_durante_copia_impide_arrancar(self):
        original = d.sha256
        def huella(ruta):
            return "0" * 64 if ruta.parent.name == "biblioteca" else original(ruta)
        with patch.object(d, "sha256", side_effect=huella), self.assertRaises(d.ErrorDemo):
            d.preparar_demo(self.repo, 8501)
        self.no_servidor.assert_not_called()

    def test_entorno_no_hereda_biblioteca_endpoints_o_subidas(self):
        variables = {"RAG_DOCUMENTOS_DIR": "privado_ficticio", "RAG_PERMITIR_SUBIDAS": "true",
                     "RAG_URL_OLLAMA": "https://no_usar.invalid/api/generate", "RAG_MODELO_LLM": "otro-cloud",
                     "STREAMLIT_SERVER_ADDRESS": "0.0.0.0", "HTTP_PROXY": "http://no_usar.invalid",
                     "HF_HUB_OFFLINE": "0", "HF_TOKEN": "credencial_ficticia"}
        with patch.dict(os.environ, variables):
            antes = dict(os.environ)
            env = d.entorno_demo(self.temporal / "biblioteca")
            self.assertEqual(dict(os.environ), antes)
        self.assertEqual(env["RAG_DOCUMENTOS_DIR"], str(self.temporal / "biblioteca"))
        self.assertEqual(env["RAG_PERMITIR_SUBIDAS"], "false")
        self.assertEqual(env["RAG_URL_OLLAMA"], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(env["RAG_MODELO_LLM"], "qwen3.5:4b")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["TRANSFORMERS_OFFLINE"], "1")
        self.assertNotIn("STREAMLIT_SERVER_ADDRESS", env)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("HF_TOKEN", env)

    def test_comando_impone_loopback_y_controles_seguridad(self):
        comando = d.comando_demo(Path("python_ficticio.exe"), 8766)
        for flag in ("-B", "--server.address=127.0.0.1", "--server.port=8766",
                     "--server.enableCORS=true", "--server.enableXsrfProtection=true",
                     "--server.enableAgentApi=false", "--server.enableStaticServing=false"):
            self.assertIn(flag, comando)
        self.assertNotIn("0.0.0.0", " ".join(comando))

    def preparar_main(self):
        self.enterContext(patch.object(d, "RAIZ", self.repo))
        python = self.repo / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"interprete ficticio: nunca ejecutar")
        self.enterContext(patch.object(sys, "prefix", str(self.repo / ".venv")))
        self.enterContext(patch.object(sys, "base_prefix", str(self.temporal / "python_base")))
        return python

    def test_modo_preparar_no_inicia_procesos(self):
        self.preparar_main()
        with redirect_stdout(StringIO()):
            self.assertEqual(d.main(["--preparar", "--puerto", "8766"]), 0)
        self.no_servidor.assert_not_called()

    def test_corpus_invalido_no_arranca_ni_muestra_excepciones(self):
        self.preparar_main()
        for datos in (b"", b"\x00", b"\xff"):
            (self.corpus / "centro.txt").write_bytes(datos)
            with self.subTest(datos=datos), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(d.main(["--preparar"]), 1)
        self.no_servidor.assert_not_called()

    def test_lanzamiento_usa_solo_venv_original_y_primer_plano(self):
        python = self.preparar_main()
        self.no_servidor.side_effect = None
        self.no_servidor.return_value = 0
        with redirect_stdout(StringIO()):
            self.assertEqual(d.main(["--puerto", "8766"]), 0)
        args, kwargs = self.no_servidor.call_args
        self.assertEqual(args[0][0], str(python))
        self.assertEqual(kwargs["cwd"], self.repo)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["RAG_PERMITIR_SUBIDAS"], "false")

    def test_ctrl_c_no_borra_biblioteca(self):
        self.preparar_main()
        self.no_servidor.side_effect = KeyboardInterrupt
        with redirect_stdout(StringIO()):
            self.assertEqual(d.main([]), 130)
        self.assertEqual(len(list(self.temporal.glob("rag-demo-h8-*/demo.json"))), 1)

    def test_entorno_equivocado_se_rechaza_antes_de_preparar(self):
        with patch.object(d, "RAIZ", self.repo), patch.object(d, "preparar_demo") as preparar, redirect_stderr(StringIO()):
            self.assertEqual(d.main(["--preparar"]), 1)
        preparar.assert_not_called()


class TestCorpusYPuerto(unittest.TestCase):
    def test_datos_ficticios_y_evidencias_fijadas(self):
        textos = {n: (RAIZ / "demo" / "corpus" / n).read_text(encoding="utf-8") for n in d.CORPUS}
        self.assertIn("8 euros", textos["centro.txt"])
        self.assertIn("3 euros adicionales", textos["taller.txt"])
        self.assertIn("11:30", textos["taller.txt"])
        for texto in textos.values():
            self.assertLessEqual(len(texto.split()), 50)
            self.assertNotIn("teléfono", texto.lower())
            self.assertIn("fictici", texto.lower())

    def test_puerto_ocupado_se_rechaza(self):
        with socket.socket() as servidor:
            servidor.bind(("127.0.0.1", 0))
            servidor.listen(1)
            with self.assertRaises(d.ErrorDemo):
                d.comprobar_puerto(servidor.getsockname()[1])

    def test_puertos_invalidos(self):
        for puerto in (0, 80, 65536, True):
            with self.subTest(puerto=puerto), self.assertRaises(d.ErrorDemo):
                d.comprobar_puerto(puerto)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Solo Windows PowerShell")
    def test_wrapper_prepara_sin_streamlit_modelos_o_instalaciones(self):
        with TemporaryDirectory(prefix="h8_wrapper_demo_") as tmp:
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                puerto = s.getsockname()[1]
            env = dict(os.environ, TEMP=tmp, TMP=tmp)
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                str(RAIZ / "scripts" / "iniciar_demo.ps1"), "-Preparar", "-Puerto", str(puerto)],
                               env=env, cwd=RAIZ, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, "El wrapper no preparó la biblioteca ficticia")
            self.assertIn(f"http://127.0.0.1:{puerto}", r.stdout)
            bibliotecas = list(Path(tmp).glob("rag-demo-h8-*/biblioteca"))
            self.assertEqual(len(bibliotecas), 1)
            self.assertEqual({p.name for p in bibliotecas[0].iterdir()}, set(d.CORPUS))
