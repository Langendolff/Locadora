"""Limpeza automática: tira da Locadora os filmes que todo mundo já viu há LIMPEZA_DIAS dias.

Regra (decidir), pensada para errar sempre para o lado de MANTER:
  - "todo mundo" = quem assistiu alguma coisa nos últimos 90 dias (contas paradas não contam);
  - o filme sai só se TODAS essas pessoas já viram e a última vez foi há LIMPEZA_DIAS dias ou mais;
  - nunca sai: favorito de alguém, filme que alguém começou e não terminou, filme que chegou há
    menos de LIMPEZA_DIAS dias, ou se ninguém assistiu nada nos últimos 90 dias.
Séries não entram (episódios novos continuam chegando).
Remover = Radarr apaga o arquivo + o torrent sai do Deluge (senão o hardlink segura o espaço).
"""
import datetime as dt
import json
import os

from .common import (Client, DELUGE, JELLYFIN, KEYS, PASSWORD, RADARR, USER, log)
from .jellyfin import JF_AUTH

ATIVO_DIAS = 90
AVISO_DIAS = 3  # avisa no Telegram este tanto antes de remover
ESTADO = "/estado/limpeza-avisados.json"


def _data(s):
    """Datas do Jellyfin ("…T21:03:12.1234567Z") e do Radarr ("…T21:03:12Z") em UTC."""
    if not s:
        return None
    base, _, resto = s.rstrip("Z").partition(".")
    frac = "".join(ch for ch in resto if ch.isdigit())[:6]
    d = dt.datetime.fromisoformat(base + (f".{frac}" if frac else ""))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def assistindo(vistos, agora):
    """Quem assistiu alguma coisa (filme ou episódio) nos últimos ATIVO_DIAS dias."""
    limite = agora - dt.timedelta(days=ATIVO_DIAS)
    return sorted(p for p, itens in vistos.items()
                  if any(i.get("quando") and i["quando"] >= limite for i in itens.values()))


def decidir(filmes, vistos, agora, dias):
    """Função pura (testada em tests/test_limpeza.py).

    filmes: {tmdb: {"nome": str, "chegou": datetime}}
    vistos: {pessoa: {tmdb: {"visto": bool, "quando": datetime|None, "favorito": bool,
                             "comecou": bool}}}  (só o que a pessoa tem registro)
    Devolve {tmdb: data em que pode sair} só para os filmes elegíveis por enquanto (a data pode
    ser no futuro: serve para o aviso antecipado).
    """
    ativos = assistindo(vistos, agora)
    if not ativos:
        return {}
    saida = {}
    for tmdb, f in filmes.items():
        regs = [vistos[p].get(tmdb, {}) for p in vistos]
        if any(r.get("favorito") for r in regs):
            continue
        if any(r.get("comecou") and not r.get("visto") for r in regs):
            continue
        dos_ativos = [vistos[p].get(tmdb, {}) for p in ativos]
        if not all(r.get("visto") and r.get("quando") for r in dos_ativos):
            continue
        ultima = max(r["quando"] for r in regs if r.get("quando"))
        pode = max(ultima, f["chegou"]) + dt.timedelta(days=dias)
        saida[tmdb] = pode
    return saida


# ---------------------------------------------------------------- leitura da stack
def _jellyfin():
    jf = Client(JELLYFIN, {"Authorization": JF_AUTH})
    auth = jf.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
    jf.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
    return jf


def ler(jf, radarr):
    filmes = {}
    for m in radarr.get("/api/v3/movie"):
        if m.get("hasFile") and m.get("movieFile"):
            filmes[m["tmdbId"]] = {"nome": f"{m['title']} ({m.get('year')})", "id": m["id"],
                                   "chegou": _data(m["movieFile"]["dateAdded"])}
    vistos = {}
    for u in jf.get("/Users"):
        if u.get("Policy", {}).get("IsDisabled"):
            continue
        itens = jf.get(f"/Users/{u['Id']}/Items?Recursive=true&IncludeItemTypes=Movie,Episode"
                       "&Fields=ProviderIds&EnableUserData=true")["Items"]
        regs = {}
        for it in itens:
            ud = it.get("UserData", {})
            tmdb = it.get("ProviderIds", {}).get("Tmdb")
            chave = int(tmdb) if it["Type"] == "Movie" and tmdb and tmdb.isdigit() else f"ep:{it['Id']}"
            regs[chave] = {"visto": bool(ud.get("Played")), "quando": _data(ud.get("LastPlayedDate")),
                           "favorito": bool(ud.get("IsFavorite")),
                           "comecou": (ud.get("PlaybackPositionTicks") or 0) > 0}
        vistos[u["Name"]] = regs
    return filmes, vistos


# ---------------------------------------------------------------- remoção
def _deluge_remover(hashes):
    c = Client(DELUGE)
    n = iter(range(1, 1000))
    rpc = lambda m, *p: c.post("/json", {"method": m, "params": list(p), "id": next(n)})
    if not rpc("auth.login", PASSWORD).get("result"):
        log("AVISO: não consegui entrar no Deluge; os torrents ficaram lá")
        return
    for h in hashes:
        rpc("core.remove_torrent", h.lower(), True)


def remover(radarr, filme):
    hist = radarr.get(f"/api/v3/history/movie?movieId={filme['id']}")
    hashes = {h["downloadId"] for h in hist if h.get("downloadId")}
    radarr.req("DELETE", f"/api/v3/movie/{filme['id']}?deleteFiles=true&addImportExclusion=false")
    if hashes:
        _deluge_remover(hashes)


# ---------------------------------------------------------------- execução
def _estado():
    try:
        return json.load(open(ESTADO))
    except Exception:
        return {}


def limpeza(simular=False, avisar=None, agora=None):
    """Roda a limpeza. avisar(texto) manda mensagem (Telegram) se houver o que contar."""
    dias = int(os.environ.get("LIMPEZA_DIAS") or 0)
    if dias <= 0 and not simular:
        return []
    dias = dias or 30
    agora = agora or dt.datetime.now(dt.timezone.utc)
    radarr = Client(RADARR, {"X-Api-Key": KEYS["radarr"]})
    filmes, vistos = ler(_jellyfin(), radarr)
    datas = decidir(filmes, vistos, agora, dias)
    sai = sorted((t for t, d in datas.items() if d <= agora), key=lambda t: filmes[t]["nome"])
    breve = sorted((t for t, d in datas.items() if agora < d <= agora + dt.timedelta(days=AVISO_DIAS)),
                   key=lambda t: filmes[t]["nome"])

    if simular:
        print(f"Regra: filmes que todo mundo viu há {dias}+ dias "
              f"(contam: {', '.join(assistindo(vistos, agora)) or 'ninguém assistiu nada nos últimos 90 dias'})")
        for t in sai:
            print(f"  sairia hoje:   {filmes[t]['nome']}")
        for t in breve:
            print(f"  sai em breve:  {filmes[t]['nome']} (em {datas[t]:%d/%m})")
        if not sai and not breve:
            print("  nada para remover")
        return sai

    removidos = []
    for t in sai:
        try:
            remover(radarr, filmes[t])
            removidos.append(filmes[t]["nome"])
            log(f"removido: {filmes[t]['nome']}")
        except Exception as e:
            log(f"AVISO: não consegui remover {filmes[t]['nome']} ({e})")

    if avisar:
        est = _estado()
        novos = [t for t in breve if str(t) not in est]
        if novos:
            avisar("🧹 Saem da Locadora em até 3 dias (todo mundo já viu):\n"
                   + "\n".join(f"• {filmes[t]['nome']}" for t in novos)
                   + "\n\nQuer manter? Marque como favorito ❤️ no Jellyfin.")
            est.update({str(t): agora.isoformat() for t in novos})
        if removidos:
            avisar("🧹 Saíram da Locadora para liberar espaço:\n" + "\n".join(f"• {n}" for n in removidos)
                   + "\n\nPara ver de novo, é só pedir outra vez.")
        for t in sai:
            est.pop(str(t), None)
        try:
            os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
            json.dump(est, open(ESTADO, "w"))
        except OSError:
            pass
    return removidos
