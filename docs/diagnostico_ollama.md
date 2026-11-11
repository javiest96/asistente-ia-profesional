# H8, fase C: diagnóstico HTTP e interfaz

## Qué se ha observado

El usuario completó las tres preguntas de la demo: 8 euros, 11 euros y 11:30 con
las dos fuentes, y abstención ante teléfono ausente. En dos sesiones también
observó un rechazo inicial del RAG, una petición directa correcta y una consulta
RAG posterior correcta. No se ha ejecutado Qwen para investigar esta fase.

La comparación con la estructura directa proporcionada por el usuario es:

| Campo | RAG | Petición directa que funcionó |
|---|---|---|
| Cliente/método | Python requests, POST | Python requests, POST desde PowerShell/VS Code |
| Endpoint local | `http://127.0.0.1:11434/api/generate` en la demo | El mismo |
| Modelo | `qwen3.5:4b` | El mismo |
| `stream` / `think` | `false` / `false` | Los mismos |
| Timeout de requests | 120 s por defecto, fuera del JSON | 120 s, fuera del JSON |
| `options` | `temperature: 0` | Ausente en la última prueba; presente y correcto en otra anterior |
| Prompt | Plantilla A con pregunta y contexto | Texto de prueba directo |

No se almacenan aquí textos de prompts, documentos o respuestas. No se conoce una
captura completa de cabeceras/entorno de la llamada directa: no afirmar identidad
completa más allá de los campos confirmados. La segunda llamada RAG funcionó con
el mismo código. No hay evidencia de que `temperature: 0` sea una opción inválida.

En una lectura de solo metadatos del registro local de Ollama se observaron:

| Fecha/hora local | HTTP | Duración del servidor |
|---|---:|---:|
| 2026-11-11 16:07:14 | 500 | 11 s |
| 2026-11-11 16:12:43 | 200 | 9,6 s |
| 2026-11-11 18:17:34 | 500 | 13,62 s |
| 2026-11-11 18:18:55 | 200 | 9,61 s |

En ambas franjas fallidas aparecen errores de inicialización CUDA. Esto es
evidencia para investigar el backend y difiere de un timeout de requests o un
rechazo local por concurrencia. Sin IDs previos no se puede atribuir cada registro
inequívocamente a un cliente, ni determinar la causa técnica de CUDA. No se ha
demostrado que el problema sea memoria, driver, carga inicial del modelo o tamaño
del contexto. Que la llamada directa preceda a un éxito no prueba por sí solo que
«calentar» el modelo sea una solución.

No se cambian prompt, parámetros, timeout predeterminado, dispositivo o modelos.
No se introducen reintentos ni peticiones de calentamiento. Una repetición puede
duplicar cómputo si el servidor siguió trabajando y además ocultaría evidencia.

## Incidencia correlacionada y prueba CPU/GPU aplazada

El usuario recuperó de la consola el evento técnico exacto:

```text
2026-11-11 18:40:57,272 WARNING rag ollama_http_error estado_http=500 duracion_s=12.688 incidencia=ad2b7a5a9c8540d9b0b5c2fddbfdd94f
```

Coincide temporalmente con el HTTP 500 de Ollama de las 18:40:57,271 y su
duración aproximada de 12,68 s. En ese intervalo aparecen errores
`CUDA error: shared object initialization failed`. La diferencia de 1 ms y las
duraciones concordantes vinculan sólidamente ambos eventos, aunque no existe
un identificador de petición compartido entre cliente y servidor. Son horas
locales de Madrid del 11 de noviembre de 2026; el registro de Ollama indica +01:00.

La causa interna sigue sin confirmarse. No se ha demostrado falta de memoria,
incompatibilidad del controlador, un defecto del prompt ni que precalentar el
modelo resuelva el problema. La duración del cliente mide comunicación hasta
el error; no debe interpretarse como tiempo de inferencia o carga del modelo.

Se decidió posponer la comparación CPU/GPU por precaución ante los **5,62 GiB
de RAM disponibles** comunicados por el usuario. El puerto 11435 estaba libre,
pero no se inició una segunda instancia ni se ejecutó esa comparación. Este
margen no demuestra que la incidencia original se deba a memoria insuficiente.
No se modificaron variables permanentes, servidor, prompt A ni parámetros.
Una prueba futura requerirá autorización, revisar memoria disponible y verificar
el backend real; no se incorpora una conmutación automática a CPU.

## Formato y privacidad del evento HTTP

Ejemplo ilustrativo, no un incidente real:

```text
WARNING rag ollama_http_error estado_http=503 duracion_s=2.500 incidencia=0123456789abcdef0123456789abcdef
```

El ID aleatorio se genera por fallo y también aparece en `ErrorOllama`, de modo
que la interfaz/CLI pueden mostrar una referencia que coincida con la consola.
El código y duración también están en campos del LogRecord. Duración es tiempo
local de comunicación hasta el error, no tiempo de carga del modelo. Si no se
dispone de un estado HTTP válido se indica `desconocido`, sin inventar un código.
Un error HTTP no se muestra como una respuesta válida del modelo.

Solo se registra estado numérico, duración e ID; no cuerpos HTTP, prompts,
preguntas, respuestas, fragmentos, URLs con credenciales, cabeceras, excepción
original ni traceback. No se crean archivos de log nuevos. El logger existente
`rag` sigue escribiendo a consola; si se redirige a disco, aplicar retención.

Se conserva la respuesta HTTP aunque su valor booleano sea falso en 4xx/5xx.
No se accede al JSON del modelo tras un error de estado. La lógica del filtro de
años y el prompt A permanecen idénticos. Las evaluaciones históricas no se modifican.

En una nueva prueba manual **pendiente de autorización**, conservar ID, código,
hora y duración del primer fallo; correlacionar con eventos técnicos saneados de
Ollama. No hacer primero una llamada de calentamiento para ocultar el fallo ni
volcar logs completos. Si reaparece el error CUDA, revisar versiones del servicio,
GPU/driver y estado del backend antes de decidir otro experimento. No cambiar
dependencias, parámetros o dispositivo automáticamente.

## Confirmación persistente e indexación

`app.py` conserva en `st.session_state['estado_biblioteca']` únicamente el resultado
de la última operación: guardado, índice pendiente/actualizado/error o rechazo.
No guarda el contenido del documento en ese estado.

- Tras un guardado válido, `st.status` muestra inmediatamente «Documento guardado»
  e indexación en curso, sin porcentaje ficticio.
- Si termina, confirma «Documento guardado correctamente. Índice actualizado».
- Si falla, distingue archivo guardado de índice no actualizado y muestra el error
  público del motor. La instantánea anterior permanece activa si existía; si la
  primera inicialización falla, no se afirma que exista una versión anterior.
- Escribir otra pregunta no borra la confirmación ni vuelve a guardar/indexar.
- Una nueva operación sustituye el estado anterior. Rechazar un duplicado no deja
  un éxito anterior engañoso; actualizar manualmente permite reintentar el índice
  de forma explícita y reemplaza el aviso si termina correctamente.

El estado es por sesión de Streamlit: una nueva sesión puede perder esos avisos.
No es un historial persistido ni prueba de que un índice sobreviva a reinicios.

## Pruebas

`tests/test_interfaz_diagnostico.py` usa requests simulado y AppTest con corpus
ficticio temporal. Cubre 400/404/500/503, duración/ID, privacidad, una sola llamada,
estado desconocido, payload conservado, progreso y persistencia, conservación de
índice y primer fallo sin índice. No llama a Qwen ni a embeddings reales.

Las Fases A/B conservan sus scripts, lock, corpus y controles. La instalación
limpia ya validada corresponde al commit exportado `a5e3ee0`; no certifica estos
cambios nuevos de interfaz, que requieren revisión/manual posterior.
