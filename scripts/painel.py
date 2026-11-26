"""Serviço "painel": interface web da Locadora (pessoas, diagnóstico, configurações, manutenção).

  python /scripts/painel.py         serviço (docker-compose: painel), porta 8585 no container

Pessoas e a parte "por dentro dos serviços" do diagnóstico chamam os módulos de scripts/stack, como
os scripts de terminal. O que precisa do Docker ou do .env (containers, IP da VPN, configurações,
atualizar, backups, senha) é pedido ao serviço "operador" (scripts/operador.py) pela rede interna:
o painel, que fica exposto na rede, não tem acesso ao Docker. Login com o STACK_USER/STACK_PASSWORD.
"""
import hashlib
import hmac
import http.server
import json
import os
import secrets
import socketserver
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stack import diagnostico as diag  # noqa: E402
from stack import pessoas  # noqa: E402
from stack.bazarr import bazarr  # noqa: E402
from stack.common import PASSWORD, USER  # noqa: E402

PORTA = 8585
ESTATICOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel")
LOGO = "/assets/logo/locadora-symbol.svg"
COOKIE = "locadora_painel"
SESSAO_DIAS = 30
MAX_CORPO = 64 * 1024
OPERADOR = "http://operador:8586"
OPERADOR_TOKEN = os.environ.get("OPERADOR_TOKEN", "")

# Sessão = validade + acaso, assinados. Sobrevive ao painel ser recriado (numa atualização, por
# exemplo) e cai sozinha quando a senha muda, porque a chave inclui a senha.
_CHAVE = hashlib.sha256(((os.environ.get("PAINEL_SEGREDO") or secrets.token_hex(32)) + "\0" + PASSWORD)
                        .encode()).digest()
_saidas = set()                  # sessões encerradas com "Sair" (até o container reiniciar)
_trava_sessoes = threading.Lock()
_trava_login = threading.Lock()  # tentativas de login uma de cada vez (com espera se errar)
_trava_mudanca = threading.Lock()  # uma mudança em pessoas por vez (Seerr/Jellyfin/Bazarr)
_trava_diag = threading.Lock()

ARQUIVOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/painel.css": ("painel.css", "text/css; charset=utf-8"),
    "/painel.js": ("painel.js", "text/javascript; charset=utf-8"),
}


class Erro(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def login_confere(usuario, senha):
    # compare_digest nos dois para o tempo de resposta não revelar qual errou
    u = hmac.compare_digest(usuario.encode(), USER.encode())
    s = hmac.compare_digest(senha.encode(), PASSWORD.encode())
    return u and s


def _assinar(corpo):
    return hmac.new(_CHAVE, corpo.encode(), hashlib.sha256).hexdigest()


def nova_sessao():
    corpo = f"{int(time.time()) + SESSAO_DIAS * 86400}.{secrets.token_hex(8)}"
    return f"{corpo}.{_assinar(corpo)}"


def sessao_valida(token):
    validade, _, resto = (token or "").partition(".")
    acaso, _, assinatura = resto.partition(".")
    if not (validade.isdigit() and acaso and assinatura):
        return False
    if not hmac.compare_digest(assinatura, _assinar(f"{validade}.{acaso}")):
        return False
    with _trava_sessoes:
        return int(validade) > time.time() and token not in _saidas


def encerrar_sessao(token):
    if sessao_valida(token):
        with _trava_sessoes:
            _saidas.add(token)


def operador(metodo, caminho, corpo=None, timeout=60):
    """Repassa um pedido ao operador. Devolve (status, json)."""
    if not OPERADOR_TOKEN:
        raise Erro(503, "Esta parte do painel ainda não está ligada: rode ./setup.sh uma vez no servidor.")
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(OPERADOR + caminho, data=dados, method=metodo,
                                 headers={"X-Token": OPERADOR_TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("erro") or f"erro {e.code}"
        except ValueError:
            msg = f"erro {e.code}"
        if e.code == 401:  # não é o login da pessoa: é o token entre painel e operador
            raise Erro(503, "O painel e o operador estão com tokens diferentes: rode ./setup.sh no servidor.") from None
        raise Erro(e.code if e.code < 500 or e.code == 503 else 502, msg[:1].upper() + msg[1:]) from None
    except OSError:
        raise Erro(503, "O operador não responde (ele reinicia durante atualizações; tente de novo em "
                        "instantes). Se continuar, rode ./setup.sh no servidor.") from None


def validar_pessoa(dados, nova):
    nome = str(dados.get("nome") or "").strip()
    if not nome or len(nome) > 64 or any(ord(c) < 32 for c in nome):
        raise Erro(400, "Nome inválido (até 64 caracteres).")
    audio, legenda = dados.get("audio"), dados.get("legenda")
    if audio not in pessoas.AUDIO:
        raise Erro(400, f"Áudio: use {' ou '.join(pessoas.AUDIO)}.")
    if legenda not in pessoas.LEGENDA:
        raise Erro(400, f"Legenda: use {' ou '.join(pessoas.LEGENDA)}.")
    senha = str(dados.get("senha") or "")
    if nova and len(senha) < 4:
        raise Erro(400, "A senha precisa ter pelo menos 4 caracteres.")
    return nome, senha, audio, legenda


def _mudar_pessoa(fn, *args):
    with _trava_mudanca:
        fn(*args)
        bazarr()  # legenda em inglês entra/sai do Bazarr conforme as escolhas


def rodar_diagnostico():
    with _trava_diag:
        r = diag.Resultado(imprimir=False)
        # Containers, IP da VPN e Tailscale: só o operador enxerga (precisa do Docker)
        try:
            _, d = operador("GET", "/diagnostico", timeout=90)
            completo = True
        except Erro:
            d, completo = {"itens": []}, False
        for it in d["itens"]:
            r.secao(it["secao"])
            if it["nivel"] == "ok":
                r.ok(it["msg"])
            elif it["nivel"] == "aviso":
                r.aviso(it["msg"], it.get("dica"))
            else:
                r.erro(it["msg"], it.get("dica"))
        r.secao("Disco")
        diag.disco(r)
        r.secao("VPN")
        porta = diag.porta_encaminhada(r)
        diag.diagnostico(r, porta)
        return {"itens": r.itens, "erros": r.erros, "avisos": r.avisos, "completo": completo}


class Painel(http.server.BaseHTTPRequestHandler):
    server_version = "Locadora"
    sys_version = ""

    # ---------- respostas
    def _cabecalhos_seguranca(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")

    def _enviar(self, status, corpo, tipo, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self._cabecalhos_seguranca()
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, status, dados, extra=()):
        self._enviar(status, json.dumps(dados, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def _cookie(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = parte.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CORPO:
            raise Erro(413, "Pedido grande demais.")
        try:
            dados = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise Erro(400, "JSON inválido.") from None
        if not isinstance(dados, dict):
            raise Erro(400, "JSON inválido.")
        return dados

    def log_message(self, fmt, *args):  # sem IP/caminho de cada estático; só a API
        if self.path.startswith("/api/") and self.path != "/api/eu" and not self.path.startswith("/api/tarefa?"):
            print(f"[painel] {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)

    # ---------- roteamento
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        caminho = self.path.split("?", 1)[0]
        if caminho == "/saude":
            return self._enviar(200, b"ok", "text/plain")
        if caminho in ARQUIVOS:
            nome, tipo = ARQUIVOS[caminho]
            with open(os.path.join(ESTATICOS, nome), "rb") as f:
                return self._enviar(200, f.read(), tipo)
        if caminho == "/logo.svg":
            try:
                with open(LOGO, "rb") as f:
                    return self._enviar(200, f.read(), "image/svg+xml")
            except OSError:
                return self._enviar(404, b"", "text/plain")
        self._api("GET", caminho)

    def do_POST(self):
        self._api("POST", self.path.split("?", 1)[0])

    def _api(self, metodo, caminho):
        try:
            if not caminho.startswith("/api/"):
                raise Erro(404, "Não encontrado.")
            if metodo == "POST":
                # Contra CSRF: além do cookie SameSite=Strict, só aceita JSON vindo do próprio painel
                if "application/json" not in (self.headers.get("Content-Type") or "") \
                        or self.headers.get("X-Locadora") != "1":
                    raise Erro(403, "Pedido recusado.")
            if (metodo, caminho) == ("POST", "/api/entrar"):
                return self._entrar()
            if not sessao_valida(self._cookie()):
                raise Erro(401, "Entre de novo.")
            rota = {
                ("GET", "/api/eu"): lambda: {"usuario": USER},
                ("POST", "/api/sair"): self._sair,
                ("GET", "/api/pessoas"): lambda: {"pessoas": pessoas.lista()},
                ("POST", "/api/pessoas/nova"): self._nova,
                ("POST", "/api/pessoas/preferencia"): self._preferencia,
                ("POST", "/api/diagnostico"): rodar_diagnostico,
                ("GET", "/api/config"): lambda: operador("GET", "/config")[1],
                ("POST", "/api/config"): lambda: operador("POST", "/config", {"valores": self._corpo().get("valores")})[1],
                ("GET", "/api/backups"): lambda: operador("GET", "/backups")[1],
                ("POST", "/api/tarefa"): lambda: operador("POST", "/tarefa", self._corpo())[1],
                ("GET", "/api/tarefa"): self._tarefa,
            }.get((metodo, caminho))
            if not rota:
                raise Erro(404, "Não encontrado.")
            res = rota()
            if res is not None:
                self._json(200, res)
        except Erro as e:
            self._json(e.status, {"erro": str(e)})
        except SystemExit as e:  # os módulos de stack/ avisam erros com sys.exit("mensagem")
            self._json(400, {"erro": str(e.code)})
        except RuntimeError as e:  # um serviço respondeu com erro (Client.req)
            print(f"[painel] {e}", flush=True)
            self._json(502, {"erro": f"Um serviço respondeu com erro: {str(e)[:300]}"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"erro": f"Erro inesperado ({type(e).__name__}). Veja: docker compose logs painel"})

    # ---------- ações
    def _entrar(self):
        dados = self._corpo()
        with _trava_login:
            if not login_confere(str(dados.get("usuario") or ""), str(dados.get("senha") or "")):
                time.sleep(1.5)
                raise Erro(401, "Usuário ou senha incorretos.")
        cookie = f"{COOKIE}={nova_sessao()}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSAO_DIAS * 86400}"
        self._json(200, {"usuario": USER}, [("Set-Cookie", cookie)])

    def _tarefa(self):
        desde = self.path.partition("desde=")[2].split("&")[0]
        return operador("GET", f"/tarefa?desde={int(desde) if desde.isdigit() else 0}", timeout=30)[1]

    def _sair(self):
        encerrar_sessao(self._cookie())
        self._json(200, {}, [("Set-Cookie", f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")])

    def _nova(self):
        nome, senha, audio, legenda = validar_pessoa(self._corpo(), nova=True)
        _mudar_pessoa(pessoas.nova, nome, senha, audio, legenda)
        return {"ok": f"{nome} cadastrada: áudio {audio}, legenda {legenda}."}

    def _preferencia(self):
        nome, _, audio, legenda = validar_pessoa(self._corpo(), nova=False)
        _mudar_pessoa(pessoas.preferencia, nome, audio, legenda)
        return {"ok": f"{nome}: áudio {audio}, legenda {legenda}."}


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"[painel] no ar na porta {PORTA} (login: {USER})", flush=True)
    Servidor(("", PORTA), Painel).serve_forever()
