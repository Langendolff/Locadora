"""Configuração compartilhada: credenciais, endereços dos serviços e cliente HTTP."""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER = os.environ["STACK_USER"]
PASSWORD = os.environ["STACK_PASSWORD"]
EMAIL = os.environ.get("STACK_EMAIL") or "admin@example.com"
HAS_GPU = os.environ.get("HAS_GPU") == "1"
KEYS = {
    "radarr": os.environ["RADARR_API_KEY"],
    "sonarr": os.environ["SONARR_API_KEY"],
    "prowlarr": os.environ["PROWLARR_API_KEY"],
}

DELUGE = "http://gluetun:8112"
RADARR = "http://radarr:7878"
SONARR = "http://sonarr:8989"
PROWLARR = "http://prowlarr:9696"
JELLYFIN = "http://jellyfin:8096"
SEERR = "http://seerr:5055"


def log(msg):
    print(f"  - {msg}", flush=True)


class Client:
    def __init__(self, base, headers=None):
        self.base = base
        self.headers = {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def req(self, method, path, body=None, ok=(200, 201, 202, 204)):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=self.headers)
        try:
            with self.opener.open(r, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw and raw.strip()[:1] in (b"{", b"[") else raw.decode()
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return None
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {self.base}{path} -> {e.code}: {detail}") from None

    get = lambda s, p, **k: s.req("GET", p, **k)
    post = lambda s, p, b=None, **k: s.req("POST", p, b, **k)
    put = lambda s, p, b=None, **k: s.req("PUT", p, b, **k)
    delete = lambda s, p, **k: s.req("DELETE", p, **k)


def wait_for(name, url, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=5)
            return
        except urllib.error.HTTPError:
            return  # respondeu (401/404 etc.) = está de pé
        except Exception:
            time.sleep(3)
    sys.exit(f"{name} não respondeu em {url}")


def set_field(fields, name, value):
    for f in fields:
        if f["name"] == name:
            f["value"] = value
            return
    raise KeyError(name)
