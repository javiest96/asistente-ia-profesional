# Pruebas reproducibles del RAG

H7 añade `test_configuracion.py`, `test_documentos.py` y `test_operacion.py`:
configuración aislada, PDFs ficticios pequeños reales, guardado completo sin
sobrescritura, errores de almacenamiento, límites, privacidad de logs, concurrencia
y subidas deshabilitadas. Todo el corpus de pruebas se crea en temporales.
El test previo de subida de Streamlit habilita expresamente las subidas, ahora
desactivadas por defecto, conservando las mismas verificaciones de archivo e índice.

Hito 6 añade tests/test_experimentos_generacion.py: prompt A exacto, variantes B/C,
contextos idénticos, revisión de completitud, comparación y guardas de reservados.
No ejecuta modelos reales. Ver evaluacion/h6/README.md para los comandos manuales.

Desde la raíz, con el entorno existente:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s . -p "test_*.py" -v
.\.venv\Scripts\python.exe -B -m unittest test_buscador_semantico -v
.\.venv\Scripts\python.exe -B -m unittest tests.test_generar_respuesta -v
```

Se usa unittest de Python (TestCase.enterContext requiere Python >= 3.11).
No se instalan dependencias: se necesitan streamlit, numpy, scikit-learn, requests y pypdf
del entorno existente. pypdf todavía falta en requirements.txt; corregirlo
requiere una tarea de producción separada.

## Datos y aislamiento

- Todos los textos son ficticios. TXT y marcadores PDF se crean únicamente en
  TemporaryDirectory y se limpian al finalizar. Nunca se usa Documentos/ real.
- La carga TXT y la fragmentación son reales. PdfReader está simulado: se prueba
  la unión de páginas y sus fuentes, no la extracción de un PDF binario real.
- buscador_semantico.py se ejecuta en un módulo independiente por caso. Antes
  se sustituyen sentence_transformers y cargar_documentos en sys.modules;
  no se importa el modelo real ni se descargan pesos.
  El soporte inyecta un MotorRAG con dobles e inicializa explícitamente por defecto;
  inicializar=False permite comprobar el estado anterior a la primera operación.
- Los embeddings explícitos dan similitudes conocidas (1, 0.6, 0), sin empates.
  numpy y cosine_similarity son reales. Textos imprevistos fallan.
- HTTP y conexiones socket están bloqueados en las pruebas unitarias del buscador.
  AppTest permite sockets internos de asyncio en Windows; mantiene HTTP bloqueado
  y usa corpus/modelo simulados. La generación usa requests.post simulado.
- Los parches se restauran también ante excepciones. Hay pruebas de restauración
  de módulos y HTTP e independencia del índice entre cargas.
  Solo se restauran las claves sustituidas de sys.modules; restaurar el diccionario
  entero eliminaba imports nativos de scipy/numpy y causaba errores al recargarlos.
- No hacen falta Ollama, Internet ni archivos privados. AppTest ejecuta la interfaz
  en proceso sin abrir servidor web ni navegador.
  -B evita generar pyc. Los ejecutores reales solo se activan por comando explícito;
  los tests de evaluación inyectan modelos y generadores ficticios.

## Cobertura y aceptación

Fragmentación: vacío, corto, ventanas exactas, cola, solapamiento y parámetros
inválidos, fuentes y separación entre documentos. Carga: TXT UTF-8, extensiones,
carpeta vacía, páginas PDF con None y PDF sin texto. Recuperación: orden, límites,
umbrales, cero coincidencias, fuentes, copias y actualización normal del índice.
Generación: payload, respuesta y detalles, conexión/timeout y filtro de años.

Aceptación: batería completa dos veces con los mismos casos aprobados, sin
fallos, omisiones o fallos esperados, sin tocar documentos privados, descargas,
servicios reales ni escrituras de resultados dentro del proyecto.

No son pruebas de calidad semántica, fidelidad factual del LLM ni rendimiento.
La concurrencia de un solo proceso se prueba con eventos y esperas acotadas,
sin pausas arbitrarias. El filtro de años solo comprueba presencia
textual: aprobar sus pruebas no demuestra veracidad.

## Problemas de producción pendientes (sin correcciones en esta fase)

1. Dependencias sin fijar y pypdf sin declarar impiden prometer una instalación
   limpia reproducible; esta fase garantiza datos y ejecución deterministas en
   el entorno disponible.

El Hito 5 sustituye el evaluador antiguo por evaluación de fragmentos ficticios,
separa errores técnicos de abstenciones y añade revisión humana de generación.
Ver evaluacion/README.md para comandos, fórmulas, calibración y comparaciones.

## Hito 4: motor e instantáneas

MotorRAG es un gestor ligero creado al importar. No importa sentence-transformers,
numpy, sklearn, pypdf ni requests, ni lee documentos o calcula embeddings durante
ese import. El cargador, el modelo y los cálculos se resuelven cuando se necesitan.
La generación Ollama es independiente de la inicialización del índice.

- inicializar_indice() devuelve la instantánea activa e inicializa una sola vez.
- recuperar_fragmentos y recuperar_contexto conservan firmas y resultados;
  inicializan automáticamente en la primera consulta, para compatibilidad.
- actualizar_indice() conserva su firma y retorno None; fuerza una reconstrucción.
- puntuar_documentos(consulta) devuelve pares (texto, puntuación), calculados sobre
  una sola versión; sustituye accesos del evaluador al modelo/matrices globales.
- Los antiguos globales modelo/documentos/embeddings no son API mantenida. No se
  publican alias que puedan volver a desalinearse; los consumidores del repositorio
  ya usan funciones públicas. Los tests inspeccionan IndiceRAG de solo lectura.

IndiceRAG agrupa versión, documentos originales, textos indexables, fragmentos y
las dos matrices. Los registros usan tuplas y mappingproxy; las matrices poseen
respaldo bytes de solo lectura, sin alias modificables del encoder. Las versiones
solo avanzan al publicar con éxito. Vacío es una versión válida, distinta de None
(sin inicializar); no necesita construir el modelo y devuelve [] en las búsquedas.

La construcción ocurre en variables locales. Se validan filas, dimensiones,
anchura no vacía y valores finitos antes de publicar. Si falla carga, fragmentación,
modelo o validación, ErrorIndice conserva la causa y la instantánea anterior.
Si falla la primera inicialización no se publica nada y se puede reintentar.

Tres bloqueos tienen responsabilidades separadas: serializar actualización,
leer/publicar la referencia, y crear/utilizar el encoder. Una consulta captura
la referencia una vez y sigue usándola aunque otra versión se publique. El bloqueo
de estado nunca se mantiene durante IO o cálculo. El encoder compartido trabaja
serialmente y puede hacer esperar una consulta mientras codifica documentos.

Las garantías son por proceso y motor. No hay persistencia, coordinación entre
servidores ni transacción del directorio si otro programa modifica archivos mientras
se leen. Durante una actualización pueden coexistir dos índices en memoria.

Streamlit muestra ErrorIndice sin anunciar éxito. Si el archivo ya se guardó pero
falló la indexación, explica ambas circunstancias y conserva el índice anterior.
La CLI usa las funciones públicas y el generador común (incluido su prompt y
ErrorOllama); mantiene un documento como contexto. El Hito 5 mantiene el motor y
sustituye los scripts de evaluación por entradas explícitas sin efectos al importar.

Nuevas pruebas: import ligero, inicialización única/idempotente y reintento,
fallos de lectura/fragmentación/segundo encode, matrices inválidas, ausencia de
alias mutables, versión vacía, consultas y actualizaciones concurrentes,
diagnóstico coherente y CLI. AppTest usa una copia del app.py real en una carpeta
temporal y comprueba guardado ficticio con indexación fallida, sin tocar Documentos.

Para ejecutar solo estas pruebas:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_indice_rag -v
```

## Robustez: contrato y nuevas regresiones

Las búsquedas vacías devuelven []. No se llama a encode con listas vacías ni
se incluyen documentos sin texto en el índice de documentos completos. Se prueba
inicio sin documentos, actualización vacía y transición con datos/vacío/con datos.
La carpeta Documentos ausente ya devuelve [] desde el cargador.

generar_respuesta conserva la firma, el texto de éxito y el diccionario de
devolver_detalles=True. Ante conexión, timeout, HTTP incorrecto, JSON inválido,
objeto de error o response ausente/no textual/vacío, lanza ErrorOllama(RuntimeError).
Los clientes deben capturar esa excepción; no se convierte en respuesta ni se
puntúa como abstención del modelo. Streamlit muestra st.error y detiene esa
ejecución antes de mostrar el encabezado de respuesta. Los errores conservan
la causa para diagnóstico; la interfaz muestra únicamente un mensaje controlado.
Las métricas opcionales mal formadas se sustituyen por cero; el texto válido se
conserva. No se exigen métricas para aceptar una respuesta.

AppTest cubre inicio, actualización, búsqueda vacía sin generación, error sin
respuesta y éxito normal. Los avisos missing ScriptRunContext del hilo principal
proceden del modo de pruebas de Streamlit; se comprueba que no hay excepciones
de la aplicación. No se validan modelos reales, extracción PDF binaria ni OCR.

Comprobación manual sin tocar Documentos: copiar los cinco módulos de producción
(app, buscador_semantico, cargar_documentos, fragmentar_documentos y configuracion)
a una carpeta temporal nueva y ejecutar allí app.py con el Python del entorno
existente. No copiar Documentos. Comprobar inicio, actualización y búsqueda vacía;
subir después un TXT ficticio y comprobar respuesta con Ollama disponible. Con
Ollama detenido debe aparecer un error, sin respuesta del modelo. Los casos HTTP
y JSON se reproducen de forma determinista con los mocks de la batería.

## Reversión

El commit f97ea66 conserva el motor anterior a este hito. Esta fase queda sin
commit final para revisión. Para ensayar ese commit sin sobrescribir el
trabajo actual se puede crear otro worktree separado. Una futura reversión de
un commit de tests se hará con git revert, sin reset ni clean.
