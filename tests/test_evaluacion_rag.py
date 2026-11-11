import json
import hashlib
import runpy
from copy import deepcopy
from io import StringIO
from tempfile import TemporaryDirectory
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import numpy as np

from evaluacion.metricas import recuperacion, senales_respuesta, evaluar_revision, resumir
from evaluacion.ejecutor import evaluar_recuperacion, evaluar_generacion, calibrar, validar_seleccion, _modelo_local, main
from evaluacion.informes import guardar, leer, completar, comparar, aplicar_revisiones, entorno
from tests.soporte import sustituir_modulos

RAIZ = Path(__file__).resolve().parents[1]


class TestCorpusMetricas(unittest.TestCase):
    def setUp(self):
        self.datos = json.loads((RAIZ / "evaluacion/casos.json").read_text(encoding="utf-8"))
        self.docs = [{"nombre": p.name, "contenido": p.read_text(encoding="utf-8")}
                     for p in sorted((RAIZ / "evaluacion/documentos").glob("*.txt"))]

    def test_particion_previa_equilibrada(self):
        casos = self.datos["casos"]
        self.assertEqual(len(casos), 20)
        self.assertEqual(len({c["id"] for c in casos}), 20)
        for grupo in ("calibracion", "validacion"):
            seleccion = [c for c in casos if c["grupo"] == grupo]
            self.assertEqual(len(seleccion), 10)
            self.assertEqual(sum(c["tiene_respuesta"] for c in seleccion), 7)
            self.assertTrue(any(c["tipo"] == "comparacion" for c in seleccion))
            self.assertTrue(any(c["tipo"] == "negacion" for c in seleccion))

    def test_evidencias_validas_y_corpus_completo(self):
        self.assertEqual(len(self.docs), 4)
        for caso in self.datos["casos"]:
            resultado = recuperacion(self.docs, caso, self.datos["evidencias"], self.docs)
            self.assertEqual(resultado["cobertura"], 1 if caso["tiene_respuesta"] else None)

    def test_cobertura_parcial_y_precision(self):
        caso = self.datos["casos"][6]
        fragmentos = [d for d in self.docs if d["nombre"] in ("club_cometa.txt", "biblioteca_luna.txt")]
        resultado = recuperacion(fragmentos, caso, self.datos["evidencias"], self.docs)
        self.assertEqual(resultado["cobertura"], .5)
        self.assertFalse(resultado["contexto_completo"])
        self.assertEqual(resultado["precision_fragmentos"], .5)

    def test_evidencia_cubierta_entre_fragmentos_solapados(self):
        docs = [{"nombre": "f.txt", "contenido": "uno dos tres cuatro cinco"}]
        ev = {"e": {"documento": "f.txt", "texto": "dos tres cuatro"}}
        fs = [{"nombre": "f.txt", "contenido": "uno dos tres"}, {"nombre": "f.txt", "contenido": "tres cuatro cinco"}]
        r = recuperacion(fs, {"evidencias": ["e"]}, ev, docs)
        self.assertEqual(r["cobertura"], 1)
        self.assertEqual(r["evidencias_cubiertas"], ["e"])

    def test_recuperacion_vacia_y_negativas_no_aplicables(self):
        self.assertEqual(recuperacion([], self.datos["casos"][0], self.datos["evidencias"], self.docs)["cobertura"], 0)
        self.assertIsNone(recuperacion([], self.datos["casos"][13], self.datos["evidencias"], self.docs)["cobertura"])

    def test_senales_siempre_provisionales(self):
        positiva, negativa = self.datos["casos"][0], self.datos["casos"][13]
        self.assertEqual(senales_respuesta("No consta información", negativa)["estado_provisional"], "abstencion_correcta")
        self.assertEqual(senales_respuesta("No consta información", positiva)["estado_provisional"], "abstencion_indebida")
        self.assertEqual(senales_respuesta("La contraseña es inventada", negativa)["estado_provisional"], "respuesta_sin_respaldo")
        self.assertTrue(senales_respuesta("Lucía Vega", positiva)["requiere_revision_humana"])

    def test_revision_humana_fidelidad(self):
        r = evaluar_revision({"abstiene": False, "correcta": False, "afirmaciones": 2, "respaldadas": 1}, self.datos["casos"][0])
        self.assertEqual(r["estado"], "respuesta_erronea")
        self.assertEqual(r["fidelidad"], .5)
        with self.assertRaises(ValueError):
            evaluar_revision({"abstiene": False, "correcta": True, "afirmaciones": 1, "respaldadas": 2}, self.datos["casos"][0])

    def test_error_no_es_abstencion_y_sin_revision_no_hay_nota(self):
        r = resumir([{"estado": "error_tecnico"}, {"estado": "ok", "recuperacion": None}])
        self.assertEqual(r["errores_tecnicos"], 1)
        self.assertEqual(r["final"]["revisadas"], 0)
        self.assertIsNone(r["final"]["fidelidad"])


def modelo_ficticio():
    modelo = Mock()
    modelo.encode.side_effect = lambda textos: np.array([
        [b + 1 for b in hashlib.sha256(t.encode("utf-8")).digest()[:8]] for t in textos], dtype=float)
    return modelo


class TestEjecutorRecuperacion(unittest.TestCase):
    def test_usa_metodo_real_de_streamlit_sin_cargador_privado_ni_ollama(self):
        from buscador_semantico import MotorRAG
        original = MotorRAG.recuperar_fragmentos
        with patch("buscador_semantico.cargar_documentos", side_effect=AssertionError("No leer privados")), patch("buscador_semantico.generar_respuesta", side_effect=AssertionError("No Ollama")), patch.object(MotorRAG, "recuperar_fragmentos", autospec=True, side_effect=original) as buscar:
            r = evaluar_recuperacion(grupo="validacion", fabrica_modelo=modelo_ficticio)
            self.assertEqual(buscar.call_count, 10)
            self.assertEqual(r["resumen"]["errores_tecnicos"], 0)
            self.assertEqual(buscar.call_args.kwargs, {"limite": 2, "umbral": .2})
            self.assertEqual({x["id"] for x in r["resultados"]}, {"P02", "P04", "P06", "P08", "P10", "P12", "P15", "P17", "P19", "P20"})

    def test_calibracion_nunca_usa_validacion_y_reutiliza_modelo(self):
        fabrica = Mock(side_effect=modelo_ficticio)
        r = calibrar(fabrica_modelo=fabrica)
        fabrica.assert_called_once_with()
        for candidato in r["candidatos"]:
            self.assertEqual({x["id"] for x in candidato["resultados"]}, {"P01", "P03", "P05", "P07", "P09", "P11", "P13", "P14", "P16", "P18"})
        self.assertIn(r["mejor_umbral"], [.2, .3, .4, .5])

    def test_fallo_indice_se_registra_sin_inventar_abstenciones(self):
        r = evaluar_recuperacion(fabrica_modelo=Mock(side_effect=RuntimeError("Fallo simulado")))
        self.assertEqual(r["resumen"]["errores_tecnicos"], 20)
        self.assertEqual(r["resumen"]["cobertura"]["n"], 0)
        self.assertTrue(all(x["estado"] == "error_tecnico" for x in r["resultados"]))

    def test_metricas_repetibles(self):
        a = evaluar_recuperacion(fabrica_modelo=modelo_ficticio)
        b = evaluar_recuperacion(fabrica_modelo=modelo_ficticio)
        self.assertEqual(a["resumen"], b["resumen"])
        self.assertEqual(a["configuracion"], b["configuracion"])

    def test_sin_descarga_automatica(self):
        modulo = ModuleType("sentence_transformers")
        modulo.SentenceTransformer = Mock(return_value=modelo_ficticio())
        with sustituir_modulos({"sentence_transformers": modulo}):
            _modelo_local()
        self.assertTrue(modulo.SentenceTransformer.call_args.kwargs["local_files_only"])

    def test_seleccion_rechaza_corpus_y_origen_distintos(self):
        r = calibrar(fabrica_modelo=modelo_ficticio)
        with self.assertRaises(ValueError):
            validar_seleccion(r, 2)
        r["configuracion"]["origen_embeddings"] = "real_local"
        self.assertEqual(validar_seleccion(r, 2), r["mejor_umbral"])
        r["configuracion"]["huella_corpus"] = "distinto"
        with self.assertRaises(ValueError):
            validar_seleccion(r, 2)

    def test_importar_entradas_no_ejecuta(self):
        with patch("evaluacion.ejecutor.evaluar_recuperacion", side_effect=AssertionError("No ejecutar")), patch("evaluacion.ejecutor.calibrar", side_effect=AssertionError("No calibrar")):
            runpy.run_path(str(RAIZ / "evaluar_umbrales.py"), run_name="_solo_importar")
            runpy.run_path(str(RAIZ / "probar_rag_fragmentos.py"), run_name="_solo_importar")


def generador_ficticio(pregunta, contexto, devolver_detalles=False):
    return {"respuesta_original": "Lucía Vega, según el texto.",
            "respuesta_final": "Lucía Vega, según el texto.", "bloqueada": False}


class TestGeneracionInformes(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP real prohibido")))
        self.enterContext(patch("evaluacion.ejecutor._modelo_local", side_effect=AssertionError("Modelo real prohibido")))

    def referencia(self):
        return evaluar_generacion("referencia", repeticiones=1, generador=generador_ficticio)

    def test_referencia_no_carga_embeddings_y_negativas_tienen_distractores(self):
        fabrica = Mock(side_effect=AssertionError("No embeddings"))
        r = evaluar_generacion("referencia", grupo="todos", repeticiones=1, fabrica_modelo=fabrica, generador=generador_ficticio)
        fabrica.assert_not_called()
        self.assertEqual(len(r["resultados"]), 20)
        self.assertTrue(all(f["contexto"] for f in r["resultados"]))
        self.assertEqual(r["tiempos_inicializacion"]["carga_modelo_s"], 0)
        self.assertEqual(r["resumen"]["final"]["revisadas"], 0)
        self.assertEqual(r["resumen"]["final"]["pendientes_revision"], 20)

    def test_original_y_final_se_conservan_sin_nota_semantica_automatica(self):
        generar = Mock(return_value={"respuesta_original": "Dato en 1998.", "respuesta_final": "No tengo información suficiente.", "bloqueada": True})
        r = evaluar_generacion("referencia", repeticiones=1, generador=generar)
        fila = r["resultados"][0]
        self.assertEqual(fila["respuestas"]["original"], "Dato en 1998.")
        self.assertEqual(fila["respuestas"]["final"], "No tengo información suficiente.")
        self.assertTrue(fila["bloqueada"])
        self.assertTrue(fila["senales"]["final"]["requiere_revision_humana"])
        self.assertIsNone(r["resumen"]["final"]["fidelidad"])

    def test_rag_sin_contexto_no_genera_y_clasifica_decision_sistema(self):
        generar = Mock(side_effect=AssertionError("No debe generar"))
        with patch("buscador_semantico.MotorRAG.recuperar_fragmentos", return_value=[]):
            r = evaluar_generacion("rag", grupo="todos", repeticiones=1, fabrica_modelo=modelo_ficticio, generador=generar)
        generar.assert_not_called()
        self.assertEqual(r["resumen"]["final"]["abstencion_correcta"]["valor"], 1)
        self.assertEqual(r["resumen"]["final"]["abstencion_indebida"]["valor"], 1)
        self.assertEqual(r["resumen"]["original"]["revisadas"], 0)
        self.assertTrue(all(f["origen"] == "sistema_sin_contexto" for f in r["resultados"]))

    def test_generacion_fallida_no_borra_metricas_de_recuperacion(self):
        r = evaluar_generacion("rag", grupo="todos", repeticiones=1, fabrica_modelo=modelo_ficticio,
                              generador=Mock(side_effect=RuntimeError("Fallo técnico ficticio")))
        self.assertEqual(r["resumen"]["errores_tecnicos"], 20)
        self.assertEqual(r["resumen"]["cobertura"]["n"], 14)
        self.assertEqual(r["resumen"]["final"]["revisadas"], 0)
        self.assertTrue(all(f["respuestas"]["final"] is None for f in r["resultados"]))

    def test_repeticiones_y_tiempos_separados(self):
        r = evaluar_generacion("rag", repeticiones=3, fabrica_modelo=modelo_ficticio, generador=generador_ficticio)
        self.assertEqual(len(r["resultados"]), 30)
        self.assertEqual({f["repeticion"] for f in r["resultados"]}, {1, 2, 3})
        self.assertTrue(all(f["busqueda_s"] >= 0 and f["generacion_s"] >= 0 for f in r["resultados"]))
        t = r["tiempos_inicializacion"]
        self.assertAlmostEqual(t["indexacion_total_s"], t["carga_modelo_s"] + t["indexacion_sin_carga_modelo_s"])

    def test_revisiones_humanas_separadas_original_final(self):
        r = self.referencia()
        clave = r["resultados"][0]["id"] + ":1"
        juicios = {clave: {
            "original": {"abstiene": False, "correcta": False, "afirmaciones": 2, "respaldadas": 1},
            "final": {"abstiene": False, "correcta": True, "afirmaciones": 1, "respaldadas": 1}}}
        nuevo = aplicar_revisiones(r, juicios)
        self.assertEqual(nuevo["resumen"]["original"]["fidelidad"], .5)
        self.assertEqual(nuevo["resumen"]["final"]["fidelidad"], 1)
        self.assertEqual(r["resumen"]["final"]["revisadas"], 0)
        self.assertEqual(nuevo["resultados"][0]["origen_revision"]["final"], "humana")

    def test_no_revisar_error_tecnico(self):
        r = evaluar_generacion("referencia", repeticiones=1, generador=Mock(side_effect=RuntimeError("Fallo")))
        clave = r["resultados"][0]["id"] + ":1"
        with self.assertRaises(ValueError):
            aplicar_revisiones(r, {clave: {"final": {"abstiene": True, "correcta": True, "afirmaciones": 0, "respaldadas": 0}}})

    def test_json_temporal_y_proteccion_sobrescritura_y_rutas(self):
        r = self.referencia()
        with TemporaryDirectory(prefix="eval_informe_") as tmp:
            destino = Path(tmp) / "ejecucion.json"
            with patch("evaluacion.informes.entorno", return_value={"commit": "ficticio", "huella_metricas": "fija"}):
                guardar(r, destino, directorio_permitido=tmp)
            leido = leer(destino)
            self.assertEqual(leido["resultados"], r["resultados"])
            self.assertEqual(leido["entorno"]["commit"], "ficticio")
            with self.assertRaises(FileExistsError):
                guardar(r, destino, directorio_permitido=tmp)
            with self.assertRaises(ValueError):
                guardar(r, Path(tmp) / "fuera" / "informe.json", directorio_permitido=Path(tmp) / "permitido")

    def test_comparacion_detecta_regresiones_emparejadas(self):
        a = evaluar_recuperacion(fabrica_modelo=modelo_ficticio)
        b = deepcopy(a)
        a["resultados"][0]["recuperacion"]["cobertura"] = 1
        b["resultados"][0]["recuperacion"]["cobertura"] = 0
        a["entorno"] = b["entorno"] = {"huella_metricas": "fija"}
        b["configuracion"]["umbral"] = .4
        salida = comparar(a, b)
        self.assertIn(a["resultados"][0]["id"] + ":1", salida["regresiones"])
        self.assertEqual(salida["cambios_configuracion"]["umbral"], [.2, .4])

    def test_comparacion_rechaza_baterias_modalidades_y_origenes_distintos(self):
        a = self.referencia()
        for campo, valor in (("huella_corpus", "otro"), ("grupo", "todos"), ("origen_generacion", "ollama_real")):
            b = deepcopy(a)
            b["configuracion"][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                comparar(a, b)
        b = deepcopy(a)
        b["modo"] = "rag"
        with self.assertRaises(ValueError):
            comparar(a, b)

    def test_resumen_tiempos_no_mezcla_fallos_con_exitos(self):
        r = self.referencia()
        r["entorno"] = {"commit": "ficticio"}
        r["resultados"][0]["estado"] = "error_tecnico"
        r["resultados"][0]["generacion_s"] = .001
        salida = completar(r)
        self.assertEqual(salida["resumen_tiempos"]["generacion_s"]["n"], 9)
        self.assertEqual(salida["resumen_tiempos"]["generacion_s"]["fallidas"]["n"], 1)

    def test_importar_evaluador_no_ejecuta(self):
        with patch("evaluacion.ejecutor.main", side_effect=AssertionError("No ejecutar main al importar")):
            runpy.run_path(str(RAIZ / "evaluar_rag.py"), run_name="_solo_importar")

    def test_cli_exige_autorizacion_explicita_modelos(self):
        with patch("sys.stderr", new_callable=StringIO), self.assertRaises(SystemExit) as error:
            main([])
        self.assertEqual(error.exception.code, 2)

    def test_cli_rechaza_salida_privada_antes_de_ejecutar(self):
        with patch("sys.stderr", new_callable=StringIO), patch("evaluacion.ejecutor.evaluar_recuperacion") as evaluar:
            with self.assertRaises(SystemExit):
                main(["--real", "--salida", "Documentos/no_escribir.json"])
            evaluar.assert_not_called()

    def test_cli_recuperacion_guarda_informe_y_compara_sin_modelos(self):
        with TemporaryDirectory(prefix="eval_cli_") as tmp:
            destino = Path(tmp) / "Informes" / "base.json"
            with patch("evaluacion.informes.RAIZ", Path(tmp)), patch("evaluacion.informes.entorno", return_value={"huella_metricas": "fija"}), patch("evaluacion.ejecutor._modelo_local", side_effect=modelo_ficticio):
                codigo = main(["--real", "--modo", "recuperacion", "--salida", str(destino)])
            self.assertEqual(codigo, 0)
            r = leer(destino)
            self.assertEqual(len(r["resultados"]), 10)
            self.assertEqual(r["configuracion"]["origen_umbral"], "fijo")
            with patch("builtins.print") as mostrar:
                self.assertEqual(main(["--comparar", str(destino), str(destino)]), 0)
            self.assertEqual(json.loads(mostrar.call_args.args[0])["regresiones"], [])

    def test_cli_revision_offline_no_invoca_modelos(self):
        with TemporaryDirectory(prefix="eval_revision_") as tmp:
            base = Path(tmp) / "Informes" / "base.json"
            revisado = base.with_name("revisado.json")
            revision = Path(tmp) / "juicios.json"
            with patch("evaluacion.informes.RAIZ", Path(tmp)), patch("evaluacion.informes.entorno", return_value={"huella_metricas": "fija"}):
                guardar(self.referencia(), base)
                revision.write_text(json.dumps({"P02:1": {"final": {"abstiene": False, "correcta": False, "afirmaciones": 1, "respaldadas": 0}}}), encoding="utf-8")
                self.assertEqual(main(["--revisar", str(base), "--revisiones", str(revision), "--salida", str(revisado)]), 0)
            r = leer(revisado)
            self.assertEqual(r["resumen"]["final"]["revisadas_humanas"], 1)
            self.assertEqual(r["resumen"]["final"]["fidelidad"], 0)

    def test_metadatos_identifican_codigo_y_prompt_sin_modelos(self):
        datos = entorno()
        for campo in ("huella_motor", "huella_prompt", "huella_metricas", "huella_evaluador"):
            self.assertEqual(len(datos[campo]), 64)
        self.assertEqual(datos["modelo_ollama"], "qwen3.5:4b")
        self.assertIn("bibliotecas", datos)

    def test_comparacion_detecta_error_nuevo_y_regresion_humana(self):
        a = self.referencia()
        a["entorno"] = {"huella_metricas": "fija"}
        juicio = {"abstiene": False, "correcta": True, "afirmaciones": 1, "respaldadas": 1}
        a = aplicar_revisiones(a, {"P02:1": {"final": juicio}})
        b = aplicar_revisiones(a, {"P02:1": {"final": dict(juicio, correcta=False)}})
        b["resultados"][1]["estado"] = "error_tecnico"
        salida = comparar(a, b)
        self.assertIn("P02:1", salida["regresiones"])
        self.assertIn(b["resultados"][1]["id"] + ":1", salida["regresiones"])

    def test_comparacion_rechaza_metadatos_ausentes_y_filas_duplicadas(self):
        a = self.referencia()
        with self.assertRaises(ValueError):
            comparar(a, a)
        a["entorno"] = {"huella_metricas": "fija"}
        a["resultados"].append(deepcopy(a["resultados"][0]))
        with self.assertRaises(ValueError):
            comparar(a, a)
