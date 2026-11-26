"""Episódios de canais do YouTube, pedidos pelo bot do Telegram.

O admin manda "/youtube <link do canal ou playlist>". O bot lista os vídeos, separa os episódios
completos (cenas, chamadas e shorts ficam de fora), descobre a série no Sonarr e a numeração
pelo título, e mostra o que vai baixar. Confirmado, baixa um episódio por vez com o yt-dlp e
entrega cada arquivo ao Sonarr (importação manual), que renomeia, põe na pasta da série e
avisa o Jellyfin como faria com um torrent.

A parte que decide (ler o título, escolher os vídeos) não fala com nada: fica testável sem a stack.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.parse

# ---------------------------------------------------------------- decisão (sem rede)

MINIMO_SEG = 20 * 60          # sem duração no Sonarr, "episódio completo" é pelo menos isto
FRACAO_DURACAO = 0.6          # ...ou 60% da duração do episódio no Sonarr
BLOQUEADOS = {"subscriber_only", "premium_only", "needs_auth"}

_RE_SXE = re.compile(r"\bS(\d{1,2})\s*EP?\s*(\d{1,3})\b", re.I)               # S02E05, #S2EP36
_RE_EP = re.compile(r"\b(?:epis[oó]dio|episode|ep\.?|cap[ií]tulo)\s*(\d{1,3})\b", re.I)
_RE_EP_TR = re.compile(r"\b(\d{1,3})\s*\.?\s*b[oö]l[uü]m\b", re.I)               # 12. Bölüm
_RE_TEMP = re.compile(r"\b(?:temporada|temp\.?|season|sezon)\s*(\d{1,2})\b", re.I)
_RE_TEMP2 = re.compile(r"\b(\d{1,2})\s*(?:ª|a|\.)?\s*(?:temporada|season|sezon)\b", re.I)


def sem_acento(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def numeracao(titulo):
    """(temporada, episódio) lidos do título; None no que não der para saber."""
    m = _RE_SXE.search(titulo)
    if m:
        return int(m.group(1)), int(m.group(2))
    ep = _RE_EP.search(titulo) or _RE_EP_TR.search(titulo)
    temp = _RE_TEMP.search(titulo) or _RE_TEMP2.search(titulo)
    return (int(temp.group(1)) if temp else None), (int(ep.group(1)) if ep else None)


def idioma(titulo):
    """'dublado', 'legendado' ou '' pelo título."""
    t = sem_acento(titulo)
    if "dublad" in t or "dubbed" in t:
        return "dublado"
    if "legend" in t or "subtitle" in t or "altyazi" in t:
        return "legendado"
    return ""


def temporada_padrao(lista_titulo, temporadas_faltando):
    """Temporada de vídeos que não dizem qual é: a da playlist, ou a única que falta."""
    t, _ = numeracao(lista_titulo or "")
    if t is not None:
        return t
    if len(temporadas_faltando) == 1:
        return next(iter(temporadas_faltando))
    return None


def escolher(videos, episodios, duracao_min=0, lista_titulo=""):
    """Decide qual vídeo vira qual episódio.

    videos: dicts do yt-dlp (--flat-playlist): id, title, duration, availability, live_status.
    episodios: do Sonarr: id, seasonNumber, episodeNumber, hasFile.
    Devolve {"baixar": [...], "ja_tem": [(t, e)], "so_membros": [(t, e)], "fora": [(t, e)]};
    cada item de "baixar": {video, titulo, temporada, episodio, episodeId, idioma}.
    """
    minimo = max(MINIMO_SEG, FRACAO_DURACAO * duracao_min * 60) if duracao_min else MINIMO_SEG
    sonarr = {(e["seasonNumber"], e["episodeNumber"]): e for e in episodios if e["seasonNumber"] > 0}
    faltando = {t for (t, _), e in sonarr.items() if not e.get("hasFile")}

    completos = []
    for v in videos:
        if not v.get("id") or (v.get("duration") or 0) < minimo:
            continue
        if v.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            continue
        t, e = numeracao(v.get("title") or "")
        if e is None:
            continue
        completos.append((t, e, v))

    # Se algum vídeo diz a temporada, os que não dizem são ambíguos (podem ser de outra): ficam de fora
    algum_com_temp = any(t is not None for t, _, _ in completos)
    padrao = None if algum_com_temp else temporada_padrao(lista_titulo, faltando)

    preferencia = {"dublado": 0, "": 1, "legendado": 2}
    melhores, bloqueados = {}, set()
    for t, e, v in completos:
        t = t if t is not None else padrao
        if t is None:
            continue
        if v.get("availability") in BLOQUEADOS:
            bloqueados.add((t, e))
            continue
        chave = (preferencia[idioma(v.get("title") or "")], -(v.get("duration") or 0))
        if (t, e) not in melhores or chave < melhores[(t, e)][0]:
            melhores[(t, e)] = (chave, v)

    r = {"baixar": [], "ja_tem": [], "so_membros": [], "fora": []}
    for te in sorted(set(melhores) | bloqueados):
        ep = sonarr.get(te)
        if te not in melhores:
            if ep and not ep.get("hasFile"):
                r["so_membros"].append(te)
            continue
        if not ep:
            r["fora"].append(te)
        elif ep.get("hasFile"):
            r["ja_tem"].append(te)
        else:
            v = melhores[te][1]
            r["baixar"].append({"video": v["id"], "titulo": v.get("title") or "", "temporada": te[0],
                                "episodio": te[1], "episodeId": ep["id"],
                                "idioma": idioma(v.get("title") or ""), "duracao": v.get("duration") or 0})
    return r


def faixas(numeros):
    """[1,2,3,5,7,8] -> 'E01–E03, E05, E07–E08'"""
    numeros, partes, i = sorted(numeros), [], 0
    while i < len(numeros):
        j = i
        while j + 1 < len(numeros) and numeros[j + 1] == numeros[j] + 1:
            j += 1
        a, b = numeros[i], numeros[j]
        partes.append(f"E{a:02d}" + (f"–E{b:02d}" if b != a else ""))
        i = j + 1
    return ", ".join(partes)


def por_temporada(pares):
    """[(2, 1), (2, 2), (1, 5)] -> 'T1: E05 · T2: E01–E02'"""
    temps = {}
    for t, e in pares:
        temps.setdefault(t, []).append(e)
    return " · ".join(f"T{t}: {faixas(es)}" for t, es in sorted(temps.items()))


def _palavras(s):
    return set(re.findall(r"[a-z0-9]{3,}", sem_acento(s)))


def adivinhar_serie(series, lista_titulo, titulos):
    """A série do Sonarr que mais aparece nos títulos dos vídeos (ou None).

    Compara pelo começo do nome ("Arafta: Bound By Fate" -> "arafta"), que é como os canais
    costumam escrever, e pelo nome inteiro."""
    textos = [sem_acento(t) for t in [lista_titulo, *titulos] if t]
    if not textos:
        return None
    melhor, nota_melhor = None, 0.0
    for s in series:
        nomes = {s["title"], *(a.get("title", "") for a in s.get("alternateTitles") or [])}
        nomes |= {n.split(":")[0].split(" - ")[0] for n in list(nomes)}
        chaves = [sem_acento(n).strip() for n in nomes if len(sem_acento(n).strip()) >= 3]
        if not chaves:
            continue
        nota = sum(any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in chaves) for t in textos) / len(textos)
        if nota > nota_melhor:
            melhor, nota_melhor = s, nota
    return melhor if nota_melhor >= 0.2 else None


def link_da_lista(url):
    """Canal sem aba (…/@canal, …/channel/ID) vira a aba de vídeos; o resto fica como está."""
    u = urllib.parse.urlsplit(url.strip())
    if not u.netloc.endswith(("youtube.com", "youtu.be")):
        return None
    partes = [p for p in u.path.split("/") if p]
    canal = partes and (partes[0].startswith("@") and len(partes) == 1
                        or partes[0] in ("channel", "c", "user") and len(partes) == 2)
    if canal:
        return urllib.parse.urlunsplit((u.scheme or "https", u.netloc, u.path.rstrip("/") + "/videos", "", ""))
    return url.strip()


# ---------------------------------------------------------------- execução (yt-dlp + Sonarr)

PASTA = "/data/youtube"              # temporária: o Sonarr move daqui para a série
ESTADO = "/estado/youtube.json"      # fila, para continuar depois de reiniciar
COOKIES = "/estado/youtube-cookies.txt"   # opcional: cookies de um navegador logado no YouTube
PAUSA_BLOQUEIO = (30 * 60, 4 * 3600)  # YouTube bloqueou: espera 30 min, dobrando até 4h


class Bloqueado(RuntimeError):
    """O YouTube recusou por excesso de pedidos ("confirm you're not a bot", HTTP 429)."""


def bloqueio(stderr):
    t = stderr.lower()
    return "not a bot" in t or "429" in t or "too many requests" in t


def _ytdlp(*args):
    extra = ["--cookies", COOKIES] if os.path.exists(COOKIES) else []
    return ["yt-dlp", *extra, *args]
FORMATO = ("bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[vcodec^=avc1][height<=1080]"
           "/bv*[height<=1080]+ba/b[height<=1080]/b")   # H.264 + AAC: o Jellyfin toca sem converter


def _sonarr():
    from .common import KEYS, SONARR, Client
    return Client(SONARR, {"X-Api-Key": KEYS["sonarr"]})


def listar(url):
    """Título da lista e os vídeos dela (sem baixar nada)."""
    p = subprocess.run(_ytdlp("--flat-playlist", "-J", "--no-warnings", "--", url),
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0 and bloqueio(p.stderr):
        raise Bloqueado("o YouTube está recusando pedidos daqui por um tempo; tente de novo mais tarde")
    if p.returncode != 0:
        raise RuntimeError((p.stderr.strip().splitlines() or ["yt-dlp falhou"])[-1][:300])
    info = json.loads(p.stdout)
    videos = []

    def juntar(entradas):
        for v in entradas or []:
            if v.get("_type") == "playlist" or v.get("entries"):
                juntar(v.get("entries"))
            else:
                videos.append(v)
    juntar(info.get("entries"))
    return info.get("title") or "", videos


def series_do_sonarr():
    return _sonarr().get("/api/v3/series")


def planejar(serie, lista_titulo, videos):
    episodios = _sonarr().get(f"/api/v3/episode?seriesId={serie['id']}")
    return escolher(videos, episodios, serie.get("runtime") or 0, lista_titulo)


def resumo(serie, plano):
    linhas = [f"📺 {serie['title']}"]
    b = plano["baixar"]
    if b:
        dub = sum(1 for x in b if x["idioma"] == "dublado")
        leg = sum(1 for x in b if x["idioma"] == "legendado")
        tipo = "dublados" if dub == len(b) else "legendados" if leg == len(b) else f"{dub} dublados" if dub else ""
        horas = sum(x["duracao"] for x in b) / 3600
        linhas.append(f"⬇️ Baixar {len(b)} episódio(s){' ' + tipo if tipo else ''}: "
                      f"{por_temporada((x['temporada'], x['episodio']) for x in b)}")
        linhas.append(f"   ~{horas:.0f}h de vídeo, uns {horas * 0.8:.0f} GB")
    if plano["ja_tem"]:
        linhas.append(f"✅ Já tem: {por_temporada(plano['ja_tem'])}")
    if plano["so_membros"]:
        linhas.append(f"🔒 Só para membros do canal: {por_temporada(plano['so_membros'])}")
    if plano["fora"]:
        linhas.append(f"❓ No canal, mas o Sonarr não conhece: {por_temporada(plano['fora'])}")
    if not b:
        linhas.append("Nada novo para baixar.")
    return "\n".join(linhas)


class Fila:
    """Um download por vez, numa thread; a fila fica salva em ESTADO."""

    def __init__(self, avisar):
        self.avisar = avisar
        self.trava = threading.Lock()
        self.tem_trabalho = threading.Event()
        self.atual = None
        self.bloqueado_ate = 0
        self.trabalhos = self._ler()
        if self.trabalhos:
            self.tem_trabalho.set()
        threading.Thread(target=self._rodar, daemon=True, name="youtube").start()
        threading.Thread(target=_atualizar_ytdlp, daemon=True, name="yt-dlp -U").start()

    def _ler(self):
        try:
            with open(ESTADO) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _salvar(self):
        os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
        with open(ESTADO + ".tmp", "w") as f:
            json.dump(self.trabalhos, f, ensure_ascii=False)
        os.replace(ESTADO + ".tmp", ESTADO)

    def adicionar(self, chat, serie, plano):
        with self.trava:
            self.trabalhos.append({"chat": chat, "seriesId": serie["id"], "serie": serie["title"],
                                   "itens": plano["baixar"], "feitos": [], "falhas": []})
            self._salvar()
        self.tem_trabalho.set()

    def situacao(self):
        with self.trava:
            if not self.trabalhos:
                return "Nada baixando do YouTube agora."
            linhas = []
            for i, t in enumerate(self.trabalhos):
                restam = len(t["itens"]) - len(t["feitos"]) - len(t["falhas"])
                linha = f"📺 {t['serie']}: {len(t['feitos'])} prontos, {restam} na fila"
                if t["falhas"]:
                    linha += f", {len(t['falhas'])} falharam"
                if i == 0 and self.bloqueado_ate > time.time():
                    falta = (self.bloqueado_ate - time.time()) / 60
                    linha += f"\n   ⏸️ YouTube bloqueou por excesso de pedidos; tento de novo em {falta:.0f} min"
                elif i == 0 and self.atual:
                    linha += f"\n   agora: T{self.atual['temporada']} E{self.atual['episodio']:02d}"
                linhas.append(linha)
            return "\n".join(linhas)

    def _rodar(self):
        pausa, avisado = 0, False
        while True:
            self.tem_trabalho.wait()
            with self.trava:
                if not self.trabalhos:
                    self.tem_trabalho.clear()
                    continue
                t = self.trabalhos[0]
                feitos = {(x["temporada"], x["episodio"]) for x in t["feitos"] + t["falhas"]}
                prox = next((x for x in t["itens"] if (x["temporada"], x["episodio"]) not in feitos), None)
            if prox is None:
                self._terminar(t)
                continue
            self.atual = prox
            try:
                baixar_e_importar(t["seriesId"], t["serie"], prox)
                destino = "feitos"
                pausa = 0
            except Bloqueado as e:
                # Não é culpa do episódio: espera e tenta o mesmo de novo, sem gastar as tentativas
                pausa = min(pausa * 2, PAUSA_BLOQUEIO[1]) if pausa else PAUSA_BLOQUEIO[0]
                print(f"[youtube] bloqueado ({e}); pausa de {pausa // 60} min", flush=True)
                if not avisado:
                    try:
                        self.avisar(t["chat"], "⏸️ O YouTube está recusando downloads daqui por excesso de "
                                    f"pedidos. Pausei a fila e tento de novo a cada {pausa // 60} min ou mais; "
                                    "nada se perde. Para ver: /youtube")
                    except Exception:
                        pass
                    avisado = True
                self.atual = None
                self.bloqueado_ate = time.time() + pausa
                time.sleep(pausa)
                continue
            except Exception as e:
                print(f"[youtube] {t['serie']} T{prox['temporada']}E{prox['episodio']}: {e}", flush=True)
                destino = "falhas"
            self.atual = None
            if avisado:
                avisado = False
                try:
                    self.avisar(t["chat"], f"▶️ O YouTube liberou; voltei a baixar {t['serie']}.")
                except Exception:
                    pass
            with self.trava:
                t[destino].append(prox)
                self._salvar()

    def _terminar(self, t):
        ok = por_temporada((x["temporada"], x["episodio"]) for x in t["feitos"])
        texto = f"✅ {t['serie']}: {len(t['feitos'])} episódio(s) do YouTube prontos no Jellyfin" + (f" ({ok})" if ok else "")
        if t["falhas"]:
            falhou = por_temporada((x["temporada"], x["episodio"]) for x in t["falhas"])
            texto += f"\n⚠️ Não consegui baixar: {falhou}. Mande o link de novo para tentar outra vez."
        try:
            self.avisar(t["chat"], texto)
        except Exception as e:
            print(f"[youtube] não consegui avisar: {e}", flush=True)
        with self.trava:
            self.trabalhos.remove(t)
            self._salvar()


def _atualizar_ytdlp():
    """O YouTube muda sempre e o yt-dlp acompanha: atualiza a cada início do serviço."""
    p = subprocess.run(["pip", "install", "-q", "--disable-pip-version-check", "-U", "yt-dlp[default]"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        print(f"[youtube] não consegui atualizar o yt-dlp: {p.stderr.strip()[-200:]}", flush=True)


def _dono(*caminhos):
    """O container roda como root; o Sonarr (PUID/PGID) precisa poder mover e apagar."""
    uid, gid = int(os.environ.get("PUID") or 1000), int(os.environ.get("PGID") or 1000)
    for c in caminhos:
        try:
            os.chown(c, uid, gid)
        except OSError:
            pass


def baixar_e_importar(series_id, serie, item):
    s = _sonarr()
    ep = s.get(f"/api/v3/episode/{item['episodeId']}")
    if ep.get("hasFile"):
        return  # chegou por outro caminho enquanto esperava na fila
    pasta = os.path.join(PASTA, item["video"])
    shutil.rmtree(pasta, ignore_errors=True)
    os.makedirs(pasta)
    _dono(PASTA, pasta)
    try:
        limpo = re.sub(r"[^\w .-]", "", serie)
        nome = f"{limpo} - S{item['temporada']:02d}E{item['episodio']:02d} - WEB-DL.%(ext)s"
        for tentativa in range(3):
            p = subprocess.run(_ytdlp("--no-progress", "--no-playlist", "-f", FORMATO,
                                      "--merge-output-format", "mkv", "-o", os.path.join(pasta, nome),
                                      "--print", "after_move:height", "--no-simulate",
                                      "--", item["video"]), capture_output=True, text=True, timeout=6 * 3600)
            if p.returncode == 0:
                break
            if bloqueio(p.stderr):
                raise Bloqueado(p.stderr.strip().splitlines()[-1][:300])
            erro = (p.stderr.strip().splitlines() or ["yt-dlp falhou"])[-1][:300]
            if tentativa < 2:
                time.sleep(60 * (tentativa + 1))
        else:
            raise RuntimeError(erro)
        arquivos = [f for f in os.listdir(pasta) if f.endswith((".mkv", ".mp4", ".webm"))]
        if not arquivos:
            raise RuntimeError("o yt-dlp terminou sem arquivo de vídeo")
        _dono(*(os.path.join(pasta, f) for f in os.listdir(pasta)))
        altura = int(next((l for l in reversed(p.stdout.split()) if l.isdigit()), "0"))
        importar(s, series_id, item, os.path.join(pasta, arquivos[0]), altura)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def resolucao(altura):
    """Altura do vídeo -> resolução do Sonarr (YouTube corta as bordas: 1012 é 1080p)."""
    for r in (2160, 1080, 720, 576, 480):
        if altura >= r * 0.85:
            return r
    return 480


def importar(s, series_id, item, caminho, altura=1080):
    """Importação manual no Sonarr: episódio, idioma e qualidade ditos por nós, não adivinhados."""
    r = resolucao(altura)
    defs = {d["quality"]["name"]: d["quality"] for d in s.get("/api/v3/qualitydefinition")}
    qualidade = defs.get(f"WEBDL-{r}p") or defs.get("WEBDL-480p")
    langs = {l["name"]: l for l in s.get("/api/v3/language")}
    if item["idioma"] == "dublado":
        idiomas = [langs["Portuguese (Brazil)"]]
    else:
        orig = s.get(f"/api/v3/series/{series_id}").get("originalLanguage") or langs["Original"]
        idiomas = [orig]
    cmd = s.post("/api/v3/command", {"name": "ManualImport", "importMode": "move", "files": [{
        "path": caminho, "folderName": os.path.basename(os.path.dirname(caminho)),
        "seriesId": series_id, "episodeIds": [item["episodeId"]],
        "quality": {"quality": qualidade, "revision": {"version": 1, "real": 0, "isRepack": False}},
        "languages": [{"id": l["id"], "name": l["name"]} for l in idiomas],
        "releaseGroup": "YouTube", "indexerFlags": 0, "releaseType": "singleEpisode",
    }]})
    for _ in range(600):
        st = s.get(f"/api/v3/command/{cmd['id']}")
        if st.get("status") in ("completed", "failed", "aborted", "cancelled"):
            break
        time.sleep(2)
    if not s.get(f"/api/v3/episode/{item['episodeId']}").get("hasFile"):
        raise RuntimeError(f"o Sonarr não importou ({st.get('status')}: {st.get('message') or ''})")
