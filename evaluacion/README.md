# Hito 5: calidad del RAG con datos ficticios

Para el sistema de experimentos H6, sin promoción del prompt de producción, ver
h6/README.md. La batería, fórmulas y comandos H5 mantienen su comportamiento.

Esta batería no utiliza Documentos/ ni modifica el motor o la interfaz. El corpus
es exclusivamente evaluacion/documentos/*.txt. Los scripts no ejecutan nada al
importarse. Sus antiguas evaluaciones sobre archivos personales quedan sustituidas
por estas entradas explícitas; el historial antiguo no se mezcla con el esquema 1.

## Tres niveles distintos

1. Tests deterministas: dobles de embeddings y generación. No descargan modelos,
   llaman a Ollama ni escriben informes dentro del proyecto; los archivos de prueba
   se crean en TemporaryDirectory. Comprueban fórmulas y comportamiento, no calidad
   semántica de un modelo real.
2. Recuperación real: usa el mismo MotorRAG.recuperar_fragmentos que Streamlit,
   con el mismo modelo y valores iniciales: 50 palabras, solapamiento 10, límite 2,
   umbral 0.20. No necesita Ollama.
3. Generación real: Qwen configurado en configuracion.py. Modalidad referencia
   entrega las evidencias correctas (o distractores en preguntas sin respuesta),
   sin cargar embeddings. Modalidad rag entrega solo el contexto recuperado.

Los tests conservan los 79 casos anteriores; el antiguo test que extraía un bloque
AST de evaluar_rag.py ahora comprueba la entrada de diagnóstico y sus fragmentos.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s . -p "test_*.py" -v
.\.venv\Scripts\python.exe -B -m unittest tests.test_evaluacion_rag -v
```

## Corpus, partición y métricas

casos.json contiene 20 preguntas, referencias, hechos esperados, incompatibilidades
y evidencias por pasajes únicos. Cada grupo fijo tiene 10 preguntas: 7 respondibles
y 3 sin respuesta, con casos factuales, negaciones y comparación. Calibración:
P01/P03/P05/P07/P09/P11/P13/P14/P16/P18. Validación: las otras diez. El caso de
premisa falsa P19 está reservado para validación; el pequeño conjunto no permite
representar todos los subtipos en ambos grupos.

- Cobertura: fracción de evidencias requeridas cuyas palabras están cubiertas por
  los fragmentos devueltos. La unión de ventanas puede completar un pasaje partido;
  el solapamiento no duplica evidencia. Se ignoran mayúsculas y espacios, no palabras.
- Contexto completo: todas las evidencias necesarias están cubiertas.
- Precisión: fragmentos que intersectan un pasaje esperado / fragmentos devueltos.
  Un fragmento parcialmente útil cuenta como relevante, aunque no complete el hecho.
- Para preguntas sin respuesta esas tres métricas son null (no aplicables). No se
  exige recuperar cero fragmentos: un texto relacionado puede no responder nada.
- Los agregados son medias por caso e indican n. En generación las repeticiones
  tienen igual peso. Recuperación completada sigue contando si luego falla Qwen.
- Error técnico tiene su contador y no es abstención ni respuesta errónea. Los
  denominadores semánticos solo incluyen juicios disponibles, con cobertura visible.
- Se conservan respuestas original/final y bloqueada. Las señales léxicas son
  provisionales, incluso si coinciden todos los hechos esperados. Pueden fallar con
  negaciones, sinónimos o frases como "no consta..., pero..."; no certifican semántica.
- Una abstención por falta de contexto es una decisión determinista del sistema:
  se marca como correcta en negativas o indebida en positivas, sin atribuirla al LLM.
  revisadas incluye decisiones evaluadas; revisadas_humanas y decisiones_sistema
  distinguen su origen. La respuesta original queda null si no se llamó a Qwen.

## Comandos reales (solo por decisión explícita del usuario)

Ejecutar desde la raíz. El entorno existente debe tener el modelo de embeddings
actual en su caché. SentenceTransformer se abre con local_files_only=True: si falta
el modelo no se descarga, se registra un error o se rechaza la calibración. Este
hito no instala ni descarga nada automáticamente.

Referencia inicial sin ajustar parámetros, solo recuperación:

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --real --modo recuperacion --grupo validacion --salida Informes/h5-base.json
```

Calibrar únicamente con los casos de calibración:

```powershell
.\.venv\Scripts\python.exe -B evaluar_umbrales.py --real --umbrales 0.20 0.30 0.40 0.50 --salida Informes/h5-seleccion.json
.\.venv\Scripts\python.exe -B evaluar_rag.py --real --modo recuperacion --grupo validacion --seleccion Informes/h5-seleccion.json --salida Informes/h5-validacion.json
```

El criterio es maximizar contexto completo; desempatar por precisión, cobertura y
menor umbral. Se reutiliza un modelo/índice para todos los candidatos. No se usan las
negativas como si proximidad semántica implicase existencia de respuesta. No volver
a elegir parámetros tras mirar validación: ampliar o crear otro conjunto reservado.
--seleccion verifica corpus, preguntas, modelo, origen, grupo y parámetros, y registra
la huella de la selección. Los valores --umbral fijos permiten medir una configuración
ya elegida; no convierten validación en un conjunto legítimo para ajustar parámetros.

Generación con Qwen, que debe estar disponible en Ollama:

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --real --modo referencia --grupo validacion --repeticiones 3 --salida Informes/h5-qwen-referencia.json
.\.venv\Scripts\python.exe -B evaluar_rag.py --real --modo rag --grupo validacion --repeticiones 3 --seleccion Informes/h5-seleccion.json --salida Informes/h5-qwen-rag.json
.\.venv\Scripts\python.exe -B probar_rag_fragmentos.py --real --caso P03
```

El diagnóstico muestra únicamente recuperación ficticia: no filtra por PDF ni llama
a Qwen. Los informes solo se guardan dentro de Informes/ (ya excluido de Git), no
sobrescriben archivos existentes y se rechazan otras rutas antes de ejecutar modelos.
Una ejecución con errores técnicos guarda su diagnóstico y devuelve código 1.
La calibración sin ningún candidato válido se rechaza y no publica una selección.

## Revisión humana de respuestas

Cada fila contiene contexto, referencia, texto original y final, señales, tiempos
y estado. Revisar las dos variantes por separado. Contar afirmaciones verificables,
cuántas están respaldadas por el contexto real entregado y si la respuesta cubre
lo preguntado sin contradicciones. No basta con comparar contra el conocimiento del
revisor: fidelidad mide respaldo en el contexto, no veracidad general.

abstiene=true significa que la respuesta realmente se abstiene de dar el dato; una
frase de desconocimiento seguida de una respuesta inventada no es abstención.
correcta=true significa respuesta completa y sin errores; no usarlo para premiar
la mera presencia de nombres, fechas o palabras clave.

Crear, por ejemplo, Informes/h5-juicios.json:

```json
{
  "P02:1": {
    "original": {"abstiene": false, "correcta": true, "afirmaciones": 2, "respaldadas": 2},
    "final": {"abstiene": false, "correcta": true, "afirmaciones": 2, "respaldadas": 2}
  }
}
```

La clave es pregunta:repetición. El ejemplo es un formato, no un juicio ya realizado.
Se pueden revisar progresivamente algunas filas. Nunca revisar un error técnico
como abstención. Fidelidad = afirmaciones respaldadas / afirmaciones emitidas;
sin afirmaciones es null, no un 100% automático. Las tasas de abstención correcta,
indebida y respuestas correctas muestran el tamaño de su denominador. Los pendientes
no se convierten en éxitos ni en fallos. No comparar porcentajes de muestras revisadas
distintas como si correspondieran al conjunto completo.

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --revisar Informes/h5-qwen-rag.json --revisiones Informes/h5-juicios.json --salida Informes/h5-qwen-rag-revisado.json
```

Este comando trabaja offline y conserva el informe original. No llama a modelos.

## Comparación y tiempos

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --comparar Informes/h5-base.json Informes/h5-validacion.json --salida Informes/h5-comparacion.json
```

Se rechazan corpus, preguntas, grupos, modalidades, orígenes simulados/reales,
repeticiones o fórmulas incompatibles. Se enumeran cambios de configuración/entorno,
resúmenes y transiciones por pregunta: pérdidas de cobertura, contexto completo,
precisión, nuevos errores y regresiones semánticas donde ambas filas están evaluadas.
Una pregunta puede mejorar cobertura y empeorar precisión: aparecerá en ambas listas.
No se proclama un ganador universal ni se mezcla el esquema antiguo de resultados.

Metadatos: commit, árbol sucio, hashes del corpus, preguntas, motor, prompt, evaluador
y métricas; modelo configurado, paquetes, Python y plataforma. Las etiquetas de
modelo no prueban identidad exacta de pesos: ambas identidades se marcan no_verificada.
Un mismo tag puede apuntar a pesos distintos. No se garantiza igualdad bit a bit
entre versiones de bibliotecas, dispositivos o respuestas de Ollama.

perf_counter mide lectura TXT, construcción del modelo, indexación residual,
búsqueda y generación por separado. Los documentos se leen una vez antes de construir
el motor; el cargador inyectado solo devuelve copias. Indexación total incluye carga
del modelo; indexacion_sin_carga_modelo_s la resta e incluye codificación, fragmentación,
validación, copias e imports necesarios. No sumar ambas cifras como fases distintas.
La carga de preguntas JSON y la preparación del informe quedan fuera de esos tiempos.

Búsqueda incluye embedding de consulta y selección, con índice inicializado. La
primera búsqueda puede incluir imports diferidos de sklearn. Generación incluye HTTP,
procesamiento de Ollama y filtros; no es el tiempo puro de inferencia ni separa la
carga interna de Qwen. Se muestra primera llamada observada y mediana/rango posteriores;
primera no significa necesariamente arranque en frío de Ollama o caché del disco.
Fallos temporizados se separan de éxitos. Con tres repeticiones no se calcula un p95
ni se afirma significación estadística. Comparar rendimiento en el mismo hardware.

## Límites y reversión

Son 20 preguntas y cuatro TXT: no representan PDF/OCR, corpus grandes ni calidad de
dominio real. Las evidencias deben ser pasajes únicos; si un cambio genera textos
ambiguos, el evaluador falla de forma explícita en lugar de inventar etiquetas.
La rúbrica humana tiene subjetividad; registrar juicios y revisar desacuerdos.
Los mocks nunca se usan para afirmar calidad semántica de los embeddings.
No se ajustan el motor, modelo, prompt ni umbral de producción con estos scripts.
El commit bb7a37c conserva el estado anterior; este hito queda sin commit final.
