"""Preferências de cada pessoa (scripts/stack/pessoas.py): o que vai pro Jellyfin e a volta."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

from stack.pessoas import AUDIO, LEGENDA, jellyfin_cfg, legenda_de  # noqa: E402


class TestPreferencias(unittest.TestCase):
    def test_legenda_ida_e_volta(self):
        # O que o ./pessoas.sh grava no Jellyfin tem que ser lido de volta igual
        for audio in AUDIO:
            for legenda in LEGENDA:
                with self.subTest(audio=audio, legenda=legenda):
                    self.assertEqual(legenda_de(jellyfin_cfg(audio, legenda)), legenda)

    def test_dublado_prefere_faixa_em_portugues(self):
        cfg = jellyfin_cfg("dublado", "pt-br")
        self.assertEqual(cfg["AudioLanguagePreference"], "por")
        self.assertFalse(cfg["PlayDefaultAudioTrack"])
        self.assertEqual(cfg["SubtitleMode"], "Smart")  # legenda só quando o áudio não é PT

    def test_original_toca_faixa_padrao_com_legenda(self):
        cfg = jellyfin_cfg("original", "en")
        self.assertEqual(cfg["AudioLanguagePreference"], "")
        self.assertTrue(cfg["PlayDefaultAudioTrack"])
        self.assertEqual((cfg["SubtitleLanguagePreference"], cfg["SubtitleMode"]), ("eng", "Always"))

    def test_sem_legenda_mostra_so_forcadas(self):
        for audio in AUDIO:
            self.assertEqual(jellyfin_cfg(audio, "nenhuma")["SubtitleMode"], "OnlyForced")

    def test_usuario_novo_do_jellyfin_le_como_sem_legenda_nao_quebra(self):
        self.assertEqual(legenda_de({}), "nenhuma")


if __name__ == "__main__":
    unittest.main()
