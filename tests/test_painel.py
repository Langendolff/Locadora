"""Painel web (scripts/painel.py): login, proteção contra CSRF, validação e rotas de pessoas.

Sobe o servidor de verdade numa porta local; os módulos que falam com a stack são trocados por falsos.
"""
import http.client
import json
import os
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

import painel  # noqa: E402
from stack import diagnostico as diag  # noqa: E402


class TestPainel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = painel.Servidor(("127.0.0.1", 0), painel.Painel)
        cls.porta = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.cookie = ""
        p = mock.patch.object(painel.time, "sleep")  # login errado espera 1,5 s
        p.start()
        self.addCleanup(p.stop)

    def req(self, metodo, caminho, corpo=None, cabecalhos=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        h = {"X-Locadora": "1", "Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(cabecalhos or {})
        c.request(metodo, caminho, json.dumps(corpo) if corpo is not None else None, h)
        r = c.getresponse()
        bruto = r.read()
        if r.getheader("Set-Cookie"):
            self.cookie = r.getheader("Set-Cookie").split(";", 1)[0]
        c.close()
        try:
            return r.status, json.loads(bruto)
        except ValueError:
            return r.status, bruto

    def entrar(self):
        st, _ = self.req("POST", "/api/entrar", {"usuario": "teste", "senha": "teste"})
        self.assertEqual(st, 200)

    def test_pagina_e_saude_sem_login(self):
        self.assertEqual(self.req("GET", "/")[0], 200)
        self.assertEqual(self.req("GET", "/painel.js")[0], 200)
        self.assertEqual(self.req("GET", "/saude")[0], 200)

    def test_api_exige_login(self):
        self.assertEqual(self.req("GET", "/api/pessoas")[0], 401)
        self.assertEqual(self.req("POST", "/api/diagnostico", {})[0], 401)
        self.cookie = "locadora_painel=inventado"
        self.assertEqual(self.req("GET", "/api/pessoas")[0], 401)

    def test_senha_errada(self):
        st, r = self.req("POST", "/api/entrar", {"usuario": "teste", "senha": "errada"})
        self.assertEqual(st, 401)
        self.assertEqual(self.cookie, "")
        st, _ = self.req("POST", "/api/entrar", {"usuario": "outro", "senha": "teste"})
        self.assertEqual(st, 401)

    def test_login_e_sair(self):
        self.entrar()
        self.assertEqual(self.req("GET", "/api/eu"), (200, {"usuario": "teste"}))
        antigo = self.cookie
        self.assertEqual(self.req("POST", "/api/sair", {})[0], 200)
        self.cookie = antigo  # o token antigo não vale mais
        self.assertEqual(self.req("GET", "/api/eu")[0], 401)

    def test_post_sem_cabecalho_do_painel_e_recusado(self):
        self.entrar()
        with mock.patch.object(painel.pessoas, "preferencia") as pref:
            st, _ = self.req("POST", "/api/pessoas/preferencia",
                             {"nome": "Ana", "audio": "original", "legenda": "en"}, {"X-Locadora": "0"})
            self.assertEqual(st, 403)
            st, _ = self.req("POST", "/api/pessoas/preferencia", None,
                             {"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(st, 403)
            pref.assert_not_called()

    def test_nova_pessoa(self):
        self.entrar()
        with mock.patch.object(painel.pessoas, "nova") as nova, mock.patch.object(painel, "bazarr") as baz:
            st, r = self.req("POST", "/api/pessoas/nova",
                             {"nome": " Ana ", "senha": "1234", "audio": "original", "legenda": "en"})
            self.assertEqual(st, 200, r)
            nova.assert_called_once_with("Ana", "1234", "original", "en")
            baz.assert_called_once()

    def test_validacao(self):
        self.entrar()
        with mock.patch.object(painel.pessoas, "nova") as nova, mock.patch.object(painel, "bazarr"):
            for corpo in ({"nome": "Ana", "senha": "123", "audio": "dublado", "legenda": "pt-br"},
                          {"nome": "", "senha": "1234", "audio": "dublado", "legenda": "pt-br"},
                          {"nome": "Ana", "senha": "1234", "audio": "mudo", "legenda": "pt-br"},
                          {"nome": "Ana", "senha": "1234", "audio": "dublado", "legenda": "klingon"},
                          {"nome": "A\nna", "senha": "1234", "audio": "dublado", "legenda": "pt-br"}):
                with self.subTest(corpo=corpo):
                    self.assertEqual(self.req("POST", "/api/pessoas/nova", corpo)[0], 400)
            nova.assert_not_called()

    def test_erro_do_modulo_vira_mensagem(self):
        # pessoas.py usa sys.exit("mensagem"); o painel tem que responder, não derrubar a conexão
        self.entrar()
        with mock.patch.object(painel.pessoas, "preferencia", side_effect=SystemExit("Pessoa 'Zé' não existe.")):
            st, r = self.req("POST", "/api/pessoas/preferencia", {"nome": "Zé", "audio": "dublado", "legenda": "pt-br"})
            self.assertEqual((st, r["erro"]), (400, "Pessoa 'Zé' não existe."))
        with mock.patch.object(painel.pessoas, "lista", side_effect=RuntimeError("GET x -> 500")):
            st, r = self.req("GET", "/api/pessoas")
            self.assertEqual(st, 502)


    def test_sessao_assinada(self):
        token = painel.nova_sessao()
        self.assertTrue(painel.sessao_valida(token))
        validade, acaso, assinatura = token.split(".")
        self.assertFalse(painel.sessao_valida(f"{int(validade) + 999}.{acaso}.{assinatura}"))  # mexeu na validade
        self.assertFalse(painel.sessao_valida(f"1.{acaso}.{painel._assinar('1.' + acaso)}"))   # vencida
        self.assertFalse(painel.sessao_valida("lixo"))

    def test_rotas_do_operador_repassam(self):
        self.entrar()
        with mock.patch.object(painel, "operador", return_value=(200, {"mudou": ["LIMPEZA_DIAS"]})) as op:
            st, r = self.req("POST", "/api/config", {"valores": {"LIMPEZA_DIAS": "30"}})
            self.assertEqual((st, r), (200, {"mudou": ["LIMPEZA_DIAS"]}))
            op.assert_called_with("POST", "/config", {"valores": {"LIMPEZA_DIAS": "30"}})
            self.req("GET", "/api/tarefa?desde=12")
            op.assert_called_with("GET", "/tarefa?desde=12", timeout=30)
            self.req("GET", "/api/tarefa?desde=../x")
            op.assert_called_with("GET", "/tarefa?desde=0", timeout=30)

    def test_operador_fora_do_ar_nao_desloga(self):
        # 401 do operador é problema de token, não de login: o navegador não pode voltar ao login
        self.entrar()
        with mock.patch.object(painel, "OPERADOR_TOKEN", "x"), \
                mock.patch.object(painel, "OPERADOR", "http://127.0.0.1:9"):
            st, r = self.req("GET", "/api/config")
        self.assertEqual(st, 503)


class TestDiagnosticoColeta(unittest.TestCase):
    def test_resultado_guarda_itens_por_secao(self):
        r = diag.Resultado(imprimir=False)
        r.secao("Busca")
        r.ok("tudo bem")
        r.aviso("hum", "faça isso")
        r.secao("Disco")
        r.erro("cheio", "apague algo")
        self.assertEqual((r.erros, r.avisos), (1, 1))
        self.assertEqual([(i["secao"], i["nivel"]) for i in r.itens],
                         [("Busca", "ok"), ("Busca", "aviso"), ("Disco", "erro")])
        self.assertEqual(r.itens[1]["dica"], "faça isso")

    def test_disco_inexistente_e_erro(self):
        r = diag.Resultado(imprimir=False)
        diag.disco(r, "/caminho/que/nao/existe")
        self.assertEqual(r.erros, 1)

    def test_porta_vpn_desligada_nao_avisa(self):
        r = diag.Resultado(imprimir=False)
        with mock.patch.dict(os.environ, {"VPN_PORT_FORWARDING": "off"}):
            self.assertEqual(diag.porta_encaminhada(r), "")
        self.assertEqual(r.itens, [])


if __name__ == "__main__":
    unittest.main()
