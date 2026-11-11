"""Métricas transparentes. Las señales léxicas no certifican semántica."""
import unicodedata


def tokens(texto):
    return unicodedata.normalize("NFKC", texto).casefold().split()


def posiciones(texto, pasaje):
    base, buscado = tokens(texto), tokens(pasaje)
    return [i for i in range(len(base) - len(buscado) + 1)
            if base[i:i + len(buscado)] == buscado] if buscado else []


def recuperacion(fragmentos, caso, evidencias, documentos):
    """Cobertura de intervalos de palabras, incluso entre ventanas solapadas."""
    corpus = {d["nombre"]: d["contenido"] for d in documentos}
    objetivos = {}
    for identificador in caso["evidencias"]:
        evidencia = evidencias[identificador]
        inicios = posiciones(corpus[evidencia["documento"]], evidencia["texto"])
        if len(inicios) != 1:
            raise ValueError("La evidencia debe identificar un pasaje único: " + identificador)
        inicio = inicios[0]
        objetivos[identificador] = (evidencia["documento"], set(range(inicio, inicio + len(tokens(evidencia["texto"])))))
    cubiertas = {nombre: set() for nombre in corpus}
    relevantes = 0
    for fragmento in fragmentos:
        nombre = fragmento["nombre"]
        inicios = posiciones(corpus[nombre], fragmento["contenido"])
        if len(inicios) != 1:
            raise ValueError("Fragmento ausente o ambiguo en el corpus ficticio")
        intervalo = set(range(inicios[0], inicios[0] + len(tokens(fragmento["contenido"]))))
        cubiertas[nombre].update(intervalo)
        relevantes += any(doc == nombre and bool(intervalo & esperado) for doc, esperado in objetivos.values())
    encontrados = [eid for eid, (doc, esperado) in objetivos.items() if esperado <= cubiertas[doc]]
    return {
        "evidencias_cubiertas": encontrados,
        "cobertura": len(encontrados) / len(objetivos) if objetivos else None,
        "contexto_completo": len(encontrados) == len(objetivos) if objetivos else None,
        "precision_fragmentos": relevantes / len(fragmentos) if objetivos and fragmentos else (0.0 if objetivos else None),
        "fragmentos_recuperados": len(fragmentos),
    }


def senales_respuesta(texto, caso):
    normal = " ".join(tokens(texto))
    abstiene = any(frase in normal for frase in (
        "no lo sé", "no consta", "no tengo información", "no hay información",
        "no se menciona", "no se indica", "no se especifica", "no puedo determinar",
        "no he encontrado información", "no tengo suficiente información",
    ))
    hechos = [any(" ".join(tokens(alias)) in normal for alias in opciones) for opciones in caso["hechos"]]
    conflictos = [s for s in caso["incompatibles"] if " ".join(tokens(s)) in normal]
    if abstiene:
        estado = "abstencion_indebida" if caso["tiene_respuesta"] else "abstencion_correcta"
    elif not caso["tiene_respuesta"]:
        estado = "respuesta_sin_respaldo"
    else:
        estado = "candidata_correcta" if all(hechos) and not conflictos else "posible_respuesta_erronea"
    return {"estado_provisional": estado, "abstencion_detectada": abstiene,
            "hechos_detectados": hechos, "conflictos_lexicos": conflictos,
            "requiere_revision_humana": True}


def evaluar_revision(revision, caso):
    """Juicio humano: abstiene/correcta y recuento explícito de afirmaciones."""
    if set(revision) != {"abstiene", "correcta", "afirmaciones", "respaldadas"}:
        raise ValueError("Campos de revisión incorrectos")
    if type(revision["abstiene"]) is not bool or type(revision["correcta"]) is not bool:
        raise ValueError("Los juicios deben ser booleanos")
    total, respaldo = revision["afirmaciones"], revision["respaldadas"]
    if type(total) is not int or type(respaldo) is not int or not 0 <= respaldo <= total:
        raise ValueError("Recuento de afirmaciones inválido")
    if revision["abstiene"]:
        estado = "abstencion_indebida" if caso["tiene_respuesta"] else "abstencion_correcta"
    else:
        estado = "respuesta_correcta" if caso["tiene_respuesta"] and revision["correcta"] else "respuesta_erronea"
    return {"estado": estado, "fidelidad": respaldo / total if total else None,
            "afirmaciones": total, "respaldadas": respaldo}


def media(valores):
    valores = [v for v in valores if v is not None]
    return sum(valores) / len(valores) if valores else None


def resumir(registros):
    validos = [r for r in registros if r["estado"] != "error_tecnico"]
    salida = {"casos": len(registros), "errores_tecnicos": len(registros) - len(validos),
              "casos_sin_error": len(validos),
              "respuestas_bloqueadas": sum(r.get("bloqueada", False) for r in validos)}
    for clave in ("cobertura", "contexto_completo", "precision_fragmentos"):
        # Un fallo de generación no borra una recuperación que sí se completó.
        valores = [r["recuperacion"][clave] for r in registros if r.get("recuperacion") is not None]
        salida[clave] = {"valor": media(valores), "n": sum(v is not None for v in valores)}
    for variante in ("original", "final"):
        revisadas = [r for r in validos if r.get("revision", {}).get(variante) is not None]
        juicios = [(r, r["revision"][variante]) for r in revisadas]
        negativas = [(r, j) for r, j in juicios if not r["tiene_respuesta"]]
        positivas = [(r, j) for r, j in juicios if r["tiene_respuesta"]]
        afirmaciones = sum(j["afirmaciones"] for _, j in juicios)
        salida[variante] = {
            "revisadas": len(revisadas),
            "revisadas_humanas": sum(r.get("origen_revision", {}).get(variante) == "humana" for r in revisadas),
            "decisiones_sistema": sum(r.get("origen_revision", {}).get(variante) == "regla_sistema" for r in revisadas),
            "pendientes_revision": sum(r.get("respuestas", {}).get(variante) is not None and r.get("revision", {}).get(variante) is None for r in validos),
            "abstencion_correcta": {"valor": media([j["estado"] == "abstencion_correcta" for _, j in negativas]), "n": len(negativas)},
            "abstencion_indebida": {"valor": media([j["estado"] == "abstencion_indebida" for _, j in positivas]), "n": len(positivas)},
            "respuestas_correctas": {"valor": media([j["estado"] == "respuesta_correcta" for _, j in positivas]), "n": len(positivas)},
            "fidelidad": sum(j["respaldadas"] for _, j in juicios) / afirmaciones if afirmaciones else None,
        }
    return salida
