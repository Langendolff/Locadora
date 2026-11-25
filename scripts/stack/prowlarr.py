"""Prowlarr: login, apps, FlareSolverr e indexadores de indexers/."""
import os

from .common import Client, KEYS, PASSWORD, PROWLARR, RADARR, SONARR, USER, log, set_field, wait_for


def prowlarr():
    print("Prowlarr")
    wait_for("prowlarr", PROWLARR + "/ping")
    c = Client(PROWLARR, {"X-Api-Key": KEYS["prowlarr"]})
    v = "/api/v1"

    host = c.get(f"{v}/config/host")
    if host.get("username") != USER or host.get("authenticationMethod") != "forms":
        host.update(authenticationMethod="forms", authenticationRequired="enabled",
                    username=USER, password=PASSWORD, passwordConfirmation=PASSWORD)
        c.put(f"{v}/config/host/{host['id']}", host)
        log("login configurado")

    apps = c.get(f"{v}/applications")
    schemas = c.get(f"{v}/applications/schema")
    for impl, url, key in (("Radarr", RADARR, "radarr"), ("Sonarr", SONARR, "sonarr")):
        if any(a["implementation"] == impl for a in apps):
            continue
        s = next(x for x in schemas if x["implementation"] == impl)
        set_field(s["fields"], "prowlarrUrl", PROWLARR)
        set_field(s["fields"], "baseUrl", url)
        set_field(s["fields"], "apiKey", KEYS[key])
        s.update(name=impl, syncLevel="fullSync")
        c.post(f"{v}/applications", s)
        log(f"{impl} conectado (indexadores sincronizam sozinhos)")

    tags = c.get(f"{v}/tag")
    tag = next((t for t in tags if t["label"] == "flare"), None) or c.post(f"{v}/tag", {"label": "flare"})
    if not any(p["implementation"] == "FlareSolverr" for p in c.get(f"{v}/indexerProxy")):
        s = next(x for x in c.get(f"{v}/indexerProxy/schema") if x["implementation"] == "FlareSolverr")
        set_field(s["fields"], "host", "http://flaresolverr:8191/")
        s.update(name="FlareSolverr", tags=[tag["id"]])
        c.post(f"{v}/indexerProxy", s)
        log("FlareSolverr adicionado (use a tag 'flare' em indexadores com Cloudflare)")

    # Indexadores da pasta indexers/ (montada em Definitions/Custom)
    custom = {os.path.splitext(f)[0] for f in os.listdir("/indexers") if f.endswith(".yml")} \
        if os.path.isdir("/indexers") else set()
    if custom:
        have = {i.get("definitionName") for i in c.get(f"{v}/indexer")}
        profile = c.get(f"{v}/appprofile")[0]["id"]
        schemas = None
        for name in sorted(custom - have):
            schemas = schemas or c.get(f"{v}/indexer/schema")
            s = next((x for x in schemas if x.get("definitionName") == name), None)
            if not s:
                log(f"AVISO: Prowlarr não carregou indexers/{name}.yml (reinicie o prowlarr)")
                continue
            set_field(s["fields"], "baseUrl", s["indexerUrls"][0])
            s.update(enable=True, appProfileId=profile, priority=25)
            c.post(f"{v}/indexer", s)
            log(f"indexador {s['name']} adicionado")

    # Indexadores públicos nativos listados em indexers/public.txt ("nome [flare]")
    path = "/indexers/public.txt"
    wanted = {}
    if os.path.isfile(path):
        for line in open(path):
            parts = line.split("#")[0].split()
            if parts:
                wanted[parts[0]] = "flare" in parts[1:]
    have = {i.get("definitionName") for i in c.get(f"{v}/indexer")}
    todo = {k: f for k, f in wanted.items() if k not in have}
    if todo:
        schemas = {x.get("definitionName"): x for x in c.get(f"{v}/indexer/schema")}
        profile = c.get(f"{v}/appprofile")[0]["id"]
    for name, flare in todo.items():
        s = schemas.get(name)
        if not s:
            log(f"AVISO: indexador '{name}' não existe no Prowlarr, pulando")
            continue
        set_field(s["fields"], "baseUrl", s["indexerUrls"][0])
        s.update(enable=True, appProfileId=profile, priority=25, tags=[tag["id"]] if flare else [])
        try:
            c.post(f"{v}/indexer?forceSave=true", s)
            log(f"indexador {s['name']} adicionado" + (" (via FlareSolverr)" if flare else ""))
        except RuntimeError as e:
            log(f"AVISO: {s['name']} não pôde ser adicionado ({str(e)[:120]})")

    c.post(f"{v}/command", {"name": "ApplicationIndexerSync"})  # empurra pro Radarr/Sonarr
