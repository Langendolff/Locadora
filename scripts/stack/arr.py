"""Radarr/Sonarr: login, pasta raiz, Deluge, hardlinks, renomeação."""
from .common import Client, KEYS, PASSWORD, USER, log, set_field, wait_for

MIN_FREE_MB = 10 * 1024


def fix_deluge_password(c, password):
    """Grava `password` no cliente Deluge do Radarr/Sonarr se a salva não funcionar mais.
    A API devolve a senha mascarada, então testa a conexão com a salva antes de trocar."""
    changed = False
    for dc in c.get("/api/v3/downloadclient"):
        if dc["implementation"] != "Deluge":
            continue
        try:
            c.post("/api/v3/downloadclient/test", dc)
            continue  # conecta com a senha salva
        except RuntimeError:
            pass
        set_field(dc["fields"], "password", password)
        c.put(f"/api/v3/downloadclient/{dc['id']}", dc)
        changed = True
    return changed


def arr(name, base, root, category_field, category):
    print(name.capitalize())
    wait_for(name, base + "/ping")
    c = Client(base, {"X-Api-Key": KEYS[name]})
    v = "/api/v3"

    host = c.get(f"{v}/config/host")
    if host.get("username") != USER or host.get("authenticationMethod") != "forms":
        host.update(authenticationMethod="forms", authenticationRequired="enabled",
                    username=USER, password=PASSWORD, passwordConfirmation=PASSWORD)
        c.put(f"{v}/config/host/{host['id']}", host)
        log("login configurado")

    if not any(r["path"].rstrip("/") == root for r in c.get(f"{v}/rootfolder")):
        c.post(f"{v}/rootfolder", {"path": root})
        log(f"pasta raiz {root}")

    if fix_deluge_password(c, PASSWORD):
        log("senha do Deluge atualizada (estava desatualizada: downloads não saíam)")
    if not any(d["implementation"] == "Deluge" for d in c.get(f"{v}/downloadclient")):
        schema = next(s for s in c.get(f"{v}/downloadclient/schema") if s["implementation"] == "Deluge")
        fields = schema["fields"]
        set_field(fields, "host", "gluetun")
        set_field(fields, "port", 8112)
        set_field(fields, "password", PASSWORD)
        set_field(fields, category_field, category)
        schema.update(name="Deluge", enable=True, priority=1)
        c.post(f"{v}/downloadclient", schema)
        log("Deluge adicionado como cliente de download")

    changed = False
    mm = c.get(f"{v}/config/mediamanagement")
    # doNotPrefer: REPACK/PROPER não passa na frente da preferência de idioma.
    # Espaço mínimo: com menos de 10 GB livres, não importa mais nada (o disco cheio trava tudo,
    # inclusive os bancos de dados); o ./diagnostico.sh avisa antes disso.
    want = {"copyUsingHardlinks": True, "downloadPropersAndRepacks": "doNotPrefer",
            "minimumFreeSpaceWhenImporting": MIN_FREE_MB}
    if any(mm.get(k) != val for k, val in want.items()):
        mm.update(want)
        c.put(f"{v}/config/mediamanagement/{mm['id']}", mm)
        changed = True
    naming = c.get(f"{v}/config/naming")
    key = "renameMovies" if name == "radarr" else "renameEpisodes"
    if not naming.get(key):
        naming[key] = True
        c.put(f"{v}/config/naming/{naming['id']}", naming)
        changed = True
    if changed:
        log(f"hardlinks, renomeação e mínimo de {MIN_FREE_MB // 1024} GB livres para importar")
