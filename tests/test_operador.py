"""Operador (scripts/operador.py) e o .env visto pelo painel (scripts/stack/envfile.py).

Sem Docker: as chamadas ao docker são trocadas por falsas e o .env é um arquivo temporário.
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
for k in ("STACK_USER", "STACK_PASSWORD", "RADARR_API_KEY", "SONARR_API_KEY", "PROWLARR_API_KEY"):
    os.environ.setdefault(k, "teste")

import operador  # noqa: E402
from stack import envfile  # noqa: E402

def texto_de(caminho):
    with open(caminho) as f:
        return f.read()


ENV_EXEMPLO = """# comentário
STACK_USER=admin
STACK_PASSWORD='s3nha'
SUBDL_API_KEY='abc'
TELEGRAM_CHAT_ID=
JELLYFIN_PORT=8096
SEERR_PORT='5055'
PAINEL_PORT=8585
"""


class TestEnvfile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.env = os.path.join(self.dir, ".env")
        with open(self.env, "w") as f:
            f.write(ENV_EXEMPLO)
        os.chmod(self.env, 0o600)

    def test_ler_tira_aspas(self):
        v = envfile.ler(self.env)
        self.assertEqual((v["STACK_PASSWORD"], v["SEERR_PORT"], v["TELEGRAM_CHAT_ID"]), ("s3nha", "5055", ""))

    def test_segredos_nao_saem(self):
        campos = {c["chave"]: c for c in envfile.para_painel(envfile.ler(self.env))["campos"]}
        self.assertEqual(campos["SUBDL_API_KEY"], {**campos["SUBDL_API_KEY"], "definido": True})
        self.assertNotIn("valor", campos["SUBDL_API_KEY"])
        self.assertFalse(campos["TS_AUTHKEY"]["definido"])
        self.assertNotIn("STACK_PASSWORD", campos)
        self.assertNotIn("STACK_USER", campos)

    def test_validar_recusa(self):
        atuais = envfile.ler(self.env)
        ruins = [
            {"STACK_PASSWORD": "x"},              # fora da lista
            {"DATA_ROOT": "mnt"},
            {"RADARR_API_KEY": "x"},
            {"SUBDL_API_KEY": "a'b"},             # quebraria o KEY='valor'
            {"SUBDL_API_KEY": "a\nSTACK_PASSWORD=x"},
            {"JELLYFIN_PORT": "80"},
            {"JELLYFIN_PORT": "abc"},
            {"JELLYFIN_PORT": "5055"},            # igual à do Seerr
            {"LIMPEZA_DIAS": "0"},
            {"TELEGRAM_CHAT_ID": "@grupo"},
            {"STACK_EMAIL": "sem-arroba"},
            {"SUBDL_API_KEY": 123},
        ]
        for novos in ruins:
            with self.subTest(novos=novos), self.assertRaises(ValueError):
                envfile.validar(novos, atuais)
        self.assertEqual(envfile.validar({"TELEGRAM_CHAT_ID": " -100123 ", "LIMPEZA_DIAS": ""}, atuais),
                         {"TELEGRAM_CHAT_ID": "-100123", "LIMPEZA_DIAS": ""})

    def test_validar_pasta(self):
        atuais = envfile.ler(self.env)
        for ruim in ("", "data", "~/filmes", "/mnt/../etc", "/mnt/hd:/x", "/", "./"):
            with self.subTest(pasta=ruim), self.assertRaises(ValueError):
                envfile.validar({"DATA_ROOT": ruim}, atuais)
        self.assertEqual(envfile.validar({"DATA_ROOT": " /mnt/hd/locadora/ "}, atuais), {"DATA_ROOT": "/mnt/hd/locadora"})
        self.assertEqual(envfile.validar({"DATA_ROOT": "./midia"}, atuais), {"DATA_ROOT": "./midia"})

    def test_gravar_troca_acrescenta_e_mantem_permissao(self):
        mudou = envfile.gravar(self.env, {"SUBDL_API_KEY": "nova", "TS_AUTHKEY": "tskey-1", "JELLYFIN_PORT": "8096"})
        self.assertEqual(sorted(mudou), ["SUBDL_API_KEY", "TS_AUTHKEY"])  # a porta já era essa
        texto = texto_de(self.env)
        self.assertIn("SUBDL_API_KEY='nova'\n", texto)
        self.assertTrue(texto.endswith("TS_AUTHKEY='tskey-1'\n"))
        self.assertIn("# comentário\nSTACK_USER=admin\n", texto)  # resto intacto
        self.assertEqual(os.stat(self.env).st_mode & 0o777, 0o600)
        self.assertEqual(envfile.gravar(self.env, {"SUBDL_API_KEY": "nova"}), [])

    def test_remover(self):
        envfile.gravar(self.env, {"NEW_STACK_PASSWORD": "x"})
        envfile.remover(self.env, "NEW_STACK_PASSWORD")
        self.assertNotIn("NEW_STACK_PASSWORD", texto_de(self.env))


class TestOperador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = operador.Servidor(("127.0.0.1", 0), operador.Operador)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        with open(os.path.join(self.dir, ".env"), "w") as f:
            f.write(ENV_EXEMPLO)
        os.mkdir(os.path.join(self.dir, "backups"))
        open(os.path.join(self.dir, "backups", "locadora-20261125-142240.tar.gz"), "w").close()
        open(os.path.join(self.dir, "backups", "outro.tar.gz"), "w").close()
        for nome, valor in (("TOKEN", "segredo"), ("DIR", self.dir), ("ENV", os.path.join(self.dir, ".env"))):
            p = mock.patch.object(operador, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        # Nenhum docker de verdade: tarefa não existe até alguém iniciar
        self.docker = mock.patch.object(operador, "docker", return_value=(1, "", "No such object")).start()
        self.addCleanup(mock.patch.stopall)

    def req(self, metodo, caminho, corpo=None, token="segredo"):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        c.request(metodo, caminho, json.dumps(corpo) if corpo is not None else None, {"X-Token": token})
        r = c.getresponse()
        dados = json.loads(r.read())
        c.close()
        return r.status, dados

    def test_token(self):
        self.assertEqual(self.req("GET", "/config", token="")[0], 401)
        self.assertEqual(self.req("GET", "/config", token="errado")[0], 401)
        self.assertEqual(self.req("GET", "/config")[0], 200)
        self.assertEqual(self.req("GET", "/saude", token="")[0], 200)

    def test_config_grava_so_o_permitido(self):
        st, r = self.req("POST", "/config", {"valores": {"STACK_PASSWORD": "hack"}})
        self.assertEqual(st, 400)
        st, r = self.req("POST", "/config", {"valores": {"LIMPEZA_DIAS": "30"}})
        self.assertEqual((st, r), (200, {"mudou": ["LIMPEZA_DIAS"]}))
        self.assertEqual(envfile.ler(operador.ENV)["LIMPEZA_DIAS"], "30")

    def test_pasta_nova_precisa_existir(self):
        # fora da pasta da Locadora: confere com um container (aqui o docker falso diz que não existe)
        st, r = self.req("POST", "/config", {"valores": {"DATA_ROOT": "/mnt/nao-existe"}})
        self.assertEqual(st, 400)
        self.assertIn("/mnt/nao-existe", r["erro"])
        run = self.docker.call_args.args
        self.assertIn("type=bind,src=/mnt/nao-existe,dst=/alvo", run)
        self.assertNotIn("DATA_ROOT", envfile.ler(operador.ENV))
        self.docker.return_value = (0, "", "")
        st, r = self.req("POST", "/config", {"valores": {"DATA_ROOT": "/mnt/hd"}})
        self.assertEqual((st, r), (200, {"mudou": ["DATA_ROOT"]}))
        # dentro da pasta da Locadora: o operador olha direto
        self.docker.reset_mock()
        st, r = self.req("POST", "/config", {"valores": {"DATA_ROOT": "./midia"}})
        self.assertEqual(st, 200)
        self.docker.assert_not_called()

    def test_backups_lista_so_os_da_locadora(self):
        st, r = self.req("GET", "/backups")
        self.assertEqual([b["arquivo"] for b in r["backups"]], ["locadora-20261125-142240.tar.gz"])

    def test_restaurar_so_backup_existente(self):
        for arq in ("../.env", "outro.tar.gz", "locadora-20990101-000000.tar.gz", "backups/locadora-20261125-142240.tar.gz"):
            with self.subTest(arq=arq), self.assertRaises(operador.Erro):
                operador.comando("restaurar", {"arquivo": arq})
        self.assertEqual(operador.comando("restaurar", {"arquivo": "locadora-20261125-142240.tar.gz"}),
                         ["./atualizar.sh", "--restaurar", "backups/locadora-20261125-142240.tar.gz"])

    def test_acao_desconhecida(self):
        with self.assertRaises(operador.Erro):
            operador.comando("rm -rf /", {})

    def test_senha_valida_e_vai_pelo_env(self):
        for ruim in ("curta", "com'aspas1", "linha\nnova1"):
            with self.subTest(senha=ruim), self.assertRaises(operador.Erro):
                operador.comando("senha", {"senha": ruim})
        self.assertNotIn("NEW_STACK_PASSWORD", texto_de(operador.ENV))
        cmd = operador.comando("senha", {"senha": "senha-nova-1"})
        self.assertIn("./change-password.sh", cmd[-1])
        self.assertNotIn("senha-nova-1", " ".join(cmd))  # não aparece no docker inspect da tarefa
        self.assertEqual(envfile.ler(operador.ENV)["NEW_STACK_PASSWORD"], "senha-nova-1")

    def test_uma_tarefa_por_vez(self):
        self.docker.return_value = (0, "running|0|2026-11-26T10:00:00Z|0001-01-01T00:00:00Z|atualizar", "")
        st, r = self.req("POST", "/tarefa", {"acao": "backup"})
        self.assertEqual(st, 409)
        self.assertIn("Atualizar", r["erro"])

    def test_iniciar_tarefa_monta_a_pasta_no_mesmo_caminho(self):
        chamadas = []

        def docker(*args, **kw):
            chamadas.append(args)
            if args[0] == "inspect":
                return (1, "", "") if len(chamadas) == 1 else (0, "running|0|x|y|backup", "")
            return 0, "", ""

        self.docker.side_effect = docker
        with mock.patch.object(operador, "usuario", return_value=(1000, 1000)), \
                mock.patch.object(operador, "grupo_do_socket", return_value=963):
            st, r = self.req("POST", "/tarefa", {"acao": "backup"})
        self.assertEqual((st, r["tarefa"]["estado"]), (200, "rodando"))
        run = next(a for a in chamadas if a[0] == "run")
        self.assertIn(f"{self.dir}:{self.dir}", run)
        self.assertEqual(run[run.index("--user") + 1], "1000:1000")
        self.assertEqual(run[-3:], ("locadora-operador", "./atualizar.sh", "--backup"))
        self.assertIn("LOCADORA_PELO_PAINEL=1", run)

    def test_tarefa_monta_a_pasta_nova_dos_filmes(self):
        envfile.gravar(operador.ENV, {"DATA_ROOT": "/mnt/hd/locadora"})
        chamadas = []

        def docker(*args, **kw):
            chamadas.append(args)
            return (1, "", "") if args[0] == "inspect" and len(chamadas) == 1 else (0, "running|0|x|y|aplicar", "")

        self.docker.side_effect = docker
        with mock.patch.object(operador, "DATA", "/srv/antiga"), mock.patch.object(operador, "usuario", return_value=None):
            self.assertEqual(self.req("POST", "/tarefa", {"acao": "aplicar"})[0], 200)
        run = next(a for a in chamadas if a[0] == "run")
        self.assertIn("/mnt/hd/locadora:/mnt/hd/locadora", run)
        self.assertIn("/srv/antiga:/srv/antiga", run)


if __name__ == "__main__":
    unittest.main()
