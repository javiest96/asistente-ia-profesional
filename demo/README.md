# Demo local de portfolio — Centro Astral de Brisa

Tres TXT completamente ficticios. No se copian documentos personales ni se
reutilizan preguntas de H5/H6. El motor conserva el prompt A; B/C no se promocionan.
Las tres preguntas fueron comprobadas manualmente por el usuario: respuesta
directa correcta, combinación correcta con ambas fuentes y abstención correcta.
Esto no es una garantía general ni sustituye las evaluaciones H5/H6. Los nuevos
cambios de interfaz/diagnóstico de Fase C siguen pendientes de validación manual.
Ejecutar nuevas pruebas reales solo tras autorización.

## Requisitos

- Windows y la `.venv` **original** del proyecto, ya instalada. El lanzador no
  utiliza ni modifica la instalación temporal validada en Fase A.
- Ollama con `qwen3.5:4b` local ya preparado y servicio en `127.0.0.1:11434`.
- Embeddings `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` ya
  disponibles en la caché del mismo usuario que ejecuta la demo.
- Puerto local libre, por defecto 8501. No se requieren permisos de administrador.

No hay `pip install`, creación de venv, descarga de modelos ni arranque de Ollama
en este procedimiento. Hugging Face se fuerza a modo offline. Si faltan pesos en
caché o el modelo de Ollama no está preparado, detenerse y preparar ese requisito
por separado con autorización. Un estado correcto de instalación no valida la IA.

## Ensayar la preparación sin modelos

En VS Code, abrir PowerShell en la raíz del proyecto:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\iniciar_demo.ps1 -Preparar -Puerto 8766
```

Este modo solo comprueba el puerto y copia el corpus a una biblioteca nueva en
`%TEMP%\rag-demo-h8-<identificador>\biblioteca`. Muestra su ruta y la URL prevista;
**no inicia ningún servidor**. Si ese puerto está ocupado, elegir otro.

`ExecutionPolicy Bypass` se limita a ese proceso; no cambia la política del equipo.
Usar únicamente scripts revisados. No es necesario activar el entorno: el wrapper
selecciona `.venv\Scripts\python.exe` mediante la ruta del repositorio.

## Lanzamiento real — pendiente de autorización

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\iniciar_demo.ps1
```

Si 8501 está ocupado:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\iniciar_demo.ps1 -Puerto 8766
```

El lanzador siempre crea **otra biblioteca nueva**: no reutiliza la del ensayo.
Abre manualmente la URL mostrada, `http://127.0.0.1:<puerto>`. Espera a que
Streamlit indique que está disponible. El proceso se queda en primer plano;
**Ctrl+C en esa terminal** lo detiene. No se detiene Ollama ni se borra la biblioteca.
No usar comandos que terminen todos los procesos Python.

El puerto se comprueba antes de copiar el corpus. Existe una ventana pequeña
entre esa comprobación y el arranque; si otro programa lo ocupa, Streamlit debe
fallar con el puerto explícito. No se mata el proceso ajeno ni se elige otro puerto
silenciosamente. Conservar el mensaje y volver a decidir el puerto.

## Preguntas de demostración y referencias

Cada documento tiene menos de 50 palabras para mantener sus hechos juntos con
la fragmentación actual. El manifiesto `demo.json`, junto a `biblioteca/`, registra
los nombres, tamaños y SHA-256 de los tres documentos copiados.

| Tipo | Pregunta | Resultado esperado | Evidencia |
|---|---|---|---|
| Directa | ¿Cuánto cuesta la entrada general del Centro Astral de Brisa? | 8 euros. | `centro.txt` |
| Combinación | ¿Cuánto cuestan en total la entrada general y el taller Órbitas de papel, y a qué hora comienza el taller? | 11 euros en total (8 + 3); empieza a las 11:30. | `centro.txt` y `taller.txt` |
| Información ausente | ¿Cuál es el número de teléfono del Centro Astral de Brisa? | Abstenerse: el teléfono no figura en los documentos. No inventar un número. | Ningún documento lo contiene. |

`exposicion.txt` añade una exposición ficticia para mostrar selección entre documentos.
No contiene el teléfono ni los precios del taller.

## Guion breve para una entrevista

1. Explicar que todo el corpus es ficticio y mostrar que las subidas están desactivadas.
2. Pulsar **Actualizar biblioteca** y esperar su finalización. La primera indexación
   carga embeddings desde caché y puede tardar. La Fase C añade un indicador
   durante la operación y un aviso persistente del resultado en la sesión.
3. Hacer la pregunta directa y contrastar respuesta y fuente.
4. Hacer la pregunta combinada: comprobar que recupera ambas evidencias y no omite
   el horario. La suma se verifica manualmente; no se da por correcta por mencionar números.
5. Hacer la pregunta ausente. Si no hay contexto, la abstención es del sistema; si
   Qwen recibe contexto, comprobar su abstención. No atribuir ambas situaciones al modelo.
6. Explicar la instantánea del índice, el control de errores, límites y evaluación
   con corpus ficticio. Mostrar la Fase A validada como evidencia de instalación,
   sin confundirla con una evaluación de calidad de esta demo.
7. Terminar con Ctrl+C. La ruta temporal queda disponible para revisar el manifiesto.

Si una respuesta no cumple la referencia, registrarlo como resultado de la prueba
manual: no cambiar el prompt o los casos H5/H6 para embellecer la demostración.
Las fuentes recuperadas no prueban por sí solas la fidelidad de una respuesta.

## Aislamiento y limitaciones

- Solo se aceptan los tres nombres del corpus; archivos adicionales, enlaces,
  TXT vacíos/binarios o cambios durante la copia impiden arrancar.
- Los TXT se copian con creación exclusiva; bibliotecas anteriores no se sobrescriben.
- Se descartan variables heredadas RAG/Streamlit, endpoints/modelos alternativos y
  proxies para la conexión local. El entorno de la terminal no se modifica.
- Se fijan biblioteca temporal, subidas desactivadas, Qwen3.5:4b, embeddings actuales,
  Ollama loopback, CORS/XSRF activos y API de agente/static serving desactivados.
- Las rutas de caché de modelos existentes se pueden conservar; sus pesos son
  distintos del corpus documental. No hay descarga implícita con Hub offline.
- No hay autenticación ni separación de usuarios: demo local, no servicio público.
  No exponer puertos ni crear túneles. Los bloqueos siguen siendo por proceso.
- Un tag de Ollama no fija los pesos para siempre. Antes de una presentación real
  conviene registrar versión de Ollama y digest del modelo mediante una lectura
  autorizada; este lanzador no realiza solicitudes de diagnóstico a Ollama.
- La carpeta temporal no se limpia automáticamente. El administrador decide su
  conservación; no contiene más documentos que los ficticios copiados.

Las pruebas automáticas usan procesos simulados y `-Preparar`; nunca inician la demo
con modelos. Ver `tests/test_demo.py`. El diagnóstico del rechazo intermitente y
la confirmación persistente se describen en [diagnóstico Fase C](../docs/diagnostico_ollama.md).
