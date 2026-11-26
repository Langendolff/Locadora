"""Episódios do YouTube (scripts/stack/youtube.py): só episódio completo, com o número certo."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

from stack.youtube import (adivinhar_serie, escolher, faixas, idioma, link_da_lista,  # noqa: E402
                           bloqueio, numeracao, resolucao)

H2 = 2 * 3600


def video(vid, titulo, dur=H2, av=None):
    return {"id": vid, "title": titulo, "duration": dur, "availability": av}


def eps(temporada, n, com_arquivo=()):
    return [{"id": temporada * 1000 + e, "seasonNumber": temporada, "episodeNumber": e,
             "hasFile": e in com_arquivo} for e in range(1, n + 1)]


# Títulos de verdade do canal "Arafta - Portuguese"
COMPLETO = "Arafta Episódio 36 Completo (Temp. 2) Novela Turca Dublado em Português #S2EP36 @Arafta-portuguese"
CENA = "Um anel do passado | ARAFTA Episódio 36 (Temporada 2) Novela Turca #S2CEP36"
CHAMADA = "Arafta Episódio 37 Chamada 4 | Temporada 2 Novela Turca #S2PEP37"
MEMBROS = "Arafta Season 2 Episódio Completo 38 | SOMENTE PARA MEMBROS #S2EP38 @Arafta-portuguese"
T1_LEGENDADO = "ARAFTA | Episódio 01 Completo | Série turca com legendas em português | @Arafta-portuguese"


class TestNumeracao(unittest.TestCase):
    def test_tag_do_canal(self):
        self.assertEqual(numeracao(COMPLETO), (2, 36))

    def test_sxxexx(self):
        self.assertEqual(numeracao("Serie S01E05 1080p"), (1, 5))

    def test_temporada_e_episodio_por_extenso(self):
        self.assertEqual(numeracao("Novela - 3ª Temporada - Capítulo 12"), (3, 12))
        self.assertEqual(numeracao("Dizi 12. Bölüm"), (None, 12))

    def test_sem_temporada(self):
        self.assertEqual(numeracao(T1_LEGENDADO), (None, 1))

    def test_idioma(self):
        self.assertEqual(idioma(COMPLETO), "dublado")
        self.assertEqual(idioma(T1_LEGENDADO), "legendado")
        self.assertEqual(idioma("Arafta 5. Bölüm"), "")


class TestEscolher(unittest.TestCase):
    def test_so_episodio_completo_entra(self):
        vids = [video("a", COMPLETO), video("b", CENA, 9 * 60), video("c", CHAMADA, 100)]
        r = escolher(vids, eps(2, 38), duracao_min=82)
        self.assertEqual([(x["temporada"], x["episodio"], x["video"]) for x in r["baixar"]], [(2, 36, "a")])

    def test_so_para_membros_nao_baixa_e_avisa(self):
        r = escolher([video("m", MEMBROS, av="subscriber_only")], eps(2, 38))
        self.assertEqual((r["baixar"], r["so_membros"]), ([], [(2, 38)]))

    def test_versao_liberada_ganha_da_de_membros(self):
        vids = [video("m", MEMBROS.replace("38", "4"), av="subscriber_only"),
                video("l", COMPLETO.replace("36", "04"))]
        r = escolher(vids, eps(2, 38))
        self.assertEqual([x["video"] for x in r["baixar"]], ["l"])
        self.assertEqual(r["so_membros"], [])

    def test_dublado_ganha_de_legendado(self):
        vids = [video("leg", "Arafta S02E03 legendado"), video("dub", "Arafta S02E03 dublado")]
        self.assertEqual([x["video"] for x in escolher(vids, eps(2, 5))["baixar"]], ["dub"])

    def test_ja_tem_arquivo_nao_baixa(self):
        r = escolher([video("a", COMPLETO)], eps(2, 38, com_arquivo={36}))
        self.assertEqual((r["baixar"], r["ja_tem"]), ([], [(2, 36)]))

    def test_sem_temporada_no_meio_de_outros_com_temporada_fica_de_fora(self):
        # o canal mistura a T1 legendada (sem "temporada" no título) com a T2: a T1 não pode virar T2
        vids = [video("t1", T1_LEGENDADO, 93 * 60), video("t2", COMPLETO.replace("36", "01"))]
        r = escolher(vids, eps(1, 100) + eps(2, 38), duracao_min=82)
        self.assertEqual([(x["temporada"], x["episodio"]) for x in r["baixar"]], [(2, 1)])

    def test_sem_temporada_usa_a_da_playlist(self):
        r = escolher([video("x", "Novela Episódio 7")], eps(1, 10) + eps(2, 10), lista_titulo="Novela - Temporada 2")
        self.assertEqual([(x["temporada"], x["episodio"]) for x in r["baixar"]], [(2, 7)])

    def test_sem_temporada_e_com_duvida_nao_baixa(self):
        r = escolher([video("x", "Novela Episódio 7")], eps(1, 10) + eps(2, 10))
        self.assertEqual(r["baixar"], [])

    def test_episodio_que_o_sonarr_nao_conhece(self):
        r = escolher([video("x", "Serie S02E40")], eps(2, 38))
        self.assertEqual(r["fora"], [(2, 40)])


class TestDiversos(unittest.TestCase):
    def test_resolucao_com_bordas_cortadas(self):
        self.assertEqual([resolucao(h) for h in (1012, 1080, 676, 720, 360)], [1080, 1080, 720, 720, 480])

    def test_bloqueio_do_youtube_pausa_em_vez_de_falhar(self):
        self.assertTrue(bloqueio("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies"))
        self.assertTrue(bloqueio("HTTP Error 429: Too Many Requests"))
        self.assertFalse(bloqueio("ERROR: [youtube] x: Video unavailable"))

    def test_faixas(self):
        self.assertEqual(faixas([1, 2, 3, 5, 7, 8]), "E01–E03, E05, E07–E08")

    def test_link_de_canal_vira_aba_de_videos(self):
        self.assertEqual(link_da_lista("https://www.youtube.com/channel/UCUKfJzYO-0I5cmfJbXIEDIQ"),
                         "https://www.youtube.com/channel/UCUKfJzYO-0I5cmfJbXIEDIQ/videos")
        self.assertEqual(link_da_lista("https://www.youtube.com/@araftadizisi"),
                         "https://www.youtube.com/@araftadizisi/videos")
        pl = "https://www.youtube.com/playlist?list=PL4B_mPHji3IdwXgPPK2w_Xbq49Irolevo"
        self.assertEqual(link_da_lista(pl), pl)
        self.assertIsNone(link_da_lista("https://vimeo.com/123"))

    def test_adivinha_a_serie_pelo_comeco_do_nome(self):
        series = [{"id": 3, "title": "Breaking Bad"}, {"id": 4, "title": "Arafta: Bound By Fate"}]
        s = adivinhar_serie(series, "Arafta - Portuguese - Videos", [COMPLETO, CENA, CHAMADA])
        self.assertEqual(s["id"], 4)
        self.assertIsNone(adivinhar_serie(series, "Receitas da vovó", ["Bolo de cenoura"]))


if __name__ == "__main__":
    unittest.main()
