# Presentación técnica del proyecto

## Explicación de un minuto

Este proyecto permite consultar una pequeña biblioteca TXT/PDF desde Streamlit.
Recupera fragmentos por similitud de embeddings y entrega ese contexto a Qwen a
través de Ollama local. Muestra las fuentes recuperadas y puede abstenerse cuando
falta información. El trabajo de ingeniería se centra en construir un índice
coherente, conservarlo si falla una actualización, validar documentos y medir
recuperación y generación por separado.

Es una demo local, sin autenticación ni aislamiento entre usuarios. No se presenta
como un servicio web listo para producción. Hay una incidencia intermitente de CUDA
en Ollama documentada; no se ha ocultado mediante reintentos ni precalentamiento.

## Cómo explicar el trabajo con transparencia

El desarrollo se realizó con asistencia de un agente de programación de IA y
supervisión del responsable del proyecto. No atribuirse programación íntegramente
manual ni experiencia de operación pública que no se haya realizado.

| Parte | Qué explicar y demostrar |
|---|---|
| Diseño | Requisitos, alcance local, compatibilidad y decisiones aprobadas por hitos |
| Programación asistida | El agente propuso e implementó código, tests y documentación; la persona dirigió y aprobó las entregas |
| Verificación automática | Tests con mocks, corpus ficticios, atomicidad, concurrencia, errores HTTP e instalación aislada |
| Verificación humana | Pruebas reales de demo, revisión de fidelidad/completitud y decisiones sobre variantes |
| Decisiones de ingeniería | Mantener A al detectar regresión en C, separar resultados del modelo y decisiones del sistema, aplazar CPU/GPU por RAM |

Conviene preparar la explicación del código relevante antes de una entrevista:
qué protege cada bloqueo, cuándo se publica la instantánea y qué ocurre al fallar.
Los commits y tests permiten enseñar el razonamiento; usar IA no sustituye poder
explicar y mantener lo entregado.

## Preguntas técnicas para preparar

- ¿Por qué RAG? Añade evidencia recuperada sin reentrenar el modelo; depende de
  la cobertura del contexto y de que el generador lo utilice correctamente.
- ¿Por qué memoria y similitud coseno? Son suficientes para la escala actual;
  no se ha medido una necesidad de base vectorial o infraestructura adicional.
- ¿Qué significa actualización atómica? Construir y validar antes de publicar;
  ante error, mantener la instantánea previa en ese proceso. No es persistencia.
- ¿Cómo se mide calidad? Separar recuperación, abstención, completitud y fidelidad;
  las palabras clave no sustituyen juicios semánticos humanos.
- ¿Por qué no promover C? Mejor claridad no compensó una regresión de completitud
  en H616. El reservado no se reutilizó para ajustar el prompt.
- ¿Qué falta? Resolver CUDA, validar otras plataformas, aislar parsers hostiles y
  diseñar autenticación/aislamiento antes de un despliegue web.

## Capturas reales propuestas

No se han creado imágenes ni se han ejecutado modelos para esta documentación.
En una sesión manual futura, usar solo el corpus de `demo/corpus/`:

1. Pantalla inicial: biblioteca ficticia, sin uploader y URL loopback.
2. Pregunta directa: respuesta de 8 euros y fuente `centro.txt`.
3. Pregunta combinada: 11 euros y 11:30, con `centro.txt` y `taller.txt`.
4. Pregunta sobre teléfono: abstención sin inventar un número.
5. Opcional: resultado de tests y error controlado, sin terminal con datos privados.

Antes de incorporar una captura, revisar pestañas, usuario de Windows, rutas,
notificaciones, nombres privados y consola. Recortar lo ajeno a la demo, identificar
fecha y condiciones y no presentar respuestas esperadas como resultados observados.
No añadir archivos de imagen vacíos ni simulaciones de la interfaz.

## Demo de entrevista

Seguir [el guion de demo](../demo/README.md), con pesos preparados, puerto libre y
RAM disponible. Una primera consulta puede fallar por la incidencia CUDA. Explicar
el diagnóstico y mostrar el error controlado; no prometer disponibilidad perfecta.
Mantener a mano los tests como evidencia independiente del funcionamiento del LLM.
