"""Regras de título do formato 'Português (BR)' (scripts/stack/language.py).

Roda sem a stack:  python3 -m unittest discover -s tests

O Radarr/Sonarr avaliam cada regra ignorando maiúsculas (regex .NET); o formato casa se
QUALQUER uma das regras de título casar. Aqui o teste reproduz isso com o `re` do Python.
Para conferir no Radarr de verdade: GET /api/v3/parse?title=<título> mostra os formatos que casam.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
# stack.common lê o .env ao ser importado; valores falsos bastam aqui
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

from stack.language import AUDIO_TAG, DUAL_TITLE, PT_TITLE  # noqa: E402

RULES = [re.compile(r, re.IGNORECASE) for r in (PT_TITLE, DUAL_TITLE, AUDIO_TAG)]

# Título -> deve contar como áudio em português?
PORTUGUES = [
    "Duna Parte Dois 2024 1080p WEB-DL DUAL 5.1",
    "Dune.Part.Two.2024.1080p.WEB-DL.Dublado",
    "Movie.2024.1080p.WEB-DL-DUBLADO",
    "Cidade de Deus 2002 1080p BluRay Nacional",
    "Movie 2024 Dublagem Classica 720p",
    "Kung Fu Panda 4 2024 1080p Dub",
    "Movie 2024 1080p PT-BR Dub",
    "Movie.2024.1080p.Dub.PT-BR",
    "Movie 2024 1080p Audio PT-BR",
    "Movie 2024 1080p Brazilian Dubbed",
    "Movie 2024 1080p WEB-DL Dual Audio Legendado",  # dual tem áudio PT; a legenda é extra
    "Dune Part Two 2024 [audio-[EN+PT]] 1080p",
    "Show S01E01 1080p [audio-[EN+PT-BR]]",
    "Frieren S01E01 1080p Dublado",
]
NAO_PORTUGUES = [
    # Legendado: áudio original
    "Dune Part Two 2024 1080p BluRay x264 Legendado PT-BR",
    "Dune.Part.Two.2024.1080p.WEB-DL.PT-BR.SUBS",
    "Dune.Part.Two.2024.1080p.Portuguese.Brazilian.WEB-DL",
    "Dune Part Two 2024 [audio-[EN]] [subs-[PT]] 1080p",
    # Dual com outro idioma
    "Dune.Part.Two.2024.1080p.WEB-DL.Dual.Audio.Hindi.English",
    "Dune.Part.Two.2024.1080p.dual.audio.latino",
    # Dublagem em inglês/japonês (anime)
    "Frieren S01E01 1080p English Dub",
    "Frieren S01E01 1080p Dub Eng",
    "Frieren S01E01 1080p Japanese Dub",
    # Nada de idioma / falso amigo
    "Dune.Part.Two.2024.1080p.AMZN.WEB-DL.DDP5.1.H.264-FLUX",
    "Movie.2024.1080p.Dubstep",
]


def em_portugues(title):
    return any(r.search(title) for r in RULES)


class TestFormatoPortugues(unittest.TestCase):
    def test_reconhece_audio_em_portugues(self):
        for t in PORTUGUES:
            with self.subTest(t):
                self.assertTrue(em_portugues(t), "deveria contar como PT-BR")

    def test_nao_confunde_legendado_nem_outras_dublagens(self):
        for t in NAO_PORTUGUES:
            with self.subTest(t):
                self.assertFalse(em_portugues(t), "não deveria contar como PT-BR")


if __name__ == "__main__":
    unittest.main()
