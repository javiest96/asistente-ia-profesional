"""Experimentos H6 con contextos fijos. No hay recuperación ni embeddings."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from evaluacion.ejecutor import cargar_bateria, huella
from evaluacion.metricas import evaluar_revision, media, resumir, senales_respuesta
from evaluacion.prompts import construir_prompt, generar_variante, identidades, huella_filtro, sha_texto


def condiciones(inyectado=False):
    from configuracion import MODELO_LLM
    return {"modelo": MODELO_LLM, "temperature": 0, "think": False, "stream": False,
            "timeout_s": 120, "huella_filtro": huella_filtro(),
            "origen_generacion": "inyectado" if inyectado else "ollama_real"}


def evaluar_juicio_h6(juicio, caso):
    if set(juicio) != {"abstiene", "correcta", "completa", "afirmaciones", "respaldadas"} or type(juicio["completa"]) is not bool:
        raise ValueError("H6 requiere los cuatro campos habituales y completa booleano")
    if juicio["correcta"] and not juicio["completa"]:
        raise ValueError("Una respuesta correcta no puede estar incompleta")
    base = {k: v for k, v in juicio.items() if k != "completa"}
    return dict(evaluar_revision(base, caso), completa=juicio["completa"])


def resumen_completitud(registros):
    salida = {}
    for variante in ("original", "final"):
        juicios = [r["revision"][variante]["completa"] for r in registros
                   if r.get("exclusion") is None and r["estado"] != "error_tecnico" and r["tiene_respuesta"]
                   and "completa" in r.get("revision", {}).get(variante, {})]
        salida[variante] = {"valor": media(juicios), "n": len(juicios)}
    return salida


def _validar_reserva(seleccion, variantes, datos, documentos, repeticiones, inyectado):
    if not seleccion or seleccion.get("modo") != "seleccion_h6" or seleccion.get("grupo_origen") != "exploracion":
        raise ValueError("Los reservados requieren una selección fijada con exploración revisada")
    elegida = seleccion.get("variante_elegida")
    if elegida not in ("A", "B", "C") or set(variantes) != {"A", elegida}:
        raise ValueError("En reservados solo se contrasta A con la variante ya elegida")
    esperados = {"huella_preguntas": huella(datos), "huella_corpus": huella(documentos),
                 "identidades_prompts": identidades(), "condiciones": condiciones(inyectado),
                 "repeticiones": repeticiones}
    for clave, valor in esperados.items():
        if seleccion.get(clave) != valor:
            raise ValueError("La selección ya no corresponde al experimento: " + clave)


def ejecutar_experimento(variantes=("A", "B", "C"), grupo="exploracion", repeticiones=3,
                        generador=None, seleccion=None, confirmar_reserva=False):
    variantes = tuple(variantes)
    if (not variantes or len(set(variantes)) != len(variantes) or set(variantes) - {"A", "B", "C"}
            or grupo not in ("exploracion", "reservados") or type(repeticiones) is not int or repeticiones < 1):
        raise ValueError("Variantes, grupo o repeticiones inválidos")
    datos, documentos, carga = cargar_bateria("h6")
    if grupo == "reservados":
        if not confirmar_reserva:
            raise ValueError("Confirma el uso final de los casos reservados")
        _validar_reserva(seleccion, variantes, datos, documentos, repeticiones, generador is not None)
    elif seleccion is not None or confirmar_reserva:
        raise ValueError("La selección de reserva no se aplica a exploración")
    casos = [c for c in datos["casos"] if c["grupo"] == grupo]
    contextos = {c["id"]: [datos["evidencias"][eid]["texto"] for eid in c["contextos"]] for c in casos}
    manifiesto = [{"id": c["id"], "pregunta": c["pregunta"], "contexto": contextos[c["id"]]} for c in casos]
    comunes = {"bateria": "h6", "version_bateria": datos["version"], "rubrica": "h6-v1", "grupo": grupo,
               "huella_preguntas": huella(datos), "huella_corpus": huella(documentos),
               "huella_contextos": huella(manifiesto), "identidades_prompts": identidades(),
               "repeticiones": repeticiones, "condiciones": condiciones(generador is not None),
               "origen_embeddings": "no_utilizado", "origen_generacion": "inyectado" if generador else "ollama_real",
               "huella_seleccion": huella(seleccion) if seleccion else None}
    informes = {v: {"esquema": 1, "modo": "experimento_prompts",
                    "configuracion": dict(deepcopy(comunes), variante=v, huella_plantilla=identidades()[v]),
                    "tiempos_inicializacion": {"carga_documentos_s": carga, "carga_modelo_s": 0.0,
                                              "indexacion_total_s": 0.0, "indexacion_sin_carga_modelo_s": 0.0},
                    "resultados": []} for v in variantes}
    for caso in casos:
        for repeticion in range(1, repeticiones + 1):
            # Rotación prefijada, no dependiente de resultados; reduce sesgo de orden.
            orden = variantes[(repeticion - 1) % len(variantes):] + variantes[:(repeticion - 1) % len(variantes)]
            for variante in orden:
                contexto = list(contextos[caso["id"]])
                r = {"id": caso["id"], "repeticion": repeticion, "pregunta": caso["pregunta"],
                     "tiene_respuesta": caso["tiene_respuesta"], "referencia": caso["referencia"], "criterio": caso["criterio"],
                     "estado": "ok", "contexto": contexto, "huella_contexto": huella(contexto),
                     "recuperacion": None, "fragmentos": [], "busqueda_s": None, "generacion_s": None,
                     "respuestas": {"original": None, "final": None}, "bloqueada": False,
                     "revision": {}, "origen_revision": {}, "senales": {}, "huella_prompt": None, "prompt": None}
                if not contexto:
                    r.update(origen="sistema_sin_contexto")
                    r["respuestas"]["final"] = "No he encontrado información suficiente."
                    r["revision"]["final"] = evaluar_juicio_h6({"abstiene": True, "correcta": not caso["tiene_respuesta"],
                                                              "completa": not caso["tiene_respuesta"], "afirmaciones": 0, "respaldadas": 0}, caso)
                    r["origen_revision"]["final"] = "regla_sistema"
                else:
                    r["prompt"] = construir_prompt(caso["pregunta"], contexto, variante)
                    r["huella_prompt"] = sha_texto(r["prompt"])
                    r["prompt_simulado"] = generador is not None
                    inicio = perf_counter()
                    try:
                        detalles = (generador or generar_variante)(caso["pregunta"], list(contexto), devolver_detalles=True, variante=variante)
                        if (not isinstance(detalles, dict) or type(detalles.get("bloqueada")) is not bool
                                or not all(isinstance(detalles.get(k), str) and detalles[k].strip() for k in ("respuesta_original", "respuesta_final"))):
                            raise ValueError("El generador incumple su contrato")
                        r["generacion_s"] = perf_counter() - inicio
                        r.update(origen="modelo", bloqueada=detalles["bloqueada"])
                        for campo, clave in (("original", "respuesta_original"), ("final", "respuesta_final")):
                            r["respuestas"][campo] = detalles[clave]
                            r["senales"][campo] = senales_respuesta(detalles[clave], caso)
                    except Exception as exc:
                        r.update(estado="error_tecnico", error={"fase": "generacion", "tipo": type(exc).__name__, "mensaje": str(exc)})
                    finally:
                        if r["generacion_s"] is None:
                            r["generacion_s"] = perf_counter() - inicio
                informes[variante]["resultados"].append(r)
    for informe in informes.values():
        informe["resumen"] = resumir(informe["resultados"])
        informe["resumen_completitud"] = resumen_completitud(informe["resultados"])
    return informes


def fijar_variante(base, candidato):
    from evaluacion.informes import comparar
    comparar(base, candidato)  # Verifica todas las condiciones y contextos.
    if (base["modo"] != "experimento_prompts" or base["configuracion"]["variante"] != "A"
            or base["configuracion"]["grupo"] != "exploracion"):
        raise ValueError("La selección requiere referencia A y exploración")
    for informe in (base, candidato):
        for r in informe["resultados"]:
            if r.get("exclusion") is not None:
                continue
            if r["estado"] == "error_tecnico":
                raise ValueError("No fijar selección con errores técnicos pendientes")
            for campo, texto in r["respuestas"].items():
                if texto is not None and "completa" not in r.get("revision", {}).get(campo, {}):
                    raise ValueError("Primero revisar original/final, incluida completitud")
    c = candidato["configuracion"]
    return {"esquema": 1, "modo": "seleccion_h6", "grupo_origen": "exploracion",
            "variante_elegida": c["variante"], "huella_preguntas": c["huella_preguntas"],
            "huella_corpus": c["huella_corpus"], "identidades_prompts": c["identidades_prompts"],
            "condiciones": c["condiciones"], "repeticiones": c["repeticiones"],
            "huella_informe_base": huella(base), "huella_informe_candidato": huella(candidato),
            "exclusiones": dict(base.get("exclusiones", {})),
            "nota": "Elección humana explícita; no promoción a producción ni garantía de mejora."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="H6: experimentos de generación con contextos ficticios fijos")
    acciones = parser.add_subparsers(dest="accion", required=True)
    ejecutar = acciones.add_parser("ejecutar")
    ejecutar.add_argument("--real", action="store_true", required=True)
    ejecutar.add_argument("--grupo", choices=["exploracion", "reservados"], default="exploracion")
    ejecutar.add_argument("--variantes", nargs="+", choices=["A", "B", "C"], default=["A", "B", "C"])
    ejecutar.add_argument("--repeticiones", type=int, default=3)
    ejecutar.add_argument("--seleccion")
    ejecutar.add_argument("--confirmar-reserva", action="store_true")
    ejecutar.add_argument("--salida-dir", required=True)
    fijar = acciones.add_parser("fijar")
    fijar.add_argument("--base", required=True)
    fijar.add_argument("--candidato", required=True)
    fijar.add_argument("--salida", required=True)
    args = parser.parse_args(argv)
    from evaluacion.informes import leer, guardar, validar_destino
    try:
        if args.accion == "fijar":
            validar_destino(args.salida)
            guardar(fijar_variante(leer(args.base), leer(args.candidato)), args.salida)
            return 0
        destinos = {v: Path(args.salida_dir) / f"{v}.json" for v in args.variantes}
        for destino in destinos.values():
            validar_destino(destino)
        informes = ejecutar_experimento(args.variantes, args.grupo, args.repeticiones,
                                        seleccion=leer(args.seleccion) if args.seleccion else None,
                                        confirmar_reserva=args.confirmar_reserva)
        for v, informe in informes.items():
            guardar(informe, destinos[v])
        return int(any(i["resumen"]["errores_tecnicos"] for i in informes.values()))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
