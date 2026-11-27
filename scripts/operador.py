"""Serviço "operador": o braço do painel que mexe no Docker e no .env.

  python /scripts/operador.py       serviço (docker-compose: operador), porta 8586 só na rede interna

É o único container da Locadora com o socket do Docker. Não publica porta no host e só atende quem
mandar o OPERADOR_TOKEN do .env (o painel). Faz uma lista fixa de coisas:

  GET  /diagnostico          estado dos containers, IP de saída da VPN, Tailscale
  GET  /config               campos editáveis do .env (segredos: só se estão preenchidos)
  POST /config               grava campos (validados por stack/envfile.py)
  GET  /backups              backups em backups/
  POST /tarefa               começa uma tarefa: aplicar | atualizar | backup | restaurar | senha
  GET  /tarefa?desde=N       andamento e saída da tarefa atual (ou da última)

As tarefas rodam os mesmos scripts do terminal (setup.sh, atualizar.sh, change-password.sh) num
container avulso, fora do compose: o atualizar.sh para e recria os serviços do compose, e a tarefa
não pode morrer junto. A saída fica no container até a próxima tarefa.
"""
import hmac
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stack import envfile  # noqa: E402

PORTA = 8586
TOKEN = os.environ.get("OPERADOR_TOKEN", "")
DIR = os.environ.get("LOCADORA_DIR", "")      # a pasta da Locadora, no mesmo caminho que no host
DATA = os.environ.get("DATA_ROOT_ABS", "")    # DATA_ROOT em caminho absoluto (pode ficar fora de DIR)
ENV = os.path.join(DIR, ".env")
SOCK = "/var/run/docker.sock"
IMAGEM = "locadora-operador"
TAREFA = "locadora-tarefa"                    # nome fixo: uma tarefa por vez
BACKUP = re.compile(r"^locadora-\d{8}-\d{6}\.tar\.gz$")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MAX_CORPO = 64 * 1024

# Containers que o diagnóstico confere (o tailscale só com a chave no .env)
SERVICOS = ["gluetun", "deluge", "prowlarr", "flaresolverr", "radarr", "sonarr", "bazarr",
            "jellyfin", "seerr", "tarefas", "painel", "operador"]  # mesma lista do ./diagnostico.sh

ACOES = {
    "aplicar": ("Aplicar as configurações", ["./setup.sh"]),
    "atualizar": ("Atualizar a Locadora", ["./atualizar.sh"]),
    "backup": ("Backup", ["./atualizar.sh", "--backup"]),
    "restaurar": ("Restaurar backup", None),   # + arquivo
    "senha": ("Trocar a senha", None),         # + senha nova
}
_trava = threading.Lock()


class Erro(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def docker(*args, timeout=30):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def grupo_do_socket():
    try:
        return os.stat(SOCK).st_gid
    except OSError:
        return None


def usuario():
    """PUID:PGID do .env, ou None para ficar como root.

    No Linux o socket é root:docker 660: dá para rodar como o usuário + o grupo do socket, e o que a
    tarefa grava (backups, .env, .git) continua sendo dele, como pelo terminal. Se o grupo não
    puder escrever no socket (Docker Desktop), fica como root; lá os arquivos da pasta compartilhada
    aparecem no host como do usuário de qualquer jeito."""
    try:
        if not os.stat(SOCK).st_mode & 0o020:
            return None
    except OSError:
        return None
    return int(os.environ.get("PUID") or 1000), int(os.environ.get("PGID") or 1000)


def baixar_privilegios():
    u = usuario()
    if os.getuid() != 0 or u is None:
        return
    os.setgroups([grupo_do_socket()])
    os.setgid(u[1])
    os.setuid(u[0])
    os.environ["HOME"] = "/tmp"


# ---------- pasta dos filmes e séries (DATA_ROOT)
def pasta_no_host(valor):
    """DATA_ROOT do .env em caminho absoluto do host (./algo é relativo à pasta da Locadora)."""
    return os.path.normpath(os.path.join(DIR, valor)) if valor else ""


def conferir_pasta(caminho):
    """A pasta existe no servidor e dá para gravar nela? O operador só enxerga a pasta da Locadora;
    o resto ele confere com um container que monta o caminho (--mount falha se ele não existir, em
    vez de criar uma pasta vazia como o -v faria)."""
    if (caminho + "/").startswith(DIR + "/"):
        if os.path.isdir(caminho) and os.access(caminho, os.W_OK):
            return
        pai = os.path.dirname(caminho)
        if not os.path.exists(caminho) and os.path.isdir(pai) and os.access(pai, os.W_OK):
            return  # dentro da pasta da Locadora o setup.sh cria
    else:
        u = usuario()
        quem = ["--user", f"{u[0]}:{u[1]}"] if u else []
        rc, _, _ = docker("run", "--rm", *quem, "--mount", f"type=bind,src={caminho},dst=/alvo",
                          "--entrypoint", "test", IMAGEM, "-w", "/alvo", timeout=60)
        if rc == 0:
            return
    raise Erro(400, f"a pasta {caminho} não existe no servidor ou não dá para gravar nela. "
                    "Crie a pasta (e monte o disco) antes")


# ---------- diagnóstico
def diagnostico():
    vals = envfile.ler(ENV)
    servicos = SERVICOS + (["tailscale"] if vals.get("TS_AUTHKEY") else [])
    itens = []

    def add(secao, nivel, msg, dica=None):
        itens.append({"secao": secao, "nivel": nivel, "msg": msg, "dica": dica})

    parados = set()
    for s in servicos:
        rc, out, _ = docker("inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} "
                            "{{.RestartCount}}", s)
        if rc:
            add("Serviços", "erro", f"{s} não existe", "aplique as configurações (Manutenção) ou rode ./setup.sh")
            parados.add(s)
            continue
        estado, *resto = out.split()
        saude = resto[0] if len(resto) == 2 else ""
        reinicios = int(resto[-1]) if resto and resto[-1].isdigit() else 0
        if estado != "running":
            add("Serviços", "erro", f"{s} está parado ({estado})", f"veja: docker compose logs --tail 50 {s}")
            parados.add(s)
        elif saude == "unhealthy":
            add("Serviços", "erro", f"{s} está rodando, mas com falha", f"veja: docker compose logs --tail 50 {s}")
        if reinicios > 5:
            add("Serviços", "aviso", f"{s} reiniciou {reinicios} vezes", f"veja: docker compose logs --tail 50 {s}")
    if not parados:
        add("Serviços", "ok", f"todos os {len(servicos)} serviços rodando")

    if parados & {"gluetun", "deluge"}:
        add("VPN", "erro", "sem VPN: gluetun ou deluge parado", "veja: docker compose logs --tail 50 gluetun")
    else:
        _, ip_vpn, _ = docker("exec", "deluge", "curl", "-fsS", "--max-time", "15", "https://ipinfo.io/ip", timeout=25)
        try:
            ip_casa = urllib.request.urlopen("https://ipinfo.io/ip", timeout=10).read().decode().strip()
        except Exception:
            ip_casa = ""
        if not ip_vpn:
            add("VPN", "erro", "o Deluge está sem internet: a VPN não está conectada",
                "veja: docker compose logs --tail 30 gluetun. Servidor gratuito da Proton não permite P2P; "
                "o .conf pode ter expirado")
        elif ip_casa and ip_vpn == ip_casa:
            add("VPN", "erro", f"o Deluge está saindo com o IP da sua casa ({ip_vpn}), não pela VPN",
                "pare os downloads agora: docker compose stop deluge. Depois rode ./setup.sh")
        else:
            add("VPN", "ok", f"downloads saem pela VPN (IP {ip_vpn})")

    if vals.get("TS_AUTHKEY") and "tailscale" not in parados:
        _, out, _ = docker("exec", "tailscale", "tailscale", "status", "--json")
        try:
            st = json.loads(out)
            nome = (st.get("Self") or {}).get("DNSName", "").rstrip(".")
            ok = st.get("BackendState") == "Running" and nome
        except ValueError:
            ok, nome = False, ""
        if ok:
            add("Fora de casa", "ok", f"acesso de fora de casa: https://{nome} (Seerr em :8443)")
        else:
            add("Fora de casa", "erro", "o Tailscale não está conectado",
                "a chave TS_AUTHKEY pode ter expirado ou já ter sido usada: gere outra no painel do Tailscale, "
                "troque em Configurações e aplique")
    return {"itens": itens}


# ---------- backups
def backups():
    pasta = os.path.join(DIR, "backups")
    try:
        nomes = [n for n in os.listdir(pasta) if BACKUP.match(n)]
    except OSError:
        nomes = []
    out = []
    for n in nomes:
        st = os.stat(os.path.join(pasta, n))
        out.append({"arquivo": n, "tamanho": st.st_size, "data": int(st.st_mtime)})
    return {"backups": sorted(out, key=lambda b: b["data"], reverse=True)}


# ---------- tarefas
def estado_tarefa():
    rc, out, _ = docker("inspect", "-f",
                        '{{.State.Status}}|{{.State.ExitCode}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|'
                        '{{index .Config.Labels "locadora.acao"}}', TAREFA)
    if rc:
        return None
    status, codigo, inicio, fim, acao = out.split("|", 4)
    if status in ("running", "created", "restarting"):
        estado = "rodando"
    else:
        estado = "ok" if codigo == "0" else "falhou"
    return {"acao": acao, "nome": ACOES.get(acao, (acao,))[0], "estado": estado,
            "inicio": inicio, "fim": fim if estado != "rodando" else ""}


def saida_tarefa(desde):
    r = subprocess.run(["docker", "logs", TAREFA], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=20)
    texto = ANSI.sub("", r.stdout if r.returncode == 0 else "")
    linhas = texto.replace("\r", "\n").split("\n")
    while linhas and not linhas[-1]:
        linhas.pop()
    return linhas[desde:], len(linhas)


def comando(acao, dados):
    if acao not in ACOES:
        raise Erro(400, "ação desconhecida")
    if acao == "restaurar":
        arq = str(dados.get("arquivo") or "")
        if not BACKUP.match(arq) or not os.path.isfile(os.path.join(DIR, "backups", arq)):
            raise Erro(400, "backup não encontrado")
        return ["./atualizar.sh", "--restaurar", f"backups/{arq}"]
    if acao == "senha":
        senha = str(dados.get("senha") or "")
        if len(senha) < 8:
            raise Erro(400, "a senha precisa ter pelo menos 8 caracteres")
        if "'" in senha or any(ord(c) < 32 for c in senha):
            raise Erro(400, "a senha não pode ter aspas simples (') nem quebras de linha")
        # O change-password.sh lê a senha nova do .env (NEW_STACK_PASSWORD) e a tira de lá ao terminar.
        # Se falhar no meio, a linha sai do mesmo jeito: senha não fica largada no .env.
        envfile.gravar(ENV, {"NEW_STACK_PASSWORD": senha})
        return ["bash", "-c", "./change-password.sh; s=$?; grep -v '^NEW_STACK_PASSWORD=' .env > .env.tmp; "
                              "cat .env.tmp > .env; rm -f .env.tmp; exit $s"]
    return ACOES[acao][1]


def iniciar_tarefa(dados):
    acao = str(dados.get("acao") or "")
    with _trava:
        atual = estado_tarefa()
        if atual and atual["estado"] == "rodando":
            raise Erro(409, f"já tem uma tarefa rodando: {atual['nome']}")
        cmd = comando(acao, dados)
        docker("rm", "-f", TAREFA)
        vols = ["-v", f"{SOCK}:{SOCK}", "-v", f"{DIR}:{DIR}"]
        # A pasta dos filmes de quando o operador subiu e a do .env agora (mudou pelo painel e o
        # setup.sh vai passar a usar), cada uma no mesmo caminho do host
        for pasta in dict.fromkeys([DATA, pasta_no_host(envfile.ler(ENV).get("DATA_ROOT", ""))]):
            if pasta and not (pasta + "/").startswith(DIR + "/"):
                vols += ["-v", f"{pasta}:{pasta}"]
        u = usuario()
        quem = ["--user", f"{u[0]}:{u[1]}", "--group-add", str(grupo_do_socket())] if u else []
        rc, _, err = docker(
            "run", "-d", "--name", TAREFA, "--label", f"locadora.acao={acao}", "--init", *quem,
            *vols, "-w", DIR, "-e", "HOME=/tmp", "-e", "LOCADORA_PELO_PAINEL=1", "-e", "TZ",
            IMAGEM, *cmd, timeout=60)
        if rc:
            if acao == "senha":
                envfile.remover(ENV, "NEW_STACK_PASSWORD")
            raise Erro(500, f"não consegui iniciar a tarefa: {err[:300]}")
    print(f"[operador] tarefa: {acao}", flush=True)
    return estado_tarefa()


# ---------- HTTP
class Operador(http.server.BaseHTTPRequestHandler):
    server_version = "Locadora"
    sys_version = ""

    def _json(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CORPO:
            raise Erro(413, "pedido grande demais")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise Erro(400, "JSON inválido") from None
        if not isinstance(d, dict):
            raise Erro(400, "JSON inválido")
        return d

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._rota("GET")

    def do_POST(self):
        self._rota("POST")

    def _rota(self, metodo):
        caminho, _, consulta = self.path.partition("?")
        try:
            if caminho == "/saude":
                return self._json(200, {"ok": True})
            if not TOKEN or not hmac.compare_digest(self.headers.get("X-Token", ""), TOKEN):
                raise Erro(401, "token inválido")
            if not DIR or not os.path.isfile(ENV):
                raise Erro(503, "LOCADORA_DIR não está no .env: rode ./setup.sh")
            if (metodo, caminho) == ("GET", "/diagnostico"):
                return self._json(200, diagnostico())
            if (metodo, caminho) == ("GET", "/config"):
                return self._json(200, envfile.para_painel(envfile.ler(ENV)))
            if (metodo, caminho) == ("POST", "/config"):
                with _trava:
                    try:
                        atuais = envfile.ler(ENV)
                        limpo = envfile.validar(self._corpo().get("valores"), atuais)
                    except ValueError as e:
                        raise Erro(400, str(e)) from None
                    if limpo.get("DATA_ROOT") and limpo["DATA_ROOT"] != atuais.get("DATA_ROOT"):
                        conferir_pasta(pasta_no_host(limpo["DATA_ROOT"]))
                    mudou = envfile.gravar(ENV, limpo)
                if mudou:
                    print(f"[operador] .env: {', '.join(mudou)}", flush=True)
                return self._json(200, {"mudou": mudou})
            if (metodo, caminho) == ("GET", "/backups"):
                return self._json(200, backups())
            if (metodo, caminho) == ("POST", "/tarefa"):
                return self._json(200, {"tarefa": iniciar_tarefa(self._corpo())})
            if (metodo, caminho) == ("GET", "/tarefa"):
                m = re.search(r"(?:^|&)desde=(\d+)", consulta)
                t = estado_tarefa()
                linhas, total = saida_tarefa(int(m.group(1)) if m else 0) if t else ([], 0)
                return self._json(200, {"tarefa": t, "linhas": linhas, "total": total})
            raise Erro(404, "não encontrado")
        except Erro as e:
            self._json(e.status, {"erro": str(e)})
        except Exception as e:
            print(f"[operador] {type(e).__name__}: {e}", flush=True)
            self._json(500, {"erro": f"{type(e).__name__}: {str(e)[:200]}"})


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    baixar_privilegios()
    if not TOKEN:
        sys.exit("[operador] falta OPERADOR_TOKEN no .env: rode ./setup.sh")
    print(f"[operador] no ar (pasta {DIR})", flush=True)
    Servidor(("", PORTA), Operador).serve_forever()
