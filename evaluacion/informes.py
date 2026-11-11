"""Informes JSON, revisión humana y comparación emparejada sin servicios."""
import ast
from collections import Counter
from copy import deepcopy
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import platform
import statistics
import subprocess

from evaluacion.ejecutor import cargar_bateria, huella
from evaluacion.metricas import evaluar_revision, resumir

RAIZ = Path(__file__).resolve().parents[1]


def leer(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def entorno():
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True,
                                  text=True, check=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    bibliotecas = {}
    for nombre in ("numpy", "scikit-learn", "sentence-transformers", "requests"):
        try:
            bibliotecas[nombre] = version(nombre)
        except PackageNotFoundError:
            bibliotecas[nombre] = None
    fuente = (RAIZ / "buscador_semantico.py").read_text(encoding="utf-8")
    funcion = next(n for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef) and n.name == "generar_respuesta")
    prompt = next(n.value for n in funcion.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "prompt" for t in n.targets))
    import configuracion
    estado = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "git_sucio": bool(estado) if estado is not None else None,
            "huella_motor": huella(fuente), "huella_prompt": huella(ast.dump(prompt)),
            "huella_evaluador": huella({p.name: p.read_text(encoding="utf-8") for p in (RAIZ / "evaluacion").glob("*.py")}),
            "huella_metricas": huella((RAIZ / "evaluacion/metricas.py").read_text(encoding="utf-8")),
            "modelo_ollama": configuracion.MODELO_LLM, "identidad_pesos_ollama": "no_verificada",
            "python": platform.python_version(), "plataforma": platform.platform(),
            "bibliotecas": bibliotecas, "opciones_ollama": {"temperature": 0, "think": False, "stream": False}}


def completar(informe):
    informe = deepcopy(informe)
    if "entorno" not in informe:
        informe["entorno"] = entorno()
    if informe.get("modo") == "experimento_prompts":
        from evaluacion.experimentos import resumen_completitud
        informe["resumen"] = resumir_h6(informe)
        informe["resumen_completitud"] = resumen_completitud(informe["resultados"])
        # No atribuir al experimento B/C la plantilla A de producción.
        if "huella_prompt_produccion" not in informe["entorno"]:
            informe["entorno"]["huella_prompt_produccion"] = informe["entorno"].get("huella_prompt")
            informe["entorno"]["huella_prompt"] = informe["configuracion"]["huella_plantilla"]
            informe["entorno"]["variante_prompt"] = informe["configuracion"]["variante"]
    informe["resumen_tiempos"] = {}
    def estadistica(valores):
        return {"n": len(valores), "mediana": statistics.median(valores) if valores else None,
                "minimo": min(valores) if valores else None, "maximo": max(valores) if valores else None}
    for campo in ("busqueda_s", "generacion_s"):
        intentos = [r for r in informe.get("resultados", []) if r.get(campo) is not None]
        valores = [r[campo] for r in intentos if r["estado"] != "error_tecnico"]
        informe["resumen_tiempos"][campo] = estadistica(valores)
        informe["resumen_tiempos"][campo]["fallidas"] = estadistica([r[campo] for r in intentos if r["estado"] == "error_tecnico"])
        informe["resumen_tiempos"][campo]["primera_observada"] = intentos[0][campo] if intentos else None
        informe["resumen_tiempos"][campo]["posteriores_correctas"] = estadistica([r[campo] for r in intentos[1:] if r["estado"] != "error_tecnico"])
    informe["senales_provisionales"] = {
        variante: dict(Counter(r.get("senales", {}).get(variante, {}).get("estado_provisional")
                              for r in informe.get("resultados", []) if variante in r.get("senales", {})))
        for variante in ("original", "final")}
    return informe


def validar_destino(ruta, directorio_permitido=None):
    permitido = Path(directorio_permitido or RAIZ / "Informes").resolve()
    destino = Path(ruta).resolve()
    if not destino.is_relative_to(permitido) or destino.suffix.lower() != ".json":
        raise ValueError("Los informes deben ser JSON dentro de Informes/")
    if destino.exists():
        raise FileExistsError("El informe ya existe; utiliza otro nombre")
    return destino


def guardar(informe, ruta, directorio_permitido=None):
    destino = validar_destino(ruta, directorio_permitido)
    texto = json.dumps(completar(informe), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # No sobrescribir una ejecución anterior.
    with destino.open("x", encoding="utf-8") as archivo:
        archivo.write(texto + "\n")


def exclusiones_h6(informe):
    """Valida una política explícita por caso, aplicada a todas sus repeticiones."""
    exclusiones = informe.get("exclusiones", {})
    ids = {r["id"] for r in informe["resultados"]}
    if not isinstance(exclusiones, dict) or any(
            k not in ids or not isinstance(v, str) or not v.strip()
            for k, v in exclusiones.items()):
        raise ValueError("Exclusiones inválidas: requieren caso presente y justificación")
    if exclusiones and len(exclusiones) == len(ids):
        raise ValueError("No se pueden excluir todos los casos")
    for r in informe["resultados"]:
        if r.get("exclusion") != exclusiones.get(r["id"]):
            raise ValueError("Exclusión incoherente entre caso y repeticiones")
    return exclusiones


def resumir_h6(informe):
    exclusiones = exclusiones_h6(informe)
    filas = [r for r in informe["resultados"] if r["id"] not in exclusiones]
    resumen = resumir(filas)
    resumen.update(casos_totales=len(informe["resultados"]),
                   casos_excluidos=len(informe["resultados"]) - len(filas),
                   exclusiones=dict(exclusiones))
    return resumen


def aplicar_revisiones(informe, revisiones):
    bateria = informe.get("configuracion", {}).get("bateria", "h5")
    datos, documentos, _ = cargar_bateria(bateria)
    if informe.get("modo") not in ("rag", "referencia", "experimento_prompts"):
        raise ValueError("La revisión requiere una evaluación de generación")
    if (informe["modo"] == "experimento_prompts") != (bateria == "h6"):
        raise ValueError("Modalidad y batería incompatibles")
    if informe["configuracion"]["huella_preguntas"] != huella(datos) or informe["configuracion"]["huella_corpus"] != huella(documentos):
        raise ValueError("Las referencias han cambiado; no se puede revisar con otra batería")
    salida = deepcopy(informe)
    payload = revisiones
    if bateria == "h6" and ("exclusiones" in revisiones or "valoraciones" in revisiones):
        if set(revisiones) != {"exclusiones", "valoraciones"} or not isinstance(revisiones["valoraciones"], dict):
            raise ValueError("Se requieren exclusiones y valoraciones")
        salida["exclusiones"] = deepcopy(revisiones["exclusiones"])
        if not isinstance(salida["exclusiones"], dict):
            raise ValueError("Exclusiones debe ser un objeto")
        for r in salida["resultados"]:
            r.pop("exclusion", None)
            if r["id"] in salida["exclusiones"]:
                r["exclusion"] = salida["exclusiones"][r["id"]]
        exclusiones_h6(salida)
        revisiones = revisiones["valoraciones"]
    casos = {c["id"]: c for c in datos["casos"]}
    filas = {f'{r["id"]}:{r["repeticion"]}': r for r in salida["resultados"]}
    for clave, variantes in revisiones.items():
        if clave not in filas or not variantes or set(variantes) - {"original", "final"}:
            raise ValueError("Identificador o variante de revisión inválidos: " + clave)
        r = filas[clave]
        if r.get("exclusion") is not None:
            raise ValueError("No valorar un caso excluido")
        for variante, juicio in variantes.items():
            if r["estado"] == "error_tecnico" or r["respuestas"][variante] is None:
                raise ValueError("No se puede revisar un error técnico o una respuesta ausente")
            if bateria == "h6":
                from evaluacion.experimentos import evaluar_juicio_h6
                r["revision"][variante] = evaluar_juicio_h6(juicio, casos[r["id"]])
            else:
                r["revision"][variante] = evaluar_revision(juicio, casos[r["id"]])
            r["origen_revision"][variante] = "humana"
    salida["resumen"] = resumir(salida["resultados"])
    if bateria == "h6":
        from evaluacion.experimentos import resumen_completitud
        salida["resumen"] = resumir_h6(salida)
        salida["resumen_completitud"] = resumen_completitud(salida["resultados"])
    salida.setdefault("historial_revisiones", []).append({"huella": huella(payload), "filas": sorted(revisiones)})
    return salida


def _validar_contextos_h6(informe):
    exclusiones_h6(informe)
    config = informe["configuracion"]
    if config.get("bateria") != "h6" or config.get("variante") not in ("A", "B", "C"):
        raise ValueError("Identidad H6 inválida")
    if config.get("huella_plantilla") != config.get("identidades_prompts", {}).get(config["variante"]):
        raise ValueError("La identidad de plantilla no coincide")
    manifiesto = {}
    repeticiones = {}
    for r in informe["resultados"]:
        if r.get("huella_contexto") != huella(r["contexto"]):
            raise ValueError("Se ha modificado un contexto de H6")
        from evaluacion.prompts import sha_texto
        if r["contexto"] and (not isinstance(r.get("prompt"), str) or sha_texto(r["prompt"]) != r.get("huella_prompt")):
            raise ValueError("La huella del prompt no corresponde al texto registrado")
        if not r["contexto"] and (r.get("prompt") is not None or r.get("huella_prompt") is not None):
            raise ValueError("No atribuir un prompt a una decisión sin modelo")
        elemento = {"id": r["id"], "pregunta": r["pregunta"], "contexto": r["contexto"]}
        if r["id"] in manifiesto and manifiesto[r["id"]] != elemento:
            raise ValueError("Las repeticiones no usan contextos/preguntas idénticos")
        manifiesto[r["id"]] = elemento
        repeticiones.setdefault(r["id"], set()).add(r["repeticion"])
    if huella([manifiesto[k] for k in sorted(manifiesto)]) != config.get("huella_contextos"):
        raise ValueError("Los contextos no coinciden con el manifiesto")
    if any(rs != set(range(1, config["repeticiones"] + 1)) for rs in repeticiones.values()):
        raise ValueError("Repeticiones incompletas")


def comparar(antes, despues):
    if antes.get("esquema") != 1 or despues.get("esquema") != 1 or antes["modo"] != despues["modo"] or antes["modo"] == "calibracion":
        raise ValueError("Esquemas o modalidades incompatibles")
    for campo in ("huella_corpus", "huella_preguntas", "grupo", "origen_embeddings", "origen_generacion"):
        if antes["configuracion"].get(campo) != despues["configuracion"].get(campo):
            raise ValueError("Comparación incompatible: " + campo)
    if antes["modo"] == "experimento_prompts":
        _validar_contextos_h6(antes)
        _validar_contextos_h6(despues)
        if exclusiones_h6(antes) != exclusiones_h6(despues):
            raise ValueError("Conjuntos de exclusiones incompatibles")
        for campo in ("bateria", "rubrica", "huella_contextos", "condiciones", "repeticiones", "identidades_prompts"):
            if antes["configuracion"].get(campo) != despues["configuracion"].get(campo):
                raise ValueError("Condiciones H6 incompatibles: " + campo)
    if not antes.get("entorno", {}).get("huella_metricas") or not despues.get("entorno", {}).get("huella_metricas"):
        raise ValueError("Faltan metadatos de métricas; utiliza informes completos")
    if antes["entorno"]["huella_metricas"] != despues["entorno"]["huella_metricas"]:
        raise ValueError("Han cambiado las métricas; no comparar notas directamente")
    def filas(informe):
        salida = {(r["id"], r.get("repeticion", 1)): r for r in informe["resultados"]}
        if len(salida) != len(informe["resultados"]):
            raise ValueError("El informe contiene preguntas/repeticiones duplicadas")
        return salida
    a, b = filas(antes), filas(despues)
    if set(a) != set(b):
        raise ValueError("Las preguntas o repeticiones no coinciden")
    transiciones, regresiones, mejoras = [], [], []
    for clave in sorted(a):
        x, y = a[clave], b[clave]
        if antes["modo"] == "experimento_prompts" and (x["pregunta"] != y["pregunta"] or x["contexto"] != y["contexto"]):
            raise ValueError("Las variantes no recibieron la misma pregunta y contexto")
        if antes["modo"] == "experimento_prompts" and x.get("exclusion") is not None:
            transiciones.append({"caso": f"{clave[0]}:{clave[1]}", "exclusion": x["exclusion"]})
            continue
        cx = (x.get("recuperacion") or {}).get("cobertura")
        cy = (y.get("recuperacion") or {}).get("cobertura")
        metricas = {}
        for campo in ("cobertura", "contexto_completo", "precision_fragmentos"):
            vx, vy = (x.get("recuperacion") or {}).get(campo), (y.get("recuperacion") or {}).get(campo)
            metricas[campo] = {"antes": vx, "despues": vy,
                               "delta": float(vy) - float(vx) if vx is not None and vy is not None else None}
        ex, ey = x["estado"] == "error_tecnico", y["estado"] == "error_tecnico"
        jx, jy = x.get("revision", {}).get("final"), y.get("revision", {}).get("final")
        sx, sy = jx["estado"] if jx else None, jy["estado"] if jy else None
        buenos = {"respuesta_correcta", "abstencion_correcta"}
        dimensiones = {}
        for campo in ("fidelidad", "completa"):
            vx, vy = (jx or {}).get(campo), (jy or {}).get(campo)
            dimensiones[campo] = {"antes": vx, "despues": vy,
                                  "delta": float(vy) - float(vx) if vx is not None and vy is not None else None}
        ox, oy = x.get("revision", {}).get("original", {}), y.get("revision", {}).get("original", {})
        dimensiones_original = {}
        for campo in ("fidelidad", "completa"):
            vx, vy = ox.get(campo), oy.get(campo)
            dimensiones_original[campo] = {"antes": vx, "despues": vy,
                                           "delta": float(vy) - float(vx) if vx is not None and vy is not None else None}
        valores = [*metricas.values(), *dimensiones.values(), *dimensiones_original.values()]
        peor = (not ex and ey) or any(v["delta"] is not None and v["delta"] < 0 for v in valores) or (sx in buenos and sy is not None and sy not in buenos) or (ox.get("estado") in buenos and oy.get("estado") is not None and oy["estado"] not in buenos)
        mejor = (ex and not ey) or any(v["delta"] is not None and v["delta"] > 0 for v in valores) or (sy in buenos and sx is not None and sx not in buenos) or (oy.get("estado") in buenos and ox.get("estado") is not None and ox["estado"] not in buenos)
        identificador = f"{clave[0]}:{clave[1]}"
        if peor:
            regresiones.append(identificador)
        if mejor:
            mejoras.append(identificador)
        transiciones.append({"caso": identificador, "error_antes": ex, "error_despues": ey,
                             "cobertura_antes": cx, "cobertura_despues": cy,
                             "metricas_recuperacion": metricas,
                             "dimensiones_respuesta": dimensiones,
                             "dimensiones_original": dimensiones_original,
                             "estado_original_antes": ox.get("estado"), "estado_original_despues": oy.get("estado"),
                             "estado_revisado_antes": sx, "estado_revisado_despues": sy})
    campos = set(antes["configuracion"]) | set(despues["configuracion"])
    entorno_a, entorno_b = antes.get("entorno", {}), despues.get("entorno", {})
    return {"esquema": 1, "modo": "comparacion", "cambios_configuracion": {
                k: [antes["configuracion"].get(k), despues["configuracion"].get(k)]
                for k in sorted(campos) if antes["configuracion"].get(k) != despues["configuracion"].get(k)},
            "cambios_entorno": {k: [entorno_a.get(k), entorno_b.get(k)] for k in sorted(set(entorno_a) | set(entorno_b)) if entorno_a.get(k) != entorno_b.get(k)},
            "resumen_antes": antes.get("resumen"), "resumen_despues": despues.get("resumen"),
            "tiempos_antes": antes.get("resumen_tiempos"), "tiempos_despues": despues.get("resumen_tiempos"),
            "exclusiones": dict(antes.get("exclusiones", {})),
            "regresiones": regresiones, "mejoras": mejoras, "transiciones": transiciones,
            "advertencia": "Las notas semánticas solo se comparan donde hay revisión en ambas ejecuciones. Los tags no verifican identidad de pesos; los tiempos dependen del entorno."}
