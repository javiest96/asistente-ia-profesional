# Publicación independiente de portfolio

## Procedencia y conservación

Esta carpeta es una exportación de los archivos versionados de la entrega H8,
con las cuatro versiones de documentación H9 incorporadas como base de trabajo.
El desarrollo completo y sus diez commits se conservan intactos en el repositorio
local de desarrollo, por separado. No se ha comprobado la visibilidad de su remoto
en GitHub y no se afirma que sea privado. No se copió su `.git`, ramas, remotes,
reflogs ni metadatos de autor o committer.

Los hashes antiguos de las guías describen evidencias históricas y no son commits
disponibles aquí. El propietario confirmó que el club y el entrenador de
`Ejemplos/ejemplo.txt` son ficticios, como los corpus de demo y evaluación.

## Identidad pública autorizada

- Nombre: Javier Esteban.
- Correo: `354447114+javiest96@users.noreply.github.com`.

Se ha inicializado un repositorio independiente con rama `main` e historial
nuevo, sin remotes. El primer commit contiene únicamente esta entrega de portfolio. La identidad está configurada solo en este repositorio; no se ha cambiado
Git global ni el proyecto de desarrollo. Se comprobaron las variables de entorno
`GIT_AUTHOR_*` y `GIT_COMMITTER_*` y la identidad efectiva de ambos roles.

## Instalador y pruebas

Los dos scripts del instalador usan `HEAD` como valor predeterminado y admiten
un commit explícito. `HEAD` no existe hasta crear el primer commit autorizado;
Preparar no puede exportar antes de ese momento. Ver [instalación](instalacion.md).
No se han instalado paquetes ni se ha validado una instalación limpia de esta copia.

La copia no incluye `.venv`. Los tests de lógica se pueden ejecutar con un intérprete
compatible que ya tenga las dependencias, sin instalar nada en este directorio.
La prueba de integración `TestCorpusYPuerto.test_wrapper_prepara_sin_streamlit_modelos_o_instalaciones`
requiere específicamente `.venv/Scripts/python.exe` en esta copia: queda pendiente
hasta disponer de ese entorno autorizado. No se elimina ni se debilita esa prueba.

## Antes del primer commit y de publicar

1. Auditar archivos ocultos, contenido y tamaños: sin documentos privados, informes,
   entornos, modelos, secretos ni objetos del historial original.
2. Revisar que autor y committer usan exactamente la identidad autorizada.
3. Revisar diferencias y ejecutar pruebas; no preparar ni crear commits sin aprobación.
4. Tras el commit, auditar todos los blobs, mensajes y referencias: sin correos
   personales ni rutas sensibles. Los ejemplos ficticios de privacidad en tests
   deben revisarse por separado.
5. Revisar las capturas reales antes de incorporarlas. El código y la documentación
   se distribuyen bajo la licencia [MIT](../LICENSE), con copyright de 2026
   Javier Esteban. Dependencias y modelos conservan sus propias licencias.
6. Autorizar por separado cualquier conexión, destino remoto o publicación.
   No se ha contactado con GitHub ni se ha configurado un remote.

El remote del desarrollo no se hereda. Antes de publicar hay que verificar el
destino y su historia: esta copia no elimina una posible exposición anterior.
La demo sigue siendo local, sin autenticación ni aislamiento multiusuario, con la
incidencia CUDA de Ollama pendiente. Publicar código no despliega un servicio.
