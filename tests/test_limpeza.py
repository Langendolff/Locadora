"""Regra da limpeza automática (scripts/stack/limpeza.py): na dúvida, o filme fica."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

from stack.limpeza import decidir  # noqa: E402

AGORA = dt.datetime(2026, 11, 25, tzinfo=dt.timezone.utc)
dias = lambda n: AGORA - dt.timedelta(days=n)
FILME = {1: {"nome": "Duna", "chegou": dias(100)}}
visto = lambda n, **k: {"visto": True, "quando": dias(n), **k}


def sai_hoje(filmes, vistos, d=30):
    return [t for t, quando in decidir(filmes, vistos, AGORA, d).items() if quando <= AGORA]


class TestLimpeza(unittest.TestCase):
    def test_todo_mundo_viu_ha_mais_de_30_dias_sai(self):
        self.assertEqual(sai_hoje(FILME, {"ana": {1: visto(40)}, "beto": {1: visto(35)}}), [1])

    def test_alguem_viu_ha_pouco_tempo_fica(self):
        self.assertEqual(sai_hoje(FILME, {"ana": {1: visto(40)}, "beto": {1: visto(10)}}), [])

    def test_alguem_ativo_ainda_nao_viu_fica(self):
        vistos = {"ana": {1: visto(40)}, "beto": {2: visto(5)}}  # beto assiste outras coisas
        self.assertEqual(sai_hoje(FILME, vistos), [])

    def test_conta_parada_nao_segura_o_filme(self):
        vistos = {"ana": {1: visto(40), 2: visto(3)}, "visita": {}}  # visita nunca assistiu nada
        self.assertEqual(sai_hoje(FILME, vistos), [1])

    def test_favorito_de_alguem_fica(self):
        self.assertEqual(sai_hoje(FILME, {"ana": {1: visto(40)}, "beto": {1: visto(40, favorito=True)}}), [])

    def test_comecou_e_nao_terminou_fica(self):
        vistos = {"ana": {1: visto(40)}, "beto": {1: {"visto": False, "quando": dias(50), "comecou": True}}}
        self.assertEqual(sai_hoje(FILME, vistos), [])

    def test_ninguem_assistindo_nada_nao_apaga_nada(self):
        self.assertEqual(sai_hoje(FILME, {"ana": {1: visto(200)}}), [])

    def test_chegou_ha_pouco_fica_mesmo_ja_visto_antes(self):
        # Ex.: baixado de novo (versão dublada) depois de já assistido
        filmes = {1: {"nome": "Duna", "chegou": dias(5)}}
        self.assertEqual(sai_hoje(filmes, {"ana": {1: visto(60), 2: visto(1)}}), [])

    def test_data_futura_serve_para_aviso_antecipado(self):
        datas = decidir(FILME, {"ana": {1: visto(28)}}, AGORA, 30)
        self.assertEqual(datas[1], dias(28) + dt.timedelta(days=30))


if __name__ == "__main__":
    unittest.main()
