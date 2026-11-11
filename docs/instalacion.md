# Hito 8, fase A: comprobar una instalación limpia en Windows

Estado comprobado: una ejecución aislada sobre `a5e3ee0` terminó con
`validacion.json` en `estado: ok`: `pip check`, imports, Python 3.14.10,
PyTorch 2.15.0+cpu, tensor CPU, 179 tests y Streamlit vacío en loopback correctos.
No ejecutó inferencia. Las instrucciones siguientes describen el procedimiento;
una ejecución nueva sigue requiriendo sus autorizaciones explícitas.

Este procedimiento valida un commit en una copia temporal. **No reutiliza la
`.venv` del proyecto** ni copia `Documentos/`, `Informes/` o secretos. No prepara
una demo con documentos ni modifica la interfaz: esas fases quedan pendientes.

## Qué está autorizado ahora

Solo preparación, revisión de scripts y tests sin instalaciones. Los modos que
descargan o instalan se documentan para una autorización posterior. No ejecutarlos
todavía. Crear un entorno vacío no demuestra que la instalación funcione: el modo
Preparar ni siquiera crea ese entorno.

| Modo | Qué hace | Autorización explícita |
|---|---|---|
| `Preparar` (predeterminado) | Comprueba requisitos, crea temporal única, exporta el commit y genera un plan | No descarga ni instala |
| `Descargar` | Descarga solo ruedas de PyPI y calcula SHA-256 | `-AutorizarDescargas` |
| `Recuperar` | Verifica y copia ruedas locales a una preparación nueva, sin red | `-AutorizarRecuperacion` |
| `Validar` | Crea una `.venv` nueva e instala exclusivamente las ruedas verificadas; ejecuta comprobaciones | `-AutorizarInstalacion` |

No hay un modo que realice todas las fases por sorpresa. Una autorización no sirve
para otro modo. Los scripts no borran carpetas, no hacen commits ni arrancan Ollama.

## Requisitos previos

- Windows x64 y un ejecutable **base** de CPython 3.14 convencional, no ARM64,
  32 bits, free-threaded, alias de Microsoft Store ni un Python dentro de un venv.
- Git disponible en PATH y acceso local al commit elegido.
- pip disponible en ese Python base. El script no instala ni actualiza pip/Python.
- PowerShell de Windows. No requiere módulos adicionales ni permisos de administrador.
- Conexión HTTPS a PyPI solo cuando se autorice Descargar.

La referencia actual es Python 3.14.10. Se registra la versión exacta en el plan
y se exige la misma al continuar. Los scripts emplean `-I` (aislamiento) y `-B`
(sin escribir bytecode); no activan entornos ni cambian la política global de PowerShell.

Si `py -3.14` no encuentra Python, eso no demuestra que no esté instalado. En el
entorno de desarrollo se puede descubrir el ejecutable base con una lectura:

```powershell
$pythonBaseH8 = & .\.venv\Scripts\python.exe -I -B -c "import sys; print(sys._base_executable)"
$pythonBaseH8
```

Esto no modifica `.venv`. En un ordenador nuevo sin ese entorno, consultar
`Get-Command python.exe` y proporcionar la ruta del Python base ya instalado.
Si apunta a `WindowsApps`, no ejecutarlo: localizar el Python real. Si falta,
detenerse y preparar ese requisito por separado. El script nunca llama a un
gestor para descargar automáticamente Python. Usar `-Python` evita depender del
entorno que VS Code pueda haber activado en su terminal.

## 1. Preparar sin instalar

Abrir VS Code en la raíz del proyecto y una terminal PowerShell. Ejecutar:

```powershell
$planH8 = powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\validar_instalacion.ps1 -Modo Preparar -Commit HEAD -Python $pythonBaseH8 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "No se ha podido preparar H8. Consulta el codigo de error." }
$trabajoH8 = $planH8.directorio_trabajo
$trabajoH8
Get-Content -LiteralPath (Join-Path $trabajoH8 "preparacion.json")
```

`ExecutionPolicy Bypass` afecta únicamente a ese proceso, no cambia la política
del equipo. Usarlo solo con los scripts revisados de este repositorio.

Se crea `%TEMP%\rag-h8-<identificador>`, con:

- `codigo.zip`: `git archive` del SHA completo resuelto.
- `codigo/`: copia de los archivos versionados, sin `.git` ni datos locales.
- `preparacion.json`: commit, versión de Python, paquetes fijados, espacio disponible
  y hashes del archivo exportado, lock y orquestador.

No hay `.venv`, ruedas ni llamadas a modelos. La preparación rechaza rutas de
documentos privados, informes, entornos, secretos y enlaces. Solo admite los cuatro
TXT ficticios H5 en `evaluacion/documentos/`; el corpus ficticio H6 se conserva.
Esto no es un detector universal de secretos hardcodeados: usar commits auditados.

En esta copia de portfolio, el historial original no está incluido. Git está
inicializado, pero `HEAD` no será válido hasta crear el primer commit autorizado.
Los dos scripts usan **`HEAD` como valor predeterminado**; `-Commit` en PowerShell
y `--commit` en Python siguen permitiendo seleccionar otra revisión disponible.
Antes del primer commit, Preparar falla sin crear la carpeta temporal.

La validación histórica de 179 tests pertenece al repositorio local de desarrollo
conservado por separado y no certifica una instalación limpia de esta copia.
La visibilidad de su remoto en GitHub todavía no se ha comprobado.

Conservar la ruta que se imprime. Cada preparación crea un directorio nuevo.
No limpiar automáticamente ni reutilizar un temporal anterior por su nombre.

## 2. Descargar ruedas — PENDIENTE DE AUTORIZACIÓN

Solo después de aprobar la descarga, usando la ruta generada:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\validar_instalacion.ps1 -Modo Descargar -DirectorioTrabajo $trabajoH8 -Python $pythonBaseH8 -AutorizarDescargas
if ($LASTEXITCODE -ne 0) { throw "La descarga no se ha completado. No continuar con Validar." }
```

Se usa `pip download --only-binary=:all:` con versiones del lock y el índice
`https://pypi.org/simple`, sin caché compartida. Se descartan configuraciones pip
heredadas. Si una rueda no existe para la plataforma o hay un conflicto, se detiene:
no compila, no cambia versiones y no agrega automáticamente una alternativa CUDA.

Se comprueba que las ruedas sean exactamente los paquetes/versiones esperados,
sin fuentes, paquetes extra ni duplicados. Salidas:

- `ruedas/`: archivos `.whl`.
- `ruedas.json`: nombre, versión, tamaño, nombre de archivo y SHA-256.
- `requirements-hashed.txt`: requisitos con hashes exigibles por pip.
- `descarga.inicio.json` y `descarga.json`: estado y errores categorizados.

Los hashes fijan los artefactos obtenidos; no certifican que sean inocuos. La primera
descarga sigue confiando en PyPI y TLS. No se guardan tokens, cabeceras ni salida
original de pip. Un proxy corporativo puede requerir preparación de red aparte.

## 3. Instalar y validar — PENDIENTE DE AUTORIZACIÓN

### Recuperar offline el fallo de METADATA, sin repetir descargas

El validador corregido exige exactamente un `.dist-info/METADATA` en el nivel
principal de cada rueda y comprueba su nombre, versión y coherencia con el nombre
del archivo/directorio. Los metadatos vendorizados anidados no cuentan como
metadatos principales; duplicados principales siguen siendo un error.

Para recuperar el fallo `rueda_sin_metadatos_unicos`, usar **Preparar** otra vez
con el script actual y el mismo commit. No modificar `preparacion.json`, la huella
antigua ni los registros del fallo. El destino nuevo debe superar los controles
normales de huellas. Después de autorizar la recuperación, pero no la instalación:

```powershell
$origenH8 = Join-Path $env:TEMP "rag-h8-IDENTIFICADOR-DEL-ORIGEN"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\validar_instalacion.ps1 -Modo Recuperar -DirectorioTrabajo $trabajoH8 -OrigenPreparacion $origenH8 -Python $pythonBaseH8 -AutorizarRecuperacion
```

`$trabajoH8` debe ser la **nueva** preparación. El origen se trata como entrada de
solo lectura, nunca como un procedimiento antiguo autorizado para ejecutarse.
Se comprueban commit, lock, registro del fallo, conjunto exacto de paquetes,
versiones y hashes de las ruedas; se copian con creación exclusiva y se vuelven
a verificar. Se comparan los hashes de todos los archivos del origen antes y
después para asegurar que no ha cambiado. No se llama a pip ni a Internet.

Se generan `ruedas.json`, `requirements-hashed.txt` y `recuperacion.json`, que
registra huellas del origen y del orquestador actual. **No** se crea un falso
`descarga.json` exitoso ni se sobrescribe el error anterior. La integridad local
verificada no es una comprobación independiente de autenticidad de PyPI.

El modo Validar acepta exactamente un registro exitoso de adquisición: descarga
o recuperación. Mantiene la autorización de instalación y todos los controles
de hashes. Una preparación ya utilizada para descargar o recuperar no se reutiliza.

### Instalar después de la autorización correspondiente

Tras una descarga correcta y una autorización específica para instalar:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\scripts\validar_instalacion.ps1 -Modo Validar -DirectorioTrabajo $trabajoH8 -Python $pythonBaseH8 -AutorizarInstalacion
if ($LASTEXITCODE -ne 0) { throw "La instalación no ha quedado validada. Revisar validacion.json." }
```

Antes de crear nada se verifican los hashes del código, lock, ruedas y requisitos;
se rechazan archivos añadidos a la copia exportada y entornos de destino existentes.
El proceso crea únicamente `$trabajoH8\.venv`, con el Python base seleccionado.

La instalación usa `--no-index --no-deps --require-hashes --only-binary=:all:`:
no solicita dependencias en la red. `pip check` detectará una declaración incompleta.
No actualiza paquetes de la `.venv` original ni ejecuta comandos `pip` sin un
intérprete explícito. Las comprobaciones posteriores son:

1. `pip check` dentro del nuevo entorno.
2. Imports reales de NumPy, scikit-learn, torch, Transformers, SentenceTransformers,
   Streamlit, requests y pypdf; no se instancia ningún modelo.
3. Tensor pequeño en **CPU**, comprobación del entorno usado y de las versiones
   instaladas contra el lock. Se registra pip, torch y CUDA compilada si existe.
4. Tests del código exportado: al menos 179, con código de salida correcto.
5. Streamlit real en puerto temporal de `127.0.0.1`: salud, renderizado y actualización
   de biblioteca vacía. La API de agente se habilita solo para ese proceso de prueba.
6. Detención exclusiva de ese proceso Streamlit, incluso si falla la comprobación.

Se fuerza biblioteca vacía, caché de modelos separada, Hub offline, CUDA oculta
y endpoint de generación sin servicio. No se carga Qwen, no se crean embeddings
ni se utilizan documentos personales. Esto no valida la calidad o velocidad del RAG.

`validacion.json` contiene estado, fase de error, resultados seguros de imports,
versiones y cantidad de tests. **Solo `estado: ok` tras todas las comprobaciones
permite afirmar que esa instalación concreta está validada.**

## Espacio, CPU/GPU y fallos

Estimaciones, no mediciones de descarga:

| Concepto | Orden de magnitud para la referencia Windows/CPU |
|---|---:|
| Ruedas descargadas | 1–3 GiB |
| Entorno instalado | 3–7 GiB |
| Espacio libre aconsejado, incluyendo temporales | 10–20 GiB |

Los modos reales exigen al menos 10 GiB libres; ese umbral no garantiza que baste.
Las cifras excluyen modelos y pueden aumentar con variantes GPU. El tamaño real
de las ruedas queda registrado tras Descargar. No se elige una variante CPU/CUDA
por suposición: primero se valida el lock tal como está. El tensor en CPU no
certifica funcionamiento de CUDA ni compatibilidad de drivers.

Cada fase real se ejecuta una sola vez por preparación. Una marca `.inicio.json`
impide reintentos accidentales o simultáneos, también tras interrupciones. Si falla,
no se eliminan ni reparan carpetas: conservarlas, revisar el código de error y
solicitar una decisión antes de repetir o ajustar versiones. Ctrl+C cancela el
procedimiento; puede quedar una instalación parcial, nunca se presenta como válida.

Los informes omiten stdout/stderr completos para no almacenar rutas, credenciales
o contenido accidental. Un error genérico puede requerir un diagnóstico manual
posterior, autorizado y saneado. No publicar el temporal entero: puede incluir
metadatos locales y varios GiB. No subir ruedas ni entornos a Git.

No se añade una demo pública, autenticación, cambios de prompts, mejoras de interfaz
o experimentos nuevos. H5/H6 y `.venv` se conservan. El primer guardado y los logs
HTTP de Ollama se abordarán en las fases siguientes si se autorizan.
