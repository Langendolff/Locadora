"""Jellyfin: assistente inicial, bibliotecas, idioma, GPU e avisos do Radarr/Sonarr."""
import os
import time
import urllib.parse

from .common import Client, HAS_GPU, JELLYFIN, KEYS, PASSWORD, RADARR, SONARR, USER, log, set_field, wait_for


# "pt" sozinho o TMDB entende como português de Portugal ("És o Maior, Meu!")
META_LANG = "pt-BR"
JF_AUTH = 'MediaBrowser Client="stack-setup", Device="setup", DeviceId="stack-setup", Version="1.0"'


def jellyfin():
    print("Jellyfin")
    wait_for("Jellyfin", JELLYFIN + "/health")
    c = Client(JELLYFIN, {"Authorization": JF_AUTH})

    for _ in range(60):  # espera o servidor terminar de iniciar
        try:
            info = c.get("/System/Info/Public")
            break
        except Exception:
            time.sleep(3)

    if not info.get("StartupWizardCompleted"):
        c.post("/Startup/Configuration", {"UICulture": "pt-BR", "MetadataCountryCode": "BR",
                                          "PreferredMetadataLanguage": META_LANG})
        c.get("/Startup/User")
        c.post("/Startup/User", {"Name": USER, "Password": PASSWORD})
        c.post("/Startup/RemoteAccess", {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False})
        c.post("/Startup/Complete")
        log("assistente inicial concluído")

    auth = c.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
    c.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'

    # Idioma dos títulos/sinopses: servidor e bibliotecas já existentes (instalações antigas: "pt")
    cfg = c.get("/System/Configuration")
    mudou = False
    if cfg.get("PreferredMetadataLanguage") != META_LANG or cfg.get("MetadataCountryCode") != "BR":
        cfg.update(PreferredMetadataLanguage=META_LANG, MetadataCountryCode="BR")
        c.post("/System/Configuration", cfg)
        mudou = True
    for f in c.get("/Library/VirtualFolders"):
        opts = f.get("LibraryOptions") or {}
        if opts.get("PreferredMetadataLanguage") != META_LANG:
            opts.update(PreferredMetadataLanguage=META_LANG, MetadataCountryCode="BR")
            c.post("/Library/VirtualFolders/LibraryOptions", {"Id": f["ItemId"], "LibraryOptions": opts})
            # Busca de novo títulos e sinopses (imagens ficam)
            q = urllib.parse.urlencode({"Recursive": "true", "MetadataRefreshMode": "FullRefresh",
                                        "ImageRefreshMode": "Default", "ReplaceAllMetadata": "true",
                                        "ReplaceAllImages": "false"})
            c.post(f"/Items/{f['ItemId']}/Refresh?{q}")
            mudou = True
    if mudou:
        log("títulos e sinopses em português do Brasil")

    existing = {f["Name"] for f in c.get("/Library/VirtualFolders")}
    for name, ctype, path in (("Filmes", "movies", "/data/media/movies"), ("Séries", "tvshows", "/data/media/tv")):
        if name in existing:
            continue
        q = urllib.parse.urlencode({"name": name, "collectionType": ctype, "paths": path, "refreshLibrary": "true"})
        c.post(f"/Library/VirtualFolders?{q}", {"LibraryOptions": {
            "PreferredMetadataLanguage": META_LANG, "MetadataCountryCode": "BR",
            "PathInfos": [{"Path": path}],
        }})
        log(f"biblioteca {name}")

    # Áudio em português quando houver; se não, legenda pt-BR ligada automaticamente ("Smart")
    uid = auth["User"]["Id"]
    ucfg = c.get(f"/Users/{uid}")["Configuration"]
    want = {"AudioLanguagePreference": "por", "SubtitleLanguagePreference": "por",
            "SubtitleMode": "Smart", "PlayDefaultAudioTrack": False}
    if any(ucfg.get(k) != val for k, val in want.items()):
        c.post(f"/Users/{uid}/Configuration", {**ucfg, **want})
        log("preferência de áudio PT e legenda pt-BR automática")

    branding(c)

    if HAS_GPU:
        enc = c.get("/System/Configuration/encoding")
        if enc.get("HardwareAccelerationType") != "vaapi":
            enc.update(HardwareAccelerationType="vaapi", VaapiDevice="/dev/dri/renderD128")
            c.post("/System/Configuration/encoding", enc)
            log("aceleração de hardware VAAPI")


# ---------------------------------------------------------------- Radarr/Sonarr avisam o Jellyfin
def jellyfin_api_key():
    c = Client(JELLYFIN, {"Authorization": JF_AUTH})
    auth = c.post("/Users/AuthenticateByName", {"Username": USER, "Pw": PASSWORD})
    c.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
    keys = c.get("/Auth/Keys")["Items"]
    key = next((k for k in keys if k.get("AppName") == "stack-arr"), None)
    if not key:
        c.post("/Auth/Keys?app=stack-arr")
        key = next(k for k in c.get("/Auth/Keys")["Items"] if k.get("AppName") == "stack-arr")
    return key["AccessToken"]


THEME_CSS = "/assets/jellyfin/locadora.css"
LOGIN_TEXT = ("Quer ver algo que ainda não está aqui? "
              "Peça no <b>Seerr</b>, na porta 5055 deste servidor.")


def branding(c):
    """Tema Locadora (CSS), nome do servidor e texto da tela de login."""
    css = open(THEME_CSS, encoding="utf-8").read() if os.path.exists(THEME_CSS) else ""
    cur = c.get("/System/Configuration/branding")
    want = {"CustomCss": css, "LoginDisclaimer": LOGIN_TEXT, "SplashscreenEnabled": True}
    if any(cur.get(k) != val for k, val in want.items()):
        c.post("/System/Configuration/branding", {**cur, **want})
        log("tema Locadora aplicado")
    cfg = c.get("/System/Configuration")
    if cfg.get("ServerName") != "Locadora":
        cfg["ServerName"] = "Locadora"
        c.post("/System/Configuration", cfg)
        log("servidor renomeado para Locadora")


def notify_jellyfin():
    """Sem isso o Jellyfin só percebe arquivo novo/trocado/apagado na varredura periódica,
    e tenta tocar um arquivo que não existe mais ("erro fatal do player")."""
    print("Avisos pro Jellyfin")
    key = jellyfin_api_key()
    for name, base in (("radarr", RADARR), ("sonarr", SONARR)):
        c = Client(base, {"X-Api-Key": KEYS[name]})
        if any(n["implementation"] == "MediaBrowser" for n in c.get("/api/v3/notification")):
            continue
        s = next(x for x in c.get("/api/v3/notification/schema") if x["implementation"] == "MediaBrowser")
        set_field(s["fields"], "host", "jellyfin")
        set_field(s["fields"], "port", 8096)
        set_field(s["fields"], "apiKey", key)
        set_field(s["fields"], "updateLibrary", True)
        events = [k for k, val in s.items() if k.startswith("on") and isinstance(val, bool)
                  and k not in ("onGrab", "onHealthIssue", "onHealthRestored", "onApplicationUpdate",
                                "onManualInteractionRequired")]
        s.update({k: True for k in events}, name="Jellyfin")
        c.post("/api/v3/notification", s)
        log(f"{name.capitalize()} atualiza a biblioteca do Jellyfin a cada download/troca/exclusão")
