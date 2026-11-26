"""Bot do Telegram: pedir filmes e séries conversando, em nome de cada pessoa da casa.

Cada pessoa se liga uma vez com "/entrar usuário senha" (o login do Jellyfin). O bot guarda o
chat dela no Seerr (o mesmo campo que o Seerr usa para avisar "seu pedido está pronto") e faz
os pedidos em nome dela, então valem as preferências do ./pessoas.sh (dublado/original).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import youtube
from .common import Client, JELLYFIN, PASSWORD, SEERR, USER
from .jellyfin import JF_AUTH

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"

# Avisos que cada pessoa recebe sobre os pedidos DELA (bits do Seerr; o padrão do Seerr é nenhum):
# disponível 8, falhou 16, recusado 64
AVISOS_PESSOA = 8 | 16 | 64

# Status de mídia no Seerr
DISPONIVEL, PARCIAL, PROCESSANDO, PENDENTE = 5, 4, 3, 2
STATUS = {DISPONIVEL: "✅ já está na Locadora", PARCIAL: "✅ parte já está na Locadora",
          PROCESSANDO: "⏳ já foi pedido, baixando", PENDENTE: "⏳ já foi pedido"}

AJUDA = ("Mande o nome de um filme ou série que eu procuro. 🎬\n\n"
         "/pedidos  o que você pediu e como está\n"
         "/sair  desliga este Telegram da sua conta")
AJUDA_ADMIN = ("\n\nSó para o admin:\n"
               "/youtube <link>  baixa os episódios de um canal ou playlist do YouTube "
               "(a série precisa estar pedida)\n"
               "/youtube  o que está baixando do YouTube")
BOAS_VINDAS = ("Oi! Eu sou o bot da Locadora. 🍿\n\n"
               "Para começar, entre com o mesmo usuário e senha do Jellyfin:\n"
               "/entrar seu_usuario sua_senha\n\n"
               "(Eu apago essa mensagem logo depois, para a senha não ficar no chat.)")


FILA = None          # youtube.Fila, criada em rodar()
YT_PENDENTE = {}     # chat -> {"lista": título, "videos": [...], "serie": dict, "plano": dict}


def admin(pessoa, chat):
    """Quem pode usar /youtube: o chat do TELEGRAM_CHAT_ID ou um admin do Seerr."""
    return str(chat) == os.environ.get("TELEGRAM_CHAT_ID", "") or bool(pessoa.get("permissions", 0) & 2)


def ajuda(pessoa, chat):
    return AJUDA + (AJUDA_ADMIN if admin(pessoa, chat) else "")


def tg(method, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(f"{API}/{method}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read()).get("result")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"Telegram {method} -> {e.code}: {detail}") from None


def enviar(chat, texto, **extra):
    return tg("sendMessage", chat_id=chat, text=texto, **extra)


class Seerr:
    """Fala com o Seerr pela chave de API, agindo como o admin ou como uma pessoa."""

    def __init__(self):
        c = Client(SEERR)
        c.post("/api/v1/auth/jellyfin", {"username": USER, "password": PASSWORD})
        self.key = c.get("/api/v1/settings/main")["apiKey"]
        self._chats = {}
        self._quando = 0

    def como(self, user_id=None):
        h = {"X-Api-Key": self.key}
        if user_id:
            h["X-API-User"] = str(user_id)
        return Client(SEERR, h)

    def pessoa_do_chat(self, chat):
        """Seerr user (dict) ligado a este chat, ou None. Cache de 60s."""
        if str(chat) not in self._chats or time.time() - self._quando > 60:
            adm = self.como()
            self._chats = {}
            for u in adm.get("/api/v1/user?take=500")["results"]:
                n = adm.get(f"/api/v1/user/{u['id']}/settings/notifications")
                if n.get("telegramChatId"):
                    self._chats[str(n["telegramChatId"])] = u
            self._quando = time.time()
        return self._chats.get(str(chat))

    def ligar(self, user_id, chat):
        """Liga (ou desliga, com chat vazio) o Telegram da pessoa, com os avisos dos pedidos dela."""
        adm = self.como()
        n = adm.get(f"/api/v1/user/{user_id}/settings/notifications")
        tipos = {**(n.get("notificationTypes") or {}), "telegram": AVISOS_PESSOA if chat else 0}
        adm.post(f"/api/v1/user/{user_id}/settings/notifications",
                 {**n, "telegramChatId": str(chat) if chat else "", "notificationTypes": tipos})
        self._quando = 0


def entrar(seerr, chat, usuario, senha):
    """Confere o login no Jellyfin e liga o chat à pessoa no Seerr."""
    jf = Client(JELLYFIN, {"Authorization": JF_AUTH})
    try:
        auth = jf.post("/Users/AuthenticateByName", {"Username": usuario, "Pw": senha})
    except RuntimeError:
        return None
    jf_id = auth["User"]["Id"].replace("-", "").lower()
    adm = seerr.como()
    achar = lambda: next((u for u in adm.get("/api/v1/user?take=500")["results"]
                          if (u.get("jellyfinUserId") or "").replace("-", "").lower() == jf_id), None)
    u = achar()
    if not u:  # nunca entrou no Seerr: importa do Jellyfin, já podendo pedir
        from .pessoas import SEERR_PERMS
        adm.post("/api/v1/user/import-from-jellyfin", {"jellyfinUserIds": [auth["User"]["Id"]]})
        u = achar()
        if u and not u["permissions"] & 2:
            adm.post(f"/api/v1/user/{u['id']}/settings/permissions", {"permissions": SEERR_PERMS})
    if not u:
        return None
    # Um chat só pode estar ligado a uma pessoa
    antigo = seerr.pessoa_do_chat(chat)
    if antigo and antigo["id"] != u["id"]:
        seerr.ligar(antigo["id"], "")
    seerr.ligar(u["id"], chat)
    return u


def titulo(r):
    nome = r.get("title") or r.get("name") or "?"
    ano = (r.get("releaseDate") or r.get("firstAirDate") or "")[:4]
    tipo = "🎬" if r["mediaType"] == "movie" else "📺"
    return f"{tipo} {nome}" + (f" ({ano})" if ano else "")


def buscar(seerr, pessoa, chat, texto):
    q = urllib.parse.quote(texto)
    res = seerr.como(pessoa["id"]).get(f"/api/v1/search?query={q}&page=1&language=pt-BR")["results"]
    res = [r for r in res if r.get("mediaType") in ("movie", "tv")][:6]
    if not res:
        return enviar(chat, f"Não achei nada para \"{texto}\". Tente o nome em inglês ou com o ano.")
    botoes = []
    for r in res:
        st = (r.get("mediaInfo") or {}).get("status")
        rotulo = titulo(r) + ("  ✅" if st in (DISPONIVEL, PARCIAL) else "  ⏳" if st in (PROCESSANDO, PENDENTE) else "")
        botoes.append([{"text": rotulo[:60], "callback_data": f"p:{r['mediaType']}:{r['id']}"}])
    enviar(chat, "Qual destes? (✅ já tem, ⏳ já foi pedido)", reply_markup={"inline_keyboard": botoes})


def pedir(seerr, pessoa, chat, tipo, tmdb):
    c = seerr.como(pessoa["id"])
    info = c.get(f"/api/v1/{tipo}/{tmdb}?language=pt-BR")
    nome = titulo({**info, "mediaType": tipo})
    st = (info.get("mediaInfo") or {}).get("status")
    if st in STATUS:
        return enviar(chat, f"{nome}: {STATUS[st]}.")
    body = {"mediaType": tipo, "mediaId": int(tmdb)}
    if tipo == "tv":
        body["seasons"] = "all"
    try:
        c.post("/api/v1/request", body)
    except RuntimeError as e:
        if "403" in str(e):
            return enviar(chat, "Sua conta não pode fazer pedidos. Peça para o admin da Locadora liberar.")
        if "quota" in str(e).lower() or "429" in str(e):
            return enviar(chat, "Você chegou no limite de pedidos por enquanto.")
        raise
    enviar(chat, f"Pedido feito: {nome}\nEu aviso aqui quando estiver pronto para assistir. 🍿")


def pedidos(seerr, pessoa, chat):
    reqs = seerr.como().get(f"/api/v1/request?take=10&sort=added&requestedBy={pessoa['id']}")["results"]
    if not reqs:
        return enviar(chat, "Você ainda não pediu nada. Mande o nome de um filme ou série.")
    linhas = []
    for r in reqs:
        m = r.get("media") or {}
        tipo = m.get("mediaType", "movie")
        try:
            info = seerr.como().get(f"/api/v1/{tipo}/{m.get('tmdbId')}?language=pt-BR")
            nome = titulo({**info, "mediaType": tipo})
        except RuntimeError:
            nome = f"#{m.get('tmdbId')}"
        st = m.get("status")
        estado = {DISPONIVEL: "pronto ✅", PARCIAL: "em parte ✅", PROCESSANDO: "baixando ⏳"}.get(
            st, "recusado ❌" if r.get("status") == 3 else "aguardando ⏳")
        linhas.append(f"{nome}: {estado}")
    enviar(chat, "Seus pedidos:\n" + "\n".join(linhas))


def yt_link(chat, texto):
    """/youtube <link> [nome da série]: lista o canal numa thread (pode levar um minuto)."""
    partes = texto.split(maxsplit=2)
    url = youtube.link_da_lista(partes[1])
    if not url:
        return enviar(chat, "Esse link não é do YouTube. Mande o link do canal ou da playlist.")
    nome = partes[2] if len(partes) > 2 else ""
    enviar(chat, "🔎 Olhando os vídeos do canal… (canais grandes levam um minuto)")

    def trabalho():
        try:
            lista, videos = youtube.listar(url)
            series = youtube.series_do_sonarr()
            if nome:
                serie = youtube.adivinhar_serie(series, nome, [])
            else:
                serie = youtube.adivinhar_serie(series, lista, [v.get("title") or "" for v in videos])
            YT_PENDENTE[str(chat)] = {"lista": lista, "videos": videos}
            if serie:
                return yt_mostrar(chat, serie)
            yt_perguntar_serie(chat, series, f"Achei {len(videos)} vídeos em \"{lista}\".")
        except Exception as e:
            print(f"[bot] /youtube {url}: {e}", flush=True)
            enviar(chat, f"Não consegui ler esse link: {e}")
    threading.Thread(target=trabalho, daemon=True).start()


def yt_perguntar_serie(chat, series, antes):
    if not series:
        return enviar(chat, antes + "\nNenhuma série pedida ainda. Peça a série (mande o nome aqui) "
                      "e depois mande o link de novo.")
    recentes = sorted(series, key=lambda s: s.get("added") or "", reverse=True)[:10]
    botoes = [[{"text": s["title"][:60], "callback_data": f"y:s:{s['id']}"}] for s in recentes]
    enviar(chat, antes + "\nDe qual série são? (se não estiver aqui, peça a série primeiro)",
           reply_markup={"inline_keyboard": botoes})


def yt_mostrar(chat, serie):
    p = YT_PENDENTE.get(str(chat))
    if not p:
        return enviar(chat, "Mande o link de novo: /youtube <link>")
    plano = youtube.planejar(serie, p["lista"], p["videos"])
    p.update(serie=serie, plano=plano)
    botoes = [[{"text": "⬇️ Baixar", "callback_data": "y:ok"}] if plano["baixar"] else [],
              [{"text": "Outra série", "callback_data": "y:outra"}, {"text": "Cancelar", "callback_data": "y:no"}]]
    enviar(chat, youtube.resumo(serie, plano), reply_markup={"inline_keyboard": [b for b in botoes if b]})


def yt_botao(chat, acao):
    p = YT_PENDENTE.get(str(chat))
    if acao == "no":
        YT_PENDENTE.pop(str(chat), None)
        return enviar(chat, "Cancelado.")
    if not p:
        return enviar(chat, "Isso já expirou. Mande o link de novo: /youtube <link>")
    if acao == "outra":
        return yt_perguntar_serie(chat, youtube.series_do_sonarr(), "")
    if acao.startswith("s:"):
        serie = next((s for s in youtube.series_do_sonarr() if str(s["id"]) == acao[2:]), None)
        return yt_mostrar(chat, serie) if serie else enviar(chat, "Essa série não está mais no Sonarr.")
    if acao == "ok" and p.get("plano", {}).get("baixar"):
        FILA.adicionar(chat, p["serie"], p["plano"])
        YT_PENDENTE.pop(str(chat), None)
        n = len(p["plano"]["baixar"])
        return enviar(chat, f"⬇️ Baixando {n} episódio(s) de {p['serie']['title']}, um por vez. "
                      "Aviso aqui quando terminar. Para ver como está: /youtube")


def tratar(seerr, upd):
    if "callback_query" in upd:
        q = upd["callback_query"]
        chat = q["message"]["chat"]["id"]
        tg("answerCallbackQuery", callback_query_id=q["id"])
        pessoa = seerr.pessoa_do_chat(chat)
        if not pessoa:
            return enviar(chat, BOAS_VINDAS)
        tg("editMessageReplyMarkup", chat_id=chat, message_id=q["message"]["message_id"],
           reply_markup={"inline_keyboard": []})
        if q.get("data", "").startswith("y:"):
            return yt_botao(chat, q["data"][2:]) if admin(pessoa, chat) else None
        _, tipo, tmdb = q.get("data", "p:movie:0").split(":")
        return pedir(seerr, pessoa, chat, tipo, tmdb)

    msg = upd.get("message") or {}
    texto = (msg.get("text") or "").strip()
    chat = msg.get("chat", {}).get("id")
    if not texto or not chat:
        return
    privado = msg["chat"].get("type") == "private"
    cmd = texto.split()[0].split("@")[0].lower() if texto.startswith("/") else ""

    if cmd == "/entrar":
        try:  # a senha não fica no chat
            tg("deleteMessage", chat_id=chat, message_id=msg["message_id"])
        except RuntimeError:
            pass
        if not privado:
            return enviar(chat, "Por segurança, use /entrar só na conversa direta comigo.")
        partes = texto.split(maxsplit=2)
        if len(partes) < 3:
            return enviar(chat, "Use assim: /entrar seu_usuario sua_senha")
        u = entrar(seerr, chat, partes[1], partes[2])
        if not u:
            return enviar(chat, "Usuário ou senha não conferem. É o mesmo login do Jellyfin.")
        return enviar(chat, f"Pronto, {u.get('displayName') or partes[1]}! 🎉\n\n" + ajuda(u, chat))

    pessoa = seerr.pessoa_do_chat(chat)
    if cmd in ("/start", "/ajuda", "/help") or not pessoa:
        return enviar(chat, (ajuda(pessoa, chat) if pessoa else BOAS_VINDAS))
    if cmd == "/sair":
        seerr.ligar(pessoa["id"], "")
        return enviar(chat, "Desliguei este Telegram da sua conta. Para voltar: /entrar")
    if cmd == "/pedidos":
        return pedidos(seerr, pessoa, chat)
    if cmd == "/youtube" and admin(pessoa, chat):
        return yt_link(chat, texto) if len(texto.split()) > 1 else enviar(chat, FILA.situacao())
    if cmd:
        return enviar(chat, ajuda(pessoa, chat))
    return buscar(seerr, pessoa, chat, texto)


def rodar():
    """Laço principal (long polling). Erros de rede ou do Seerr não derrubam o bot."""
    me = tg("getMe")
    tg("setMyCommands", commands=[
        {"command": "entrar", "description": "ligar sua conta (usuário e senha do Jellyfin)"},
        {"command": "pedidos", "description": "o que você pediu e como está"},
        {"command": "sair", "description": "desligar este Telegram da sua conta"},
    ])
    print(f"[bot] @{me['username']} no ar", flush=True)
    global FILA
    FILA = youtube.Fila(avisar=enviar)
    seerr, offset = None, None
    while True:
        try:
            seerr = seerr or Seerr()
            for upd in tg("getUpdates", timeout=50, offset=offset, allowed_updates=["message", "callback_query"]) or []:
                offset = upd["update_id"] + 1
                try:
                    tratar(seerr, upd)
                except Exception as e:  # uma mensagem ruim não para o bot
                    print(f"[bot] erro tratando mensagem: {e}", flush=True)
                    chat = (upd.get("message") or upd.get("callback_query", {}).get("message") or {}).get("chat", {}).get("id")
                    if chat:
                        try:
                            enviar(chat, "Algo deu errado aqui. Tente de novo em alguns minutos.")
                        except Exception:
                            pass
        except Exception as e:
            print(f"[bot] {e}; tentando de novo em 15s", flush=True)
            seerr = None
            time.sleep(15)
