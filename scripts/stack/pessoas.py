"""Pessoas da casa: conta no Jellyfin/Seerr e preferência de áudio e legenda de cada uma.

Onde cada preferência mora (não há arquivo extra):
  áudio   -> regra do Seerr por usuário: quem prefere o original pede no perfil "Original + legenda"
             (sem regra = padrão da casa, dublado PT-BR)
  legenda -> configuração de reprodução do usuário no Jellyfin; o Bazarr baixa legenda em
             inglês além da pt-BR se alguém escolher inglês (bazarr.subtitle_languages)
"""
import sys

from .common import Client, JELLYFIN, KEYS, PASSWORD, RADARR, SEERR, SONARR, USER, log
from .jellyfin import JF_AUTH
from .language import ORIG_PROFILE

AUDIO = ("dublado", "original")
LEGENDA = ("pt-br", "en", "nenhuma")
# Seerr: pode pedir e o pedido é aprovado sozinho (sem esperar o admin)
SEERR_PERMS = 32 | 128

# Reprodução no Jellyfin para cada combinação
_SUB_LANG = {"pt-br": "por", "en": "eng", "nenhuma": ""}


def jellyfin_cfg(audio, legenda):
    cfg = {"SubtitleLanguagePreference": _SUB_LANG[legenda]}
    if audio == "dublado":
        # Faixa em português quando houver; legenda só quando o áudio não for português
        cfg.update(AudioLanguagePreference="por", PlayDefaultAudioTrack=False,
                   SubtitleMode="Smart" if legenda != "nenhuma" else "OnlyForced")
    else:
        # Faixa padrão do arquivo (o original) e legenda sempre ligada, se escolhida
        cfg.update(AudioLanguagePreference="", PlayDefaultAudioTrack=True,
                   SubtitleMode="Always" if legenda != "nenhuma" else "OnlyForced")
    return cfg


def legenda_de(cfg):
    if cfg.get("SubtitleMode") in ("OnlyForced", "None") or not cfg.get("SubtitleLanguagePreference"):
        return "nenhuma"
    return {"por": "pt-br", "eng": "en"}.get(cfg["SubtitleLanguagePreference"],
                                            cfg["SubtitleLanguagePreference"])


def _norm(guid):
    return (guid or "").replace("-", "").lower()


class Casa:
    """Clientes logados como admin no Jellyfin e no Seerr."""

    def __init__(self):
        self.jf = Client(JELLYFIN, {"Authorization": JF_AUTH})
        auth = self.jf.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
        self.jf.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
        self.seerr = Client(SEERR)
        self.seerr.post("/api/v1/auth/jellyfin", {"username": USER, "password": PASSWORD})

    # ---------- Jellyfin
    def jf_users(self):
        return self.jf.get("/Users")

    def jf_user(self, nome):
        u = next((u for u in self.jf_users() if u["Name"].lower() == nome.lower()), None)
        if not u:
            sys.exit(f"Pessoa '{nome}' não existe. Para cadastrar: ./pessoas.sh nova {nome}")
        return u

    # ---------- Seerr
    def seerr_user(self, jf_user, criar=True):
        users = self.seerr.get("/api/v1/user?take=500")["results"]
        su = next((u for u in users if _norm(u.get("jellyfinUserId")) == _norm(jf_user["Id"])), None)
        if su or not criar:
            return su
        self.seerr.post("/api/v1/user/import-from-jellyfin", {"jellyfinUserIds": [jf_user["Id"]]})
        su = self.seerr_user(jf_user, criar=False)
        if su and not su["permissions"] & 2:  # não mexe no admin
            self.seerr.post(f"/api/v1/user/{su['id']}/settings/permissions",
                            {"permissions": SEERR_PERMS})
        return su

    def servicos(self):
        """[(campo do serviço na regra, id do serviço no Seerr, id do perfil Original)]"""
        out = []
        for kind, base, field in (("radarr", RADARR, "radarrServiceId"), ("sonarr", SONARR, "sonarrServiceId")):
            perfis = Client(base, {"X-Api-Key": KEYS[kind]}).get("/api/v3/qualityprofile")
            pid = next((p["id"] for p in perfis if p["name"] == ORIG_PROFILE), None)
            if pid is None:
                sys.exit(f"Perfil '{ORIG_PROFILE}' não existe no {kind}: rode ./setup.sh antes")
            for srv in self.seerr.get(f"/api/v1/settings/{kind}"):
                out.append((field, srv["id"], pid))
        return out

    def regras(self, seerr_id):
        """Regras 'só este usuário -> perfil' (as que a Locadora cria)."""
        return [r for r in self.seerr.get("/api/v1/overrideRule")
                if r.get("users") == str(seerr_id)
                and not any(r.get(k) for k in ("genre", "language", "keywords"))]

    def audio_de(self, seerr_user, orig_ids):
        if not seerr_user:
            return "dublado"
        return "original" if any(r.get("profileId") in orig_ids for r in self.regras(seerr_user["id"])) \
            else "dublado"

    # ---------- Aplicar
    def aplicar(self, jf_user, audio, legenda):
        cfg = self.jf.get(f"/Users/{jf_user['Id']}")["Configuration"]
        want = jellyfin_cfg(audio, legenda)
        if any(cfg.get(k) != v for k, v in want.items()):
            self.jf.post(f"/Users/{jf_user['Id']}/Configuration", {**cfg, **want})
        su = self.seerr_user(jf_user)
        servicos = self.servicos()
        regras = self.regras(su["id"])
        for field, srv_id, pid in servicos:
            minhas = [r for r in regras if r.get(field) == srv_id]
            if audio == "original" and not any(r.get("profileId") == pid for r in minhas):
                for r in minhas:
                    self.seerr.delete(f"/api/v1/overrideRule/{r['id']}")
                self.seerr.post("/api/v1/overrideRule", {"users": str(su["id"]), field: srv_id,
                                                         "profileId": pid})
            elif audio == "dublado":
                for r in minhas:
                    self.seerr.delete(f"/api/v1/overrideRule/{r['id']}")


def _escolher(pergunta, opcoes, padrao):
    if not sys.stdin.isatty():
        return padrao
    while True:
        r = input(f"{pergunta} [{'/'.join(opcoes)}] ({padrao}): ").strip().lower() or padrao
        if r in opcoes:
            return r
        print(f"  escolha uma de: {', '.join(opcoes)}")


def lista():
    """[{nome, audio, legenda, admin, no_seerr}] de cada pessoa (usado também pelo painel)."""
    casa = Casa()
    orig_ids = {pid for _, _, pid in casa.servicos()}
    out = []
    for u in casa.jf_users():
        cfg = casa.jf.get(f"/Users/{u['Id']}")["Configuration"]
        su = casa.seerr_user(u, criar=False)
        out.append({"nome": u["Name"], "audio": casa.audio_de(su, orig_ids), "legenda": legenda_de(cfg),
                    "admin": bool(u.get("Policy", {}).get("IsAdministrator")), "no_seerr": bool(su)})
    return out


def listar():
    print(f"{'Pessoa':20} {'Áudio':10} Legenda")
    for p in lista():
        extra = "" if p["no_seerr"] else "   (ainda não entrou no Seerr)"
        print(f"{p['nome']:20} {p['audio']:10} {p['legenda']}{extra}")


def nova(nome, senha, audio, legenda):
    casa = Casa()
    if any(u["Name"].lower() == nome.lower() for u in casa.jf_users()):
        sys.exit(f"'{nome}' já existe. Para mudar a preferência: ./pessoas.sh preferencia {nome}")
    audio = audio or _escolher("Áudio preferido", AUDIO, "dublado")
    legenda = legenda or _escolher("Legenda", LEGENDA, "pt-br")
    u = casa.jf.post("/Users/New", {"Name": nome, "Password": senha})
    casa.aplicar(u, audio, legenda)
    log(f"{nome}: conta criada (Jellyfin e Seerr, pedidos aprovados sozinhos), "
        f"áudio {audio}, legenda {legenda}")
    return legenda


def preferencia(nome, audio, legenda):
    casa = Casa()
    u = casa.jf_user(nome)
    orig_ids = {pid for _, _, pid in casa.servicos()}
    cfg = casa.jf.get(f"/Users/{u['Id']}")["Configuration"]
    audio = audio or _escolher("Áudio preferido", AUDIO, casa.audio_de(casa.seerr_user(u, criar=False), orig_ids))
    legenda = legenda or _escolher("Legenda", LEGENDA, legenda_de(cfg))
    casa.aplicar(u, audio, legenda)
    log(f"{u['Name']}: áudio {audio}, legenda {legenda}")
    return legenda
