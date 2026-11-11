"""Ejecutores explícitos. Usan un MotorRAG propio y nunca Documentos/."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from evaluacion.metricas import recuperacion, resumir, senales_respuesta, evaluar_revision

BASE = Path(__file__).resolve().parent
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def huella(valor):
    return hashlib.sha256(json.dumps(valor, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def cargar_bateria(bateria="h5"):
    if bateria not in ("h5", "h6"):
        raise ValueError("Batería desconocida")
    base = BASE if bateria == "h5" else BASE / "h6"
    carpeta = "documentos" if bateria == "h5" else "corpus"
    datos = json.loads((base / "casos.json").read_text(encoding="utf-8"))
    inicio = perf_counter()
    documentos = [{"nombre": p.name, "contenido": p.read_text(encoding="utf-8")}
                  for p in sorted((base / carpeta).glob("*.txt"))]
    tiempo = perf_counter() - inicio
    return datos, documentos, tiempo


def _modelo_local():
    from sentence_transformers import SentenceTransformer
    # No descarga pesos de forma implícita. El usuario debe prepararlos antes.
    return SentenceTransformer(MODELO_EMBEDDINGS, local_files_only=True)


def preparar(fabrica_modelo=None):
    from buscador_semantico import MotorRAG, ErrorIndice
    datos, documentos, carga = cargar_bateria()
    tiempos = {"carga_documentos_s": carga, "carga_modelo_s": 0.0,
               "indexacion_total_s": 0.0, "indexacion_sin_carga_modelo_s": 0.0}

    def fabrica():
        inicio = perf_counter()
        try:
            return (fabrica_modelo or _modelo_local)()
        finally:
            tiempos["carga_modelo_s"] += perf_counter() - inicio

    motor = MotorRAG(cargador=lambda: [dict(d) for d in documentos], fabrica_modelo=fabrica)
    inicio = perf_counter()
    error = None
    try:
        motor.inicializar()
    except ErrorIndice as exc:
        error = str(exc)
    tiempos["indexacion_total_s"] = perf_counter() - inicio
    tiempos["indexacion_sin_carga_modelo_s"] = max(0.0, tiempos["indexacion_total_s"] - tiempos["carga_modelo_s"])
    return motor, datos, documentos, tiempos, error


def configuracion(datos, documentos, grupo, limite, umbral, inyectado):
    return {"version_bateria": datos["version"], "huella_corpus": huella(documentos),
            "huella_preguntas": huella(datos), "grupo": grupo, "limite": limite,
            "umbral": umbral, "tamano_palabras": 50, "solapamiento_palabras": 10,
            "modelo_embeddings": MODELO_EMBEDDINGS,
            "origen_embeddings": "inyectado" if inyectado else "real_local",
            "identidad_pesos_embeddings": "no_verificada"}


def seleccionar(datos, grupo):
    if grupo not in ("todos", "calibracion", "validacion"):
        raise ValueError("Grupo desconocido")
    return [c for c in datos["casos"] if grupo == "todos" or c["grupo"] == grupo]


def _recuperar(motor, datos, documentos, casos, limite, umbral, error_indice):
    from buscador_semantico import ErrorIndice
    registros = []
    for caso in casos:
        r = {"id": caso["id"], "pregunta": caso["pregunta"], "tiene_respuesta": caso["tiene_respuesta"],
             "estado": "ok", "recuperacion": None, "fragmentos": [], "busqueda_s": None}
        inicio = perf_counter()
        try:
            if error_indice:
                raise ErrorIndice(error_indice)
            fragmentos = motor.recuperar_fragmentos(caso["pregunta"], limite=limite, umbral=umbral)
            r["busqueda_s"] = perf_counter() - inicio
            r["fragmentos"] = fragmentos
            r["recuperacion"] = recuperacion(fragmentos, caso, datos["evidencias"], documentos)
        except ErrorIndice as exc:
            r.update(estado="error_tecnico", error={"fase": "indice" if error_indice else "busqueda", "mensaje": str(exc)})
            if not error_indice:
                r["busqueda_s"] = perf_counter() - inicio
        registros.append(r)
    return registros


def evaluar_recuperacion(grupo="todos", limite=2, umbral=.20, fabrica_modelo=None):
    if limite < 1 or not -1 <= umbral <= 1:
        raise ValueError("Límite o umbral inválido")
    motor, datos, documentos, tiempos, error = preparar(fabrica_modelo)
    registros = _recuperar(motor, datos, documentos, seleccionar(datos, grupo), limite, umbral, error)
    return {"esquema": 1, "modo": "recuperacion", "configuracion": configuracion(datos, documentos, grupo, limite, umbral, fabrica_modelo is not None),
            "tiempos_inicializacion": tiempos, "resultados": registros, "resumen": resumir(registros)}


def calibrar(umbrales=(.20, .30, .40, .50), limite=2, fabrica_modelo=None):
    if not umbrales or limite < 1 or any(not -1 <= u <= 1 for u in umbrales):
        raise ValueError("Candidatos inválidos")
    motor, datos, documentos, tiempos, error = preparar(fabrica_modelo)
    casos = seleccionar(datos, "calibracion")
    candidatos = []
    for umbral in sorted(set(umbrales)):
        registros = _recuperar(motor, datos, documentos, casos, limite, umbral, error)
        candidatos.append({"umbral": umbral, "resultados": registros, "resumen": resumir(registros)})
    elegibles = [c for c in candidatos if c["resumen"]["errores_tecnicos"] == 0]
    if not elegibles:
        raise ValueError("Calibración sin candidatos válidos; comprueba el modelo local")

    def criterio(candidato):
        r = candidato["resumen"]
        return (r["contexto_completo"]["valor"], r["precision_fragmentos"]["valor"],
                r["cobertura"]["valor"], -candidato["umbral"])

    ganador = max(elegibles, key=criterio)
    return {"esquema": 1, "modo": "calibracion", "configuracion": configuracion(datos, documentos, "calibracion", limite, ganador["umbral"], fabrica_modelo is not None),
            "criterio": ["contexto_completo", "precision_fragmentos", "cobertura", "menor_umbral"],
            "tiempos_inicializacion": tiempos, "mejor_umbral": ganador["umbral"], "candidatos": candidatos}


def validar_seleccion(seleccion, limite):
    datos, documentos, _ = cargar_bateria()
    esperado = configuracion(datos, documentos, "calibracion", limite, 0, False)
    if (seleccion.get("modo") != "calibracion" or seleccion.get("esquema") != 1
            or seleccion.get("configuracion", {}).get("grupo") != "calibracion"):
        raise ValueError("El archivo no es una calibración válida")
    for campo in ("huella_corpus", "huella_preguntas", "limite", "modelo_embeddings", "origen_embeddings", "tamano_palabras", "solapamiento_palabras"):
        if seleccion["configuracion"].get(campo) != esperado[campo]:
            raise ValueError("Selección incompatible: " + campo)
    umbral = seleccion["mejor_umbral"]
    if (not isinstance(umbral, (int, float)) or not -1 <= umbral <= 1
            or umbral != seleccion["configuracion"]["umbral"]
            or umbral not in [c["umbral"] for c in seleccion.get("candidatos", [])]):
        raise ValueError("Umbral seleccionado inválido")
    return umbral


def evaluar_generacion(modo="rag", grupo="validacion", limite=2, umbral=.20,
                       repeticiones=3, fabrica_modelo=None, generador=None):
    from buscador_semantico import generar_respuesta
    if modo not in ("rag", "referencia") or repeticiones < 1 or limite < 1 or not -1 <= umbral <= 1:
        raise ValueError("Configuración de generación inválida")
    if modo == "rag":
        motor, datos, documentos, tiempos, error = preparar(fabrica_modelo)
    else:
        datos, documentos, carga = cargar_bateria()
        tiempos = {"carga_documentos_s": carga, "carga_modelo_s": 0.0,
                   "indexacion_total_s": 0.0, "indexacion_sin_carga_modelo_s": 0.0}
    registros = []
    for caso in seleccionar(datos, grupo):
        for repeticion in range(1, repeticiones + 1):
            if modo == "rag":
                r = _recuperar(motor, datos, documentos, [caso], limite, umbral, error)[0]
                contexto = [f["contenido"] for f in r["fragmentos"]]
            else:
                ids = caso["evidencias"] or caso["contexto_referencia"]
                contexto = [datos["evidencias"][eid]["texto"] for eid in ids]
                r = {"id": caso["id"], "pregunta": caso["pregunta"], "tiene_respuesta": caso["tiene_respuesta"],
                     "estado": "ok", "recuperacion": None, "fragmentos": [], "busqueda_s": None}
            r.update(repeticion=repeticion, contexto=contexto, referencia=caso["referencia"],
                     respuestas={"original": None, "final": None}, revision={},
                     origen_revision={}, senales={}, generacion_s=None, bloqueada=False)
            if r["estado"] == "error_tecnico":
                registros.append(r)
                continue
            if not contexto:
                # Mismo cortocircuito que Streamlit: no se llama al modelo.
                r["origen"] = "sistema_sin_contexto"
                r["respuestas"]["final"] = "No he encontrado información suficiente."
                r["revision"]["final"] = evaluar_revision({"abstiene": True, "correcta": not caso["tiene_respuesta"],
                                                          "afirmaciones": 0, "respaldadas": 0}, caso)
                r["origen_revision"]["final"] = "regla_sistema"
            else:
                inicio = perf_counter()
                try:
                    detalles = (generador or generar_respuesta)(caso["pregunta"], contexto, devolver_detalles=True)
                    if (not isinstance(detalles, dict) or
                            not all(isinstance(detalles.get(k), str) for k in ("respuesta_original", "respuesta_final"))
                            or type(detalles.get("bloqueada")) is not bool):
                        raise ValueError("El generador devolvió un contrato inválido")
                    r.update(origen="modelo", bloqueada=detalles["bloqueada"])
                    for variante, campo in (("original", "respuesta_original"), ("final", "respuesta_final")):
                        r["respuestas"][variante] = detalles[campo]
                        r["senales"][variante] = senales_respuesta(detalles[campo], caso)
                except Exception as exc:
                    r.update(estado="error_tecnico", error={"fase": "generacion", "tipo": type(exc).__name__, "mensaje": str(exc)})
                finally:
                    r["generacion_s"] = perf_counter() - inicio
            registros.append(r)
    config = configuracion(datos, documentos, grupo, limite, umbral, fabrica_modelo is not None)
    config.update(repeticiones=repeticiones, origen_generacion="inyectado" if generador is not None else "ollama_real")
    if modo == "referencia":
        config["origen_embeddings"] = "no_utilizado"
    return {"esquema": 1, "modo": modo, "configuracion": config,
            "tiempos_inicializacion": tiempos, "resultados": registros, "resumen": resumir(registros)}


def main_umbrales(argv=None):
    parser = argparse.ArgumentParser(description="Calibrar solo con preguntas de calibración; embeddings locales, sin Ollama")
    parser.add_argument("--real", action="store_true", required=True)
    parser.add_argument("--umbrales", nargs="+", type=float, default=[.2, .3, .4, .5])
    parser.add_argument("--limite", type=int, default=2)
    parser.add_argument("--salida", required=True)
    args = parser.parse_args(argv)
    from evaluacion.informes import guardar, validar_destino
    try:
        validar_destino(args.salida)
        guardar(calibrar(args.umbrales, args.limite), args.salida)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


def main_diagnostico(argv=None):
    parser = argparse.ArgumentParser(description="Inspeccionar fragmentos ficticios sin filtrar después del top-k")
    parser.add_argument("--real", action="store_true", required=True)
    parser.add_argument("--caso", default="P03")
    args = parser.parse_args(argv)
    informe = evaluar_recuperacion()
    resultados = [r for r in informe["resultados"] if r["id"] == args.caso]
    if not resultados:
        parser.error("Caso desconocido")
    print(json.dumps(resultados[0], ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluación RAG exclusivamente con documentos ficticios")
    acciones = parser.add_mutually_exclusive_group()
    acciones.add_argument("--comparar", nargs=2, metavar=("ANTES", "DESPUES"))
    acciones.add_argument("--revisar", metavar="INFORME")
    parser.add_argument("--revisiones", help="JSON de juicios humanos; no utiliza modelos")
    parser.add_argument("--real", action="store_true", help="Autoriza ejecución explícita con modelos reales")
    parser.add_argument("--modo", choices=["recuperacion", "referencia", "rag"], default="recuperacion")
    parser.add_argument("--grupo", choices=["calibracion", "validacion", "todos"], default="validacion")
    parser.add_argument("--limite", type=int, default=2)
    parser.add_argument("--umbral", type=float)
    parser.add_argument("--seleccion", help="JSON producido por evaluar_umbrales.py")
    parser.add_argument("--repeticiones", type=int)
    parser.add_argument("--salida", help="Archivo JSON nuevo dentro de Informes/")
    args = parser.parse_args(argv)
    from evaluacion.informes import leer, guardar, comparar, aplicar_revisiones, validar_destino
    try:
        if args.salida:
            validar_destino(args.salida)
        if args.comparar:
            informe = comparar(leer(args.comparar[0]), leer(args.comparar[1]))
        elif args.revisar:
            if not args.revisiones or not args.salida:
                parser.error("--revisar requiere --revisiones y --salida")
            informe = aplicar_revisiones(leer(args.revisar), leer(args.revisiones))
        else:
            if not args.real or not args.salida:
                parser.error("Evaluar requiere --real y --salida; no se ejecutan modelos implícitamente")
            if args.seleccion and args.umbral is not None:
                parser.error("Utiliza --seleccion o --umbral, no ambos")
            seleccion = leer(args.seleccion) if args.seleccion else None
            umbral = validar_seleccion(seleccion, args.limite) if seleccion else (args.umbral if args.umbral is not None else .2)
            if args.modo == "recuperacion":
                if args.repeticiones not in (None, 1):
                    parser.error("Recuperación realiza una pasada; repeticiones es para generación")
                informe = evaluar_recuperacion(args.grupo, args.limite, umbral)
            else:
                informe = evaluar_generacion(args.modo, args.grupo, args.limite, umbral,
                                              args.repeticiones if args.repeticiones is not None else 3)
            informe["configuracion"]["origen_umbral"] = "calibracion" if seleccion else "fijo"
            informe["configuracion"]["huella_seleccion"] = huella(seleccion) if seleccion else None
        if args.salida:
            guardar(informe, args.salida)
        else:
            print(json.dumps(informe, ensure_ascii=False, indent=2))
        return int(informe.get("resumen", {}).get("errores_tecnicos", 0) > 0)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
