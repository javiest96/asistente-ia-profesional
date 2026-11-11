def dividir_texto(texto, tamano=50, solapamiento=10):
    palabras = texto.split()
    fragmentos = []

    if tamano <= 0:
        raise ValueError("El tamaño debe ser mayor que cero.")

    if solapamiento < 0 or solapamiento >= tamano:
        raise ValueError("El solapamiento debe ser menor que el tamaño y no negativo.")

    paso = tamano - solapamiento

    for inicio in range(0, len(palabras), paso):
        fragmento = " ".join(palabras[inicio:inicio + tamano])
        fragmentos.append(fragmento)

        if inicio + tamano >= len(palabras):
            break

    return fragmentos

def preparar_fragmentos(documentos, tamano=50):
    fragmentos_con_fuente = []

    for documento in documentos:
        fragmentos = dividir_texto(documento["contenido"], tamano)

        for fragmento in fragmentos:
            fragmentos_con_fuente.append({
                "nombre": documento["nombre"],
                "contenido": fragmento
            })

    return fragmentos_con_fuente

if __name__ == "__main__":

    from cargar_documentos import cargar_documentos

    documentos = cargar_documentos()

    fragmentos_con_fuente = []

    for documento in documentos:

        fragmentos = dividir_texto(documento["contenido"], tamano=50)

        print(f"{documento['nombre']}: {len(fragmentos)} fragmentos")

        for fragmento in fragmentos:
            fragmentos_con_fuente.append({
                "nombre": documento["nombre"],
                "contenido": fragmento
            })

    print(f"\nTotal de fragmentos con fuente: {len(fragmentos_con_fuente)}")