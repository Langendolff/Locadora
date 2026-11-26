"""Diagnóstico pelas APIs (chamado por ./diagnostico.sh dentro da rede do compose).

Não muda configuração nenhuma (só pede ao Radarr/Sonarr que refaçam a verificação de saúde). Cada verificação imprime uma linha
"✓ / ! / ✗" e, quando há problema, o que fazer.
"""
import os
import time
import urllib.request

from .common import (Client, DELUGE, JELLYFIN, KEYS, PASSWORD, PROWLARR, RADARR, SEERR, SONARR,
                     USER)
from .jellyfin import JF_AUTH
from .language import CF_NAME, PROFILE

FLARESOLVERR = "http://flaresolverr:8191"
BAZARR = "http://bazarr:6767"


class Resultado:
    """Imprime cada verificação (terminal) e guarda em `itens` (painel)."""

    _MARCA = {"ok": "\033[32m✓\033[0m", "aviso": "\033[33m!\033[0m", "erro": "\033[31m✗\033[0m"}

    def __init__(self, imprimir=True):
        self.erros = self.avisos = 0
        self.imprimir = imprimir
        self.itens = []  # {"secao", "nivel": ok|aviso|erro, "msg", "dica"}
        self._secao = ""

    def secao(self, nome):
        self._secao = nome
        if self.imprimir:
            print(nome, flush=True)

    def _add(self, nivel, msg, dica=None):
        self.itens.append({"secao": self._secao, "nivel": nivel, "msg": msg, "dica": dica})
        if self.imprimir:
            print(f"  {self._MARCA[nivel]} {msg}", flush=True)
            if dica:
                print(f"      → {dica}", flush=True)

    def ok(self, msg):
        self._add("ok", msg)

    def aviso(self, msg, dica=None):
        self.avisos += 1
        self._add("aviso", msg, dica)

    def erro(self, msg, dica=None):
        self.erros += 1
        self._add("erro", msg, dica)


def _quieto(c, path):
    """GET que devolve (dados, erro) em vez de lançar exceção."""
    try:
        return c.get(path), None
    except RuntimeError as e:
        return None, str(e)
    except Exception as e:  # serviço fora do ar, DNS, timeout
        return None, f"{type(e).__name__}: {e}"


def _fora_do_ar(r, nome, err):
    if "401" in err:
        r.erro(f"{nome}: chave de API não confere", "rode ./setup.sh para reaplicar a configuração")
    else:
        r.erro(f"{nome} não responde ({err[:80]})", f"veja: docker compose logs {nome.lower()}")


# Mensagens de saúde que o próprio diagnóstico já explica melhor
_REDUNDANTES = ("DownloadClientStatusCheck", "IndexerStatusCheck")
_DICAS = {
    "DownloadClientCheck": "rode ./setup.sh (corrige a senha do Deluge) e confira a VPN acima",
    "RootFolderCheck": "a pasta de mídia sumiu: confira DATA_ROOT no .env e se o disco está montado",
    "IndexerSearchCheck": "adicione indexadores no Prowlarr (docs/indexadores.md)",
    "IndexerRssCheck": "adicione indexadores no Prowlarr (docs/indexadores.md)",
    "UpdateCheck": None,
}


def arr(r, nome, base):
    c = Client(base, {"X-Api-Key": KEYS[nome.lower()]})
    status, err = _quieto(c, "/api/v3/system/status")
    if err:
        return _fora_do_ar(r, nome, err)

    # Pede uma verificação nova: o resultado guardado pode ser de antes de um reinício
    try:
        cmd = c.post("/api/v3/command", {"name": "CheckHealth"})
        for _ in range(15):
            if c.get(f"/api/v3/command/{cmd['id']}").get("status") in ("completed", "failed"):
                break
            time.sleep(1)
    except RuntimeError:
        pass
    problemas = 0
    for h in c.get("/api/v3/health"):
        if h["source"] in _REDUNDANTES or h["type"] not in ("warning", "error"):
            continue
        problemas += 1
        fn = r.erro if h["type"] == "error" else r.aviso
        fn(f"{nome}: {h['message']}", _DICAS.get(h["source"], h.get("wikiUrl")))

    for rf in c.get("/api/v3/rootfolder"):
        if not rf.get("accessible"):
            problemas += 1
            r.erro(f"{nome}: pasta {rf['path']} inacessível", _DICAS["RootFolderCheck"])

    perfis = {p["name"] for p in c.get("/api/v3/qualityprofile")}
    formatos = {f["name"] for f in c.get("/api/v3/customformat")}
    if PROFILE not in perfis or CF_NAME not in formatos:
        problemas += 1
        r.aviso(f"{nome}: preferência por PT-BR não está configurada", "rode ./setup.sh")

    fila = c.get("/api/v3/queue?pageSize=200&includeUnknownMovieItems=true")
    presos = [q for q in fila.get("records", [])
              if q.get("trackedDownloadStatus") in ("warning", "error")
              or q.get("status") in ("warning", "failed")]
    if presos:
        problemas += 1
        nomes = ", ".join(q.get("title", "?")[:40] for q in presos[:3])
        r.aviso(f"{nome}: {len(presos)} download(s) com problema na fila ({nomes}"
                f"{'…' if len(presos) > 3 else ''})",
                "Activity → Queue → ❌ → 'Blocklist Release' para buscar outra versão "
                "(docs/solucao-de-problemas.md)")
    if not problemas:
        total = fila.get("totalRecords", 0)
        r.ok(f"{nome} {status['version']}: sem alertas" + (f", {total} na fila" if total else ""))


def prowlarr(r):
    c = Client(PROWLARR, {"X-Api-Key": KEYS["prowlarr"]})
    idx, err = _quieto(c, "/api/v1/indexer")
    if err:
        return _fora_do_ar(r, "Prowlarr", err)
    ativos = {i["id"]: i["name"] for i in idx if i.get("enable")}
    if not ativos:
        return r.erro("Prowlarr: nenhum indexador ativo, então nada é encontrado",
                      "adicione indexadores no Prowlarr (docs/indexadores.md)")
    falhando = [ativos[s["indexerId"]] for s in c.get("/api/v1/indexerstatus")
                if s.get("disabledTill") and s["indexerId"] in ativos]
    if len(falhando) == len(ativos):
        r.erro(f"Prowlarr: todos os {len(ativos)} indexadores estão falhando",
               "geralmente é a VPN ou o site fora do ar; confira a VPN acima e tente mais tarde")
    elif falhando:
        r.aviso(f"Prowlarr: {len(falhando)} de {len(ativos)} indexadores falhando agora "
                f"({', '.join(falhando)})",
                "normal de vez em quando: o Prowlarr tenta de novo sozinho. Se persistir por dias, "
                "desative-os no Prowlarr")
    else:
        r.ok(f"Prowlarr: {len(ativos)} indexadores ativos")
    apps = {a["implementation"] for a in c.get("/api/v1/applications")}
    if not {"Radarr", "Sonarr"} <= apps:
        r.erro("Prowlarr não está ligado ao Radarr/Sonarr", "rode ./setup.sh")


def deluge(r, porta_vpn):
    c = Client(DELUGE)
    n = iter(range(1, 1000))

    def rpc(method, *params):
        res = c.post("/json", {"method": method, "params": list(params), "id": next(n)})
        if res.get("error"):
            raise RuntimeError(res["error"])
        return res["result"]

    try:
        if not rpc("auth.login", PASSWORD):
            return r.erro("Deluge: a senha do .env não funciona", "rode ./change-password.sh ou ./setup.sh")
        if not rpc("web.connected"):
            return r.erro("Deluge: a interface web não está ligada ao serviço de download",
                          "rode ./setup.sh ou: docker compose restart deluge")
        porta = rpc("core.get_listen_port")
        livre = rpc("core.get_free_space", "/data/torrents")
    except Exception as e:
        return _fora_do_ar(r, "Deluge", str(e))
    if porta_vpn:
        if str(porta) != porta_vpn:
            r.aviso(f"Deluge escuta na porta {porta}, mas a VPN abriu a {porta_vpn}",
                    "espere 1 minuto (ele ajusta sozinho) ou: docker compose restart deluge")
        else:
            r.ok(f"Deluge: conectado, porta {porta} aberta pela VPN")
    else:
        r.ok("Deluge: conectado")
    if isinstance(livre, int) and livre >= 0 and livre < 10 * 1024**3:
        r.erro(f"Deluge: só {livre / 1024**3:.1f} GB livres para downloads", "libere espaço no disco")


def jellyfin(r):
    c = Client(JELLYFIN, {"Authorization": JF_AUTH})
    _, err = _quieto(c, "/System/Info/Public")
    if err:
        return _fora_do_ar(r, "Jellyfin", err)
    try:
        auth = c.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
    except RuntimeError:
        return r.erro(f"Jellyfin: login '{USER}' com a senha do .env não funciona",
                      "a senha foi trocada pelo Jellyfin? Use ./change-password.sh para trocar em todos")
    c.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
    libs = c.get("/Library/VirtualFolders")
    if not libs:
        return r.erro("Jellyfin: nenhuma biblioteca", "rode ./setup.sh")
    filmes = c.get("/Items?Recursive=true&IncludeItemTypes=Movie&Limit=0").get("TotalRecordCount", 0)
    series = c.get("/Items?Recursive=true&IncludeItemTypes=Series&Limit=0").get("TotalRecordCount", 0)
    r.ok(f"Jellyfin: {len(libs)} bibliotecas, {filmes} filmes e {series} séries")


def seerr(r):
    c = Client(SEERR)
    pub, err = _quieto(c, "/api/v1/settings/public")
    if err:
        return _fora_do_ar(r, "Seerr", err)
    if not pub.get("initialized"):
        return r.erro("Seerr ainda não foi configurado", "rode ./setup.sh")
    r.ok("Seerr: no ar")


def bazarr(r):
    erro = None
    for _ in range(10):  # demora a abrir a porta depois de reiniciar
        try:
            urllib.request.urlopen(BAZARR, timeout=10)
            return r.ok("Bazarr: no ar")
        except urllib.error.HTTPError:
            return r.ok("Bazarr: no ar")
        except Exception as e:
            erro = e
            time.sleep(3)
    _fora_do_ar(r, "Bazarr", str(erro))


def flaresolverr(r):
    try:
        urllib.request.urlopen(FLARESOLVERR, timeout=10)
        r.ok("FlareSolverr: no ar")
    except Exception as e:
        r.aviso(f"FlareSolverr não responde ({str(e)[:60]})",
                "indexadores com Cloudflare vão falhar. Veja: docker compose logs flaresolverr")


def disco(r, data="/data"):
    """Espaço livre e hardlink (o ./diagnostico.sh faz o mesmo no host; aqui é para o painel)."""
    try:
        st = os.statvfs(data)
    except OSError:
        return r.erro(f"a pasta de mídia não está acessível ({data})",
                      "confira DATA_ROOT no .env e se o disco está montado")
    livre = st.f_bavail * st.f_frsize // 1024**3
    if livre < 10:
        r.erro(f"só {livre} GB livres", "apague filmes/séries que já viu (no Radarr/Sonarr, para não baixar de novo)")
    elif livre < 50:
        r.aviso(f"{livre} GB livres (um filme 1080p ocupa 2 a 15 GB)", "considere liberar espaço")
    else:
        r.ok(f"{livre} GB livres")
    try:
        if os.stat(f"{data}/torrents").st_dev != os.stat(f"{data}/media").st_dev:
            r.aviso("downloads e biblioteca estão em discos diferentes",
                    "cada filme ocupa o dobro do espaço (sem hardlink). Deixe torrents/ e media/ no mesmo disco")
    except OSError:
        pass


def porta_encaminhada(r, arquivo="/gluetun/forwarded_port"):
    """Porta que a VPN abriu ('' se não abriu ou se o port forwarding está desligado)."""
    if os.environ.get("VPN_PORT_FORWARDING") != "on":
        return ""
    try:
        porta = "".join(c for c in open(arquivo).read() if c.isdigit())
    except OSError:
        porta = ""
    if porta:
        r.ok(f"porta {porta} aberta pela VPN (mais fontes, downloads mais rápidos)")
    else:
        r.aviso("a VPN não abriu porta (port forwarding)",
                "os downloads funcionam, mas mais devagar. Confira se o .conf é de um servidor P2P com NAT-PMP")
    return porta


def diagnostico(r=None, porta_vpn=None):
    r = r or Resultado()
    if porta_vpn is None:
        porta_vpn = os.environ.get("FORWARDED_PORT", "").strip()
    r.secao("Downloads")
    deluge(r, porta_vpn)
    r.secao("Busca")
    prowlarr(r)
    flaresolverr(r)
    r.secao("Filmes e séries")
    arr(r, "Radarr", RADARR)
    arr(r, "Sonarr", SONARR)
    r.secao("Assistir e pedir")
    jellyfin(r)
    seerr(r)
    bazarr(r)
    return r
