import streamlit as st
import time
import configuracion
from buscador_semantico import (
    recuperar_fragmentos, generar_respuesta, actualizar_indice, ErrorOllama, ErrorIndice,
)
from pathlib import Path
from documentos import guardar_documento, ErrorDocumento
from operacion import configurar_logging, validar_pregunta, ErrorConsulta

configurar_logging()

st.title("🤖 Mi asistente de inteligencia artificial")

st.write("Bienvenido a mi primera aplicación de IA.")

st.write("Pronto podrás hacer preguntas a tus documentos.")

st.subheader("📁 Mis documentos")


def _indexar_biblioteca(documento_guardado=False):
    estado = {"operacion": "guardar" if documento_guardado else "actualizar",
              "guardado": documento_guardado, "indice": "pendiente"}
    st.session_state["estado_biblioteca"] = estado
    etiqueta = "Documento guardado. Indexando documentos..." if documento_guardado else "Actualizando el índice..."
    with st.status(etiqueta, expanded=True) as progreso:
        try:
            actualizar_indice()
        except ErrorIndice as error:
            estado.update(indice="error", mensaje=str(error))
            progreso.update(label="No se pudo actualizar el índice", state="error", expanded=False)
        else:
            estado["indice"] = "actualizado"
            progreso.update(label="Índice actualizado", state="complete", expanded=False)
    st.session_state["estado_biblioteca"] = estado


def _mostrar_estado_biblioteca():
    estado = st.session_state.get("estado_biblioteca")
    if not estado:
        return
    if estado["indice"] == "actualizado":
        if estado["guardado"]:
            st.success("Documento guardado correctamente. Índice actualizado.")
        else:
            st.success("Biblioteca actualizada correctamente.")
    elif estado["indice"] == "error":
        prefijo = "Documento guardado. No se pudo actualizar el índice. " if estado["guardado"] else ""
        st.error(prefijo + estado["mensaje"])
    elif estado["indice"] == "rechazado":
        st.error(estado["mensaje"])
    else:
        st.info("Documento guardado; indexación pendiente." if estado["guardado"] else "Actualización pendiente.")


if st.button("🔄 Actualizar biblioteca"):
    _indexar_biblioteca()

archivo_subido = None
if configuracion.PERMITIR_SUBIDAS:
    archivo_subido = st.file_uploader(
        "Sube un documento TXT o PDF",
        type=["txt", "pdf"],
        max_upload_size=configuracion.MAX_ARCHIVO_MB,
    )
else:
    st.caption("Las subidas están deshabilitadas en esta demo.")

if archivo_subido is not None:

    if st.button("Guardar documento"):

        carpeta = configuracion.carpeta_documentos(Path(__file__).resolve().parent)
        try:
            if getattr(archivo_subido, "size", 0) > configuracion.MAX_ARCHIVO_BYTES:
                raise ErrorDocumento("El archivo supera el tamaño máximo permitido.")
            guardar_documento(archivo_subido.name, archivo_subido.getvalue(), carpeta)
        except ErrorDocumento as error:
            st.session_state["estado_biblioteca"] = {
                "operacion": "guardar", "guardado": False, "indice": "rechazado", "mensaje": str(error)}
        else:
            _indexar_biblioteca(documento_guardado=True)

_mostrar_estado_biblioteca()

pregunta = st.text_input("Escribe tu pregunta:", max_chars=configuracion.MAX_PREGUNTA_CARACTERES)

if pregunta:
    st.write("Has preguntado:", pregunta)

    if st.button("Buscar en mis documentos"):

        inicio_total = time.perf_counter()

        inicio_busqueda = time.perf_counter()

        try:
            validar_pregunta(pregunta)
            fragmentos = recuperar_fragmentos(pregunta)
        except (ErrorIndice, ErrorConsulta) as error:
            st.error(str(error))
            st.stop()

        contexto = [fragmento["contenido"] for fragmento in fragmentos]

        fuentes = list(dict.fromkeys(fragmento["nombre"] for fragmento in fragmentos))

        tiempo_busqueda = time.perf_counter() - inicio_busqueda

        st.caption(f"🔎 Tiempo de búsqueda: {tiempo_busqueda:.2f} segundos")

        if contexto:
            inicio = time.perf_counter()

            with st.spinner("La IA está pensando..."):
                try:
                    respuesta = generar_respuesta(pregunta, contexto)
                except (ErrorOllama, ErrorConsulta) as error:
                    st.error(str(error))
                    st.stop()

            duracion = time.perf_counter() - inicio

            tiempo_total = time.perf_counter() - inicio_total

            st.caption(f"🚀 Tiempo total del RAG: {tiempo_total:.2f} segundos")

            st.caption(f"⏱️ Tiempo de generación: {duracion:.2f} segundos")

            st.subheader("🤖 Respuesta de nuestra IA")
            st.write(respuesta)

            if fuentes:
                st.caption("📄 Fuentes recuperadas: " + ", ".join(fuentes))
        else:
            st.warning("No he encontrado información suficiente.")
