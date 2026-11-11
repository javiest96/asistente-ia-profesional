import configuracion
from fragmentar_documentos import preparar_fragmentos
from dataclasses import dataclass
from threading import Lock
from types import MappingProxyType
import logging
from time import perf_counter
from uuid import uuid4
from operacion import validar_pregunta, ErrorConsulta, limitar_generacion, ServicioOcupado

logger = logging.getLogger("rag")

MODELO_LLM = configuracion.MODELO_LLM


class ErrorOllama(RuntimeError):
    """Fallo técnico de generación; nunca es una respuesta del modelo."""


class ErrorIndice(RuntimeError):
    """No se pudo construir o consultar un índice; conserva la causa original."""


def cargar_documentos():
    from cargar_documentos import cargar_documentos as cargar
    return cargar()


def _crear_modelo():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(configuracion.MODELO_EMBEDDINGS)


@dataclass(frozen=True)
class IndiceRAG:
    version: int
    documentos_cargados: tuple
    documentos: tuple
    fragmentos: tuple
    embeddings_documentos: object
    embeddings_fragmentos: object


class MotorRAG:
    """Un modelo fijo y una instantánea activa por motor, dentro de un proceso.

    Orden de bloqueos: actualización -> encoder; estado solo para leer/publicar.
    Las consultas sueltan estado antes de pedir encoder. Nunca esperan una
    actualización mientras mantienen el bloqueo del encoder.
    """

    def __init__(self, cargador=None, fabrica_modelo=None):
        self._cargador = cargador if cargador is not None else cargar_documentos
        self._fabrica_modelo = fabrica_modelo if fabrica_modelo is not None else _crear_modelo
        self._modelo = None
        self._indice = None
        self._actualizacion = Lock()
        self._estado = Lock()
        self._encoder = Lock()

    def _codificar(self, textos):
        import numpy as np
        with self._encoder:
            if self._modelo is None:
                self._modelo = self._fabrica_modelo()
            return np.array(self._modelo.encode(textos), dtype=float, copy=True)

    @staticmethod
    def _matriz(valores, filas):
        import numpy as np
        matriz = np.array(valores, dtype=float, copy=True)
        if (matriz.ndim != 2 or matriz.shape[0] != filas
                or (filas and matriz.shape[1] == 0) or not np.isfinite(matriz).all()):
            raise ValueError("Embeddings con forma o valores inválidos")
        # El respaldo bytes evita reactivar escritura con setflags(write=True).
        return np.frombuffer(matriz.tobytes(), dtype=float).reshape(matriz.shape)

    def _construir(self, version):
        registros = tuple(MappingProxyType({"nombre": d["nombre"], "contenido": d["contenido"]})
                          for d in self._cargador())
        textos = tuple(d["contenido"] for d in registros if d["contenido"].strip())
        fragmentos = tuple(MappingProxyType(dict(f)) for f in preparar_fragmentos(registros))
        textos_fragmentos = tuple(f["contenido"] for f in fragmentos)
        documentos_vec = self._matriz(self._codificar(list(textos)), len(textos)) if textos else self._matriz_vacia()
        fragmentos_vec = self._matriz(self._codificar(list(textos_fragmentos)), len(fragmentos)) if fragmentos else self._matriz_vacia()
        if textos and fragmentos and documentos_vec.shape[1] != fragmentos_vec.shape[1]:
            raise ValueError("Dimensiones de embeddings incompatibles")
        return IndiceRAG(version, registros, textos, fragmentos, documentos_vec, fragmentos_vec)

    def _matriz_vacia(self):
        import numpy as np
        return self._matriz(np.empty((0, 0)), 0)

    def _publicar_nuevo(self):
        # Llamar solo con _actualizacion adquirido; no se toca estado activo
        # hasta terminar toda la construcción y validación.
        with self._estado:
            version = 1 if self._indice is None else self._indice.version + 1
        try:
            candidato = self._construir(version)
        except Exception as exc:
            logger.warning("indice_construccion_error")
            mensaje = ("No se ha podido inicializar el índice. Puedes volver a intentarlo."
                       if version == 1 else
                       "No se ha podido actualizar el índice. La versión anterior se conserva.")
            raise ErrorIndice(mensaje) from exc
        with self._estado:
            self._indice = candidato
        logger.info("indice_publicado version=%d", candidato.version)
        return candidato

    def inicializar(self):
        with self._estado:
            indice = self._indice
        if indice is not None:
            return indice
        with self._actualizacion:
            with self._estado:
                indice = self._indice
            return indice if indice is not None else self._publicar_nuevo()

    def actualizar(self):
        with self._actualizacion:
            return self._publicar_nuevo()

    def _similitudes(self, consulta, matriz):
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            return cosine_similarity(self._codificar([consulta]), matriz)[0]
        except Exception as exc:
            logger.warning("indice_busqueda_error")
            raise ErrorIndice("No se ha podido calcular la búsqueda en el índice.") from exc

    def puntuar_documentos(self, consulta):
        validar_pregunta(consulta)
        indice = self.inicializar()
        if not indice.documentos:
            return []
        puntuaciones = self._similitudes(consulta, indice.embeddings_documentos)
        return list(zip(indice.documentos, map(float, puntuaciones)))

    def recuperar_contexto(self, consulta):
        pares = sorted(self.puntuar_documentos(consulta), key=lambda par: par[1], reverse=True)
        return [texto for texto, puntuacion in pares[:2] if puntuacion >= 0.20]

    def recuperar_fragmentos(self, consulta, limite=2, umbral=0.20):
        validar_pregunta(consulta)
        import numpy as np
        indice = self.inicializar()
        if not indice.fragmentos:
            return []
        puntuaciones = self._similitudes(consulta, indice.embeddings_fragmentos)
        resultados = []
        for posicion in np.argsort(puntuaciones)[::-1][:limite]:
            if puntuaciones[posicion] >= umbral:
                resultado = dict(indice.fragmentos[posicion])
                resultado["similitud"] = float(puntuaciones[posicion])
                resultados.append(resultado)
        return resultados


_motor = MotorRAG()


def inicializar_indice():
    return _motor.inicializar()


def actualizar_indice():
    _motor.actualizar()


def puntuar_documentos(consulta):
    return _motor.puntuar_documentos(consulta)


def recuperar_contexto(consulta):
    return _motor.recuperar_contexto(consulta)


def recuperar_fragmentos(consulta, limite=2, umbral=0.20):
    return _motor.recuperar_fragmentos(consulta, limite, umbral)

def generar_respuesta(pregunta, contexto, devolver_detalles=False):
    """Devuelve texto/detalles en éxito; lanza ErrorOllama ante fallos técnicos."""
    validar_pregunta(pregunta)
    contexto_texto = "\n".join(contexto)

    prompt = f"""
Responde utilizando únicamente el contexto proporcionado.
Si no encuentras la respuesta, indica que no lo sabes.
No inventes información.
Responde en una o dos frases cuando la pregunta sea sencilla.
Responde exclusivamente a lo que se pregunta. No añadas información que no sea necesaria para responder.

Contexto:
{contexto_texto}

Pregunta:
{pregunta}
"""
    return _generar_con_prompt(prompt, contexto_texto, devolver_detalles)


def _generar_con_prompt(prompt, contexto_texto, devolver_detalles=False):
    """Transporte y filtros comunes. Producción siempre construye su prompt A."""
    import requests

    inicio = perf_counter()
    respuesta = None
    try:
        with limitar_generacion():
            respuesta = requests.post(
                configuracion.URL_OLLAMA,
                json={
                    "model": MODELO_LLM,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0}
                },
                timeout=configuracion.OLLAMA_TIMEOUT_S
            )
            respuesta.raise_for_status()
    except ServicioOcupado as exc:
        raise ErrorOllama(str(exc)) from None
    except requests.exceptions.Timeout as exc:
        logger.warning("ollama_timeout")
        raise ErrorOllama("Ollama ha tardado demasiado en responder. Inténtalo de nuevo.") from exc
    except requests.exceptions.ConnectionError as exc:
        logger.warning("ollama_conexion_error")
        raise ErrorOllama("No se puede conectar con Ollama. Comprueba que esté iniciado.") from exc
    except requests.exceptions.HTTPError as exc:
        # Response es falsy en HTTP 4xx/5xx: comprobar identidad, no truthiness.
        respuesta_error = exc.response if exc.response is not None else respuesta
        estado_http = getattr(respuesta_error, "status_code", None)
        if type(estado_http) is not int or not 100 <= estado_http <= 599:
            estado_http = None
        duracion = max(0.0, perf_counter() - inicio)
        incidencia = uuid4().hex
        codigo = estado_http if estado_http is not None else "desconocido"
        logger.warning("ollama_http_error estado_http=%s duracion_s=%.3f incidencia=%s", codigo, duracion, incidencia,
                       extra={"estado_http": estado_http, "duracion_s": duracion, "incidencia": incidencia})
        raise ErrorOllama(f"Ollama ha rechazado la solicitud (HTTP {codigo}). "
                          f"Incidencia: {incidencia}. Comprueba el servicio y el modelo configurado.") from None
    except requests.exceptions.RequestException as exc:
        logger.warning("ollama_comunicacion_error")
        raise ErrorOllama("No se ha podido completar la comunicación con Ollama.") from exc

    try:
        datos_ollama = respuesta.json()
    except ValueError as exc:
        logger.warning("ollama_json_error")
        raise ErrorOllama("Ollama ha devuelto una respuesta JSON inválida.") from exc

    if (not isinstance(datos_ollama, dict)
            or "error" in datos_ollama
            or not isinstance(datos_ollama.get("response"), str)
            or not datos_ollama["response"].strip()):
        logger.warning("ollama_respuesta_invalida")
        raise ErrorOllama("Ollama ha devuelto una respuesta incompleta o inválida.")

    # Las métricas son opcionales: un valor mal formado no debe invalidar texto
    # correcto ni provocar errores aritméticos al imprimir los tiempos.
    for clave in ("eval_count", "eval_duration", "prompt_eval_duration",
                  "total_duration", "load_duration"):
        valor = datos_ollama.get(clave, 0)
        if not isinstance(valor, (int, float)) or isinstance(valor, bool) or valor < 0:
            valor = 0
        datos_ollama[clave] = valor

    import re

    texto_respuesta = datos_ollama["response"]

    anios = re.findall(r"\b(?:18|19|20)\d{2}\b", texto_respuesta)

    texto_final = texto_respuesta

    for anio in anios:
        if anio not in contexto_texto:
            logger.warning("respuesta_filtrada")
            texto_final = "No tengo información suficiente para confirmar esa fecha."
            break

    logger.info("generacion_ok duracion_s=%.3f bloqueada=%s", perf_counter() - inicio, texto_respuesta != texto_final)
    if devolver_detalles:
        return {
            "respuesta_original": texto_respuesta,
            "respuesta_final": texto_final,
            "bloqueada": texto_respuesta != texto_final
        }

    return texto_final

def _ejecutar_cli():
    """Cliente de consola sobre las mismas funciones públicas que la interfaz."""
    from operacion import configurar_logging
    configurar_logging()
    while True:

        consulta = input("¿Qué quieres buscar? ")

        if consulta.strip().lower() == "salir":
            print("Cerrando buscador semántico...")
            break

        if not consulta.strip():
            print("Debes escribir algo para buscar.")
            continue

        try:
            contexto = recuperar_contexto(consulta)[:1]
            if not contexto:
                print("No tengo información suficiente para responder.")
                continue
            respuesta = generar_respuesta(consulta, contexto)
        except (ErrorIndice, ErrorOllama, ErrorConsulta) as error:
            print("ERROR:", error)
            continue
        print("RESPUESTA DE NUESTRA IA:", respuesta)


if __name__ == "__main__":
    _ejecutar_cli()
