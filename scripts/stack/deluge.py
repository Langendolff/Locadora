"""Deluge: senha, pastas, plugin Label, rede."""
import sys
import time

from .common import Client, DELUGE, PASSWORD, log, wait_for


def deluge():
    print("Deluge")
    wait_for("Deluge", DELUGE)
    c = Client(DELUGE)
    n = iter(range(1, 10_000))

    def rpc(method, *params):
        res = c.post("/json", {"method": method, "params": list(params), "id": next(n)})
        if res.get("error"):
            raise RuntimeError(f"deluge {method}: {res['error']}")
        return res["result"]

    if rpc("auth.login", PASSWORD):
        log("senha já configurada")
    elif rpc("auth.login", "deluge"):
        rpc("auth.change_password", "deluge", PASSWORD)
        log("senha padrão trocada")
    else:
        sys.exit("Deluge: não consegui logar nem com a senha do .env nem com a padrão")

    hosts = rpc("web.get_hosts")
    # Sem default_daemon, a interface web volta desligada a cada reinício do Deluge e o
    # Radarr/Sonarr recebem "Connection refused" até alguém religar à mão
    if rpc("web.get_config").get("default_daemon") != hosts[0][0]:
        rpc("web.set_config", {"default_daemon": hosts[0][0]})
        log("reconecta sozinho depois de reiniciar")
    if not rpc("web.connected"):
        rpc("web.connect", hosts[0][0])
        for _ in range(20):
            if rpc("web.connected"):
                break
            time.sleep(1)

    rpc("core.set_config", {
        "download_location": "/data/torrents/incomplete",
        "move_completed": True,
        "move_completed_path": "/data/torrents",
        "max_active_seeding": 10,
        # Sem prender a uma interface: prender ao tun0 quebra o DHT. Não há vazamento:
        # o Deluge usa a rede do gluetun, cujo firewall só deixa sair pela VPN.
        "listen_interface": "",
        "outgoing_interface": "",
        "upnp": False,
        "natpmp": False,
    })
    if "Label" not in rpc("core.get_enabled_plugins"):
        rpc("core.enable_plugin", "Label")
    log("pastas de download + plugin Label")
