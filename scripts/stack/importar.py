"""Importa filmes que você já tem (ex.: ~/Videos/Movies) para a biblioteca, via Radarr.

O ./importar.sh põe hardlinks dos arquivos em DATA_ROOT/importar/<data> (sem copiar nem mexer
nos originais) e chama isto com a pasta como o Radarr a vê. Aqui:
  1. cada arquivo que o Radarr não reconhece é procurado pelo nome e ano (busca do Seerr, que
     entende títulos em português) e o filme é adicionado ao Radarr sem baixar nada;
  2. o Radarr importa (hardlink para /data/media/movies) e renomeia; o Jellyfin é avisado.
Filmes que já têm arquivo na Locadora ficam como estão.
"""
import re
import time
import urllib.parse

from .common import Client, JELLYFIN, KEYS, PASSWORD, RADARR, SEERR, USER, log
from .language import PROFILE

MARCAS = re.compile(r"\s*[-–]\s*(dublado|legendado|dual|nacional)\b.*$", re.I)
ANO_PARENTESES = re.compile(r"[(\[]((?:19|20)\d{2})[)\]]")
ANO_SOLTO = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def titulo_e_ano(nome):
    """'Terra Fria (2005) - Dublado' -> ('Terra Fria', '2005').
    Vale o ano entre parênteses; sem parênteses, o último ano do nome, para não confundir
    número do título com ano ("Blade.Runner.2049.2017.1080p" -> 2017)."""
    nome = MARCAS.sub("", re.sub(r"\.(mkv|mp4|avi|m4v|mov|wmv)$", "", nome, flags=re.I))
    m = ANO_PARENTESES.search(nome)
    if not m:
        anos = [a for a in ANO_SOLTO.finditer(nome) if a.start() > 0]
        m = anos[-1] if anos else None
    if not m:
        return nome.replace(".", " ").strip(), None
    return nome[:m.start()].replace(".", " ").replace("_", " ").strip(" -_(["), m.group(1)


def achar_tmdb(seerr, titulo, ano):
    q = urllib.parse.quote(titulo)
    res = [r for r in seerr.get(f"/api/v1/search?query={q}&page=1&language=pt-BR")["results"]
           if r.get("mediaType") == "movie"]
    if ano:
        for tolerancia in (0, 1):
            for r in res:
                a = (r.get("releaseDate") or "")[:4]
                if a.isdigit() and abs(int(a) - int(ano)) <= tolerancia:
                    return r
        return None
    return res[0] if len(res) == 1 else None


def importar(pasta, simular=False):
    print(f"{'Simulando' if simular else 'Importando'} {pasta}")
    radarr = Client(RADARR, {"X-Api-Key": KEYS["radarr"]})
    seerr = Client(SEERR)
    seerr.post("/api/v1/auth/jellyfin", {"username": USER, "password": PASSWORD})
    perfil = next(p["id"] for p in radarr.get("/api/v3/qualityprofile") if p["name"] == PROFILE)
    q = urllib.parse.urlencode({"folder": pasta, "filterExistingFiles": "false"})

    def itens():
        return radarr.get(f"/api/v3/manualimport?{q}")

    lista = itens()
    if not lista:
        print("  nenhum vídeo encontrado")
        return
    nao_achei = []
    achados = {}  # relativePath -> tmdb: o Radarr nem sempre reconhece o título em português
    for it in lista:
        if it.get("movie"):
            continue
        nome = it.get("folderName") or it.get("name") or it["relativePath"]
        titulo, ano = titulo_e_ano(nome.split("/")[0])
        r = achar_tmdb(seerr, titulo, ano)
        if not r:
            titulo, ano = titulo_e_ano(it["relativePath"].split("/")[-1])
            r = achar_tmdb(seerr, titulo, ano)
        if not r:
            nao_achei.append(it["relativePath"])
            continue
        achados[it["relativePath"]] = r["id"]
        if simular:
            log(f"{it['relativePath'].split('/')[0]}  ->  {r.get('title')} ({(r.get('releaseDate') or '')[:4]})"
                f"  tmdb {r['id']}")
            continue
        existe = [m for m in radarr.get(f"/api/v3/movie?tmdbId={r['id']}")]
        if not existe:
            look = radarr.get(f"/api/v3/movie/lookup/tmdb?tmdbId={r['id']}")
            # monitored=False: o Radarr não sai baixando outra versão do que você já tem
            radarr.post("/api/v3/movie", {**look, "qualityProfileId": perfil,
                                          "rootFolderPath": "/data/media/movies", "monitored": False,
                                          "addOptions": {"searchForMovie": False}})

    if simular:
        for it in lista:
            if it.get("movie"):
                log(f"{it['relativePath'].split('/')[0]}  ->  {it['movie']['title']} (já no Radarr)")
        for n in nao_achei:
            log(f"AVISO: não reconheci {n}")
        return
    filmes = {m["id"]: m for m in radarr.get("/api/v3/movie")}
    por_tmdb = {m["tmdbId"]: m for m in filmes.values()}
    arquivos, ja_tinha = [], []
    for it in itens():
        mv = it.get("movie") or por_tmdb.get(achados.get(it["relativePath"]))
        if not mv:
            if it["relativePath"] not in nao_achei:
                nao_achei.append(it["relativePath"])
            continue
        if filmes.get(mv["id"], {}).get("hasFile"):
            ja_tinha.append(f"{mv['title']} ({mv.get('year')})")
            continue
        arquivos.append({"path": it["path"], "movieId": mv["id"], "quality": it["quality"],
                         "languages": it.get("languages") or [], "releaseGroup": it.get("releaseGroup") or "",
                         "indexerFlags": it.get("indexerFlags", 0), "downloadId": ""})
    if arquivos:
        # copy = hardlink no mesmo disco (copyUsingHardlinks): não ocupa espaço de novo
        cmd = radarr.post("/api/v3/command", {"name": "ManualImport", "files": arquivos, "importMode": "copy"})
        for _ in range(300):
            st = radarr.get(f"/api/v3/command/{cmd['id']}")["status"]
            if st in ("completed", "failed", "aborted"):
                break
            time.sleep(2)
        if st != "completed":
            log(f"AVISO: o Radarr terminou a importação com status '{st}'")
    filmes = {m["id"]: m for m in radarr.get("/api/v3/movie")}
    ok = sorted(f"{filmes[a['movieId']]['title']} ({filmes[a['movieId']].get('year')})"
                for a in arquivos if filmes.get(a["movieId"], {}).get("hasFile"))
    falhou = sorted({a["path"].split("/")[-1] for a in arquivos if not filmes.get(a["movieId"], {}).get("hasFile")})
    if ok:  # o aviso do Radarr ao Jellyfin pode demorar; pede a varredura já
        try:
            from .jellyfin import JF_AUTH
            jf = Client(JELLYFIN, {"Authorization": JF_AUTH})
            auth = jf.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
            jf.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
            jf.post("/Library/Refresh")
        except Exception as e:
            log(f"AVISO: não consegui pedir a atualização do Jellyfin ({e}); ele atualiza sozinho depois")
    for n in ok:
        log(f"importado: {n}")
    for n in sorted(set(ja_tinha)):
        log(f"já estava na Locadora: {n}")
    for n in falhou:
        log(f"AVISO: o Radarr não importou {n} (veja Radarr → Activity → Queue/History)")
    for n in nao_achei:
        log(f"AVISO: não reconheci {n}: renomeie a pasta para 'Título (Ano)' e rode de novo")
    print(f"\n{len(ok)} importado(s), {len(set(ja_tinha))} já existia(m), {len(nao_achei) + len(falhou)} com problema.")
