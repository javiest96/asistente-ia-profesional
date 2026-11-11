import unittest
from fragmentar_documentos import dividir_texto, preparar_fragmentos


class TestDividirTexto(unittest.TestCase):

    def test_solapamiento_invalido(self):
        with self.assertRaises(ValueError):
            dividir_texto("Hola mundo", tamano=10, solapamiento=10)

    def test_solapamiento_correcto(self):
        texto = "uno dos tres cuatro cinco seis siete ocho nueve diez"

        resultado = dividir_texto(texto, tamano=5, solapamiento=2)

        esperado = [
            "uno dos tres cuatro cinco",
            "cuatro cinco seis siete ocho",
            "siete ocho nueve diez"
        ]

        self.assertEqual(resultado, esperado)

    def test_conservar_fuentes(self):
        documentos = [
            {
                "nombre": "reglas.txt",
                "contenido": "El fuera de juego tiene sus propias reglas."
            },
            {
                "nombre": "horarios.pdf",
                "contenido": "Los partidos se juegan los domingos."
            }
        ]

        resultado = preparar_fragmentos(documentos)

        self.assertEqual(len(resultado), 2)
        self.assertEqual(resultado[0]["nombre"], "reglas.txt")
        self.assertEqual(resultado[1]["nombre"], "horarios.pdf")

    def test_conservar_contenido(self):
        documentos = [
            {
                "nombre": "horarios.pdf",
                "contenido": "Los partidos se juegan los domingos."
            }
        ]

        resultado = preparar_fragmentos(documentos)

        self.assertEqual(len(resultado), 1)

        self.assertEqual(
            resultado[0]["contenido"],
            documentos[0]["contenido"]
        )

class TestLimitesFragmentacion(unittest.TestCase):
    def test_texto_vacio(self):
        self.assertEqual(dividir_texto("  \n\t"), [])

    def test_texto_corto(self):
        self.assertEqual(dividir_texto("Texto ficticio breve"), ["Texto ficticio breve"])

    def test_tamano_exacto_sin_fragmento_redundante(self):
        self.assertEqual(dividir_texto("uno dos tres cuatro cinco", tamano=5, solapamiento=2), ["uno dos tres cuatro cinco"])

    def test_conserva_ultimo_tramo(self):
        self.assertEqual(dividir_texto("uno dos tres cuatro cinco seis", tamano=5, solapamiento=2), [
            "uno dos tres cuatro cinco", "cuatro cinco seis",
        ])

    def test_sin_solapamiento(self):
        self.assertEqual(dividir_texto("uno dos tres cuatro cinco", tamano=2, solapamiento=0), [
            "uno dos", "tres cuatro", "cinco",
        ])

    def test_parametros_invalidos(self):
        for tamano, solapamiento in [(0, 0), (-1, 0), (5, -1), (5, 5), (5, 6)]:
            with self.subTest(tamano=tamano, solapamiento=solapamiento):
                with self.assertRaises(ValueError):
                    dividir_texto("Texto ficticio", tamano=tamano, solapamiento=solapamiento)

    def test_separacion_de_documentos_y_fuentes_en_varias_ventanas(self):
        palabras = [f"palabra{i}" for i in range(55)]
        documentos = [
            {"nombre": "largo_ficticio.txt", "contenido": " ".join(palabras)},
            {"nombre": "otro_ficticio.txt", "contenido": "Contenido independiente"},
        ]
        self.assertEqual(preparar_fragmentos(documentos), [
            {"nombre": "largo_ficticio.txt", "contenido": " ".join(palabras[:50])},
            {"nombre": "largo_ficticio.txt", "contenido": " ".join(palabras[40:])},
            documentos[1],
        ])

    def test_corpus_vacio(self):
        self.assertEqual(preparar_fragmentos([]), [])


if __name__ == "__main__":
    unittest.main()
