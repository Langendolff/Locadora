"""Seerr: admin via Jellyfin, bibliotecas e Radarr/Sonarr."""
import os
import urllib.parse

from .common import Client, EMAIL, KEYS, PASSWORD, SEERR, USER, log, wait_for
from .language import PROFILE


def seerr_profiles(c):
    for kind in ("radarr", "sonarr"):
        for srv in c.get(f"/api/v1/settings/{kind}"):
            test = c.post(f"/api/v1/settings/{kind}/test", {k: srv[k] for k in
                                                           ("hostname", "port", "apiKey", "useSsl", "baseUrl")})
            prof = next((p for p in test["profiles"] if p["name"] == PROFILE), None)
            if prof and srv.get("activeProfileId") != prof["id"]:
                upd = {k: val for k, val in srv.items() if k != "id"}
                upd.update(activeProfileId=prof["id"], activeProfileName=prof["name"])
                if kind == "sonarr":
                    upd.update(activeAnimeProfileId=prof["id"], activeAnimeProfileName=prof["name"])
                c.put(f"/api/v1/settings/{kind}/{srv['id']}", upd)
                log(f"{kind.capitalize()}: pedidos novos usam o perfil '{PROFILE}'")


def seerr_brasil(c):
    """Catálogo com olhar brasileiro: 'Em alta' e 'onde assistir' (Netflix BR, Globoplay…) do Brasil."""
    main = c.get("/api/v1/settings/main")
    want = {"applicationTitle": "Locadora", "locale": "pt-BR",
            "discoverRegion": "BR", "streamingRegion": "BR"}
    remoto = os.environ.get("LOCADORA_URL_REMOTA")  # Tailscale: links dos avisos abrem de qualquer lugar
    if remoto:
        want["applicationUrl"] = remoto + ":8443"
    if any(main.get(k) != val for k, val in want.items()):
        c.post("/api/v1/settings/main", want)  # aceita parcial; apiKey é só leitura
        log("catálogo e 'onde assistir' do Brasil, nome Locadora")


# Tipos de aviso do Seerr (bits): pendente de aprovação 2, disponível 8, falhou 16
TG_TYPES = 2 | 8 | 16


def seerr_telegram(c):
    """Avisos do Seerr pelo bot do Telegram. Cada pessoa recebe os dos pedidos dela no próprio chat
    (ligado com /entrar no bot); TELEGRAM_CHAT_ID (opcional) recebe os do admin: tudo que fica
    disponível, falha ou espera aprovação."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token:
        return
    cur = c.get("/api/v1/settings/notifications/telegram")
    opts = cur.get("options", {})
    if cur.get("enabled") and opts.get("botAPI") == token and opts.get("chatId") == chat \
            and cur.get("types") == TG_TYPES:
        return
    c.post("/api/v1/settings/notifications/telegram", {
        **cur, "enabled": True, "types": TG_TYPES,
        "options": {**opts, "botAPI": token, "chatId": chat, "sendSilently": False}})
    log("avisos no Telegram ligados" + ("" if chat else " (só para cada pessoa; sem TELEGRAM_CHAT_ID do admin)"))


def seerr():
    print("Seerr")
    wait_for("Seerr", SEERR + "/api/v1/status")
    c = Client(SEERR)

    if c.get("/api/v1/settings/public").get("initialized"):
        c.post("/api/v1/auth/jellyfin", {"username": USER, "password": PASSWORD, "email": EMAIL})
        seerr_profiles(c)
        seerr_brasil(c)
        seerr_telegram(c)
        log("já inicializado")
        return

    # Primeiro login com a conta do Jellyfin -> vira admin e liga o Seerr ao Jellyfin
    creds = {"username": USER, "password": PASSWORD, "email": EMAIL}
    try:
        c.post("/api/v1/auth/jellyfin", {**creds, "hostname": "jellyfin", "port": 8096,
                                         "useSsl": False, "urlBase": "", "serverType": 2})
        log("admin criado e Jellyfin conectado")
    except RuntimeError:
        c.post("/api/v1/auth/jellyfin", creds)  # já configurado numa execução anterior
        log("login com admin existente")

    libs = c.post("/api/v1/settings/jellyfin/library/sync")
    for lib in libs:
        if not lib.get("enabled"):
            c.put(f"/api/v1/settings/jellyfin/library/{urllib.parse.quote(lib['id'])}", {"enabled": True})
    log(f"{len(libs)} bibliotecas habilitadas")

    for kind, host, port, root in (("radarr", "radarr", 7878, "/data/media/movies"),
                                   ("sonarr", "sonarr", 8989, "/data/media/tv")):
        if c.get(f"/api/v1/settings/{kind}"):
            continue
        conn = {"hostname": host, "port": port, "apiKey": KEYS[kind], "useSsl": False, "baseUrl": ""}
        test = c.post(f"/api/v1/settings/{kind}/test", conn)
        profile = next((p for p in test["profiles"] if p["name"] == PROFILE),
                       next((p for p in test["profiles"] if p["name"] == "HD-1080p"), test["profiles"][0]))
        body = {**conn, "name": kind.capitalize(), "activeProfileId": profile["id"],
                "activeProfileName": profile["name"], "activeDirectory": root, "is4k": False,
                "isDefault": True, "externalUrl": "", "syncEnabled": True, "preventSearch": False,
                "tags": []}
        if kind == "radarr":
            body["minimumAvailability"] = "released"
        else:
            body.update(seriesType="standard", animeSeriesType="anime", activeAnimeProfileId=profile["id"],
                        activeAnimeProfileName=profile["name"], activeAnimeDirectory=root,
                        enableSeasonFolders=True)
        c.post(f"/api/v1/settings/{kind}", body)
        log(f"{kind.capitalize()} conectado (perfil {profile['name']})")

    c.post("/api/v1/settings/initialize")
    seerr_brasil(c)
    seerr_telegram(c)
    log("inicialização concluída")
