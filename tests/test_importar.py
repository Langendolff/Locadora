"""Reconhecimento de 'Título (Ano)' nos nomes de pasta/arquivo (scripts/stack/importar.py)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

from stack.importar import titulo_e_ano  # noqa: E402

CASOS = {
    "Terra Fria (2005)": ("Terra Fria", "2005"),
    "Terra Fria (2005) - Dublado.mp4": ("Terra Fria", "2005"),
    "Encontro de Irmãs (2001) - Legendado.mp4": ("Encontro de Irmãs", "2001"),
    "Dollhouse - A Boneca da Casa (2025)": ("Dollhouse - A Boneca da Casa", "2025"),  # hífen do título fica
    "Eu Te Amo, Cara (2009)": ("Eu Te Amo, Cara", "2009"),
    "The.Matrix.1999.1080p.BluRay.x264.mkv": ("The Matrix", "1999"),
    "Blade Runner 2049 (2017)": ("Blade Runner 2049", "2017"),
    "Filme sem ano.mkv": ("Filme sem ano", None),
}


class TestTituloEAno(unittest.TestCase):
    def test_nomes(self):
        for nome, esperado in CASOS.items():
            with self.subTest(nome):
                self.assertEqual(titulo_e_ano(nome), esperado)


if __name__ == "__main__":
    unittest.main()
