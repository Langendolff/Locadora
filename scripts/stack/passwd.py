"""Troca a senha do admin em todos os serviços."""
import sys

from .common import Client, DELUGE, JELLYFIN, KEYS, PROWLARR, RADARR, SONARR, USER, log
from .arr import fix_deluge_password
from .jellyfin import JF_AUTH


def change_password(old, new):
    print("Deluge")
    c = Client(DELUGE)
    res = c.post("/json", {"method": "auth.login", "params": [old], "id": 1})
    if res["result"]:
        c.post("/json", {"method": "auth.change_password", "params": [old, new], "id": 2})
        log("senha trocada")
    elif c.post("/json", {"method": "auth.login", "params": [new], "id": 3})["result"]:
        log("já estava com a senha nova")
    else:
        sys.exit("Deluge: a senha atual não confere")

    for name, base, v in (("radarr", RADARR, "v3"), ("sonarr", SONARR, "v3"), ("prowlarr", PROWLARR, "v1")):
        print(name.capitalize())
        c = Client(base, {"X-Api-Key": KEYS[name]})
        host = c.get(f"/api/{v}/config/host")
        host.update(username=USER, password=new, passwordConfirmation=new)
        c.put(f"/api/{v}/config/host/{host['id']}", host)
        log("senha trocada")
        if name != "prowlarr" and fix_deluge_password(c, new):  # senha que ele usa no Deluge
            log("senha do Deluge atualizada")

    print("Jellyfin (Seerr usa este mesmo login)")
    c = Client(JELLYFIN, {"Authorization": JF_AUTH})
    try:
        auth = c.post("/Users/AuthenticateByName", {"Username": USER, "Pw": old})
    except RuntimeError:
        c.post("/Users/AuthenticateByName", {"Username": USER, "Pw": new})
        log("já estava com a senha nova")
        return
    c.headers["Authorization"] = JF_AUTH + f', Token="{auth["AccessToken"]}"'
    c.post(f"/Users/{auth['User']['Id']}/Password", {"CurrentPw": old, "NewPw": new})
    log("senha trocada")
