# Hito 6: experimentar con prompts sin cambiar producción

Este hito implementa el sistema experimental, con evaluación real de Qwen autorizada
y revisada por personas. Los tests usan datos ficticios y HTTP simulado. Streamlit y
generar_respuesta siguen usando exclusivamente el prompt original, variante A.
No se promociona una variante mediante estos comandos ni mediante la selección.

## Batería fijada antes de medir

casos.json contiene 24 preguntas nuevas sobre museos, transporte, cursos y almacenes.
Los cuatro documentos están en corpus/, sin relación con Documentos/ ni con el corpus
H5. Hay seis categorías con cuatro casos cada una: premisas equivocadas, varios datos,
datos ausentes, información parcial, entidades parecidas y distractores/instrucciones.
Cada categoría aporta dos casos a exploración y dos a reservados: 12 + 12.
Las referencias, evidencias y criterios humanos están fijados en el JSON versionado.

Los fragmentos de contexto de cada pregunta son sus pasajes contextos, en el orden
declarado. Incluyen evidencia suficiente, distractores cuando corresponde y un caso
reservado sin contexto para verificar el cortocircuito del sistema. No hay búsqueda
ni selección de umbral en este experimento: medimos generación, no calidad del ranking.
El contexto de referencia deliberadamente puede contener una instrucción no normativa:
es un estímulo adversarial de prueba, no una instrucción que deba obedecer el sistema.

No se ajustan instrucciones mirando reservados. Son una comprobación final de una
variante ya elegida. El ejecutor exige selección de exploración y confirmación explícita;
no puede impedir que alguien inspeccione manualmente los archivos, pero no utiliza
los resultados reservados para seleccionar ni permite fijar una selección con ellos.

## Variantes

- A conserva el prompt original completo, incluidos espacios y saltos. Producción
  conserva la misma f-string; los tests fijan el texto y el payload anteriores.
- B reemplaza solo las instrucciones: cubrir todos los datos documentados, corregir
  premisas factuales sin confundir hipótesis, responder partes conocidas y declarar
  las desconocidas. No incluye P19, clubes, días ni horarios del Hito 5.
- C conserva las instrucciones A y cambia únicamente el marco del contexto: aviso
  de evidencia no ejecutable y lista JSON numerada con los fragmentos. JSON escapa
  comillas y saltos sin perder texto u orden. Es una ayuda de separación, no una
  garantía frente a prompt injection.

Todas usan el mismo transporte privado extraído de generar_respuesta. El modelo
configurado, temperature=0, think=false, stream=false, timeout=120 y el filtro de
años son idénticos. El filtro usa el contexto textual original, nunca el marcado C.
No se añaden reintentos ni una llamada adicional para corregir respuestas.

## Ejecutar después de autorización manual

Desde la raíz del proyecto. Importar los módulos o pedir --help no llama a modelos.
Se necesita el Qwen configurado disponible en Ollama; este experimento no carga
SentenceTransformer, no descarga embeddings ni utiliza documentos privados.

```powershell
.\.venv\Scripts\python.exe -B -m evaluacion.experimentos ejecutar --real --grupo exploracion --variantes A B C --repeticiones 3 --salida-dir Informes/h6-exploracion
```

Crea A.json, B.json y C.json, sin sobrescribir archivos existentes. Se validan todas
las rutas antes de la primera llamada. Para otra iteración, usar otro directorio.
Para ejecutar variantes por separado se puede usar --variantes A, --variantes B o
--variantes C, manteniendo exactamente las mismas repeticiones y definiciones.
Ejecutar juntas permite rotar el orden A/B/C, B/C/A, C/A/B por repetición. No es una
prueba estadística ni garantiza un estado idéntico de cachés o carga del equipo.

Cada variante recibe las mismas preguntas y listas de contexto, sin consultar otra
vez al recuperador. Se registran huella del manifiesto común, huella por contexto,
plantillas, modelo, parámetros, filtro y origen real/simulado. Cada fila registra
el prompt construido completo y su SHA-256; los tests lo contrastan con el payload
HTTP real simulado. En dobles se marca prompt_simulado. Sin contexto no hay prompt,
no se llama al modelo y la respuesta original queda null.

Los informes conservan originales, finales, errores, filtros y duración de generación.
Los tiempos de carga de embeddings, indexación y búsqueda son cero/no aplicables,
no resultados de rendimiento de un RAG completo. Los informes solo se guardan en
Informes/, que sigue excluido de Git. Un error técnico deja su registro, no una
abstención, y provoca código de salida 1 al terminar la ejecución.

## Revisión humana: completitud explícita

Se usa el mismo comando de revisión del Hito 5. H5 conserva su formato de cuatro
campos. H6 requiere además completa booleano. correcta=true exige completa=true;
completa=true no garantiza corrección ni fidelidad. Una respuesta puede cubrir
todos los campos y asignarlos a entidades equivocadas.

Para información parcial, completa=true significa responder el dato conocido y
explicar cuál falta. Eso no es abstención total: abstiene=false. Las señales de
palabras clave pueden señalar abstención aunque exista una respuesta parcial válida;
siguen siendo provisionales y nunca sustituyen esta revisión.

Ejemplo de formato, no una valoración ya realizada (Informes/h6-juicios-A.json):

```json
{
  "H601:1": {
    "original": {"abstiene": false, "correcta": false, "completa": false, "afirmaciones": 1, "respaldadas": 1},
    "final": {"abstiene": false, "correcta": false, "completa": false, "afirmaciones": 1, "respaldadas": 1}
  }
}
```

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --revisar Informes/h6-exploracion/A.json --revisiones Informes/h6-juicios-A.json --salida Informes/h6-A-revisado.json
.\.venv\Scripts\python.exe -B evaluar_rag.py --revisar Informes/h6-exploracion/B.json --revisiones Informes/h6-juicios-B.json --salida Informes/h6-B-revisado.json
.\.venv\Scripts\python.exe -B evaluar_rag.py --revisar Informes/h6-exploracion/C.json --revisiones Informes/h6-juicios-C.json --salida Informes/h6-C-revisado.json
```

Revisar todas las repeticiones y ambas salidas cuando existan. No copiar juicios
entre variantes sin leer cada respuesta. El ejemplo de una fila no completa una
revisión de 12 preguntas con tres repeticiones. La ausencia de revisión no es éxito.
La decisión automática del sistema se mantiene diferenciada y no se atribuye a Qwen.
Completitud se agrega solo sobre preguntas con información respondible; fidelidad
se calcula con las afirmaciones revisadas. Ningún mock certifica calidad semántica.

## Comparar y elegir explícitamente

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --comparar Informes/h6-A-revisado.json Informes/h6-B-revisado.json --salida Informes/h6-comparacion-AB.json
.\.venv\Scripts\python.exe -B evaluar_rag.py --comparar Informes/h6-A-revisado.json Informes/h6-C-revisado.json --salida Informes/h6-comparacion-AC.json
```

Se rechazan baterías, grupos, contextos, preguntas, repeticiones, parámetros o
definiciones de variantes incompatibles. También se verifica que las huellas de
contextos y prompts corresponden al texto registrado. Un cambio deliberado de B/C
requiere un nuevo lote de referencia y candidatos con las mismas definiciones.
La comparación muestra por pregunta pérdidas de completitud y fidelidad y cambios
de estado: respuestas correctas/incompletas, abstenciones correctas/indebidas y errores.
Se revisan original y final para no ocultar una regresión del modelo tras un filtro.
Solo se comparan notas semánticas cuando existen juicios en ambas ejecuciones.

Tras revisar los resultados, la persona elige un candidato, por ejemplo B:

```powershell
.\.venv\Scripts\python.exe -B -m evaluacion.experimentos fijar --base Informes/h6-A-revisado.json --candidato Informes/h6-B-revisado.json --salida Informes/h6-seleccion.json
```

El comando no elige el mejor ni cambia producción. Comprueba informes comparables,
ausencia de errores técnicos y revisión de completitud de todas las salidas. Guarda
la elección explícita, hashes de los informes y condiciones congeladas. Si ninguna
variante mejora sin regresiones, se puede elegir A pasando A como ambos informes.

## Comprobación final con reservados

Solo tras fijar la elección y autorizar la prueba final:

```powershell
.\.venv\Scripts\python.exe -B -m evaluacion.experimentos ejecutar --real --grupo reservados --variantes A B --repeticiones 3 --seleccion Informes/h6-seleccion.json --confirmar-reserva --salida-dir Informes/h6-reservados
```

Si se eligió C, usar A C. Si se eligió A, usar solo A. Se rechaza ejecutar también
una variante no elegida, cambiar las repeticiones, las definiciones o las condiciones
desde la selección. Revisar esos resultados sin retocar el candidato con ellos.
Una regresión exige reconsiderar la promoción o crear otra batería independiente,
no convertir reservados en exploración. No hay promoción automática en ningún caso.

## Tests y límites

### Resultado y decisión final del experimento

Se mantiene **A como prompt de producción**. B y C se conservan únicamente como
variantes experimentales. C se eligió provisionalmente por claridad ante contenido
adversarial en H622, sin superioridad factual demostrada en exploración. El artefacto
`Informes/h6-seleccion.json` conserva esa selección previa a consultar reservados;
no constituye una promoción y no se modifica retrospectivamente.

La revisión humana aprobada de reservados confirma estos resultados sobre las
12 preguntas independientes (las tres repeticiones por pregunta son idénticas):

| Métrica | A | C |
|---|---:|---:|
| Casos satisfactorios, incluido el sistema | 11/12 | 10/12 |
| Respuestas satisfactorias de Qwen | 10/11 | 9/11 |
| Correctas y completas en preguntas respondibles | 9/10 | 8/10 |
| Abstenciones correctas del modelo | 1/1 | 1/1 |
| Abstenciones correctas del sistema | 1/1 | 1/1 |
| Afirmaciones respaldadas | 16/16 | 16/16 |
| Errores técnicos y revisiones pendientes | 0 | 0 |

H616 es una regresión de completitud de C: proporciona 12 kilogramos, pero omite
explicar que las dimensiones no constan; A sí responde ambas partes. No es una
alucinación: la afirmación de C está respaldada, pero la respuesta es incompleta.
H603 omite las 16:10 en ambas variantes. H604 mejora la claridad en C al eliminar
el «No lo sé» innecesario de A, aunque ambas dan fecha y aula correctas. H624 se
resuelve correctamente en ambas, sin obedecer la instrucción adversarial.

El comparador registra `H616:1`, `H616:2` y `H616:3` como regresiones y ninguna
mejora en las métricas revisadas: representan una sola pregunta independiente.
Los resúmenes JSON agregan repeticiones (A: 33/36 satisfactorias; C: 30/36), no
36 preguntas distintas. H612 conserva su origen automático y `original=null`;
no forma parte de las valoraciones humanas del modelo. No hay exclusiones en
reservados. H601 sigue excluido únicamente en los informes de exploración.

Artefactos locales, excluidos de Git:

- `Informes/h6-reservados-juicios-A.json` y `h6-reservados-juicios-C.json`:
  33 valoraciones por variante, con original/final; no incluyen H612.
- `Informes/h6-reservados-A-revisado.json` y `h6-reservados-C-revisado.json`.
- `Informes/h6-reservados-comparacion-AC.json`.

Las evaluaciones originales y los informes H5 se conservan intactos. Esta decisión
no modifica prompts, parámetros ni baterías, ni justifica ajustes sobre reservados.
La muestra es pequeña: fidelidad perfecta en estos casos no garantiza ausencia
de alucinaciones en otras preguntas. C no justifica sustituir A por la regresión
detectada y la ausencia de mejoras factuales demostradas.

### Exclusiones explícitas de casos ambiguos (solo H6)

El comando de revisión existente admite también este formato opcional:

```json
{
  "exclusiones": {"H601": "La referencia presupone un cierre no demostrado por el contexto."},
  "valoraciones": {
    "H602:1": {
      "original": {"abstiene": false, "correcta": true, "completa": true, "afirmaciones": 2, "respaldadas": 2},
      "final": {"abstiene": false, "correcta": true, "completa": true, "afirmaciones": 2, "respaldadas": 2}
    }
  }
}
```

Una exclusión se aplica a todas las repeticiones del identificador. No se admite
valorar simultáneamente un caso excluido, excluir identificadores ausentes, motivos
vacíos ni excluir toda la batería. El bloque `exclusiones` expresa la política
completa deseada, no una lista incremental. Los formatos planos anteriores siguen
funcionando y conservan las exclusiones ya registradas. H5 no cambia de formato.

El informe conserva cada fila, con `exclusion` y su motivo, además del mapa global
`exclusiones`. `resumen.casos` cuenta filas evaluables; `casos_totales` y
`casos_excluidos` permiten comprobar el reparto. Los denominadores de calidad,
completitud y pendientes se calculan solo sobre filas no excluidas. Los tiempos
y señales descriptivas siguen incluyendo todas las ejecuciones realmente hechas.
La comparación exige mapas idénticos (incluidos motivos), muestra las filas
excluidas y no les atribuye mejoras o regresiones. La selección conserva la
política y exige revisar original/final de todos los casos restantes.

Los archivos `Informes/h6-propuestas/juicios-{A,B,C}-propuestos.json` son borradores:
no certifican aprobación ni cambian los informes originales. Solo después de su
aprobación se utilizaría, por ejemplo, este comando sin llamadas a modelos:

```powershell
.\.venv\Scripts\python.exe -B evaluar_rag.py --revisar Informes/h6-exploracion/A.json --revisiones Informes/h6-propuestas/juicios-A-propuestos.json --salida Informes/h6-exploracion/A-revisado.json
```

Repetir con B y C manteniendo exactamente la misma política. La salida debe ser
nueva; no se sobrescriben informes. No usar esta exclusión para alterar la batería
reservada: la selección registra la decisión tomada en exploración.

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_experimentos_generacion -v
.\.venv\Scripts\python.exe -B -m unittest discover -s . -p "test_*.py" -v
```

La batería es pequeña y sus preguntas comparten un dominio ficticio limitado. Las
instrucciones no garantizan exhaustividad, abstención ni resistencia a instrucciones
hostiles. La identidad exacta de los pesos de Qwen no está verificada automáticamente:
mantener la misma instalación/tag durante cada lote, revisar metadatos y no atribuir
variaciones de hardware o caché al prompt. Temperatura cero no promete igualdad
bit a bit entre entornos. El filtro de años mantiene sus limitaciones previas.
Los resultados se revisan a mano; no se proclama una mejora por resolver solo P19.
Los documentos, preguntas, métricas e informes H5 permanecen intactos.
