"""Bazarr: legendas pt-BR sincronizadas."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import Client, KEYS, PASSWORD, RADARR, SONARR, USER, log, wait_for


BAZARR = "http://bazarr:6767"
SUB_LANG = "pb"  # Portuguese (Brazil) no Bazarr
SUB_EN = "en"
SUB_NAMES = {SUB_LANG: "pt-BR", SUB_EN: "inglês"}


def subtitle_languages():
    """pt-BR sempre; inglês também se alguma pessoa escolheu legenda em inglês (./pessoas.sh)."""
    try:
        from .pessoas import Casa
        casa = Casa()
        prefs = {casa.jf.get(f"/Users/{u['Id']}")["Configuration"].get("SubtitleLanguagePreference")
                 for u in casa.jf_users()}
    except Exception:  # Jellyfin/Seerr ainda não configurados (primeira instalação)
        prefs = set()
    return [SUB_LANG] + ([SUB_EN] if "eng" in prefs else [])


def bazarr_apikey():
    section = None
    for line in open("/bazarr-config/config.yaml"):
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            section = line.strip()[:-1]
        elif section == "auth" and line.strip().startswith("apikey:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    raise RuntimeError("API key do Bazarr não encontrada")


def bazarr():
    print("Bazarr")
    wait_for("Bazarr", BAZARR)
    for _ in range(40):
        if os.path.exists("/bazarr-config/config.yaml"):
            break
        time.sleep(3)
    key = bazarr_apikey()
    c = Client(BAZARR, {"X-API-KEY": key, "Content-Type": "application/x-www-form-urlencoded"})

    def post_form(fields):
        data = urllib.parse.urlencode(fields, doseq=True).encode()
        r = urllib.request.Request(BAZARR + "/api/system/settings", data=data, method="POST", headers=c.headers)
        try:
            c.opener.open(r, timeout=60).read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Bazarr settings -> {e.code}: {e.read().decode()[:300]}") from None

    providers = ["embeddedsubtitles", "yifysubtitles", "subf2m"]
    extra = {}
    if os.environ.get("OPENSUBTITLES_USER"):
        providers.append("opensubtitlescom")
        extra.update({"settings-opensubtitlescom-username": os.environ["OPENSUBTITLES_USER"],
                      "settings-opensubtitlescom-password": os.environ.get("OPENSUBTITLES_PASSWORD", "")})
    if os.environ.get("SUBDL_API_KEY"):
        providers.append("subdl")
        extra["settings-subdl-api_key"] = os.environ["SUBDL_API_KEY"]
    if os.environ.get("LEGENDASNET_USER"):
        providers.append("legendasnet")
        extra.update({"settings-legendasnet-username": os.environ["LEGENDASNET_USER"],
                      "settings-legendasnet-password": os.environ.get("LEGENDASNET_PASSWORD", "")})

    langs = subtitle_languages()
    profile = [{
        "profileId": 1, "name": "Português (BR)", "cutoff": None, "tag": None,
        "mustContain": [], "mustNotContain": [], "originalFormat": False,
        # audio_exclude: não baixa legenda no mesmo idioma do áudio (ex.: pt-BR em filme dublado)
        "items": [{"id": i, "language": lang, "hi": "False", "forced": "False",
                   "audio_exclude": "True", "audio_only_include": "False"}
                  for i, lang in enumerate(langs, 1)],
    }]
    current = c.get("/api/system/settings")
    auth = {}
    if current["auth"].get("username") != USER:
        auth = {"settings-auth-type": "form", "settings-auth-username": USER, "settings-auth-password": PASSWORD}

    post_form({
        **auth, **extra,
        "languages-enabled": langs,
        "languages-profiles": json.dumps(profile),
        "settings-general-enabled_providers": providers,
        "settings-general-use_sonarr": "true", "settings-general-use_radarr": "true",
        "settings-sonarr-ip": "sonarr", "settings-sonarr-port": "8989", "settings-sonarr-apikey": KEYS["sonarr"],
        "settings-sonarr-base_url": "/",
        "settings-radarr-ip": "radarr", "settings-radarr-port": "7878", "settings-radarr-apikey": KEYS["radarr"],
        "settings-radarr-base_url": "/",
        "settings-general-serie_default_enabled": "true", "settings-general-serie_default_profile": "1",
        "settings-general-movie_default_enabled": "true", "settings-general-movie_default_profile": "1",
        "settings-general-parse_embedded_audio_track": "true",  # lê o idioma do áudio dentro do arquivo
        "settings-general-use_embedded_subs": "true",
        # Sincroniza toda legenda baixada com o áudio do arquivo (corrige atraso/adiantamento)
        "settings-subsync-use_subsync": "true",
        "settings-subsync-use_subsync_threshold": "false",
        "settings-subsync-use_subsync_movie_threshold": "false",
        "settings-subsync-gss": "true",
        "settings-subsync-max_offset_seconds": "120",
        # Mínimo baixo é seguro porque a legenda é sincronizada com o áudio depois (subsync)
        "settings-general-minimum_score_movie": "50",
        "settings-general-minimum_score": "60",
        # Subf2m recusa clientes sem User-Agent de navegador
        "settings-subf2m-user_agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"),
    })
    log("legendas " + " + ".join(SUB_NAMES[l] for l in langs) + ", Radarr/Sonarr conectados, provedores: "
        + ", ".join(providers))

    # Sincroniza agora e aplica o perfil pt-BR ao que já existe (o padrão só vale pros novos)
    def form(method, path, fields):
        data = urllib.parse.urlencode(fields, doseq=True).encode()
        r = urllib.request.Request(BAZARR + path, data=data, method=method, headers=c.headers)
        c.opener.open(r, timeout=60).read()

    targets = (("movies", "radarrid", "radarrId", "update_movies", RADARR, "movie"),
               ("series", "seriesid", "sonarrSeriesId", "update_series", SONARR, "series"))
    for kind, arg, idkey, task, base, arr_path in targets:
        # O Bazarr só cadastra o que já tem arquivo baixado
        media = Client(base, {"X-Api-Key": KEYS["radarr" if kind == "movies" else "sonarr"]}).get(f"/api/v3/{arr_path}")
        expected = sum(1 for m in media if m.get("hasFile") or m.get("statistics", {}).get("episodeFileCount"))
        if not expected:
            continue
        form("POST", "/api/system/tasks", {"taskid": task})
        items = []
        for _ in range(40):
            items = c.get(f"/api/{kind}?start=0&length=-1")["data"]
            if len(items) >= expected:
                break
            time.sleep(3)
        todo = [i[idkey] for i in items if i.get("profileId") in (None, "")]
        if todo:
            form("POST", f"/api/{kind}", {arg: todo, "profileid": ["1"] * len(todo)})
            log(f"perfil pt-BR aplicado a {len(todo)} {'filme(s)' if kind == 'movies' else 'série(s)'} existentes")
    if auth:
        log("login configurado")
